"""Gemini model access layer (Vertex AI, Application Default Credentials).

Models used:
  - gemini-3.5-flash                  chat / UI assistant (function calling)
  - gemini-3.1-flash-image            Nano Banana 2 (image editing, background removal)
  - gemini-3.1-flash-lite-image       Nano Banana 2 Lite (fast 5-option character generation)
  - gemini-live-2.5-flash-native-audio  Gemini Native Audio via Live API (voice generation)
"""

import asyncio
import base64
import io
import os
import random
import wave

from google import genai
from google.genai import types

CHAT_MODEL = "gemini-3.5-flash"
IMAGE_MODEL = "gemini-3.1-flash-image"
IMAGE_MODEL_LITE = "gemini-3.1-flash-lite-image"
AUDIO_MODEL = "gemini-live-2.5-flash-native-audio"

VOICES = {
    "male": ["Puck", "Charon", "Fenrir"],
    "female": ["Kore", "Leda", "Zephyr"],
}

# Live API native audio output is 16-bit PCM, 24 kHz, mono.
AUDIO_SAMPLE_RATE = 24000

# Gemini 3.x chat/image models are served from the global endpoint only.
# The Live API (native audio) is NOT supported on global — it needs a region.
GLOBAL_LOCATION = "global"

_clients: dict[str, genai.Client] = {}


def get_client(location: str = GLOBAL_LOCATION) -> genai.Client:
    if location not in _clients:
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        if not project:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT is not set. Copy .env.example to .env, "
                "set your project id, and run: gcloud auth application-default login"
            )
        _clients[location] = genai.Client(vertexai=True, project=project, location=location)
    return _clients[location]


def get_live_client() -> genai.Client:
    return get_client(os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"))


# ---------------------------------------------------------------- images

def _extract_image(response) -> dict | None:
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            if part.inline_data and part.inline_data.data:
                return {
                    "mime_type": part.inline_data.mime_type or "image/png",
                    "data_b64": base64.b64encode(part.inline_data.data).decode(),
                }
    return None


async def _with_retry(coro_factory, attempts: int = 5, base_delay: float = 12.0):
    """Retry on 429 RESOURCE_EXHAUSTED with exponential backoff.

    Image model quota on the global endpoint is a low requests-per-minute
    budget, so waits between retries have to span a quota window.
    """
    last_exc = None
    for attempt in range(attempts):
        try:
            return await coro_factory()
        except Exception as exc:
            if "429" not in str(exc) and "RESOURCE_EXHAUSTED" not in str(exc):
                raise
            last_exc = exc
            if attempt < attempts - 1:
                await asyncio.sleep(base_delay * (2**attempt) + random.uniform(0, 2))
    raise last_exc


# At most 2 image requests in flight - the model's requests-per-minute quota
# is easily exceeded by a burst of 5.
_image_semaphore = asyncio.Semaphore(2)


async def _generate_one_character(prompt: str, index: int) -> dict | None:
    full_prompt = (
        "Game character concept art, full body, clean readable silhouette, "
        f"plain neutral studio background. Design variation {index + 1} of 5 - "
        "make this take clearly distinct from the other variations in pose, "
        f"costume and color palette.\n\nCharacter brief: {prompt}"
    )
    async with _image_semaphore:
        response = await _with_retry(
            lambda: get_client().aio.models.generate_content(
                model=IMAGE_MODEL_LITE,
                contents=full_prompt,
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
        )
    image = _extract_image(response)
    if image:
        image["label"] = f"Option {index + 1}"
    return image


async def enhance_prompt(prompt: str, style_guide: str = "") -> str:
    """Rewrite a short character brief into a detailed art-direction prompt."""
    style_line = f"\nProject style guide to honor: {style_guide}" if style_guide else ""
    response = await get_client().aio.models.generate_content(
        model=CHAT_MODEL,
        contents=(
            "Rewrite this game character brief into one vivid, detailed concept-art "
            "description for an image generation model. Add specifics: distinctive "
            "silhouette, materials and textures, color palette, lighting, mood, and "
            "notable props or markings. Stay true to the original intent - do not "
            "change the character's core identity or invent a name/backstory beyond "
            "visual details. Output only the rewritten description, one paragraph, "
            f"no preamble.{style_line}\n\n"
            f"Original brief: {prompt}"
        ),
    )
    text = "".join(
        part.text or ""
        for candidate in response.candidates or []
        for part in candidate.content.parts or []
    ).strip()
    return text or prompt


async def generate_characters(prompt: str, style_guide: str = "") -> dict:
    """Five character options on Nano Banana 2 Lite, throttled to fit quota."""
    try:
        enhanced_prompt = await enhance_prompt(prompt, style_guide)
    except Exception:
        enhanced_prompt = prompt
    results = await asyncio.gather(
        *(_generate_one_character(enhanced_prompt, i) for i in range(5)),
        return_exceptions=True,
    )
    images = [r for r in results if isinstance(r, dict)]
    errors = [r for r in results if isinstance(r, Exception)]
    if not images and errors:
        raise errors[0]
    failed = 5 - len(images)
    return {
        "images": images,
        "failed": failed,
        "error": str(errors[0])[:200] if errors else None,
        "enhanced_prompt": enhanced_prompt,
    }


async def _edit_image_call(image_b64: str, mime_type: str, instruction: str) -> dict:
    async with _image_semaphore:
        response = await _with_retry(
            lambda: get_client().aio.models.generate_content(
                model=IMAGE_MODEL,
                contents=[
                    types.Part.from_bytes(data=base64.b64decode(image_b64), mime_type=mime_type),
                    instruction,
                ],
                config=types.GenerateContentConfig(response_modalities=["TEXT", "IMAGE"]),
            )
        )
    image = _extract_image(response)
    if not image:
        raise RuntimeError("Model returned no image for the edit request.")
    return image


async def edit_image(image_b64: str, mime_type: str, instruction: str) -> dict:
    """Object editing on Nano Banana 2."""
    prompt = (
        "Edit the provided image. Apply exactly this change and keep everything "
        f"else identical: {instruction}"
    )
    return await _edit_image_call(image_b64, mime_type, prompt)


async def remove_background(image_b64: str, mime_type: str) -> dict:
    prompt = (
        "Remove the background from the provided image completely. Keep the main "
        "subject pixel-perfect and unchanged. Output the subject on a fully "
        "transparent background (PNG with alpha). Do not add shadows or new elements."
    )
    return await _edit_image_call(image_b64, mime_type, prompt)


# Character sheet views: (label, instruction). Each keeps identity fixed via
# the reference image and only changes viewing angle / expression.
CHARACTER_SHEET_VIEWS = [
    ("Front view", "Show this exact character from a straight-on front view, full body, "
                    "same design, outfit, colors and proportions, neutral standing pose, "
                    "plain neutral studio background."),
    ("Side profile", "Show this exact character from a full side profile view (90 degrees), "
                      "same design, outfit, colors and proportions, neutral standing pose, "
                      "plain neutral studio background."),
    ("Back view", "Show this exact character from directly behind, full body, same design, "
                  "outfit, colors and proportions, neutral standing pose, plain neutral "
                  "studio background."),
    ("Happy expression", "Show this exact character's face and upper body with a happy, "
                          "warm expression. Keep the same design, outfit and colors."),
    ("Angry expression", "Show this exact character's face and upper body with an angry, "
                          "intense expression. Keep the same design, outfit and colors."),
    ("Determined expression", "Show this exact character's face and upper body with a "
                               "focused, determined expression. Keep the same design, "
                               "outfit and colors."),
]


async def _generate_sheet_view(
    image_b64: str, mime_type: str, label: str, instruction: str, style_guide: str
) -> dict | None:
    style_line = f" Honor this project style guide: {style_guide}" if style_guide else ""
    try:
        image = await _edit_image_call(image_b64, mime_type, instruction + style_line)
        image["label"] = label
        return image
    except Exception:
        return None


async def generate_character_sheet(image_b64: str, mime_type: str, style_guide: str = "") -> dict:
    """Turnaround + expression sheet for one character, via reference-image conditioning."""
    results = await asyncio.gather(
        *(
            _generate_sheet_view(image_b64, mime_type, label, instruction, style_guide)
            for label, instruction in CHARACTER_SHEET_VIEWS
        )
    )
    images = [r for r in results if r]
    return {"images": images, "failed": len(CHARACTER_SHEET_VIEWS) - len(images)}


# ---------------------------------------------------------------- voice

def _pcm_to_wav_b64(pcm: bytes) -> str:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(AUDIO_SAMPLE_RATE)
        wav.writeframes(pcm)
    return base64.b64encode(buffer.getvalue()).decode()


async def _synthesize_voice(text: str, voice_name: str) -> dict:
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
        system_instruction=types.Content(
            parts=[
                types.Part(
                    text="You are a game voice actor. Speak the user's text exactly "
                    "as written, with fitting emotion and delivery. Do not add, "
                    "remove or comment on any words."
                )
            ]
        ),
    )
    pcm = bytearray()
    client = get_live_client()
    async with client.aio.live.connect(model=AUDIO_MODEL, config=config) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )
        async for message in session.receive():
            content = message.server_content
            if content and content.model_turn:
                for part in content.model_turn.parts or []:
                    if part.inline_data and part.inline_data.data:
                        pcm.extend(part.inline_data.data)
            if content and content.turn_complete:
                break
    if not pcm:
        raise RuntimeError(f"No audio returned for voice {voice_name}.")
    return {"voice": voice_name, "wav_b64": _pcm_to_wav_b64(bytes(pcm))}


async def generate_voice(text: str, voice_name: str) -> dict:
    """Single line in a specific named voice (used for bound-character dialogue)."""
    return await _synthesize_voice(text, voice_name)


async def generate_voices(text: str, gender: str = "female") -> list[dict]:
    """Same line in three prebuilt voices of the chosen gender, generated in parallel."""
    voices = VOICES.get(gender, VOICES["female"])
    results = await asyncio.gather(
        *(_synthesize_voice(text, voice) for voice in voices),
        return_exceptions=True,
    )
    clips = [r for r in results if isinstance(r, dict)]
    errors = [r for r in results if isinstance(r, Exception)]
    if not clips and errors:
        raise errors[0]
    return clips


# ---------------------------------------------------------------- chat

CHAT_SYSTEM_INSTRUCTION = (
    "You are the assistant inside a game-asset studio web app. The app has four "
    "tabs: Characters (generates 5 character image options from a prompt - the "
    "prompt is automatically rewritten with more visual detail before "
    "generation), Editing (edits the selected/uploaded image, can remove "
    "backgrounds), Voice (speaks a line in 3 different voices of one gender - "
    "ask the user male or female if they haven't said), and Gallery (all saved "
    "assets). When the user asks for something one of your tools can do, call "
    "the tool - the app executes it and shows the result in the matching tab. "
    "Answer briefly; you are a production tool, not a chatbot."
)

CHAT_TOOLS = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="generate_characters",
            description="Generate 5 game character image options from a text prompt.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "prompt": types.Schema(
                        type=types.Type.STRING,
                        description="Character description to generate from.",
                    )
                },
                required=["prompt"],
            ),
        ),
        types.FunctionDeclaration(
            name="edit_image",
            description=(
                "Edit the image currently selected in the Editing tab "
                "(add/remove/change objects, colors, style)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "instruction": types.Schema(
                        type=types.Type.STRING,
                        description="The edit to apply to the current image.",
                    )
                },
                required=["instruction"],
            ),
        ),
        types.FunctionDeclaration(
            name="remove_background",
            description="Remove the background of the image currently selected in the Editing tab.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="generate_voices",
            description="Speak a line of dialogue in 3 different voices of one gender.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "text": types.Schema(
                        type=types.Type.STRING,
                        description="The exact line to speak.",
                    ),
                    "gender": types.Schema(
                        type=types.Type.STRING,
                        enum=["male", "female"],
                        description="Voice gender to use. Defaults to female if unspecified.",
                    ),
                },
                required=["text"],
            ),
        ),
    ]
)


async def _chat_call(history: list[dict], message: str, has_image: bool) -> dict:
    contents = []
    for turn in history:
        contents.append(
            types.Content(
                role=turn["role"],
                parts=[types.Part(text=turn["text"])],
            )
        )
    context = f"[App state: an image {'is' if has_image else 'is NOT'} currently selected in the Editing tab.]"
    contents.append(
        types.Content(role="user", parts=[types.Part(text=f"{context}\n{message}")])
    )
    response = await get_client().aio.models.generate_content(
        model=CHAT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=CHAT_SYSTEM_INSTRUCTION,
            tools=[CHAT_TOOLS],
        ),
    )
    reply_text = ""
    action = None
    for candidate in response.candidates or []:
        for part in candidate.content.parts or []:
            if part.function_call and not action:
                action = {
                    "name": part.function_call.name,
                    "args": dict(part.function_call.args or {}),
                }
            elif part.text:
                reply_text += part.text
    return {"reply": reply_text.strip(), "action": action}


async def chat(history: list[dict], message: str, has_image: bool) -> dict:
    return await _chat_call(history, message, has_image)
