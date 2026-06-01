import numpy as np
from flask import Flask, request, jsonify
import chromadb
from sklearn.preprocessing import normalize
from collections import defaultdict
import random
import numpy as np
import os

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# --- Configuration ---
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
COLLECTION_NAME = os.environ.get("CROPS_COLLECTION_NAME","")
THRESHOLD = float(os.environ.get("PREDICTION_THRESHOLD", "0.75"))
GAP_THRESHOLD = float(os.environ.get("GAP_THRESHOLD", "0.08"))
RERANK_N = int(os.environ.get("RERANK_N", "20"))
RERANK_THRESHOLD = float(os.environ.get("RERANK_THRESHOLD", "0.50"))

# Initialize ChromaDB client
chroma = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
collection = chroma.get_collection(name=COLLECTION_NAME)

def rerank(embedding, candidate_name, candidate_cluster_id,camera,
           n=RERANK_N, agree_threshold=RERANK_THRESHOLD):
    # We prioritize cluster_id but fallback to person_name if unassigned
    
    cluster_results = collection.get(
        where={
            "$and": [
                {"cluster_id": candidate_cluster_id} if candidate_cluster_id != "unassigned" else {"person_name": candidate_name},
                {"camera": {"$eq": camera}}
            ]
        },
        include=["embeddings"]
    )
    all_embeddings = cluster_results.get("embeddings")

    #Trigger global fallback if camera has 0 history OR not enough samples
    if all_embeddings is None or len(all_embeddings) < n:
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
    sample_size = min(n, len(all_vecs))
    
    # Randomly select indices for the comparison
    indices = np.random.choice(len(all_vecs), sample_size, replace=False)
    sample_mat = all_vecs[indices]

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
    agree_ratio = matches / sample_size

    return {
        "confirmed":   bool(agree_ratio >= agree_threshold),
        "agree_ratio": round(float(agree_ratio), 3),
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
                {"person_name": {"$ne": "Unknown"}},
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
                "person_name": {"$ne": "Unknown"}
            },
            include=["metadatas", "distances"]
        )

        distances = results["distances"][0]   # list of n_votes distances
        metas     = results["metadatas"][0]   # list of n_votes metadatas

        if not distances:
            return jsonify({"identity": "Unknown", "confidence": 0.0,
                            "match_found": False, "reason": "no_named_crops"})

        # Nearest neighbour check — if closest is too far, reject immediately
        nearest_dist = distances[0]
        if nearest_dist > threshold:
            return jsonify({
                "identity":    "Unknown",
                "confidence":  round(1 - nearest_dist, 3),
                "match_found": False,
                "reason":      "below_threshold",
                "nearest_dist": round(nearest_dist, 3)
            })

        # Weighted vote across top-k neighbours
        # Weight = 1 / distance so closer neighbours vote stronger
        vote_scores = {}
        for dist, meta in zip(distances, metas):
            name   = meta.get("person_name", "Unknown")
            weight = 1.0 / (dist + 1e-6)
            vote_scores[name] = vote_scores.get(name, 0.0) + weight

        # Sort by vote score
        ranked     = sorted(vote_scores.items(), key=lambda x: x[1], reverse=True)
        best_name  = ranked[0][0]
        best_score = ranked[0][1]

        # After determining best_name, find the nearest crop that actually belongs to them
        best_cluster_id = "unassigned"
        for dist, meta in zip(distances, metas):
            if meta.get("person_name") == best_name:
                best_cluster_id = meta.get("cluster_id", "unassigned")
                break   # first hit is already the closest one for that person

        # Ambiguity check — runner-up too close
        if len(ranked) > 1:
            second_score = ranked[1][1]
            total        = sum(s for _, s in ranked)
            gap          = (best_score - second_score) / total
            if gap < GAP_THRESHOLD:
                return jsonify({
                    "identity":    "unknown",
                    "confidence":  round(best_score / total, 3),
                    "match_found": False,
                    "reason":      "ambiguous",
                    "candidates":  [{"name": n, "score": round(s/total, 3)}
                                    for n, s in ranked[:3]]
                })

        total      = sum(s for _, s in ranked)
        confidence = best_score / total

        response = rerank(embedding,best_name,best_cluster_id,camera)
        print(response)
        if response is not None and response['confirmed']:
            return jsonify({
                "identity":     best_name,
                "confidence":   round(float(confidence), 3),
                "match_found":  True,
                "nearest_dist": round(nearest_dist, 3),
                "cluster_id": best_cluster_id
            })
        else:
            return jsonify({
                "identity":     best_name,
                "confidence":   round(float(confidence), 3),
                "match_found":  False,
                "nearest_dist": round(nearest_dist, 3),
                "cluster_id": best_cluster_id
            })

    except Exception as e:
        print(e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host=os.environ.get("PREDICTION_SERVER_HOST", "0.0.0.0"),
            port=int(os.environ.get("PREDICTION_SERVER_PORT", "8010")),
            debug=True)