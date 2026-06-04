import io
import os
import base64
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image

import cv2
import openvino as ov
import numpy as np
import torch
import open_clip

import uvicorn

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="CCTV Embedding API")

#Load search embedding model
MODEL_NAME = os.environ.get("CLIP_MODEL_NAME", "ViT-H-14")
PRETRAINED = os.environ.get("CLIP_PRETRAINED", "laion2b_s32b_b79k")

#Load the person reid model
REID_MODEL_PATH = os.environ.get("REID_MODEL_PATH", "models/person-reidentification-retail-0277.xml")
core           = ov.Core()
model          = core.read_model(model=REID_MODEL_PATH)
compiled_model = core.compile_model(model, device_name="CPU")

print(f"[LOADING] OpenCLIP {MODEL_NAME} into RAM...")
model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED)
tokenizer = open_clip.get_tokenizer(MODEL_NAME)
model.eval()
print("[READY] Server is accepting requests.")

class TextRequest(BaseModel):
    text: str

class ImageRequest(BaseModel):
    image_path: str

@app.post("/embed/reid/image")
def embed_reid_image(req: ImageRequest):
    try:
        img = cv2.imread(req.image_path)
        img = cv2.resize(img, (128, 256))
        input_tensor = np.expand_dims(img.transpose(2, 0, 1), axis=0).astype(np.float32)
        embedding = compiled_model([input_tensor])[compiled_model.output(0)]
        return {"embedding":embedding[0].tolist()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed/search/text")
def embed_text(req: TextRequest):
    try:
        text_tokens = tokenizer([req.text])
        with torch.no_grad():
            features = model.encode_text(text_tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        return {"embedding": features[0].numpy().tolist()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed/search/image")
def embed_image(req: ImageRequest):
    try:
        # Load image from the shared local disk
        image = Image.open(req.image_path).convert("RGB")
        image_tensor = preprocess(image).unsqueeze(0)
        
        with torch.no_grad():
            features = model.encode_image(image_tensor)
            features = features / features.norm(dim=-1, keepdim=True)
        return {"embedding": features[0].numpy().tolist()}
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Image file not found on server disk")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "healthy", "service": "embedding", "model": MODEL_NAME}

if __name__ == "__main__":
    uvicorn.run(app,
                host=os.environ.get("EMBEDDING_SERVER_HOST", "0.0.0.0"),
                port=int(os.environ.get("EMBEDDING_SERVER_PORT", "8002")))
