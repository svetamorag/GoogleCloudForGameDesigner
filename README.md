# Game Asset Studio

It is a **demo** of a local web app that puts a game designer's asset loop on one screen: describe
a character, pick from five generated options, refine the image, build a
turnaround sheet, and give the character a voice — without alt-tabbing between
a dozen AI tools and a downloads folder.

Everything runs on Gemini models on **Gemini Enterprise Agent Platform** (formerly Vertex AI) with **Application Default
Credentials (ADC)** — there are no API keys anywhere in the code. A chat panel
on the left acts as the director: it understands requests like *"make me a
goblin alchemist, then remove the background"*, calls the right tool via
function calling, and the result appears in the matching tab on the right.

## How it works

 The app is deliberately plain plumbing around the models. The backend is Python: **FastAPI** (async, with pydantic-validated request models) served by **uvicorn**, calling Agent Platform through the official `google-genai` SDK's async client — two clients under the hood, one on the `global` endpoint for the chat/image models and one regional for the Live API, with a semaphore plus exponential-backoff retries to stay inside image-model quota. Configuration is a two-variable `.env` (via `python-dotenv`); those four packages are the entire dependency list. There is no database — assets land as files in `assets/` with JSON indexes in `data/`. The frontend is three static files (an HTML page, a stylesheet, and one plain-JavaScript file — no framework, no build step) served directly by FastAPI. Each feature is one model doing the one thing it's good at:


| Feature | Model | Role |
|---|---|---|
| Chat assistant | `gemini-3.5-flash` | The director: routes requests to tools via function calling, and rewrites short briefs ("a knight") into detailed art direction before image generation — the biggest quality win in the app |
| Character generation | `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) | The exploration phase: 5 fast, cheap, distinct options per brief — most exist to be discarded |
| Image editing | `gemini-3.1-flash-image` (Nano Banana 2) | The careful work: targeted edits ("change the cape to red"), background removal, and character turnaround/expression sheets from a single reference image |
| Voice generation | `gemini-live-2.5-flash-native-audio` (Live API) | Dialogue: 3 takes per line in male (Puck, Charon, Fenrir) or female (Kore, Leda, Zephyr) voices; bind a take to a character, then batch-voice whole scripts |

## Prerequisites

- Python 3.11+
- A Google Cloud project with the **Agent Platform API enabled**
- [gcloud CLI](https://cloud.google.com/sdk/docs/install)

## Setup

```bash
# 1. Authenticate with Application Default Credentials
gcloud auth application-default login

# 2. Configure the project
copy .env.example .env    # then edit GOOGLE_CLOUD_PROJECT

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
uvicorn server.main:app --reload --port 8000
```

Open http://localhost:8000

## Usage

- **Chat (left panel)** — ask in natural language: "generate a goblin alchemist",
  "remove the background", "make the armor gold", "voice the line 'Halt, traveler!'".
  The assistant calls the matching tool and the result appears in the right tab.
- **Characters tab** — enter a prompt; it is automatically rewritten into
  detailed art direction (shown to you), then 5 distinct options are generated.
  Pick an **aspect ratio** (1:1 up to 21:9) or leave it on Auto. Click **Edit**
  on any card to send it to the editor.
- **Editing tab** — edit the selected/uploaded image with text instructions,
  remove backgrounds, generate a character sheet (front/side/back views plus
  expressions from one reference image), browse edit history, download results.
  The **Aspect** and **Size** selectors control the output: aspect ratio
  reframes the result (Auto keeps the source framing; background removal always
  keeps it), and size sets the output resolution (1K/2K/4K — supported by
  Nano Banana 2 only; the Lite character generator supports aspect ratio but
  not resolution).
- **Voice tab** — enter a line; it is spoken by 3 different Gemini Native Audio
  voices in parallel. Bind the take you like to a character name, then paste a
  whole script into **Batch dialogue** (`Character, Line` per row) and every
  line comes back in its character's bound voice.
- **Gallery tab** — every generated, edited and uploaded image (and voice clip)
  is saved locally under `assets/` (JSON indexes live in `data/`, which is not
  web-served) and listed here with Edit / Delete actions.

## Security notes

This is a local, single-user tool with no authentication — do not expose it to
the internet as-is.

- The server only answers requests addressed to `localhost` / `127.0.0.1`
  (protects against DNS rebinding) and rejects state-changing requests from
  foreign browser origins. To serve on another hostname deliberately, set
  `ALLOWED_HOSTS=host1,host2` in `.env`.
- Responses carry a strict Content-Security-Policy and related headers.
- All inputs are validated server-side: image payloads are size-limited
  (15 MB), MIME types are allowlisted, and upstream error details are logged
  server-side rather than echoed to the browser.
- Keep uvicorn on its default bind (`127.0.0.1`); don't run with `--host 0.0.0.0`.

## Build your own version

This app is a sketch of *one* asset pipeline — yours is probably different.
The models do all the heavy lifting; the app itself is a few hundred lines of
plumbing arranged in the shape of a workflow, which means you can stand up
your own version in an afternoon.

Paste the prompt below into [Google AI Studio](https://aistudio.google.com)
(Build mode), [Antigravity](https://antigravity.google), or any other
application generator / coding agent (Claude Code, Cursor, etc.). Everything
in `[brackets]` is where your pipeline goes — swap in your own steps and keep
the rest, especially the "hard-won details" section, which saves you the
first three debugging sessions. Best starting point: don't build the whole
thing — pick the single step you repeat fifty times a week, wire up just
that, and add the prompt-rewriting step first (it's the biggest win for one
model call).

```
Build a local web app for [game asset creation] using Gemini models via the
google-genai Python SDK.

Auth (pick by env, no keys in code): if GEMINI_API_KEY is set, use the
Gemini API (Google AI Studio key — no cloud project needed); otherwise use
Vertex AI with vertexai=True + Application Default Credentials and
GOOGLE_CLOUD_PROJECT from .env.

Stack: Python FastAPI backend; plain HTML/JS frontend served as static files.

Layout: chat panel on the left drives the app via function calling; tabs on
the right: [Characters, Editing, Voice, Gallery].

Features:
1. [Characters]: rewrite the user's short brief with gemini-3.5-flash into
   detailed art direction (silhouette, materials, palette, lighting, mood),
   show it, then generate [5] distinct options with
   gemini-3.1-flash-lite-image.
2. [Editing]: text-instruction edits and background removal on any generated
   or uploaded image with gemini-3.1-flash-image; keep a clickable edit
   history.
3. [Voice]: speak a user line in 3 takes with
   gemini-live-2.5-flash-native-audio via the Live API (collect PCM 24 kHz
   16-bit mono, wrap as WAV). Voice sets: male (Puck, Charon, Fenrir) or
   female (Kore, Leda, Zephyr).
4. Gallery: save every asset to a local assets/ folder with a JSON index;
   list newest-first with delete buttons.

Chat: gemini-3.5-flash with one function declaration per feature; when the
model calls a tool, the frontend runs the action and switches to that tab.

Hard-won details:
- On Vertex AI, Gemini 3.x chat/image models are served ONLY from
  location="global", but the Live API needs a region like us-central1 —
  keep two clients. (The Gemini API path has no location setting.)
- Image quota is a few requests per minute: cap concurrency at 2 with a
  semaphore, retry 429s with exponential backoff, stagger launches.
- Use the async client (client.aio) for parallel calls; the sync client is
  not thread-safe.
```

## References

- [Gemini Live API native audio in Vertex AI](https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai)
- [Nano Banana 2 announcement](https://blog.google/innovation-and-ai/technology/developers-tools/build-with-nano-banana-2/)
- [Vertex AI Live API docs](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api)
- [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
