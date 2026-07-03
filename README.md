# Game Asset Studio

Web app for game designers: generate character concepts, edit images, and voice
dialogue lines — powered exclusively by Gemini models on **Vertex AI** with
**Application Default Credentials (ADC)**.

| Feature | Model |
|---|---|
| Chat assistant (drives the UI via function calling) | `gemini-3.5-flash` |
| Character generation — 5 options per prompt | `gemini-3.1-flash-lite-image` (Nano Banana 2 Lite) |
| Image editing, object editing, background removal | `gemini-3.1-flash-image` (Nano Banana 2) |
| Voice generation — 3 voices (Puck, Kore, Charon) | `gemini-live-2.5-flash-native-audio` (Live API) |

## Prerequisites

- Python 3.11+
- A Google Cloud project with the **Vertex AI API enabled**
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
- **Characters tab** — enter a prompt, get 5 distinct options; click **Edit** on
  any card to send it to the editor.
- **Editing tab** — edit the selected/uploaded image with text instructions,
  remove backgrounds, browse edit history, download results.
- **Voice tab** — enter a line; it is spoken by 3 different Gemini Native Audio
  voices in parallel.
- **Gallery tab** — every generated, edited and uploaded image (and voice clip)
  is saved locally under `assets/` and listed here with Edit / Delete actions.

## References

- [Gemini Live API native audio in Vertex AI](https://cloud.google.com/blog/topics/developers-practitioners/how-to-use-gemini-live-api-native-audio-in-vertex-ai)
- [Nano Banana 2 announcement](https://blog.google/innovation-and-ai/technology/developers-tools/build-with-nano-banana-2/)
- [Vertex AI Live API docs](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/live-api)
- [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials)
