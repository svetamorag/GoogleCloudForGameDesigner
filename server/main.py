"""Game Asset Studio - FastAPI backend.

Run:
    gcloud auth application-default login
    uvicorn server.main:app --reload --port 8000
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server import gemini_service, storage

app = FastAPI(title="Game Asset Studio")

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class CharacterRequest(BaseModel):
    prompt: str = Field(min_length=1)
    project_id: str = storage.DEFAULT_PROJECT_ID


class EditRequest(BaseModel):
    image_b64: str
    mime_type: str = "image/png"
    instruction: str = Field(min_length=1)
    project_id: str = storage.DEFAULT_PROJECT_ID


class BackgroundRequest(BaseModel):
    image_b64: str
    mime_type: str = "image/png"
    project_id: str = storage.DEFAULT_PROJECT_ID


class SheetRequest(BaseModel):
    image_b64: str
    mime_type: str = "image/png"
    project_id: str = storage.DEFAULT_PROJECT_ID


class VoiceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    gender: Literal["male", "female"] = "female"
    project_id: str = storage.DEFAULT_PROJECT_ID


class VoiceBindRequest(BaseModel):
    character: str = Field(min_length=1, max_length=100)
    voice: str
    gender: Literal["male", "female"]


class DialogueRow(BaseModel):
    character: str = Field(min_length=1, max_length=100)
    line: str = Field(min_length=1, max_length=1000)


class BatchDialogueRequest(BaseModel):
    rows: list[DialogueRow]
    project_id: str = storage.DEFAULT_PROJECT_ID


class ProjectRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    style_guide: str = ""


class StyleGuideRequest(BaseModel):
    style_guide: str = ""


class ChatTurn(BaseModel):
    role: str  # "user" | "model"
    text: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    history: list[ChatTurn] = []
    has_image: bool = False


def _wrap(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=str(exc))


@app.post("/api/characters/generate")
async def generate_characters(req: CharacterRequest):
    project = await storage.get_project(req.project_id)
    style_guide = project["style_guide"] if project else ""
    try:
        result = await gemini_service.generate_characters(req.prompt, style_guide)
    except Exception as exc:  # surface model/auth errors to the UI
        raise _wrap(exc)
    if not result["images"]:
        raise HTTPException(status_code=502, detail="Model returned no images.")
    for image in result["images"]:
        await storage.save_asset(
            "generated", f"{image.get('label', 'Option')}: {req.prompt}",
            image["mime_type"], image["data_b64"], req.project_id,
        )
    return result


@app.post("/api/images/edit")
async def edit_image(req: EditRequest):
    try:
        image = await gemini_service.edit_image(req.image_b64, req.mime_type, req.instruction)
    except Exception as exc:
        raise _wrap(exc)
    await storage.save_asset(
        "edited", req.instruction, image["mime_type"], image["data_b64"], req.project_id
    )
    return {"image": image}


@app.post("/api/images/remove-background")
async def remove_background(req: BackgroundRequest):
    try:
        image = await gemini_service.remove_background(req.image_b64, req.mime_type)
    except Exception as exc:
        raise _wrap(exc)
    await storage.save_asset(
        "edited", "Background removed", image["mime_type"], image["data_b64"], req.project_id
    )
    return {"image": image}


@app.post("/api/characters/sheet")
async def character_sheet(req: SheetRequest):
    project = await storage.get_project(req.project_id)
    style_guide = project["style_guide"] if project else ""
    try:
        result = await gemini_service.generate_character_sheet(
            req.image_b64, req.mime_type, style_guide
        )
    except Exception as exc:
        raise _wrap(exc)
    if not result["images"]:
        raise HTTPException(status_code=502, detail="Model returned no character sheet views.")
    for image in result["images"]:
        await storage.save_asset(
            "generated", f"Character sheet: {image.get('label', 'View')}",
            image["mime_type"], image["data_b64"], req.project_id,
        )
    return result


@app.post("/api/voice/generate")
async def generate_voices(req: VoiceRequest):
    try:
        clips = await gemini_service.generate_voices(req.text, req.gender)
    except Exception as exc:
        raise _wrap(exc)
    for clip in clips:
        await storage.save_asset(
            "voice", f"{clip['voice']}: {req.text}", "audio/wav", clip["wav_b64"], req.project_id
        )
    return {"clips": clips, "sample_rate": gemini_service.AUDIO_SAMPLE_RATE}


@app.post("/api/voices/bind")
async def bind_voice(req: VoiceBindRequest):
    binding = await storage.bind_voice(req.character, req.voice, req.gender)
    return {"character": req.character, "binding": binding}


@app.get("/api/voices/bindings")
async def list_voice_bindings():
    return {"bindings": await storage.list_voice_bindings()}


@app.post("/api/voice/batch")
async def batch_dialogue(req: BatchDialogueRequest):
    if not req.rows:
        raise HTTPException(status_code=400, detail="No dialogue rows provided.")
    clips = []
    errors = []
    for i, row in enumerate(req.rows):
        binding = await storage.get_voice_binding(row.character)
        voice_name = binding["voice"] if binding else gemini_service.VOICES["female"][0]
        try:
            clip = await gemini_service.generate_voice(row.line, voice_name)
        except Exception as exc:
            errors.append(f"{row.character} (line {i + 1}): {str(exc)[:150]}")
            continue
        asset = await storage.save_asset(
            "voice", f"{row.character}: {row.line}", "audio/wav", clip["wav_b64"], req.project_id
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
        raise _wrap(exc)
    return result


class UploadAssetRequest(BaseModel):
    image_b64: str
    mime_type: str = "image/png"
    label: str = "Upload"
    project_id: str = storage.DEFAULT_PROJECT_ID


@app.get("/api/assets")
async def list_assets(project_id: str | None = None):
    return {"assets": await storage.list_assets(project_id)}


@app.post("/api/assets/upload")
async def upload_asset(req: UploadAssetRequest):
    entry = await storage.save_asset(
        "uploaded", req.label, req.mime_type, req.image_b64, req.project_id
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
