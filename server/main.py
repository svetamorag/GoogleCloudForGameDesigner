"""Game Asset Studio - FastAPI backend.

Run:
    gcloud auth application-default login
    uvicorn server.main:app --reload --port 8000
"""

import base64
import binascii
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server import gemini_service, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("game_asset_studio")

app = FastAPI(title="Game Asset Studio")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

# Local tool: only answer requests addressed to localhost (blocks DNS
# rebinding). Set ALLOWED_HOSTS=comma,separated,hosts to serve elsewhere.
ALLOWED_HOSTS = [
    h.strip()
    for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1,::1").split(",")
    if h.strip()
]
app.add_middleware(TrustedHostMiddleware, allowed_hosts=ALLOWED_HOSTS)

_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; media-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    # Reject state-changing requests from foreign origins (browser CSRF).
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in ALLOWED_HOSTS:
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin requests are not allowed."},
            )
    response = await call_next(request)
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    return response


# ---------------------------------------------------------------- request models

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_IMAGE_B64_CHARS = 21_000_000  # base64 of 15 MB, with margin

PROJECT_ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"

ImageMime = Literal["image/png", "image/jpeg", "image/webp", "image/gif"]

ALL_VOICES = frozenset(v for group in gemini_service.VOICES.values() for v in group)


class CharacterRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=2000)
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


class EditRequest(BaseModel):
    image_b64: str = Field(min_length=1, max_length=MAX_IMAGE_B64_CHARS)
    mime_type: ImageMime = "image/png"
    instruction: str = Field(min_length=1, max_length=2000)
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


class BackgroundRequest(BaseModel):
    image_b64: str = Field(min_length=1, max_length=MAX_IMAGE_B64_CHARS)
    mime_type: ImageMime = "image/png"
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


class SheetRequest(BaseModel):
    image_b64: str = Field(min_length=1, max_length=MAX_IMAGE_B64_CHARS)
    mime_type: ImageMime = "image/png"
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    gender: Literal["male", "female"] = "female"
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


class VoiceBindRequest(BaseModel):
    character: str = Field(min_length=1, max_length=100)
    voice: str = Field(min_length=1, max_length=50)
    gender: Literal["male", "female"]


class DialogueRow(BaseModel):
    character: str = Field(min_length=1, max_length=100)
    line: str = Field(min_length=1, max_length=1000)


class BatchDialogueRequest(BaseModel):
    rows: list[DialogueRow] = Field(min_length=1, max_length=50)
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    style_guide: str = Field(default="", max_length=2000)


class StyleGuideRequest(BaseModel):
    style_guide: str = Field(default="", max_length=2000)


class ChatTurn(BaseModel):
    role: Literal["user", "model"]
    text: str = Field(max_length=8000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=40)
    has_image: bool = False


class UploadAssetRequest(BaseModel):
    image_b64: str = Field(min_length=1, max_length=MAX_IMAGE_B64_CHARS)
    mime_type: ImageMime = "image/png"
    label: str = Field(default="Upload", max_length=200)
    project_id: str = Field(default=storage.DEFAULT_PROJECT_ID, pattern=PROJECT_ID_PATTERN)


# ---------------------------------------------------------------- helpers

def _decode_image(data_b64: str) -> bytes:
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Image data is not valid base64.")
    if not raw:
        raise HTTPException(status_code=400, detail="Image data is empty.")
    if len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image exceeds the 15 MB size limit.")
    return raw


def _model_error(exc: Exception) -> HTTPException:
    """Log the full exception server-side; return a sanitized message to the UI."""
    logger.exception("Model request failed")
    status = 429 if gemini_service.is_quota_error(exc) else 502
    return HTTPException(status_code=status, detail=gemini_service.error_summary(exc))


# ---------------------------------------------------------------- endpoints

@app.post("/api/characters/generate")
async def generate_characters(req: CharacterRequest):
    project = await storage.get_project(req.project_id)
    style_guide = project["style_guide"] if project else ""
    try:
        result = await gemini_service.generate_characters(req.prompt, style_guide)
    except Exception as exc:
        raise _model_error(exc)
    if not result["images"]:
        raise HTTPException(status_code=502, detail="Model returned no images.")
    for image in result["images"]:
        await storage.save_asset(
            "generated", f"{image.get('label', 'Option')}: {req.prompt}",
            image["mime_type"], base64.b64decode(image["data_b64"]), req.project_id,
        )
    return result


@app.post("/api/images/edit")
async def edit_image(req: EditRequest):
    image_bytes = _decode_image(req.image_b64)
    try:
        image = await gemini_service.edit_image(image_bytes, req.mime_type, req.instruction)
    except Exception as exc:
        raise _model_error(exc)
    await storage.save_asset(
        "edited", req.instruction, image["mime_type"],
        base64.b64decode(image["data_b64"]), req.project_id,
    )
    return {"image": image}


@app.post("/api/images/remove-background")
async def remove_background(req: BackgroundRequest):
    image_bytes = _decode_image(req.image_b64)
    try:
        image = await gemini_service.remove_background(image_bytes, req.mime_type)
    except Exception as exc:
        raise _model_error(exc)
    await storage.save_asset(
        "edited", "Background removed", image["mime_type"],
        base64.b64decode(image["data_b64"]), req.project_id,
    )
    return {"image": image}


@app.post("/api/characters/sheet")
async def character_sheet(req: SheetRequest):
    image_bytes = _decode_image(req.image_b64)
    project = await storage.get_project(req.project_id)
    style_guide = project["style_guide"] if project else ""
    try:
        result = await gemini_service.generate_character_sheet(
            image_bytes, req.mime_type, style_guide
        )
    except Exception as exc:
        raise _model_error(exc)
    if not result["images"]:
        raise HTTPException(status_code=502, detail="Model returned no character sheet views.")
    for image in result["images"]:
        await storage.save_asset(
            "generated", f"Character sheet: {image.get('label', 'View')}",
            image["mime_type"], base64.b64decode(image["data_b64"]), req.project_id,
        )
    return result


@app.post("/api/voice/generate")
async def generate_voices(req: VoiceRequest):
    try:
        clips = await gemini_service.generate_voices(req.text, req.gender)
    except Exception as exc:
        raise _model_error(exc)
    for clip in clips:
        await storage.save_asset(
            "voice", f"{clip['voice']}: {req.text}", "audio/wav",
            base64.b64decode(clip["wav_b64"]), req.project_id,
        )
    return {"clips": clips, "sample_rate": gemini_service.AUDIO_SAMPLE_RATE}


@app.post("/api/voices/bind")
async def bind_voice(req: VoiceBindRequest):
    if req.voice not in ALL_VOICES:
        raise HTTPException(status_code=400, detail="Unknown voice name.")
    binding = await storage.bind_voice(req.character, req.voice, req.gender)
    return {"character": req.character, "binding": binding}


@app.get("/api/voices/bindings")
async def list_voice_bindings():
    return {"bindings": await storage.list_voice_bindings()}


@app.post("/api/voice/batch")
async def batch_dialogue(req: BatchDialogueRequest):
    clips = []
    errors = []
    for i, row in enumerate(req.rows):
        binding = await storage.get_voice_binding(row.character)
        voice_name = (
            binding["voice"]
            if binding and binding.get("voice") in ALL_VOICES
            else gemini_service.VOICES["female"][0]
        )
        try:
            clip = await gemini_service.generate_voice(row.line, voice_name)
        except Exception as exc:
            logger.exception("Batch line %d (%s) failed", i + 1, row.character)
            errors.append(
                f"{row.character} (line {i + 1}): {gemini_service.error_summary(exc)}"
            )
            continue
        asset = await storage.save_asset(
            "voice", f"{row.character}: {row.line}", "audio/wav",
            base64.b64decode(clip["wav_b64"]), req.project_id,
        )
        clips.append({
            "character": row.character, "voice": voice_name, "line": row.line,
            "wav_b64": clip["wav_b64"], "filename": asset["filename"],
        })
    return {"clips": clips, "errors": errors}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        result = await gemini_service.chat(
            [t.model_dump() for t in req.history], req.message, req.has_image
        )
    except Exception as exc:
        raise _model_error(exc)
    return result


@app.get("/api/assets")
async def list_assets(project_id: str | None = None):
    return {"assets": await storage.list_assets(project_id)}


@app.post("/api/assets/upload")
async def upload_asset(req: UploadAssetRequest):
    data = _decode_image(req.image_b64)
    entry = await storage.save_asset(
        "uploaded", req.label, req.mime_type, data, req.project_id
    )
    return {"asset": entry}


@app.get("/api/projects")
async def list_projects():
    return {"projects": await storage.list_projects()}


@app.post("/api/projects")
async def create_project(req: ProjectRequest):
    return {"project": await storage.create_project(req.name, req.style_guide)}


@app.put("/api/projects/{project_id}/style-guide")
async def set_style_guide(project_id: str, req: StyleGuideRequest):
    project = await storage.update_project_style_guide(project_id, req.style_guide)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {"project": project}


@app.delete("/api/assets/{asset_id}")
async def delete_asset(asset_id: str):
    if not await storage.delete_asset(asset_id):
        raise HTTPException(status_code=404, detail="Asset not found.")
    return {"ok": True}


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


storage.ASSETS_DIR.mkdir(exist_ok=True)
app.mount("/assets", StaticFiles(directory=storage.ASSETS_DIR), name="assets")
app.mount("/", StaticFiles(directory=WEB_DIR), name="static")
