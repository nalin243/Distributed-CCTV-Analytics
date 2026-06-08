import numpy as np
from flask import Flask, request, jsonify
import chromadb
from collections import defaultdict
import os

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# --- Configuration ---
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
COLLECTION_NAME = os.environ.get("CROPS_COLLECTION_NAME","")
THRESHOLD = float(os.environ.get("DISTANCE_THRESHOLD", "0.3"))
GAP_THRESHOLD = float(os.environ.get("GAP_THRESHOLD", "0.08"))
FALLBACK_N = int(os.environ.get("FALLBACK_N", "10"))
RERANK_THRESHOLD = float(os.environ.get("RERANK_THRESHOLD", "5.0"))
RANK_DISTRIBUTION_THRESHOLD = float(os.environ.get("RANK_DISTRIBUTION_THRESHOLD", "0.60"))
RERANK_MIN_DISTANCE_THRESHOLD = float(os.environ.get("RERANK_MIN_DISTANCE_THRESHOLD", "0.20"))

# Initialize ChromaDB client
chroma = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection = chroma.get_collection(name=COLLECTION_NAME)

def rerank(embedding, candidate_name, candidate_cluster_id,agree_threshold=RERANK_THRESHOLD):

    cluster_results = collection.get(
            where={"cluster_id": candidate_cluster_id} if candidate_cluster_id != "unassigned" else {"person_name": candidate_name},
            include=["embeddings"]
        )
    all_embeddings = cluster_results.get("embeddings")

    # Absolute safety check: If the entire database has zero files for this person
    if all_embeddings is None or len(all_embeddings) == 0:
        return None

    # 2. Convert to NumPy once and Sample
    # This avoids the "Population must be a sequence" error
    all_vecs = np.array(all_embeddings, dtype=np.float32)
    
    sample_mat = all_vecs
    sample_size = len(sample_mat)

    # 3. Vectorized Math (Cosine Distance)
    # Normalize query vector
    query_vec = np.array(embedding, dtype=np.float32)
    query_vec /= (np.linalg.norm(query_vec) + 1e-9)

    # Normalize sample matrix rows for consistent cosine similarity
    norms = np.linalg.norm(sample_mat, axis=1, keepdims=True)
    sample_mat /= (norms + 1e-9)

    # Compute all similarities in one CPU burst
    # Dot product of (N, 256) @ (256,) -> (N,)
    sims = sample_mat @ query_vec
    dists = 1 - sims

    # 4. Compile Results
    # Using float() and int() casts ensures the JSON response is serializable
    matches = int((dists <= THRESHOLD).sum())
    # agree_ratio = matches / sample_size

    confirmed = False
    if (bool(matches >= agree_threshold) or (np.min(dists) < RERANK_MIN_DISTANCE_THRESHOLD) ):
        confirmed = True

    return {
        "confirmed":   confirmed,
        "matches":     round(float(matches), 3),
        "mean_dist":   round(float(np.mean(dists)), 3),
        "min_dist":    round(float(np.min(dists)),  3),
        "max_dist":    round(float(np.max(dists)),  3),
        "n_compared":  int(sample_size),
        "n_agreed":    int(matches)
    }

@app.route('/predict', methods=['POST'])
def predict():
    data      = request.json
    embedding = data.get('embedding')
    camera = data.get('camera')
    threshold = float(data.get('threshold', THRESHOLD))
    n_votes   = int(data.get('n_votes', 5))   # how many neighbours to poll

    if not embedding:
        return jsonify({"error": "No embedding provided"}), 400

    try:
        # Query top-k nearest named crops
        results = collection.query(
            query_embeddings=[embedding],
            n_results=n_votes,
            where={
            "$and":[
                {"person_name": {"$nin": ["unknown","noise"]}},
                {"camera": {"$eq":camera}}
            ]
            },
            include=["metadatas", "distances"]
        )

        distances = results["distances"][0]   # list of n_votes distances
        metas     = results["metadatas"][0]   # list of n_votes metadatas

        if len(distances) < 5: #the person has probably not appeared in that camera before, try if it gets a match from other cameras
            # Query top-k nearest named crops
            results = collection.query(
            query_embeddings=[embedding],
            n_results=n_votes,
            where={
                "person_name": {"$nin": ["unknown","noise"]}
            },
            include=["metadatas", "distances"]
        )

        distances = results["distances"][0]   # list of n_votes distances
        metas     = results["metadatas"][0]   # list of n_votes metadatas

        # print(f"[DEBUG] {results}")

        if not distances:
            return jsonify({
                "identity": "unknown",
                "match_found": False, 
                "reason": "no_named_crops"
            })

        # Weighted vote across top-k neighbours
        vote_scores = {}
        min_distances = {}
        for dist, meta in zip(distances, metas):
            name   = meta.get("person_name", "unknown")
            weight = 1.0 / (dist + 1e-6)
            vote_scores[name] = vote_scores.get(name, 0.0) + weight
            min_distances[name] = min(min_distances.get(name,float('inf')),dist)

        # Sort by vote score
        ranked     = sorted(vote_scores.items(), key=lambda x: x[1], reverse=True)
        best_name  = ranked[0][0]
        best_score = ranked[0][1]

        print(f"[DEBUG] {ranked}")

        # After determining best_name, find the nearest crop that actually belongs to them
        best_cluster_id = "unassigned"
        for dist, meta in zip(distances, metas):
            if meta.get("person_name") == best_name:
                best_cluster_id = meta.get("cluster_id", "unassigned")
                break   # first hit is already the closest one for that person

        total_score = sum(s for _, s in ranked)
        norm_ranked = [(name, score / total_score) for name, score in ranked]

        match_found = False

        if len(ranked) > 1:
            print(f"[DEBUG] Winner has rank distribution of: {norm_ranked[0][1]}, {best_name}: {min_distances[best_name]} (distance)")
            if(norm_ranked[0][1] < RANK_DISTRIBUTION_THRESHOLD):
                response = rerank(embedding,best_name,best_cluster_id)
                print(f"[DEBUG] best_name: {best_name}: {response}")
                if response is not None and response['confirmed']:
                    match_found = True
                else:
                    match_found = False
            else:
                if min_distances[best_name] < THRESHOLD:
                    match_found = True
                else:
                    match_found = False
        else:
            print(f"[DEBUG] Only one result returned, {best_name}: {min_distances[best_name]} (distance)")
            if min_distances[best_name] < THRESHOLD:
                match_found = True
            else:
                match_found = False

        return jsonify({
            "identity":     best_name,
            "match_found":  match_found,
            "cluster_id": best_cluster_id
        })



    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health():
    try:
        count = collection.count()
        return jsonify({"status": "healthy", "service": "prediction", "crops_count": count})
    except Exception as e:
        return jsonify({"status": "unhealthy", "service": "prediction", "error": str(e)}), 503

if __name__ == '__main__':
    app.run(host=os.environ.get("PREDICTION_SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("PREDICTION_SERVER_PORT", "8010")),
            debug=True)