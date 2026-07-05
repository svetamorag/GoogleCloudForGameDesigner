# I Built a Game Asset Studio With Four Gemini Models in a Weekend (the Prompt Is at the Bottom, Steal It)

*Nothing to buy here — the only thing I'm selling is "build it yourself."*

I should say up front that I'm not a game designer. I've never shipped a game. I don't even have an itch.io page.

I do meet a lot of game designers and creators, though, and they all use AI — a *lot* of AI. A dozen open tabs of it, sometimes two. One model for concept art, another for cleanup, a third for voices: fragmented apps, fragmented results, and no single tool that's perfect at any of it. 

These are people who are genuinely great at their craft. And the connective tissue between their tools is... alt-tab and a downloads folder.

**The bottleneck has moved from the developer to the game designer — and AI can help there too.**

So we hold an event for Gaming industry and I got curious: what happens if that whole loop lives on one screen? Describe a character, pick from a few generated options, clean up the image, give them a voice — one tab per step, one chat box bossing everything around, all of it running on Gemini models through Gemini Enterprise Agent Platform.

I expected the hard part to be wiring it all together. It wasn't. That's kind of the whole story, but let me show you the pieces first.

## The setup: four models, one job each

The app itself is embarrassingly plain — a chat panel on the left, tabs on the right (Characters, Editing, Voice, Gallery). The backend is Python: FastAPI served by uvicorn, talking to Vertex AI through the `google-genai` SDK. The frontend is exactly three files — an HTML page, a stylesheet, and one plain-JavaScript file full of `getElementById` — no framework, no build step, served straight from FastAPI as static files. Each feature is one model doing the one thing it's good at:

**Gemini 3.5 Flash** runs the chat and acts as the director. It decides which tool to call when I type something like "make me a goblin alchemist, then remove the background." It also does something I didn't originally plan for: it rewrites my lazy prompts. I type "a knight." It sends the image model a paragraph about battle-scarred plate mail, dramatic lighting, a two-handed sword resting on damp stone. The difference in output quality is honestly a little insulting to my prompting skills.

**Nano Banana 2 Lite** (`gemini-3.1-flash-lite-image`) does the exploration phase — five distinct character options per brief. It's fast and cheap, which is what you want when four of the five results exist to be discarded.

**Nano Banana 2** (`gemini-3.1-flash-image`) does the careful work: targeted edits ("change the cape to red"), background removal, and turnaround sheets — front, side, back — generated from a single reference image.

**Gemini native audio** (`gemini-live-2.5-flash-native-audio`, over the Live API) voices dialogue. Pick a male or female voice set, get three takes of a line, bind the take you like to a character. After that you can paste a whole script and every line comes back in that character's voice.

Auth is one command — `gcloud auth application-default login` — and then Application Default Credentials handle everything. There are no API keys anywhere in the code, which took me a while to fully believe.


## Don't use my app — build your own

Okay, so, the part I actually care about. It's not "use my app." Please don't use my app.

My pipeline is a guess. I assembled it from other people's notes, from the outside, without ever having done the job. If you make games for real, your loop is different from my sketch — different steps, different order, probably a bottleneck I've never heard of.

For most of software history that would've been the sad ending: sorry, the tooling you need doesn't exist, here's a generic product that half fits, please bend your workflow around it. That's roughly how we all ended up with the alt-tab-and-downloads-folder pipeline in the first place.

But this demo show it may be different The models do all the heavy lifting; the app is a few hundred lines of plumbing arranged in the shape of a workflow. With Google AI Studio or Antigravity you could stand up your version in an afternoon. Not "an afternoon" the way landing pages promise it — an actual afternoon.

The person best positioned to build your tooling is no longer whoever ships the most polished product. It's you — because you're the only one who knows what your loop actually looks like, and the cost of acting on that knowledge just dropped to roughly zero.

Even a rough guess at your own workflow, wired to the right models, beats a polished tool built around somebody else's assumptions about your job.

## The prompt

Here it is. Paste it into Google AI Studio, Antigravity, or whatever coding agent you use. Everything in `[brackets]` is where your pipeline goes; keep the rest, especially the "learned the hard way" section, which is the distilled version of my three lost ~~evenings~~ minutes.

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

Where to start, if you want my advice: don't build the whole thing. Pick the single step you repeat fifty times a week — mine was "five character options from one sentence," yours might be voice barks or icon cleanup or lore cards — swap it into the brackets, and wire up just that. Add the prompt-rewriting step first; it's the biggest win for one model call. And cap image concurrency at 2 *before* your first 429, not after, because after is annoying.

That's it. The models are ready. The glue was the easy part all along.

---

I'm genuinely curious what step people would automate first — tell me in the responses, because "steal this loop" ideas from actual game folks are exactly what my outsider's sketch is missing. 
