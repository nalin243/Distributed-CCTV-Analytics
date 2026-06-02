import os
import time
import logging
import requests
import chromadb
from pathlib import Path
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler

from datetime import datetime, timedelta
from collections import OrderedDict
import threading

from dotenv import load_dotenv
load_dotenv()

from state import already_embedded, mark_embedded, mark_for_retry, get_retry_queue, clear_retry, remove_entry

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[logging.StreamHandler()]
)
log = logging.getLogger(__name__)

CROPS_DIR  = os.environ.get("CROPS_DIR", "/var/cctv/crops")
PREDICTION_MICROSERVICE_URL = os.environ.get("PREDICTION_URL", "http://0.0.0.0:8010/")
EMBED_IMAGE_API_REID_URL = os.environ.get("EMBED_IMAGE_API_REID_URL","")
CLEANUP_URL     = os.environ.get("CLEANUP_URL","")

SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png')

DEDUP_SECONDS       = int(os.environ.get("DEDUP_SECONDS", "10"))
EVICT_AFTER_SECONDS = int(os.environ.get("EVICT_AFTER_SECONDS", "60"))

CAMERA_MAP = {
    "Back_Door":      "Back Door",
    "Front_Driveway": "Front Driveway",
    "Front_Door":     "Front Door",
}

# --- IN-MEMORY CACHE ---
_LAST_STORED = OrderedDict()

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

CROPS_COLLECTION_NAME = os.environ.get("CROPS_COLLECTION_NAME","")

# --- ChromaDB ---
chroma     = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection = chroma.get_or_create_collection(
    name=CROPS_COLLECTION_NAME,
    metadata={"hnsw:space": "cosine"}
)

def _eviction_worker(interval_seconds=60):
    while True:
        time.sleep(interval_seconds)
        now     = datetime.now()
        cutoff  = now - timedelta(seconds=EVICT_AFTER_SECONDS)
        evicted = 0
        while _LAST_STORED:
            cluster_id, last_time = next(iter(_LAST_STORED.items()))
            if last_time < cutoff:
                _LAST_STORED.popitem(last=False)
                evicted += 1
            else:
                break
        if evicted:
            log.info(f"Eviction: removed {evicted} stale dedup entries")


def _evict_old_entries(now):
    cutoff = now - timedelta(seconds=EVICT_AFTER_SECONDS)
    while _LAST_STORED:
        cluster_id, last_time = next(iter(_LAST_STORED.items()))
        if last_time < cutoff:
            _LAST_STORED.popitem(last=False)
        else:
            break


def is_too_recent(cluster_id, parsed_time):
    _evict_old_entries(parsed_time)
    last_time = _LAST_STORED.get(cluster_id)
    if last_time is None:
        return False
    return (parsed_time - last_time).total_seconds() < DEDUP_SECONDS


def mark_stored(cluster_id, parsed_time):
    _LAST_STORED.pop(cluster_id, None)
    _LAST_STORED[cluster_id] = parsed_time


def wait_for_file_ready(path, timeout=5, interval=1):
    start     = time.time()
    prev_size = -1
    while time.time() - start < timeout:
        try:
            curr_size = os.path.getsize(path)
        except OSError:
            time.sleep(interval)
            continue
        if curr_size == prev_size and curr_size > 0:
            return True
        prev_size = curr_size
        time.sleep(interval)
    return False


def parse_metadata(image_path):
    parts      = Path(image_path).parts
    snap_parts = len(Path(CROPS_DIR).parts)

    camera_raw = parts[snap_parts]
    date       = parts[snap_parts + 1]
    filename   = parts[-1]
    camera     = CAMERA_MAP.get(camera_raw, camera_raw)
    time_str   = os.path.splitext(filename)[0]

    hour = "unknown"
    try:
        hour = filename.split('-')[1]
    except Exception:
        pass

    return camera, date, hour, time_str, filename


def process_image(image_path):
    if already_embedded(image_path):
        return True

    try:
        camera, date, hour, time_str, filename = parse_metadata(image_path)

        temp_date   = time_str.split('-')
        parsed_time = temp_date[1] + "/" + temp_date[2] + "/" + (temp_date[3]).split('_')[0]
        parsed_time = datetime.strptime(parsed_time, "%H/%M/%S")

        log.info(f"Embedding: camera={camera} date={date} hour={int(hour)} file={filename}")

        response = requests.post(
            EMBED_IMAGE_API_REID_URL,
            json={
            'image_path': image_path,
            },
            timeout=5,
        )

        response.raise_for_status()

        embedding = response.json()['embedding']

        response = requests.post(
            PREDICTION_MICROSERVICE_URL + "predict",
            json={
            'embedding': embedding,
            'camera':camera
            },
            timeout=5,
        ).json()

        match_found = response['match_found']
        assigned_cluster = "unassigned"
        assigned_name = "unknown"

        if match_found and response['identity'] not in ('noise', 'unknown', 'Unknown'):
            assigned_cluster = response['cluster_id']
            assigned_name    = response['identity']

            if is_too_recent(assigned_cluster, parsed_time):
                elapsed = (parsed_time - _LAST_STORED[assigned_cluster]).total_seconds()
                log.info(f"Dedup skip: {assigned_name} ({assigned_cluster}) — {elapsed:.1f}s ago")
                #Cleanup
                mark_embedded(image_path)
                remove_entry(image_path)#state db cleanup
                response_cleanup = (requests.post(CLEANUP_URL + "delete_snapshot",
                                    json={'image_path': image_path}, timeout=3)).json()

                return True

            log.info(f"Auto-match: {assigned_name} → cluster {assigned_cluster}")
            mark_stored(assigned_cluster, parsed_time)

        collection.add(
            ids=[image_path],
            embeddings=[embedding],
            metadatas=[{
                "camera":      camera,
                "date":        date,
                "hour":        int(hour),
                "time":        time_str,
                "filename":    filename,
                "image_path":  image_path,
                "cluster_id":  assigned_cluster,
                "person_name": assigned_name,
            }]
        )

        mark_embedded(image_path)
        log.info(f"Stored: {filename}")
        return True

    except Exception as e:
        log.error(f"Failed to process {image_path}: {e}", exc_info=True)
        return False


class ImageHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.lower().endswith(SUPPORTED_EXTENSIONS):
            return
        log.info(f"Live crop detected: {event.src_path}")
        if not wait_for_file_ready(event.src_path, timeout=5):
            log.warning(f"File not ready — queued for retry: {event.src_path}")
            mark_for_retry(event.src_path)
            return
        process_image(event.src_path)


def startup_scan():
    threading.Thread(
        target=_eviction_worker, args=(60,), daemon=True, name="dedup-eviction"
    ).start()
    log.info("Dedup eviction worker started")

    retry_queue = get_retry_queue()
    if retry_queue:
        log.info(f"Retrying {len(retry_queue)} queued files...")
        for image_path in retry_queue:
            if not os.path.exists(image_path):
                clear_retry(image_path)
                continue
            if wait_for_file_ready(image_path, timeout=5):
                if process_image(image_path):
                    clear_retry(image_path)
                else:
                    log.error(f"Retry failed again: {image_path}")
            else:
                log.error(f"Retry timed out: {image_path}")
                clear_retry(image_path)

    log.info(f"Scanning {CROPS_DIR} for new files...")
    new_count = 0
    for root, dirs, files in os.walk(CROPS_DIR):
        for fname in sorted(files):
            if fname.lower().endswith(SUPPORTED_EXTENSIONS):
                full_path = os.path.join(root, fname)
                if not already_embedded(full_path):
                    process_image(full_path)
                    new_count += 1

    log.info(f"Startup scan complete — {new_count} new files processed")


if __name__ == "__main__":
    startup_scan()

    handler  = ImageHandler()
    observer = PollingObserver(timeout=2)
    observer.schedule(handler, CROPS_DIR, recursive=True)
    observer.start()
    log.info(f"Watching: {CROPS_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()