import os
import time
import logging
import cv2
import numpy as np
from ultralytics import YOLO
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from dotenv import load_dotenv
load_dotenv()

# --- Logging ---
LOG_FILE = os.environ.get("LOG_FILE", "/var/log/cctv-processor.log")
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE)
    ]
)
log = logging.getLogger(__name__)

# --- Config ---
INPUT_DIR          = os.environ.get("INPUT_DIR")
OUTPUT_DIR         = os.environ.get("OUTPUT_DIR", "/var/cctv/snapshots")
OUTPUT_DIR_CROPS   = os.environ.get("OUTPUT_DIR_CROPS", "/var/cctv/crops")
PROCESSED_LOG      = os.environ.get("PROCESSED_LOG", "/var/cctv/processed.log")

CONTOUR_TOP_N    = int(os.environ.get("CONTOUR_TOP_N", "150"))
YOLO_TOP_N       = int(os.environ.get("YOLO_TOP_N", "5"))
MOTION_THRESHOLD = int(os.environ.get("MOTION_THRESHOLD", "600"))
MIN_CONTOUR_AREA = int(os.environ.get("MIN_CONTOUR_AREA", "500"))
YOLO_CONFIDENCE  = float(os.environ.get("YOLO_CONFIDENCE", "0.4"))

SUPPORTED_EXTENSIONS = ('.mp4', '.avi', '.mov', '.mkv')

# Load YOLO once at startup
YOLO_MODEL = os.environ.get("YOLO_MODEL", "yolo26s.pt")
yolo = YOLO(YOLO_MODEL)


# --- File stability check ---
def wait_for_file_ready(path, timeout=120, interval=5):
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


# --- Processed log helpers ---
def already_processed(video_path):
    if not os.path.exists(PROCESSED_LOG):
        return False
    with open(PROCESSED_LOG) as f:
        return video_path in f.read()

def mark_processed(video_path):
    with open(PROCESSED_LOG, 'a') as f:
        f.write(video_path + '\n')


# --- Motion extraction ---
def extract_top_motion_frames(video_path, video_name, output_dir, crops_dir):
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(crops_dir, exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        log.error(f"Could not open {video_path}")
        return []

    fps = cap.get(cv2.CAP_PROP_FPS)
    log.info(f"{video_name}: Processing video stream @ {fps:.1f} FPS")

    kernel        = np.ones((5, 5), np.uint8)
    motion_scores = []
    prev_gray     = None

    # Fix: Track frames manually via an open-ended while loop to avoid negative MKV frame counts
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret: 
            break
            
        if frame_idx % 3 != 0: 
            frame_idx += 1
            continue

        small = cv2.resize(frame, (320, 180))
        gray  = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)

        if prev_gray is not None:
            diff        = cv2.absdiff(prev_gray, gray)
            _, thresh   = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
            thresh      = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel)
            thresh      = cv2.morphologyEx(thresh, cv2.MORPH_DILATE, kernel)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            significant = [c for c in contours if cv2.contourArea(c) > MIN_CONTOUR_AREA]

            if significant:
                score = sum(cv2.contourArea(c) for c in significant)
                if score > MOTION_THRESHOLD:
                    motion_scores.append((score, frame_idx, frame.copy()))
        prev_gray = gray
        frame_idx += 1

    cap.release()

    if not motion_scores:
        log.info(f"{video_name}: No significant motion detected.")
        return []

    # Contour top-n
    contour_top = sorted(motion_scores, key=lambda x: x[0], reverse=True)[:CONTOUR_TOP_N]
    contour_top.sort(key=lambda x: x[1])

    # YOLO Check
    yolo_results = []
    for score, idx, frame in contour_top:
        timestamp = idx / fps
        results   = yolo(frame, classes=[0], verbose=False)
        boxes     = results[0].boxes
        
        # Filter persons by confidence
        persons = (
            [b for b in boxes if float(b.conf) >= YOLO_CONFIDENCE]
            if boxes is not None else []
        )

        if not persons:
            continue

        # Use box area*confidence for scoring
        yolo_score = sum(
            float(b.conf) * float(b.xywh[0][2]) * float(b.xywh[0][3])
            for b in persons
        )
        yolo_results.append((yolo_score, idx, timestamp, frame, persons))

    if not yolo_results:
        log.info(f"{video_name}: No persons detected.")
        return []

    final_frames = sorted(yolo_results, key=lambda x: x[0], reverse=True)[:YOLO_TOP_N]
    final_frames.sort(key=lambda x: x[1])

    # Save snapshots and crops
    saved_paths = []
    for i, (yolo_score, idx, timestamp, frame, persons) in enumerate(final_frames, start=1):
        snap_name = f"{video_name}_{i}.jpg"
        snap_path = os.path.join(output_dir, snap_name)
        cv2.imwrite(snap_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
        saved_paths.append(snap_path)

        for p_idx, box in enumerate(persons, start=1):
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            
            h, w = frame.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            crop = frame[y1:y2, x1:x2]
            
            if crop.size > 0:
                crop_name = f"{video_name}_{i}_p{p_idx}.jpg"
                crop_path = os.path.join(crops_dir, crop_name)
                cv2.imwrite(crop_path, crop, [cv2.IMWRITE_JPEG_QUALITY, 100])

        log.info(f"Saved: {snap_name} | Persons: {len(persons)} | Score: {yolo_score:,.0f}")

    return saved_paths

# --- Process a single video ---
def process_video(video_path):
    if already_processed(video_path):
        log.info(f"Already processed, skipping: {video_path}")
        return

    video_name = os.path.splitext(os.path.basename(video_path))[0]
    rel_path   = os.path.relpath(os.path.dirname(video_path), INPUT_DIR)
    
    # Generate mirrored output paths
    output_dir = os.path.join(OUTPUT_DIR, rel_path)
    crops_dir  = os.path.join(OUTPUT_DIR_CROPS, rel_path)

    log.info(f"Processing: {rel_path}/{video_name}")

    try:
        saved = extract_top_motion_frames(video_path, video_name, output_dir, crops_dir)
        if saved:
            log.info(f"Done: {video_name} → {len(saved)} snapshots (plus crops) saved.")
        mark_processed(video_path)
    except Exception as e:
        log.error(f"Failed: {video_name}: {e}")


# --- Watchdog handler ---
class VideoHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory or not event.src_path.lower().endswith(SUPPORTED_EXTENSIONS):
            return

        log.info(f"New file detected: {event.src_path}")
        if not wait_for_file_ready(event.src_path, timeout=120):
            log.error(f"Timed out waiting for file: {event.src_path}")
            return

        process_video(event.src_path)


# --- Main ---
if __name__ == "__main__":
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR_CROPS, exist_ok=True)
    os.makedirs(os.path.dirname(PROCESSED_LOG), exist_ok=True)

    log.info(f"Startup scan: {INPUT_DIR}")
    for root, dirs, files in os.walk(INPUT_DIR):
        for fname in sorted(files):
            if fname.lower().endswith(SUPPORTED_EXTENSIONS):
                process_video(os.path.join(root, fname))

    handler  = VideoHandler()
    observer = Observer()
    observer.schedule(handler, INPUT_DIR, recursive=True)
    observer.start()
    log.info(f"Watching: {INPUT_DIR} (recursive)")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
