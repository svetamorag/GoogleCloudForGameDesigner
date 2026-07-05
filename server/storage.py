"""Local store: binary assets under assets/ (web-served), JSON indexes under data/ (private)."""

import asyncio
import json
import os
import time
import uuid
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = _ROOT / "assets"
DATA_DIR = _ROOT / "data"
META_PATH = DATA_DIR / "meta.json"
PROJECTS_PATH = DATA_DIR / "projects.json"
VOICES_PATH = DATA_DIR / "voices.json"

DEFAULT_PROJECT_ID = "default"

_lock = asyncio.Lock()

_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "audio/wav": "wav",
}


def _migrate_legacy_indexes() -> None:
    """Older versions kept the JSON indexes inside the web-served assets/ dir.
    Move them into data/ so they are never exposed over HTTP."""
    for path in (META_PATH, PROJECTS_PATH, VOICES_PATH):
        legacy = ASSETS_DIR / path.name
        if legacy.exists() and not path.exists():
            DATA_DIR.mkdir(exist_ok=True)
            legacy.replace(path)


_migrate_legacy_indexes()


def _load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default
    return default


def _write_json(path: Path, data) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------------------------------------------------------------- assets

def _load_meta() -> list[dict]:
    return _load_json(META_PATH, [])


async def save_asset(
    kind: str, label: str, mime_type: str, data: bytes, project_id: str = DEFAULT_PROJECT_ID
) -> dict:
    """kind: generated | edited | uploaded | voice"""
    ext = _EXTENSIONS.get(mime_type, "bin")
    asset_id = uuid.uuid4().hex[:12]
    filename = f"{int(time.time())}_{kind}_{asset_id}.{ext}"
    entry = {
        "id": asset_id,
        "kind": kind,
        "label": label[:200],
        "mime_type": mime_type,
        "filename": filename,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "project_id": project_id or DEFAULT_PROJECT_ID,
    }
    async with _lock:
        ASSETS_DIR.mkdir(exist_ok=True)
        (ASSETS_DIR / filename).write_bytes(data)
        entries = _load_meta()
        entries.append(entry)
        _write_json(META_PATH, entries)
    return entry


async def list_assets(project_id: str | None = None) -> list[dict]:
    async with _lock:
        entries = list(reversed(_load_meta()))  # newest first
    if project_id:
        entries = [e for e in entries if e.get("project_id", DEFAULT_PROJECT_ID) == project_id]
    return entries


async def delete_asset(asset_id: str) -> bool:
    async with _lock:
        entries = _load_meta()
        keep = [e for e in entries if e["id"] != asset_id]
        if len(keep) == len(entries):
            return False
        assets_root = ASSETS_DIR.resolve()
        for entry in entries:
            if entry["id"] == asset_id:
                path = (ASSETS_DIR / entry["filename"]).resolve()
                # Defense in depth: never delete outside the assets dir.
                if path.is_relative_to(assets_root) and path.is_file():
                    path.unlink()
        _write_json(META_PATH, keep)
        return True


# ---------------------------------------------------------------- projects

def _load_projects() -> list[dict]:
    projects = _load_json(PROJECTS_PATH, [])
    if not projects:
        projects = [{"id": DEFAULT_PROJECT_ID, "name": "Default", "style_guide": ""}]
    return projects


async def list_projects() -> list[dict]:
    async with _lock:
        return _load_projects()


async def create_project(name: str, style_guide: str = "") -> dict:
    async with _lock:
        projects = _load_projects()
        entry = {"id": uuid.uuid4().hex[:12], "name": name[:100], "style_guide": style_guide[:2000]}
        projects.append(entry)
        _write_json(PROJECTS_PATH, projects)
        return entry


async def update_project_style_guide(project_id: str, style_guide: str) -> dict | None:
    async with _lock:
        projects = _load_projects()
        for p in projects:
            if p["id"] == project_id:
                p["style_guide"] = style_guide[:2000]
                _write_json(PROJECTS_PATH, projects)
                return p
        return None


async def get_project(project_id: str) -> dict | None:
    async with _lock:
        projects = _load_projects()
    for p in projects:
        if p["id"] == project_id:
            return p
    return None


# ---------------------------------------------------------------- voice bindings

def _load_voices() -> dict:
    return _load_json(VOICES_PATH, {})


async def bind_voice(character: str, voice: str, gender: str) -> dict:
    async with _lock:
        bindings = _load_voices()
        bindings[character] = {"voice": voice, "gender": gender}
        _write_json(VOICES_PATH, bindings)
        return bindings[character]


async def get_voice_binding(character: str) -> dict | None:
    async with _lock:
        return _load_voices().get(character)


async def list_voice_bindings() -> dict:
    async with _lock:
        return _load_voices()
