import io
import os
import base64
import torch
import open_clip
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image

import uvicorn

from dotenv import load_dotenv
load_dotenv()

app = FastAPI(title="CCTV Embedding API")

# --- Load Model ONCE ---
MODEL_NAME = os.environ.get("CLIP_MODEL_NAME", "ViT-H-14")
PRETRAINED = os.environ.get("CLIP_PRETRAINED", "laion2b_s32b_b79k")

print(f"[LOADING] OpenCLIP {MODEL_NAME} into RAM...")
model, _, preprocess = open_clip.create_model_and_transforms(MODEL_NAME, pretrained=PRETRAINED)
tokenizer = open_clip.get_tokenizer(MODEL_NAME)
model.eval()
print("[READY] Server is accepting requests.")

# --- API Data Models ---
class TextRequest(BaseModel):
    text: str

class ImageRequest(BaseModel):
    image_path: str

# --- Endpoints ---
@app.post("/embed/text")
def embed_text(req: TextRequest):
    try:
        text_tokens = tokenizer([req.text])
        with torch.no_grad():
            features = model.encode_text(text_tokens)
            features = features / features.norm(dim=-1, keepdim=True)
        return {"embedding": features[0].numpy().tolist()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/embed/image")
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

if __name__ == "__main__":
    uvicorn.run(app,
                host=os.environ.get("EMBEDDING_SERVER_HOST", "0.0.0.0"),
                port=int(os.environ.get("EMBEDDING_SERVER_PORT", "8002")))
