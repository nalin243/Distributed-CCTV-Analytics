from annotated_types import IsDigits
from flask import Flask, request, jsonify
import chromadb
from datetime import datetime
import logging

from collections import defaultdict
import json
import builtins
import traceback

import os

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)

# --- Logging ---
LOG_FILE = os.environ.get("LOG_FILE_CLEANUP", "/var/log/cctv-cleanup-microservice.log")
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

# --- Configuration ---
CHROMA_HOST = os.environ.get("CHROMA_HOST")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))
BASE_CCTV_DIR = os.environ.get("BASE_CCTV_DIR", "/var/cctv")

# Initialize ChromaDB client
chroma = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
person_crops_collection = chroma.get_collection(name="person_crops")
cctv_images_collection = chroma.get_collection(name="cctv_images")

def delete_snapshot_helper(image_path):
    try:
        abs_path = os.path.abspath(image_path)
        if not abs_path.startswith(BASE_CCTV_DIR):
            return False
            
        if os.path.exists(abs_path):
            os.remove(abs_path)
            return True
        return False
    except Exception:
        return False

@app.route('/delete_snapshot', methods=['POST'])
def delete_snapshot():
	data = request.json
	image_path = data.get('image_path')
	try:
		delete_snapshot_helper(image_path)
		return jsonify({"sucess":True})
	except Exception as e:
		print(e)
		return jsonify( {"error":str(e)} ),500

@app.route('/cleanup_unknowns', methods=['POST'])
def cleanup_unknowns():
	try:
		response = person_crops_collection.get(where={"person_name":"unknown"}, include=['metadatas'])
		ids = response['ids']

		sort_list = []
		for cid in ids:
			parts = cid.split('/')
			date_part = parts[5] # "Date-11-05-2026"
			time_part = parts[6] # "Time-14-16..."

			d, m, y = date_part.replace("Date-", "").split('-')
			sortable_key = f"{y}-{m}-{d}_{time_part}"
			sort_list.append((cid, sortable_key))

		sort_list.sort(key=lambda x: x[1], reverse=True)
		ids_to_delete = [item[0] for item in sort_list]

		person_crops_collection.delete(ids=ids_to_delete)

		for img_id in ids_to_delete:
			delete_snapshot_helper(img_id)

		return jsonify({"status":"success"}), 200

	except Exception as e:
		return jsonify({"error":str(e)}), 500

@app.route('/cleanup_noise', methods=['POST'])
def cleanup_noise():
	try:
		response = person_crops_collection.get(where={"person_name":"noise"}, include=['metadatas'])
		ids = response['ids']

		if len(ids)<450:
			return jsonify({"status":"Not enough noise"}), 200

		sort_list = []
		for cid in ids:
			parts = cid.split('/')
			date_part = parts[5] # "Date-11-05-2026"
			time_part = parts[6] # "Time-14-16..."

			d, m, y = date_part.replace("Date-", "").split('-')
			sortable_key = f"{y}-{m}-{d}_{time_part}"
			sort_list.append((cid, sortable_key))

		sort_list.sort(key=lambda x: x[1], reverse=True)
		ids_to_delete = [item[0] for item in sort_list[450:]]

		person_crops_collection.delete(ids=ids_to_delete)

		for img_id in ids_to_delete:
			delete_snapshot_helper(img_id)

		return jsonify({"status":"success"}), 200

	except Exception as e:
		return jsonify({"error":str(e)}), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    MIN_PER_CAMERA = 20
    NIGHT_RESERVE  = 10
    MAX_TOTAL      = 150
    NIGHT_HOUR     = 18        # 6 PM
    CAMERA_IDX     = 4

    try:

        results = person_crops_collection.get(
            where={"$and": [
                {"person_name": {"$ne": "noise"}},
                {"person_name": {"$ne": "unknown"}},
            ]},
            include=['metadatas']
        )
        unique_persons = {m['person_name'] for m in results['metadatas']}

        for person in unique_persons:

            response = person_crops_collection.get(
                where={"person_name": person},
                include=['metadatas']
            )
            ids   = response['ids']
            metas = response['metadatas']

            if len(ids) < MAX_TOTAL:
                continue

            entries = []
            for cid, meta in zip(ids, metas):
                parts     = cid.split('/')
                date_part = parts[5]                          # Date-19-05-2026
                time_part = parts[6]                          # Time-14-16-32
                d, mo, y  = date_part.replace("Date-", "").split('-')
                sort_key  = f"{y}-{mo}-{d}_{time_part}"
                hour      = int(time_part.replace("Time-", "").split('-')[0])
                camera    = (
                    meta.get('camera_name')
                    or meta.get('camera')
                    or parts[CAMERA_IDX]
                )
                entries.append({
                    'id':       cid,
                    'camera':   camera,
                    'sort_key': sort_key,
                    'is_night': hour >= NIGHT_HOUR,
                })

            entries.sort(key=lambda x: x['sort_key'], reverse=True)  # newest first

            #reserve night slots
            night_entries = [e for e in entries if e['is_night']]
            night_keep    = {e['id'] for e in night_entries[:NIGHT_RESERVE]}

            #group by the camera name
            camera_buckets: dict[str, list] = {}
            for e in entries:
                camera_buckets.setdefault(e['camera'], []).append(e)

            #largest remainder allocation
            camera_budget    = MAX_TOTAL - len(night_keep)#if there are no night entries discard it 
            num_cameras      = len(camera_buckets)
            estimated_total = num_cameras * MIN_PER_CAMERA
            remainder_slots  = max(0, camera_budget - estimated_total)
            total_images     = len(entries)

            # log.info(f"night_keep: {len(night_keep)}")
            # log.info(f"camera_budget: {camera_budget}")
            # log.info(f"estimated_total: {estimated_total}")
            # log.info(f"remainder_slots: {remainder_slots}")
            # log.info(f"total_images: {total_images}")

            # Exact fractional share each camera deserves of the remainder
            raw = {
                cam: int((len(cams) / total_images) * remainder_slots)
                for cam, cams in camera_buckets.items()
            }

            leftover = remainder_slots - sum(raw.values())

            # Hand the leftover slots to whoever had the biggest fractional loss, though this may fail if that camera does not actually have that many crops
            for cam in sorted(camera_buckets, key=lambda c: raw[c] - raw[c], reverse=True)[:leftover]:
                raw[cam] += 1

            ids_to_keep = set(night_keep) if len(night_keep)>0 else set()
            for cam, cam_entries in camera_buckets.items():#TO FIX: camera_buckets already contains night_entries, below code is just temporary until this can be fixed, count is fine but proportional allocations do not occur
                keep_count = MIN_PER_CAMERA + raw[cam]
                for e in cam_entries[:keep_count]:
                    ids_to_keep.add(e['id'])

            #if the leftover slotting failed just take remaining newest snapshots of the camera with largest amount of crops
            if len(ids_to_keep)<MAX_TOTAL:
                max_count_camera = builtins.sorted(camera_buckets, key=lambda x: len(camera_buckets[x]), reverse=True)
                for c in max_count_camera:

                    if(len(ids_to_keep)==MAX_TOTAL):
                        break

                    log.info(c)
                    for item in camera_buckets[c]:
                        if(len(ids_to_keep) == MAX_TOTAL):
                            break
                        ids_to_keep.add(item['id'])

            #perform deletions
            ids_to_delete = [cid for cid in ids if cid not in ids_to_keep]
            if ids_to_delete:
                person_crops_collection.delete(ids=ids_to_delete)
                for img_id in ids_to_delete:
                    delete_snapshot_helper(img_id)

    except Exception as e:
        error_stack = traceback.format_exc()
        log.error(f"Exception occured aborting deletion: {e}")
        log.error(f"Stack: {error_stack}")

    return jsonify({"success": True}), 200

if __name__ == '__main__':
    app.run(host=os.environ.get("CLEANUP_HOST"),
            port=int(os.environ.get("CLEANUP_PORT", "8009")),
            debug=True)
