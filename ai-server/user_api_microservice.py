import os
import glob
import json
import requests
import subprocess
import chromadb
from flask import Flask, request, jsonify, send_file, Response
from flask_cors import CORS

from dotenv import load_dotenv
load_dotenv()

from state import remove_entry,search_remove_entry

# --- Config ---
CHROMA_DB_PATH  = os.environ.get("CHROMA_DB_PATH", "/var/cctv/chromadb")
LLM_URL         = os.environ.get("LLM_URL")
CLUSTERING_URL  = os.environ.get("CLUSTERING_URL")
CLEANUP_URL     = os.environ.get("CLEANUP_URL")
USE_LLM         = os.environ.get("USE_LLM", "False").lower() in ("true", "1", "yes")
EMBED_TEXT_API_URL  = os.environ.get("EMBED_TEXT_API_SEARCH_URL")
EMBED_CENTRAL_SERVER_URL = os.environ.get("EMBED_CENTRAL_SERVER_URL","")
PREDICTION_URL = os.environ.get("PREDICTION_URL","")
WORKING_DIR = os.environ.get("WORKING_DIR",'/var/cctv')

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
SNAPSHOTS_COLLECTION_NAME = os.environ.get("SNAPSHOTS_COLLECTION_NAME","")
CROPS_COLLECTION_NAME = os.environ.get("CROPS_COLLECTION_NAME","")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}, r"/image": {"origins": "*"}, r"/video": {"origins": "*"}, r"/health": {"origins": "*"}})

# --- ChromaDB ---
chroma                 = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection_cctv_images = chroma.get_collection(name=SNAPSHOTS_COLLECTION_NAME)
collection_cctv_crops  = chroma.get_collection(name=CROPS_COLLECTION_NAME)


#LLM Time Parser - CURRENTLY  NOT IN USE
def parse_time_to_json(user_query):
    prompt = f"""<|system|>
You extract time ranges from text and remove the time words.
Rule 1: morning = 6 to 11
Rule 2: afternoon = 12 to 16
Rule 3: evening = 17 to 20
Rule 4: night = 21 to 5
<|user|>
Text: "white car in the morning"
<|assistant|>
{{"start": 6, "end": 11, "clean_query": "white car"}}
<|user|>
Text: "old woman combing hair at night"
<|assistant|>
{{"start": 21, "end": 5, "clean_query": "old woman combing hair"}}
<|user|>
Text: "old man in striped shirt"
<|assistant|>
{{"start": 0, "end": 0, "clean_query": "old man in striped shirt"}}
<|user|>
Text: "{user_query}"
<|assistant|>
"""
    schema = {
        "type": "object",
        "properties": {
            "start":       {"type": "integer"},
            "end":         {"type": "integer"},
            "clean_query": {"type": "string"}
        },
        "required": ["start", "end", "clean_query"]
    }
    try:
        response = requests.post(LLM_URL, json={
            "prompt": prompt, "temperature": 0.1,
            "n_predict": 50, "json_schema": schema
        }, timeout=20)
        return json.loads(response.json().get("content", "").strip())
    except Exception as e:
        print(f"LLM parsing failed: {e}")
        return None


def embed_text(text):
    response = requests.post(
        EMBED_TEXT_API_URL,
        json={"text": 'cctv security camera footage of ' + text}
    )
    response.raise_for_status()
    return response.json()["embedding"]

def build_where(camera=None, date=None, hour=None, start_time=None, end_time=None):
    conditions = []
    if camera:
        conditions.append({"camera": {"$eq": camera}})
    if date:
        conditions.append({"date": {"$eq": date}})
    if start_time is not None and end_time is not None:
        conditions.append({"hour": {"$gte": start_time}})
        conditions.append({"hour": {"$lte": end_time}})
    elif hour:
        conditions.append({"hour": {"$gte": int(hour)}})
        conditions.append({"hour": {"$lte": int(hour) + 1}})

    if not conditions:    return None
    if len(conditions) == 1: return conditions[0]
    return {"$and": conditions}

def safe_get(meta, key, default="unknown"):
    return meta.get(key, default)

def query_db(text, n_results=9, camera=None, date=None, hour=None):
    cleaned_text = text
    start_time   = None
    end_time     = None

    if USE_LLM:
        llm = parse_time_to_json(text)
        if llm and "clean_query" in llm:
            cleaned_text = llm['clean_query']
            start_time   = llm['start']
            end_time     = llm['end']

    embedding    = embed_text(cleaned_text)
    where        = build_where(camera=camera, date=date, hour=hour,
                               start_time=start_time, end_time=end_time)
    fetch_amount = n_results * 3

    results = collection_cctv_images.query(
        query_embeddings=[embedding],
        n_results=fetch_amount,
        where=where,
        include=["metadatas", "distances"]
    )

    metas  = results["metadatas"][0]
    scores = results["distances"][0]

    if not metas:
        return {"results": []}

    formatted = []
    for meta, score in zip(metas, scores):
        formatted.append({
            "similarity": round(1 - score, 3),
            "camera":     safe_get(meta, 'camera'),
            "date":       safe_get(meta, 'date'),
            "hour":       safe_get(meta, 'hour', 'N/A'),
            "time":       safe_get(meta, 'time'),
            "image_path": safe_get(meta, 'image_path'),
        })
        if len(formatted) == n_results:
            break

    return {"results": formatted}


# --- Routes ---

@app.route('/api/search', methods=['POST'])
def search_api():
    data      = request.json
    text      = data.get('query')
    camera    = data.get('camera') or None
    date      = data.get('date')   or None
    hour      = data.get('hour')   or None
    n_results = int(data.get('n', 9))
    if not text:
        return jsonify({"error": "Query is required"}), 400
    return jsonify(query_db(text, n_results=n_results, camera=camera, date=date, hour=hour))

@app.route('/api/metadata')
def metadata_api():
    all_docs = collection_cctv_images.get(include=["metadatas"])
    metas    = all_docs.get("metadatas", [])
    cameras  = sorted(set(safe_get(m, "camera") for m in metas if "camera" in m))
    dates    = sorted(set(safe_get(m, "date")   for m in metas if "date"   in m), reverse=True)
    hours    = sorted(set(str(safe_get(m, "hour")) for m in metas if m.get("hour")))
    return jsonify({"cameras": cameras, "dates": dates, "hours": hours, "total": len(metas)})

@app.route('/api/cluster/run', methods=['GET'])
def cluster_run():
    try:
        response = requests.get(CLUSTERING_URL + "/api/run_clustering", timeout=10)
        return response.json()
    except Exception as e:
        print(f"Clustering failed.: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/cluster/stats')
def cluster_stats():
    cluster_stats_response = None
    overall_stats_response = None

    try:
        cluster_stats_response = (requests.get(CLUSTERING_URL + "/api/get_cluster_stats", timeout=10)).json()
    except Exception as e:
        print(f"Failed to get cluster stats: {e}")

    try:
        overall_stats_response = (requests.get(CLUSTERING_URL + "/api/get_overall_stats", timeout=10)).json()
    except Exception as e:
        print(f"Failed to get cluster stats: {e}")

    return jsonify({"clusters": cluster_stats_response, "stats": overall_stats_response})

@app.route('/api/cluster/name', methods=['POST'])
def cluster_name():
    data       = request.json
    cluster_id = data.get('cluster_id')
    name       = data.get('name', '').strip()
    try:
        response = (requests.post(CLUSTERING_URL + "/api/cluster/name",
                                  json={'cluster_id': cluster_id, 'name': name}, timeout=10)).json()
        return response
    except Exception as e:
        print(f"Failed to rename cluster: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/cluster/merge', methods=['POST'])
def cluster_merge():
    data      = request.json
    source_id = data.get('source_id')
    target_id = data.get('target_id')
    try:
        response = (requests.post(CLUSTERING_URL + "/api/cluster/merge",
                                  json={'source_id': source_id, 'target_id': target_id}, timeout=10)).json()
        return response
    except Exception as e:
        print(f"Failed to merge cluster: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/cluster/delete', methods=['POST'])
def cluster_delete():
    data       = request.json
    cluster_id = data.get('cluster_id')
    try:
        response = (requests.post(CLUSTERING_URL + "/api/cluster/delete",
                                  json={'cluster_id': cluster_id}, timeout=10)).json()
        return response
    except Exception as e:
        print(f"Failed to delete cluster: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/image')
def get_image():
    image_path = request.args.get('path')
    if not image_path or not os.path.isfile(image_path):
        return jsonify({"error":"Image not found"}), 400
    if WORKING_DIR not in image_path:
            return jsonify({"error":"Invalid image path"}), 400
    return send_file(image_path)

@app.route('/api/crop/delete', methods=['POST'])
def crop_delete():
    data       = request.json
    image_path = data.get('image_path')

    if not image_path:
        return jsonify({"error": "image_path required"}), 400


    if WORKING_DIR not in image_path:
        return jsonify({"error":"Invalid image path"}), 400

    try:
        collection_cctv_crops.delete(ids=[image_path])
        response_cleanup = (requests.post(CLEANUP_URL + "delete_snapshot",
                                          json={'image_path': image_path}, timeout=10)).json()
        remove_entry(image_path)#state db cleanup
        return jsonify({"success": True})
    except Exception as e:
        print(f"Failed to delete snapshot {image_path}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/snapshot/delete', methods=['POST'])
def snapshot_delete():
    data       = request.json
    image_path = data.get('image_path')

    if not image_path:
        return jsonify({"error": "image_path required"}), 400

    if WORKING_DIR not in image_path:
        return jsonify({"error":"Invalid image path"}), 400

    try:
        collection_cctv_images.delete(ids=[image_path])
        response_cleanup = (requests.post(CLEANUP_URL + "delete_snapshot",
                                          json={'image_path': image_path}, timeout=10)).json()
        search_remove_entry(image_path)#state db cleanup
        return jsonify({"success": True})
    except Exception as e:
        print(f"Failed to delete snapshot {image_path}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/snapshot/update_cluster', methods=['POST'])
def snapshot_update_cluster():
    data = request.json
    image_path = data.get('image_path')
    new_cluster_id  = data.get('new_cluster_id')
    new_person_name = data.get('new_person_name')

    if not image_path:
        return jsonify({"error": "image_path required"}), 400
    try:
        existing = collection_cctv_crops.get(ids=[image_path], include=['metadatas'])
        
        # Initialize with a fallback dictionary if the ID wasn't found or had no metadata
        current_metadata = {}
        if existing and existing['metadatas'] and existing['metadatas'][0]:
            current_metadata = existing['metadatas'][0]

        # 2. Merge the new updates directly into the existing fields
        current_metadata["person_name"] = new_person_name or current_metadata.get("person_name", "unknown")
        current_metadata["cluster_id"] = new_cluster_id or current_metadata.get("cluster_id", "unassigned")

        # 3. Push the preserved, updated dictionary back to the index
        collection_cctv_crops.update(
            ids=[image_path],
            metadatas=[current_metadata]
        )
        return jsonify({"success": True}), 200
    except Exception as e:
        print(f"Failed to update cluster of snapshot {image_path}: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/video')
def get_video():
    image_path = request.args.get('image_path')
    if not image_path:
        return jsonify({"error":"No path provided"}), 400

    if WORKING_DIR not in image_path:
        return jsonify({"error":"Invalid image path"}), 400

    vid_dir_path = image_path.replace('/var/cctv/snapshots', '/var/cctv/footage')
    vid_dir_path = vid_dir_path.replace('/var/cctv/crops', '/var/cctv/footage')

    dir_name    = os.path.dirname(vid_dir_path)
    name_no_ext = os.path.splitext(os.path.basename(vid_dir_path))[0]
    timestamp   = name_no_ext.split('_')[0]
    matches     = glob.glob(os.path.join(dir_name, timestamp + ".*"))

    if not matches:
        print(f"DEBUG: Could not find video for {timestamp} in {dir_name}")
        return "Video not found", 404

    def generate():
        cmd = [
            '/usr/bin/ffmpeg', '-loglevel', 'error',
            '-i', matches[0],
            '-c:v', 'libx264', '-preset', 'ultrafast', '-crf', '28',
            '-c:a', 'aac',
            '-movflags', 'frag_keyframe+empty_moov',
            '-f', 'mp4', 'pipe:1'
        ]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            for chunk in iter(lambda: proc.stdout.read(8192), b""):
                yield chunk
        finally:
            proc.kill()
            proc.wait()

    return Response(generate(), mimetype='video/mp4')

@app.route('/api/debug/view/cctv_images')
def debug_db():
    sample = collection_cctv_images.get(limit=5, include=["metadatas"])
    return jsonify({"sample_metadata": sample["metadatas"]})

@app.route('/api/debug/view/person_crops')
def debug_db2():
    sample = collection_cctv_crops.get(limit=5, include=["metadatas"])
    return jsonify({"sample_metadata": sample["metadatas"]})



@app.route('/api/health')
def health():
    status = {"service": "user_api", "chromadb": "unknown", "clustering": "unknown", "embedding": "unknown", "prediction": "unknown"}
    healthy = True

    try:
        collection_cctv_images.count()
        collection_cctv_crops.count()
        status["chromadb"] = "healthy"
    except Exception as e:
        status["chromadb"] = f"unhealthy: {e}"
        healthy = False

    try:
        r = requests.get(CLUSTERING_URL + "/health", timeout=3)
        status["clustering"] = "healthy" if r.ok else f"unhealthy: {r.status_code}"
    except Exception:
        status["clustering"] = "unreachable"
        healthy = False

    try:
        r = requests.get(EMBED_CENTRAL_SERVER_URL + "/health", timeout=3)
        status["embedding"] = "healthy" if r.ok else f"unhealthy: {r.status_code}"
    except Exception:
        status["embedding"] = "unreachable"
        healthy = False

    try:
        r = requests.get(PREDICTION_URL + "health", timeout=3)
        status["prediction"] = "healthy" if r.ok else f"unhealthy: {r.status_code}"
    except Exception:
        status["prediction"] = "unreachable"
        healthy = False

    status["status"] = "healthy" if healthy else "degraded"
    return jsonify(status), 200 if healthy else 503

if __name__ == '__main__':
    app.run(host=os.environ.get("API_SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("API_SERVER_PORT", "5000")),
            debug=True)