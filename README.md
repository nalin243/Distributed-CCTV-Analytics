# Distributed CCTV Analytics

A self-hosted, distributed surveillance analytics platform that turns raw CCTV footage into a searchable, person-indexed database. This system combines ONVIF motion detection, YOLO person detection, OpenCLIP semantic search, and DBSCAN clustering into a set of cooperating microservices running across two servers.

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Node.js-18+-339933?style=flat-square&logo=nodedotjs&logoColor=white" alt="Node.js">
  <img src="https://img.shields.io/badge/React-18-61DAFB?style=flat-square&logo=react&logoColor=black" alt="React">
  <img src="https://img.shields.io/badge/Vite-5-646CFF?style=flat-square&logo=vite&logoColor=white" alt="Vite">
  <br>
  <img src="https://img.shields.io/badge/Flask-3-000000?style=flat-square&logo=flask&logoColor=white" alt="Flask">
  <img src="https://img.shields.io/badge/FastAPI-0.100+-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/ChromaDB-Vector_DB-0052FF?style=flat-square" alt="ChromaDB">
  <img src="https://img.shields.io/badge/SQLite-WAL_Mode-003B57?style=flat-square&logo=sqlite&logoColor=white" alt="SQLite">
  <br>
  <img src="https://img.shields.io/badge/YOLO-Object_Detection-00FFFF?style=flat-square" alt="YOLO">
  <img src="https://img.shields.io/badge/OpenCLIP-Semantic_Search-FF6F00?style=flat-square" alt="OpenCLIP">
  <img src="https://img.shields.io/badge/Intel_OpenVINO-Re--ID-0071C5?style=flat-square&logo=intel&logoColor=white" alt="OpenVINO">
  <img src="https://img.shields.io/badge/OpenCV-Computer_Vision-5C3EE8?style=flat-square&logo=opencv&logoColor=white" alt="OpenCV">
  <img src="https://img.shields.io/badge/FFmpeg-Stream_Copy-007800?style=flat-square&logo=ffmpeg&logoColor=white" alt="FFmpeg">
  <img src="https://img.shields.io/badge/ONVIF-Camera_Control-007ACC?style=flat-square" alt="ONVIF">
</p>

---

## Architecture

```text
┌───────────────────────────────────────────────────┐
│                 RECORDING SERVER                  │
│                                                   │
│  ┌──────────────────┐   ┌──────────────────────┐  │
│  │  ONVIF Camera    │──▶│  Motion Extraction   │  │
│  │  Controller      │   │  (YOLO v26s)         │  │
│  │  (motion clips)  │   │  Snapshots + Crops   │  │
│  └──────────────────┘   └──────────────────────┘  │
│  ┌──────────────────┐                             │
│  │  Cleanup         │                             │
│  │  Microservice    │                             │
│  └──────────────────┘                             │
└───────────────────────────────────────────────────┘
               │  NFS / shared disk  │
┌───────────────────────────────────────────────────┐
│                    AI SERVER                      │
│                                                   │
│  ┌──────────────────┐   ┌──────────────────────┐  │
│  │  Embedding Gen   │   │  Embed Snapshots     │  │
│  │  (OpenCLIP)      │◀──│  (search pipeline)   │  │
│  │  :8002           │   └──────────────────────┘  │
│  └──────────────────┘   ┌──────────────────────┐  │
│  ┌──────────────────┐   │  Embed Persons       │  │
│  │  Prediction      │◀──│  (re-ID pipeline)    │  │
│  │  :8010           │   └──────────────────────┘  │
│  └──────────────────┘   ┌──────────────────────┐  │
│  ┌──────────────────┐   │  User API + Frontend │  │
│  │  DBSCAN          │◀──│  (React + Flask)     │  │
│  │  Clustering      │   │  :5000               │  │
│  │  :8005           │   └──────────────────────┘  │
│  └──────────────────┘                             │
│           ┌────────────────────┐                  │
│           │     ChromaDB       │                  │
│           │     :8001          │                  │
│           └────────────────────┘                  │
└───────────────────────────────────────────────────┘
```

---

## Features

### Semantic Search
* **Natural-Language Search:** Query CCTV snapshots using natural language (e.g., "man in red shirt", "white delivery van in the evening").
* **OpenCLIP Embeddings:** Powered by OpenCLIP ViT-H-14 for high-quality joint image/text representations.
* **Filtering and Ranking:** Filter queries by camera, date, and hour. Results are ranked using cosine similarity.

### Person Re-Identification & Clustering
* **Object Detection:** Detects and crops persons from motion footage using YOLOv26s.
* **OpenVINO Re-ID:** Generates person re-identification embeddings with OpenVINO using the `person-reidentification-retail-0277` model.
* **DBSCAN Clustering:** Groups occurrences of the same person across different cameras and days.
* **Real-time Prediction:** Uses weighted k-NN voting with reranking to predict identity when new crops are generated.
* **Temporal Deduplication:** Prevents duplicate crop generation within a configurable timing window.

### Web Dashboard
* **Search Interface:** Perform semantic searches, filter by parameters, view thumbnail grids, and inspect source video/images in a lightbox.
* **Visitor Management:** Manage person clusters with rename, merge, move, and delete actions.
* **Analytics & Statistics:** Monitor activity with hourly/daily line charts, per-camera breakdowns, and a visitor schedule heatmap.
* **Responsive Design:** Optimized for desktop, tablet, and mobile screens.

### Recording Pipeline
* **ONVIF Event Polling:** Polls motion events with a fallback mechanism for automatic PullPoint subscription.
* **FFmpeg Stream Copying:** Records stream footage directly to MKV without expensive re-encoding.
* **Threaded Monitoring:** Handles multiple camera streams independently with configurable cooldowns and idle timeouts.
* **Motion Extraction:** Runs frame differencing, contour scoring, YOLO person filtering, and saves top-N snapshots and crops.
* **Live Processing:** Watches target directories via `watchdog` to index new footage as soon as it is written.

### Data Management
* **Vector Indexing:** Utilizes ChromaDB to store and index embeddings using cosine similarity.
* **Idempotent Pipelines:** Uses SQLite to keep track of processed files, ensuring safe recovery and retries from transient errors.
* **Smart Retention:** Cleans up historical data automatically based on per-camera quotas, night-time reserves, and noise-pruning criteria.

---

## Project Structure

```text
distributed-cctv-analytics/
├── ai-server/
│   ├── .env                              # AI server configuration
│   ├── requirements.txt
│   ├── embedding_generation_microservice.py   # OpenCLIP text/image embedding API (FastAPI, :8002)
│   ├── embed_snapshots_microservice.py        # Watches /var/cctv/snapshots → embeds for search
│   ├── embed_persons_microservice.py          # Watches /var/cctv/crops → re-ID embeddings
│   ├── prediction_microservice.py             # Real-time identity prediction (Flask, :8010)
│   ├── dbscan_clustering_microservice.py      # Person clustering (Flask, :8005)
│   ├── user_api_microservice.py               # Main API gateway (Flask, :5000)
│   ├── state.py                               # SQLite-backed embedding state tracker
│   ├── models/                                # OpenVINO IR model files
│   │   ├── person-reidentification-retail-0277.xml
│   │   └── person-reidentification-retail-0277.bin
│   └── user_frontend/                         # React + Vite web UI
│       ├── package.json
│       ├── vite.config.js
│       └── src/
│           ├── main.jsx
│           ├── App.jsx
│           ├── api/client.js
│           └── utils/paths.js
│
├── recording-server/
│   ├── .env                              # Recording server configuration
│   ├── requirements.txt
│   ├── onvif_camera_controller.py        # ONVIF motion detection + clip recording
│   ├── motion_extraction_service_v2.py   # YOLO-based snapshot/crop extraction
│   └── cleanup_microservice.py           # Data retention + pruning (Flask, :8009)
│
└── .gitignore
```

---

## Setup & Deployment

### Prerequisites

* Python 3.10+
* Node.js 18+ (for frontend dashboard)
* ChromaDB server (listening on port 8001)
* System-wide installation of FFmpeg
* ONVIF-compatible IP cameras

### 1. Recording Server

Navigate to the recording server directory and install dependencies:

```bash
cd recording-server
pip install -r requirements.txt
```

Create a `camera_config.json` configuration file:

```json
{
    "save_folder": "/var/cctv/footage",
    "cooldown_seconds": 10,
    "motion_idle_seconds": 3,
    "cameras": [
        {
            "name": "Front Door",
            "host": "192.168.1.100",
            "onvif_port": 80,
            "username": "admin",
            "password": "your_password",
            "rtsp_url": "rtsp://admin:your_password@192.168.1.100:554/stream1"
        }
    ]
}
```

Configure environment paths in the `.env` file, then launch the background services:

```bash
# Start ONVIF camera motion logging and clip recording
python onvif_camera_controller.py --config camera_config.json

# Start motion extraction (YOLO frame-differencing pipeline)
python motion_extraction_service_v2.py

# Start the cleanup service
python cleanup_microservice.py
```

### 2. AI Server

Navigate to the AI server directory and install dependencies:

```bash
cd ai-server
pip install -r requirements.txt
```

Run your ChromaDB server instance:

```bash
chroma run --host 0.0.0.0 --port 8001 --path /var/cctv/chromadb
```

Configure your `.env` file, and start the processing microservices:

```bash
# Start OpenCLIP model API (Requires ~6 GB RAM)
python embedding_generation_microservice.py

# Start snapshot embedding pipeline
python embed_snapshots_microservice.py

# Start person re-ID embedding pipeline
python embed_persons_microservice.py

# Start identity prediction service
python prediction_microservice.py

# Start clustering service
python dbscan_clustering_microservice.py

# Start the user API service
python user_api_microservice.py
```

### 3. Frontend Dashboard

Navigate to the frontend application directory, install package dependencies, and run the development server:

```bash
cd ai-server/user_frontend
npm install
npm run dev
```

The web console will be accessible locally at `http://localhost:3000`.

---

## Configuration Reference

System behavior is defined via environmental variables located in the `.env` file of each server.

### AI Server Configuration (`ai-server/.env`)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `CHROMA_HOST` | ChromaDB hostname | `localhost` |
| `CHROMA_PORT` | ChromaDB port | `8001` |
| `CROPS_DIR` | Person crop images directory | `/var/cctv/crops` |
| `SNAPSHOTS_DIR` | Full-frame snapshots directory | `/var/cctv/snapshots` |
| `CLUSTERING_URL` | DBSCAN clustering service URL | — |
| `CLEANUP_URL` | Cleanup microservice URL | — |
| `EMBED_TEXT_API_URL` | Text embedding endpoint | — |
| `EMBED_IMAGE_API_URL` | Image embedding endpoint | `http://localhost:8002/embed/image` |
| `PREDICTION_URL` | Identity prediction endpoint | `http://0.0.0.0:8010/` |
| `CLUSTER_EPS` | DBSCAN epsilon (cosine distance) | `0.40` |
| `PREDICTION_THRESHOLD` | Min cosine distance for match | `0.75` |
| `CLIP_MODEL_NAME` | OpenCLIP model architecture | `ViT-H-14` |
| `DEDUP_SECONDS` | Temporal dedup window | `10` |

### Recording Server Configuration (`recording-server/.env`)

| Variable | Description | Default |
| :--- | :--- | :--- |
| `CHROMA_HOST` | ChromaDB hostname (AI server IP) | — |
| `CHROMA_PORT` | ChromaDB port | `8001` |
| `INPUT_DIR` | Raw footage input directory | — |
| `OUTPUT_DIR` | Snapshot output directory | `/var/cctv/snapshots` |
| `OUTPUT_DIR_CROPS` | Person crop output directory | `/var/cctv/crops` |
| `YOLO_CONFIDENCE` | YOLO detection confidence threshold | `0.4` |
| `MOTION_THRESHOLD` | Minimum motion score to consider | `600` |
| `CLEANUP_HOST` | Cleanup service bind address | — |
| `CLEANUP_PORT` | Cleanup service port | `8009` |

---

## Database Schema

### ChromaDB Collections

The database contains two collections using the `cosine` similarity metric for index operations.

#### 1. `cctv_images` (Semantic Search Index)

Stores 1024-dimensional OpenCLIP embeddings of full-frame CCTV snapshots. Managed by `embed_snapshots_microservice.py`.

* **Primary Key (`id`):** Absolute path to the snapshot image file (e.g., `/var/cctv/snapshots/Front_Door/Date-29-05-2026/Time-14-30-12_1.jpg`).
* **Vector Embedding:** `FLOAT[1024]` (OpenCLIP ViT-H-14 image embeddings).

| Metadata Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `camera` | `string` | Camera source identifier | `Front Door` |
| `date` | `string` | Date directory name | `Date-29-05-2026` |
| `hour` | `int` | Hour of recording (0–23) | `14` |
| `time` | `string` | File timestamp details | `Time-14-30-12_1` |
| `filename` | `string` | Physical file name | `Time-14-30-12_1.jpg` |
| `image_path` | `string` | Complete location path | `/var/cctv/snapshots/Front_Door/Date-29-05-2026/Time-14-30-12_1.jpg` |

#### 2. `person_crops` (Person Re-ID Index)

Stores 256-dimensional OpenVINO embeddings of cropped person crops. Updated by `dbscan_clustering_microservice.py`.

* **Primary Key (`id`):** Absolute path to the crop image file (e.g., `/var/cctv/crops/Front_Door/Date-29-05-2026/Time-14-30-12_1_p1.jpg`).
* **Vector Embedding:** `FLOAT[256]` (OpenVINO `person-reidentification-retail-0277` embeddings).

| Metadata Field | Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `camera` | `string` | Camera source identifier | `Front Door` |
| `date` | `string` | Date directory name | `Date-29-05-2026` |
| `hour` | `int` | Hour of recording (0–23) | `14` |
| `time` | `string` | File timestamp details | `Time-14-30-12_1_p1` |
| `filename` | `string` | Physical file name | `Time-14-30-12_1_p1.jpg` |
| `image_path` | `string` | Complete crop path | `/var/cctv/crops/Front_Door/...` |
| `cluster_id` | `string` | Cluster identifier assigned by DBSCAN | `cluster_8f3b` |
| `person_name` | `string` | Human-defined label for cluster | `John` |

### SQLite State Database (`state.db`)

Maintained at the `STATE_DB_PATH` destination (defaulting to `/var/cctv/state.db`). Configured with WAL journal mode for safe parallel writes from active microservices.

#### 1. `person_crops` (Re-ID Pipeline State)

| Column | Type | Description |
| :--- | :--- | :--- |
| `image_path` | `TEXT PRIMARY KEY` | Absolute path to the crop file |
| `status` | `TEXT NOT NULL` | `'embedded'` or `'retry'` |
| `retry_count` | `INTEGER NOT NULL` | Count of failures during embedding extraction |
| `processed_at` | `TEXT NOT NULL` | ISO-8601 timestamp of last state transition |

#### 2. `search_embeddings` (Search Pipeline State)

| Column | Type | Description |
| :--- | :--- | :--- |
| `image_path` | `TEXT PRIMARY KEY` | Absolute path to the snapshot file |
| `status` | `TEXT NOT NULL` | `'embedded'` or `'retry'` |
| `retry_count` | `INTEGER NOT NULL` | Count of failures during embedding extraction |
| `processed_at` | `TEXT NOT NULL` | ISO-8601 timestamp of last state transition |

### Persistent State Records

| File Path | Storage Format | Functionality |
| :--- | :--- | :--- |
| `/var/cctv/person_names.json` | JSON Object | Maps `cluster_id` keys to human-assigned name strings |
| `/var/cctv/processed.log` | Plain Text | Text log of raw video files processed by the motion extractor |
| `/var/log/cctv-embedder.log` | System Log | Process logs from snapshot embedding service |
| `/var/log/cctv-processor.log` | System Log | Process logs from YOLO detector and motion extractor |

---

## Data Flow

```text
Cameras (RTSP)
     │
     ▼
ONVIF Motion Events ──▶ FFmpeg clip recording ──▶ .mkv files
     │
     ▼
Motion Extraction ──▶ YOLO person detection
     │
     ├──▶ /var/cctv/snapshots/ (full frames)
     │         │
     │         ▼
     │    Embed Snapshots ──▶ OpenCLIP ──▶ ChromaDB (cctv_images)
     │                                           │
     │                                           ▼
     │                                    Semantic Search API
     │
     └──▶ /var/cctv/crops/ (person crops)
               │
               ▼
          Embed Persons ──▶ OpenVINO Re-ID ──▶ ChromaDB (person_crops)
               │                                      │
               ▼                                      ▼
          Prediction ◀──────────────────────── DBSCAN Clustering
               │
               ▼
          Identity Assignment
```

---

## Technology Stack

| Component | Technology |
| :--- | :--- |
| **Semantic Embeddings** | OpenCLIP ViT-H-14 (LAION-2B) |
| **Person Re-ID** | OpenVINO `person-reidentification-retail-0277` |
| **Object Detection** | YOLOv26s (Ultralytics) |
| **Vector Database** | ChromaDB |
| **State Tracking** | SQLite (WAL mode) |
| **API Layer** | Flask, FastAPI |
| **Frontend** | React 18 + Vite |
| **Video Capture** | OpenCV + FFmpeg |
| **Camera Control** | ONVIF (python-onvif-zeep) |

---

## License

This project is for personal/educational use.
