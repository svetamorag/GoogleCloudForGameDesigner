# I Built a Game Asset Studio with Four Gemini Models (and You Should Build Your Own)

Full disclosure: I'm not a game designer. But I've watched enough streams, devlogs and "how we made our indie game" postmortems to notice a pattern — a lot of jumping between tools. Concept art in one place, image cleanup in another, voice samples in a third, and somewhere a folder called `final_final_v3` holding it all together.

So I tried an experiment: what would that loop look like if it lived in a single screen, powered entirely by Gemini models on Vertex AI? I sketched a sample pipeline from what I'd seen — describe a character, pick from a few options, refine the image, give them a voice — and built a demo around it. The interesting part isn't the app. It's how little glue it took.

## One screen, four models, each with a job

The app is a plain web page: a chat panel on the left, tabs for Characters, Editing, Voice and a Gallery on the right. Under the hood, every feature maps to one model doing the thing it's best at:

- **Gemini 3.5 Flash** is the director. It powers the chat, decides which tool to call ("make me a goblin alchemist, then remove the background"), and quietly rewrites my lazy prompts into proper art direction. I type "a knight" — it sends a full paragraph about battle-scarred plate mail, dramatic lighting and a two-handed sword resting on damp stone. The five images that come back are dramatically better for it.
- **Nano Banana 2 Lite** (`gemini-3.1-flash-lite-image`) generates five distinct character options per brief. It's fast and cheap, which feels right for the exploration phase.
- **Nano Banana 2** (`gemini-3.1-flash-image`) handles the precision work: object edits ("change the cape to red"), background removal, and character turnaround sheets generated from a single reference image.
- **Gemini native audio** (`gemini-live-2.5-flash-native-audio`, via the Live API) voices dialogue lines. Pick male or female, get three takes, bind the winner to a character — after that, paste a whole script and every line comes back in the right voice.

Authentication is one command: `gcloud auth application-default login`. No API keys in the code, no secrets to rotate. Application Default Credentials just work.

## Notes from the field

A few things I learned the slightly hard way, so you don't have to:

**Gemini 3.x image models live on the global endpoint.** Point your client at `location="global"` or you'll get a confusing 404 telling you the model doesn't exist. Meanwhile the Live API for native audio is the opposite — it needs a regional endpoint like `us-central1`. My backend just keeps two clients.

**Respect the quota.** Firing five image generations in parallel is a great way to meet HTTP 429. A semaphore, a little exponential backoff, and staggered launches turned "2 out of 5 images" into "5 out of 5, a minute later." Boring engineering, big difference.

**Prompt rewriting is the cheapest quality upgrade available.** One extra Flash call before each image request improved output more than any parameter tuning I tried.

## The actual point

Here's the thing I want you to take away, and it isn't "use my app." My pipeline is a guess — an outsider's sketch of how this work might flow. If you actually do this for a living, yours will look different, and that's exactly the point.

This demo is a few hundred lines of Python and vanilla JavaScript. With Google AI Studio or Antigravity, you could stand up something like it in minutes — genuinely minutes, not marketing minutes. The models do the heavy lifting; the app is just plumbing shaped like a workflow. Which means the person best positioned to build your tooling isn't whoever ships the most polished off-the-shelf pipeline. It's you, because you're the only one who knows what your loop actually looks like.

So don't bend your process around someone else's product. Fit the models into your pipeline — even a rough guess at your own workflow, wired to the right models, beats a polished tool built around somebody else's.

Start small: pick the one step you repeat fifty times a week, wire a Gemini model to it, and see what happens. Mine was "five character options from one sentence." Yours might be voice barks, or icon cleanup, or lore cards.

## Steal this prompt

To make "build your own" concrete: here's the prompt that produces an app like mine. Paste it into Google AI Studio, Antigravity, or any coding agent you like. The parts in `[brackets]` are where your pipeline goes — change those, keep the rest.

```
Build a local web app for [game asset creation] that works only with Gemini
models on Vertex AI, using Application Default Credentials (no API keys).

Stack: Python FastAPI backend + plain HTML/JS frontend, google-genai SDK with
vertexai=True. Read GOOGLE_CLOUD_PROJECT from .env.

Layout: a chat panel on the left that drives the whole app via function
calling, and tabs on the right: [Characters, Editing, Voice, Gallery].

Features:
1. [Character generation]: user enters a short brief. First rewrite it with
   gemini-3.5-flash into a detailed art-direction prompt (silhouette,
   materials, palette, lighting, mood), then generate [5] distinct options
   with gemini-3.1-flash-lite-image. Show the rewritten prompt to the user.
2. [Image editing]: apply text-instruction edits and background removal to
   any generated or uploaded image using gemini-3.1-flash-image. Keep an
   edit history the user can click back through.
3. [Voice]: speak a user-provided line in 3 voices using
   gemini-live-2.5-flash-native-audio via the Live API (collect PCM 24 kHz
   16-bit mono, wrap as WAV). Let the user pick male (Puck, Charon, Fenrir)
   or female (Kore, Leda, Zephyr) voice sets.
4. Gallery: save every generated/edited/uploaded asset to a local assets/
   folder with a JSON index; list them newest-first with delete buttons.

Chat: gemini-3.5-flash with function declarations for each feature above.
When the model calls a tool, the frontend runs the matching action and
switches to the right tab.

Important implementation details (learned the hard way):
- Gemini 3.x chat/image models are served ONLY from location="global";
  the Live API is NOT on global and needs a region like us-central1.
  Keep two clients.
- Image model quota is a low requests-per-minute budget: limit concurrency
  to 2 with a semaphore and retry 429s with exponential backoff.
- Use the async client (client.aio) for parallel calls; the sync client
  is not safe across threads.
```

Swap the bracketed pieces for your own loop — sound effects instead of voices, level-tile sheets instead of characters, whatever you actually repeat all day — and you'll have a working first version before your coffee cools.

The models are ready. The glue is the easy part now.
