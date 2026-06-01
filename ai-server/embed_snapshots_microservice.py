import os
import time
import logging
import requests
import chromadb
from pathlib import Path
from watchdog.observers.polling import PollingObserver  # Polling — works across all filesystems
from watchdog.events import FileSystemEventHandler

from dotenv import load_dotenv
load_dotenv()

from state import search_already_embedded, search_mark_embedded, search_mark_for_retry, search_get_retry_queue, search_clear_retry

# --- Logging ---
LOG_FILE = os.environ.get("LOG_FILE", "/var/log/cctv-embedder.log")
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
SNAPSHOTS_DIR  = os.environ.get("SNAPSHOTS_DIR", "/var/cctv/snapshots")
CHROMA_DB_PATH = os.environ.get("CHROMA_DB_PATH", "/var/cctv/chromadb")

# API Server Config
EMBED_API_URL  = os.environ.get("EMBED_IMAGE_API_SEARCH_URL", "http://localhost:8002/embed/image")

SUPPORTED_EXTENSIONS = ('.jpg', '.jpeg', '.png')

CAMERA_MAP = {
    "Back_Door":      "Back Door",
    "Front_Driveway": "Front Driveway",
    "Front_Door":     "Front Door",
}

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

# --- ChromaDB ---
# Connects to the background ChromaDB server
chroma     = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection = chroma.get_or_create_collection(
    name="cctv_images",
    metadata={"hnsw:space": "cosine"}
)


# --- File stability check ---
def wait_for_file_ready(path, timeout=5, interval=1):
    """Wait until file size stops changing."""
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


# --- Embed image via API ---
def embed_image(image_path):
    """Asks the central API server to generate the embedding."""
    payload = {"image_path": image_path}
    
    try:
        response = requests.post(EMBED_API_URL, json=payload, timeout=15)
        response.raise_for_status()
        return response.json()["embedding"]
    except requests.exceptions.RequestException as e:
        log.error(f"Embedding API failed for {image_path}: {e}")
        raise


# --- Parse metadata from path ---
def parse_metadata(image_path):
    parts      = Path(image_path).parts
    snap_parts = len(Path(SNAPSHOTS_DIR).parts)

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


# --- Embed and store a single image ---
def process_image(image_path):
    if search_already_embedded(image_path):
        return True

    try:
        camera, date, hour, time_str, filename = parse_metadata(image_path)
        log.info(f"New file found! Embedding: {camera} | {date} | hour={int(hour)} | {filename}")

        embedding = embed_image(image_path)

        collection.add(
            ids=[image_path],
            embeddings=[embedding],
            metadatas=[{
                "camera":     camera,
                "date":       date,
                "hour":       int(hour),
                "time":       time_str,
                "filename":   filename,
                "image_path": image_path,
            }]
        )

        search_mark_embedded(image_path)
        log.info(f"Successfully Stored: {filename}")
        return True

    except Exception as e:
        log.error(f"Failed to process {image_path}: {e}")
        return False


# --- Watchdog handler ---
class ImageHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.lower().endswith(SUPPORTED_EXTENSIONS):
            return

        log.info(f"Incoming live image detected: {event.src_path}")

        if not wait_for_file_ready(event.src_path, timeout=5):
            log.warning(f"Timed out — queued for retry: {event.src_path}")
            search_mark_for_retry(event.src_path)
            return

        process_image(event.src_path)


# --- Startup scan ---
def startup_scan():
    # 2. Retry queue first
    retry_queue = search_get_retry_queue()
    if retry_queue:
        log.info(f"Retrying {len(retry_queue)} previously failed images...")
        for image_path in retry_queue:
            if not os.path.exists(image_path):
                search_clear_retry(image_path)
                continue

            if wait_for_file_ready(image_path, timeout=5):
                if process_image(image_path):
                    search_clear_retry(image_path)
                else:
                    log.error(f"Retry failed again: {image_path}")
            else:
                log.error(f"Retry timed out again: {image_path}")
                search_clear_retry(image_path)

    # 3. Scan all existing snapshots
    log.info(f"Scanning {SNAPSHOTS_DIR} for new files. This will be very fast...")
    
    new_files_count = 0
    for root, dirs, files in os.walk(SNAPSHOTS_DIR):
        for fname in sorted(files):
            if fname.lower().endswith(SUPPORTED_EXTENSIONS):
                full_path = os.path.join(root, fname)
                # Quick check before processing to count
                if not search_already_embedded(full_path):
                    process_image(full_path)
                    new_files_count += 1
                    
    log.info(f"Startup scan complete. Processed {new_files_count} new files.")


# --- Main ---
if __name__ == "__main__":
    os.makedirs("/var/cctv", exist_ok=True)
    startup_scan()

    # PollingObserver
    handler  = ImageHandler()
    observer = PollingObserver(timeout=2)
    observer.schedule(handler, SNAPSHOTS_DIR, recursive=True)
    observer.start()
    log.info(f"Watching (polling) for live updates in: {SNAPSHOTS_DIR}")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
