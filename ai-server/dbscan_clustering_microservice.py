import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.preprocessing import normalize
from flask import Flask, request, jsonify, render_template_string, send_file, Response
import chromadb
import uuid

import requests
import os
import json

from dotenv import load_dotenv
load_dotenv()

from state import remove_entry

CLUSTER_EPS     = float(os.environ.get("CLUSTER_EPS", "0.40"))
CLUSTER_SAMPLES = int(os.environ.get("CLUSTER_SAMPLES", "2"))
NAMES_FILE      = os.environ.get("NAMES_FILE", "/var/cctv/person_names.json")

CLEANUP_URL     = os.environ.get("CLEANUP_URL","")

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

SNAPSHOTS_COLLECTION_NAME = os.environ.get("SNAPSHOTS_COLLECTION_NAME","")
CROPS_COLLECTION_NAME = os.environ.get("CROPS_COLLECTION_NAME","")

# 1. Connect to your local ChromaDB
chroma = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection_cctv_crops  = chroma.get_collection(name=CROPS_COLLECTION_NAME)
collection_cctv_images = chroma.get_collection(name=SNAPSHOTS_COLLECTION_NAME)

app = Flask(__name__)

# --- Person names persistence ---
def load_names():
    if not os.path.exists(NAMES_FILE):
        return {}
    with open(NAMES_FILE) as f:
        return json.load(f)

def save_names(names):
    with open(NAMES_FILE, 'w') as f:
        json.dump(names, f, indent=2)

# --- Helper functions ---
def safe_get(meta, key, default="unknown"):
    return meta.get(key, default)

# --- Clustering ---
@app.route('/api/run_clustering', methods=['GET'])
def run_clustering():
    """Run DBSCAN on all person crop embeddings and update cluster_id in ChromaDB."""
    results    = collection_cctv_crops.get(where={"cluster_id": "unassigned"},include=["embeddings", "metadatas"])
    ids        = results["ids"]
    embeddings = results["embeddings"]
    metas      = results["metadatas"]

    if not embeddings.size>0 or len(embeddings) < 2:
        return {"message": "Not enough data to cluster", "clusters": 0, "noise": 0}

    X      = np.array(embeddings)
    labels = DBSCAN(eps=CLUSTER_EPS, min_samples=CLUSTER_SAMPLES, metric="cosine").fit_predict(X)

    # 3. Generate permanent unique IDs for the new clusters found
    unique_dbscan_labels = set(labels)
    cluster_id_map = {}
    for label in unique_dbscan_labels:
        if label != -1:
            # Create a permanent short ID like 'cluster_8f3b'
            cluster_id_map[label] = f"cluster_{uuid.uuid4().hex[:4]}"

    # 4. Batch update ChromaDB
    batch_metadatas = []
    for id_, label, meta in zip(ids, labels, metas):
        if label == -1:
            final_cluster_id = "noise"
            person_name = "noise"
        else:
            final_cluster_id = cluster_id_map[label]
            person_name = "unknown" # Newly discovered people are always Unknown at first
            
        collection_cctv_crops.update(
            ids=[id_],
            metadatas=[{**meta, "cluster_id": final_cluster_id, "person_name": person_name}]
        )

    n_clusters = len(cluster_id_map)
    n_noise = int(np.sum(labels == -1))
    return jsonify({"message": "Delta clustering complete", "clusters": n_clusters, "noise": n_noise})

@app.route('/api/get_cluster_stats', methods=['GET'])
def get_cluster_stats():
    """Build cluster statistics for the UI."""
    results  = collection_cctv_crops.get(include=["metadatas"])
    metas    = results["metadatas"]
    names    = load_names()

    if not metas:
        return []

    clusters = {}
    for meta in metas:
        cid = safe_get(meta, "cluster_id", "unassigned")
        if cid == "noise":
            continue

        if cid not in clusters:
            clusters[cid] = {
                "cluster_id":   cid,
                "person_name":  names.get(cid, safe_get(meta, "person_name", "Unknown")),
                "count":        0,
                "cameras":      set(),
                "dates":        set(),
                "last_seen":    None,
                "crop_paths":   [],
                "source_paths": [],
            }

        c = clusters[cid]
        c["count"]    += 1
        c["cameras"].add(safe_get(meta, "camera"))
        c["dates"].add(safe_get(meta, "date"))

        ts = safe_get(meta, "time", None)
        if ts and (c["last_seen"] is None or ts > c["last_seen"]):
            c["last_seen"] = ts

        if len(c["crop_paths"]) < 5:
            crop = safe_get(meta, "crop_path", None)
            src  = safe_get(meta, "image_path", None)
            if crop:  c["crop_paths"].append(crop)
            if src:   c["source_paths"].append(src)

    # Convert sets and sort by count
    result = []
    for c in clusters.values():
        c["cameras"] = sorted(c["cameras"])
        c["dates"]   = sorted(c["dates"], reverse=True)
        result.append(c)

    return sorted(result, key=lambda x: x["count"], reverse=True)

@app.route('/api/get_overall_stats', methods=['GET'])
def get_overall_stats():
    """Overall database statistics."""
    img_metas  = collection_cctv_images.get(include=["metadatas"])["metadatas"]
    crop_metas = collection_cctv_crops.get(include=["metadatas"])["metadatas"]

    total_images = len(img_metas)
    total_crops  = len(crop_metas)

    camera_counts = {}
    for m in img_metas:
        cam = safe_get(m, "camera")
        camera_counts[cam] = camera_counts.get(cam, 0) + 1

    n_clusters = len(set(
        safe_get(m, "cluster_id") for m in crop_metas
        if safe_get(m, "cluster_id") not in ("unassigned", "noise", "unknown")
    ))

    named = load_names()

    return {
        "total_images":  total_images,
        "total_crops":   total_crops,
        "total_clusters": n_clusters,
        "named_persons": len(named),
        "camera_counts": camera_counts,
    }

@app.route('/api/cluster/name', methods=['POST'])
def cluster_name():
    data       = request.json
    cluster_id = data.get('cluster_id')
    name       = data.get('name', '').strip()

    if not cluster_id or not name:
        return jsonify({"error": "cluster_id and name required"}), 400

    names              = load_names()
    names[cluster_id]  = name
    save_names(names)

    # Update all entries in this cluster
    results = collection_cctv_crops.get(include=["metadatas"])
    for id_, meta in zip(results["ids"], results["metadatas"]):
        if safe_get(meta, "cluster_id") == cluster_id:
            collection_cctv_crops.update(
                ids=[id_],
                metadatas=[{**meta, "person_name": name}]
            )

    return jsonify({"success": True, "cluster_id": cluster_id, "name": name})

@app.route('/api/cluster/merge', methods=['POST'])
def cluster_merge():
    """Merge two clusters into one."""
    data       = request.json
    source_id  = data.get('source_id')
    target_id  = data.get('target_id')

    if not source_id or not target_id:
        return jsonify({"error": "source_id and target_id required"}), 400

    names = load_names()
    target_name = names.get(target_id, "Unknown")

    results = collection_cctv_crops.get(include=["metadatas"])
    merged  = 0
    for id_, meta in zip(results["ids"], results["metadatas"]):
        if safe_get(meta, "cluster_id") == source_id:
            collection_cctv_crops.update(
                ids=[id_],
                metadatas=[{**meta, "cluster_id": target_id, "person_name": target_name}]
            )
            merged += 1

    # Remove source from names
    names.pop(source_id, None)
    save_names(names)

    return jsonify({"success": True, "merged": merged, "into": target_id})

@app.route('/api/cluster/delete', methods=['POST'])
def cluster_delete():
    """Delete all entries in a cluster."""
    data       = request.json
    cluster_id = data.get('cluster_id')

    if not cluster_id:
        return jsonify({"error": "cluster_id required"}), 400

    results = collection_cctv_crops.get(include=["metadatas"])
    del_ids = [id_ for id_, meta in zip(results["ids"], results["metadatas"])
               if safe_get(meta, "cluster_id") == cluster_id]

    if del_ids:
        collection_cctv_crops.delete(ids=del_ids)
        try:
            for image_path in del_ids:
                response_cleanup = (requests.post(CLEANUP_URL + "delete_snapshot",
                                                  json={'image_path': image_path}, timeout=3)).json()
                remove_entry(image_path)#state db cleanup
        except Exception as e:
            print("Error while deleting images", str(e))
            return jsonify({"error": str(e)}), 500


    names = load_names()
    names.pop(cluster_id, None)
    save_names(names)

    return jsonify({"success": True, "deleted": len(del_ids)})

if __name__ == '__main__':
    app.run(host=os.environ.get("CLUSTERING_SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("CLUSTERING_SERVER_PORT", "8005")),
            debug=True)