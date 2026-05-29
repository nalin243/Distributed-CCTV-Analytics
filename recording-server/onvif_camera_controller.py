"""
CCTV Motion Recording Service — headless ONVIF + RTSP clip recorder.

Connects to cameras via ONVIF, polls for motion events, and saves MKV clips to disk

Config format (camera_config.json):
    {
        "save_folder": "motion_clips",
        "cooldown_seconds": 10,
        "default_profile_token": null,
        "cameras": [
            {
                "name": "Front Door",
                "host": "192.168.1.100",
                "onvif_port": 80,
                "username": "admin",
                "password": "password",
                "rtsp_url": "rtsp://admin:password@192.168.1.100:554/stream1",
                "profile_token": null
            }
        ]
    }
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
import subprocess

import cv2
from lxml import etree
from onvif import ONVIFCamera
from zeep.helpers import serialize_object

try:
    from onvif.client import ONVIFService, SERVICES as ONVIF_SERVICES
    _ONVIF_CLIENT_AVAILABLE = True
except ImportError:
    _ONVIF_CLIENT_AVAILABLE = False


###Logging###

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("cctv")


###Config###

@dataclass
class CameraConfig:
    name: str
    host: str
    onvif_port: int
    username: str
    password: str
    rtsp_url: str
    profile_token: Optional[str] = None


def load_config(path: Path) -> tuple[List[CameraConfig], dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config: {exc}") from exc

    cameras_data = data.get("cameras", [])
    if not cameras_data:
        raise ValueError("No cameras defined in config")

    default_token = data.get("default_profile_token")
    cameras: List[CameraConfig] = []
    for camera_id, item in enumerate(cameras_data):
        missing = [k for k in ("host", "username", "password", "rtsp_url") if k not in item]
        if missing:
            raise ValueError(f"Camera {camera_id} missing fields: {missing}")
        cameras.append(CameraConfig(
            name=item.get("name", f"Camera {camera_id + 1}"),
            host=item["host"],
            onvif_port=int(item.get("onvif_port", 80)),
            username=item["username"],
            password=item["password"],
            rtsp_url=item["rtsp_url"],
            profile_token=item.get("profile_token") or default_token,
        ))

    settings = {
        "save_folder":       data.get("save_folder", "motion_clips"),#If the user doesn't specify then save in the project root
        "cooldown_seconds":  int(data.get("cooldown_seconds", 10)),
        "motion_idle_seconds": int(data.get("motion_idle_seconds", 3)),
    }
    return cameras, settings


###Helper functions###

def _safe_name(name: str) -> str:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    return safe or "camera"


def _clip_path(save_folder: Path, camera_name: str, when: Optional[datetime] = None) -> Path:
    stamp = when or datetime.now()
    day_dir = save_folder / _safe_name(camera_name) / stamp.strftime("Date-%d-%m-%Y")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / stamp.strftime("Time-%H-%M-%S.mkv")


###Rtsp capture###

def _open_rtsp_capture(rtsp_url: str, open_ms: int = 5000, read_ms: int = 5000) -> cv2.VideoCapture:
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
        "rtsp_transport;tcp|stimeout;5000000|max_delay;500000"
    )
    params: List[int] = []
    if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
        params.extend([int(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC), open_ms])
    if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
        params.extend([int(cv2.CAP_PROP_READ_TIMEOUT_MSEC), read_ms])

    cap = None
    if params:
        try:
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG, params)
        except TypeError:
            cap = None
    if cap is None:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    for attr, val in [(cv2.CAP_PROP_BUFFERSIZE, 1),
                      (getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None), float(open_ms)),
                      (getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None), float(read_ms))]:
        if attr is not None:
            try:
                cap.set(attr, val)
            except Exception:
                pass
    return cap


###Clip recorder runs in a separate thread to ensure that the system can capture motion from all cameras simultaneously###

class ClipRecorder(threading.Thread):
    def __init__(self, rtsp_url: str, output_file: Path, camera_name: str) -> None:
        super().__init__(name=f"clip-{_safe_name(camera_name)}", daemon=True)
        self.rtsp_url    = rtsp_url
        self.output_file = output_file
        self.camera_name = camera_name
        self.process     = None

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            log.info("[%s] clip: Stopping recording gracefully...", self.camera_name)
            try:
                # Sending 'q' to FFmpeg's stdin closes the video file cleanly
                self.process.communicate(b'q', timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()

    def run(self) -> None:
        log.info("[%s] clip: recording stream + audio → %s", self.camera_name, self.output_file)
        
        # Build the FFmpeg command to stream-copy video and audio without re-encoding
        cmd = [
            "ffmpeg", "-y",
            "-rtsp_transport", "tcp",
            "-i", self.rtsp_url,
            "-c:v", "copy",  # Direct copy of the raw video stream
            "-c:a", "copy",  # Direct copy of the raw audio stream
            str(self.output_file)
        ]
        
        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            # Block thread until FFmpeg exits or is stopped
            self.process.wait()
        except Exception as exc:
            log.error("[%s] clip: FFmpeg process failed: %s", self.camera_name, exc)


###Onvif Helper Functions###

def _onvif_connect(camera: CameraConfig):
    cam = ONVIFCamera(camera.host, camera.onvif_port, camera.username, camera.password)
    return cam, cam.create_events_service()


def _topic_filter(expr_text: str):
    filt = etree.Element("{http://docs.oasis-open.org/wsn/b-2}Filter")
    expr = etree.SubElement(filt, "{http://docs.oasis-open.org/wsn/b-2}TopicExpression")
    expr.set("Dialect", "http://www.onvif.org/ver10/tev/topicExpression/ConcreteSet")
    expr.text = expr_text
    return filt


_SUBSCRIPTION_ATTEMPTS = [
    ("MotionAlarm prefixed PT30S",    {"Filter": None, "InitialTerminationTime": "PT30S"},
     "tns1:VideoSource/tns1:MotionAlarm"),
    ("MotionAlarm PT30S",             {"Filter": None, "InitialTerminationTime": "PT30S"},
     "tns1:VideoSource/MotionAlarm"),
    ("GlobalSceneChange PT30S",       {"Filter": None, "InitialTerminationTime": "PT30S"},
     "tns1:VideoSource/tns1:GlobalSceneChange/tns1:ImagingService"),
    ("CellMotion prefixed PT30S",     {"Filter": None, "InitialTerminationTime": "PT30S"},
     "tns1:RuleEngine/tns1:CellMotionDetector/tns1:Motion"),
    ("CellMotion PT30S",              {"Filter": None, "InitialTerminationTime": "PT30S"},
     "tns1:RuleEngine/CellMotionDetector/Motion"),
    ("MotionAlarm prefixed PT1M",     {"Filter": None, "InitialTerminationTime": "PT1M"},
     "tns1:VideoSource/tns1:MotionAlarm"),
    ("MotionAlarm PT1M",              {"Filter": None, "InitialTerminationTime": "PT1M"},
     "tns1:VideoSource/MotionAlarm"),
    ("unfiltered PT30S",              {"InitialTerminationTime": "PT30S"}, None),
    ("unfiltered PT1M",               {"InitialTerminationTime": "PT1M"},  None),
    ("unfiltered default",            {},                                   None),
]


def _create_pullpoint(onvif_cam, events):
    #Create a PullPoint subscription with multiple fallbacks
    pullpoint = None
    try:
        pullpoint = onvif_cam.create_pullpoint_service()
    except Exception:
        pass

    sub_address = None
    selected_desc = "none"
    last_error = None

    for desc, payload, topic_expr in _SUBSCRIPTION_ATTEMPTS:
        if topic_expr is not None:
            payload = dict(payload)
            payload["Filter"] = _topic_filter(topic_expr)
        try:
            resp = events.CreatePullPointSubscription(payload)
            sub  = serialize_object(resp) if not isinstance(resp, dict) else resp
            ref  = sub.get("SubscriptionReference", {}) if isinstance(sub, dict) else {}
            addr = ref.get("Address") if isinstance(ref, dict) else None
            if isinstance(addr, dict):
                sub_address = addr.get("_value_1") or addr.get("Value")
            elif isinstance(addr, str):
                sub_address = addr
            if sub_address:
                selected_desc = desc
                break
        except Exception as exc:
            last_error = exc

    if pullpoint is not None:
        if sub_address:
            pullpoint.xaddr = sub_address
        try:
            pullpoint.SetSynchronizationPoint()
        except Exception:
            pass
        if sub_address:
            pullpoint._svc_desc = selected_desc
            return pullpoint
        # Some cameras have a fixed endpoint that doesn't need explicit subscription
        try:
            pullpoint.PullMessages({"Timeout": "PT0S", "MessageLimit": 1})
            pullpoint._svc_desc = "fixed-endpoint"
            return pullpoint
        except Exception:
            pass

    if not sub_address:
        detail = f" — {last_error}" if last_error else ""
        raise RuntimeError(f"Cannot create PullPoint{detail}")

    if not _ONVIF_CLIENT_AVAILABLE:
        raise RuntimeError(
            f"PullPoint address found ({sub_address}) but onvif.client "
            "internals unavailable to build manual service"
        )

    pull_cfg     = ONVIF_SERVICES["pullpoint"]
    binding_name = f"{{{pull_cfg['ns']}}}{pull_cfg['binding']}"
    wsdl_path    = os.path.join(onvif_cam.wsdl_dir, pull_cfg["wsdl"])
    pp = ONVIFService(
        sub_address, onvif_cam.user, onvif_cam.passwd,
        wsdl_path, onvif_cam.encrypt, onvif_cam.daemon,
        no_cache=onvif_cam.no_cache,
        portType="PullPointSubscription",
        dt_diff=onvif_cam.dt_diff,
        binding_name=binding_name,
        transport=onvif_cam.transport,
    )
    try:
        pp.SetSynchronizationPoint()
    except Exception:
        pass
    pp._svc_desc = selected_desc
    return pp


def _is_resource_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in (
        "unknown resource", "resource unknown", "resourceunknown",
        "ter:unknownresource", "requested resource does not exist",
    ))


def _extract_motion(notification) -> Optional[bool]:
    """Parse an ONVIF notification and return True/False/None (unknown)."""
    payload = serialize_object(notification)
    if not isinstance(payload, dict):
        return None

    message = payload.get("Message")
    node    = message.get("_value_1") if isinstance(message, dict) else None

    MOTION_NAMES = {"motion", "cellmotion", "state", "ismotion",
                    "ispeople", "isperson", "isvehicle"}
    TRUE_VALS    = {"true", "1", "on", "active", "yes"}
    FALSE_VALS   = {"false", "0", "off", "inactive", "no"}

    def _norm(v) -> str:
        if isinstance(v, bool): return "true" if v else "false"
        return str(v).strip().lower() if v is not None else ""

    def _to_bool(v) -> Optional[bool]:
        s = _norm(v)
        if s in TRUE_VALS:  return True
        if s in FALSE_VALS: return False
        return None

    def _topic_str(obj) -> str:
        parts: List[str] = []
        def _walk(o):
            if o is None: return
            if isinstance(o, dict):
                for v in o.values(): _walk(v)
            elif isinstance(o, (list, tuple)):
                for i in o: _walk(i)
            elif hasattr(o, "itertext"):
                t = " ".join(x for x in o.itertext() if x)
                if t: parts.append(t)
            else:
                t = str(o).strip()
                if t: parts.append(t)
        _walk(obj)
        return " ".join(parts)

    topic_lower = _topic_str(payload.get("Topic")).lower()
    is_motion_topic = any(t in topic_lower for t in (
        "ruleengine/cellmotiondetector/motion", "videosource/motionalarm",
        "cellmotiondetector", "motionalarm", "motion",
    ))

    # Try lxml xpath on the message node first (most reliable)
    if node is not None:
        for tag in ("SimpleItem", "ElementItem"):
            try:
                for item in node.xpath(f'.//*[local-name()="{tag}"]'):
                    name = _norm(item.attrib.get("Name", ""))
                    val  = item.attrib.get("Value", "") or "".join(item.itertext())
                    b = _to_bool(val)
                    if b is None: continue
                    if name in MOTION_NAMES: return b
                    if is_motion_topic and name not in {"source", "videosource", "token", "inputtoken"}:
                        return b
            except Exception:
                pass

        if is_motion_topic:
            try:
                items = node.xpath('.//*[local-name()="Data"]//*[local-name()="SimpleItem"]')
                bools = [_to_bool(i.attrib.get("Value", "")) for i in items]
                bools = [b for b in bools if b is not None]
                if len(bools) == 1: return bools[0]
            except Exception:
                pass

    # Fallback: walk the serialised dict
    def _iter_named(o):
        if isinstance(o, dict):
            if "Name" in o:
                yield _norm(o.get("Name")), o.get("Value", o.get("_value_1"))
            for v in o.values(): yield from _iter_named(v)
        elif isinstance(o, (list, tuple)):
            for i in o: yield from _iter_named(i)

    scan = message if isinstance(message, dict) else payload
    for name, val in _iter_named(scan):
        b = _to_bool(val)
        if b is None: continue
        if name in MOTION_NAMES: return b
        if is_motion_topic and name not in {"source", "videosource", "token", "inputtoken"}:
            return b

    if isinstance(scan, dict):
        for key in ("IsMotion", "CellMotion", "Motion", "State", "IsPeople", "IsVehicle"):
            if key in scan:
                b = _to_bool(scan[key])
                if b is not None: return b

    return None


###camera monitor loop###

def _monitor_camera(
    camera: CameraConfig,
    save_folder: Path,
    cooldown_seconds: int,
    motion_idle_seconds: int,
    stop_event: threading.Event,
) -> None:
    #Runs forever or if stop_event is set for one camera.
    #Reconnects via ONVIF automatically on any failure.

    clog = logging.getLogger(f"cctv.{_safe_name(camera.name)}")

    pullpoint    = None
    onvif_cam    = None
    events_svc   = None
    clip: Optional[ClipRecorder] = None
    last_clip_end   = 0.0
    last_motion_at  = 0.0
    next_retry      = 0.0

    while not stop_event.is_set():
        now = time.monotonic()

        #reconnect if needed
        if pullpoint is None:
            if now < next_retry:
                time.sleep(0.2)
                continue
            try:
                onvif_cam, events_svc = _onvif_connect(camera)
                pullpoint = _create_pullpoint(onvif_cam, events_svc)
                clog.info("PullPoint ready (%s): %s",
                          getattr(pullpoint, "_svc_desc", "?"), pullpoint.xaddr)
            except Exception as exc:
                clog.warning("ONVIF connect failed: %s — retry in 5s", exc)
                pullpoint = None
                next_retry = time.monotonic() + 5.0
                continue

        #poll for events
        try:
            resp = pullpoint.PullMessages({"Timeout": "PT0S", "MessageLimit": 50})
        except Exception as exc:
            if _is_resource_error(exc):
                clog.info("Subscription expired — recreating PullPoint")
                try:
                    pullpoint = _create_pullpoint(onvif_cam, events_svc)
                    continue
                except Exception:
                    pass
            clog.warning("PullMessages error: %s — reconnecting", exc)
            pullpoint  = None
            next_retry = time.monotonic() + 3.0
            continue

        notifications = getattr(resp, "NotificationMessage", None) or []

        for notif in notifications:
            if stop_event.is_set():
                break
            motion = _extract_motion(notif)
            if motion is None:
                continue

            last_motion_at = time.monotonic()

            if motion is False:
                # Motion ended
                if clip is not None and clip.is_alive():
                    clog.info("Motion ended — closing clip")
                    clip.stop()
                    clip.join()
                    clip = None
                    last_clip_end = time.monotonic()
                continue

            # motion is True
            clog.info("Motion detected")

            if clip is not None and clip.is_alive():
                continue  # already recording

            elapsed = time.monotonic() - last_clip_end
            if elapsed < cooldown_seconds:
                clog.debug("In cooldown (%.0fs remaining)", cooldown_seconds - elapsed)
                continue

            out = _clip_path(save_folder, camera.name)
            clip = ClipRecorder(camera.rtsp_url, out, camera.name)
            clip.start()
            last_clip_end = 0.0  # reset so cooldown starts when clip ends

        #idle timeout - stop clip if motion has gone quiet
        if clip is not None and clip.is_alive():
            if last_motion_at > 0 and (time.monotonic() - last_motion_at) >= motion_idle_seconds:
                clog.info("Motion idle for %ds — closing clip", motion_idle_seconds)
                clip.stop()
                clip.join()
                clip = None
                last_clip_end = time.monotonic()

        time.sleep(0.08 if notifications else 0.12)

    #clean up on shutdown
    if clip is not None and clip.is_alive():
        clog.info("Shutdown — closing active clip")
        clip.stop()
        clip.join()

    if pullpoint is not None:
        try:
            pullpoint.Unsubscribe()
        except Exception:
            pass


def run_service(cameras: List[CameraConfig], settings: dict) -> None:
    save_folder         = Path(settings["save_folder"])
    cooldown_seconds    = settings["cooldown_seconds"]
    motion_idle_seconds = settings["motion_idle_seconds"]

    save_folder.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()

    #Graceful shutdown on SIGTERM / SIGINT
    def _handle_signal(signum, _frame):
        log.info("Signal %s received — stopping", signal.Signals(signum).name)
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    log.info("Starting motion service — %d camera(s)", len(cameras))
    log.info("Save folder  : %s", save_folder.resolve())
    log.info("Cooldown     : %ds", cooldown_seconds)
    log.info("Motion idle  : %ds", motion_idle_seconds)

    threads = []
    for camera in cameras:
        t = threading.Thread(
            target=_monitor_camera,
            args=(camera, save_folder, cooldown_seconds, motion_idle_seconds, stop_event),
            name=f"monitor-{_safe_name(camera.name)}",
            daemon=True,
        )
        threads.append(t)
        t.start()
        log.info("Monitor started for: %s (%s)", camera.name, camera.host)

    # Block main thread until signal
    while not stop_event.is_set():
        time.sleep(0.5)

    log.info("Waiting for threads to finish…")
    for t in threads:
        t.join(timeout=10.0)
    log.info("Service stopped cleanly")


def main() -> int:
    p = argparse.ArgumentParser(description="CCTV headless motion recording service")
    p.add_argument("--config", default="camera_config.json",
                   help="Path to JSON config file (default: camera_config.json)")
    p.add_argument("--debug", action="store_true", help="Enable DEBUG logging")
    args = p.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = Path(args.config).expanduser().resolve()
    if not cfg.exists():
        log.error("Config file not found: %s", cfg)
        return 1

    try:
        cameras, settings = load_config(cfg)
    except ValueError as exc:
        log.error("Config error: %s", exc)
        return 1

    run_service(cameras, settings)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())