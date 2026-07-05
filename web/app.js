/* Game Asset Studio frontend. Talks to FastAPI backend at /api/*. */

const state = {
  chatHistory: [],          // [{role: "user"|"model", text}]
  currentImage: null,       // {data_b64, mime_type}
  editHistory: [],          // [{data_b64, mime_type, label}]
  busy: { characters: false, edit: false, voice: false, chat: false, sheet: false, batch: false },
  voiceGender: "female",
  projects: [],             // [{id, name, style_guide}]
  projectId: "default",
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- tabs

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-page").forEach((p) =>
    p.classList.toggle("active", p.id === `tab-${name}`));
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => {
    switchTab(t.dataset.tab);
    if (t.dataset.tab === "gallery") loadGallery();
  }));

// ---------------------------------------------------------------- helpers

// Status text is always inserted via DOM APIs (never innerHTML) - server
// error details must not be interpreted as markup.
function setStatus(el, text, kind = "") {
  el.className = `status ${kind}`;
  el.textContent = "";
  if (!text) return;
  if (kind === "") {
    const spinner = document.createElement("span");
    spinner.className = "spinner";
    el.append(spinner);
  }
  el.append(document.createTextNode(text));
}

function errorDetail(data, res) {
  if (Array.isArray(data.detail)) {
    return data.detail.map((d) => d.msg || String(d)).join("; ");
  }
  return data.detail || `${res.status} ${res.statusText}`;
}

async function request(path, method = "GET", body) {
  const res = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(errorDetail(data, res));
  return data;
}

const api = (path, body) => request(path, "POST", body);

const ALLOWED_IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp", "image/gif"];

function imgSrc(image) {
  return `data:${image.mime_type};base64,${image.data_b64}`;
}

// ---------------------------------------------------------------- projects

function currentProject() {
  return state.projects.find((p) => p.id === state.projectId);
}

function renderProjectSelect() {
  const select = $("project-select");
  select.innerHTML = "";
  state.projects.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    select.append(opt);
  });
  select.value = state.projectId;
}

async function loadProjects() {
  try {
    const { projects } = await request("/api/projects");
    state.projects = projects;
    if (!projects.some((p) => p.id === state.projectId)) {
      state.projectId = projects[0]?.id || "default";
    }
    renderProjectSelect();
  } catch (err) {
    addMessage("system", `Could not load projects: ${err.message}`);
  }
}

$("project-select").addEventListener("change", (e) => {
  state.projectId = e.target.value;
  $("style-guide-text").value = currentProject()?.style_guide || "";
  if (document.querySelector('.tab[data-tab="gallery"]').classList.contains("active")) {
    loadGallery();
  }
});

$("project-new").addEventListener("click", async () => {
  const name = prompt("New project name:");
  if (!name || !name.trim()) return;
  try {
    const { project } = await api("/api/projects", { name: name.trim() });
    state.projects.push(project);
    state.projectId = project.id;
    renderProjectSelect();
  } catch (err) {
    addMessage("system", `Could not create project: ${err.message}`);
  }
});

$("project-style").addEventListener("click", () => {
  const panel = $("style-guide-panel");
  panel.classList.toggle("hidden");
  if (!panel.classList.contains("hidden")) {
    $("style-guide-text").value = currentProject()?.style_guide || "";
  }
});

$("style-guide-save").addEventListener("click", async () => {
  try {
    const { project } = await request(
      `/api/projects/${encodeURIComponent(state.projectId)}/style-guide`, "PUT",
      { style_guide: $("style-guide-text").value }
    );
    const idx = state.projects.findIndex((p) => p.id === project.id);
    if (idx >= 0) state.projects[idx] = project;
    $("style-guide-panel").classList.add("hidden");
  } catch (err) {
    addMessage("system", `Could not save style guide: ${err.message}`);
  }
});

// ---------------------------------------------------------------- characters

async function generateCharacters(prompt) {
  if (state.busy.characters || !prompt.trim()) return;
  state.busy.characters = true;
  switchTab("characters");
  $("character-prompt").value = prompt;
  const status = $("character-status");
  setStatus(status, "Generating 5 options on Nano Banana 2 Lite...");
  $("character-grid").innerHTML = "";
  try {
    const { images, failed, enhanced_prompt } = await api("/api/characters/generate", {
      prompt, project_id: state.projectId,
    });
    renderCharacters(images);
    const note = failed
      ? ` (${failed} failed - model quota; retry in a minute for more)`
      : "";
    setStatus(status, `${images.length} option(s) ready${note}. Click "Edit" to refine one.`, "ok");
    if (enhanced_prompt && enhanced_prompt !== prompt) {
      const rewritten = document.createElement("div");
      rewritten.className = "rewritten";
      rewritten.textContent = `Rewritten prompt: "${enhanced_prompt}"`;
      status.append(rewritten);
    }
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    state.busy.characters = false;
  }
}

function renderCharacters(images) {
  const grid = $("character-grid");
  grid.innerHTML = "";
  images.forEach((image) => {
    const card = document.createElement("div");
    card.className = "card";
    const img = document.createElement("img");
    img.src = imgSrc(image);
    const bar = document.createElement("div");
    bar.className = "card-bar";
    const label = document.createElement("span");
    label.textContent = image.label || "Option";
    const btn = document.createElement("button");
    btn.textContent = "Edit";
    btn.addEventListener("click", () => sendToEditor(image));
    bar.append(label, btn);
    card.append(img, bar);
    grid.append(card);
  });
}

$("generate-characters").addEventListener("click", () =>
  generateCharacters($("character-prompt").value));
$("character-prompt").addEventListener("keydown", (e) => {
  if (e.key === "Enter") generateCharacters($("character-prompt").value);
});

// ---------------------------------------------------------------- editing

function sendToEditor(image, label = "Source") {
  state.currentImage = { data_b64: image.data_b64, mime_type: image.mime_type };
  state.editHistory.push({ ...state.currentImage, label });
  renderEditor();
  switchTab("editing");
}

function renderEditor() {
  const preview = $("edit-preview");
  const hasImage = !!state.currentImage;
  if (hasImage) {
    preview.className = "preview";
    preview.innerHTML = "";
    const img = document.createElement("img");
    img.src = imgSrc(state.currentImage);
    preview.append(img);
  }
  $("apply-edit").disabled = !hasImage;
  $("remove-bg").disabled = !hasImage;
  $("download-image").disabled = !hasImage;
  $("generate-sheet").disabled = !hasImage;

  const history = $("edit-history");
  history.innerHTML = "";
  state.editHistory.forEach((entry) => {
    const thumb = document.createElement("img");
    thumb.src = imgSrc(entry);
    thumb.title = entry.label;
    if (state.currentImage && entry.data_b64 === state.currentImage.data_b64) {
      thumb.classList.add("current");
    }
    thumb.addEventListener("click", () => {
      state.currentImage = { data_b64: entry.data_b64, mime_type: entry.mime_type };
      renderEditor();
    });
    history.append(thumb);
  });
}

async function runEdit(kind, instruction) {
  if (!state.currentImage || state.busy.edit) return;
  state.busy.edit = true;
  switchTab("editing");
  const status = $("edit-status");
  setStatus(status, kind === "bg" ? "Removing background (Nano Banana 2)..." : "Applying edit (Nano Banana 2)...");
  try {
    const body = {
      image_b64: state.currentImage.data_b64,
      mime_type: state.currentImage.mime_type,
      project_id: state.projectId,
    };
    const data = kind === "bg"
      ? await api("/api/images/remove-background", body)
      : await api("/api/images/edit", { ...body, instruction });
    state.currentImage = { data_b64: data.image.data_b64, mime_type: data.image.mime_type };
    state.editHistory.push({
      ...state.currentImage,
      label: kind === "bg" ? "Background removed" : instruction,
    });
    renderEditor();
    setStatus(status, "Done.", "ok");
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    state.busy.edit = false;
  }
}

$("apply-edit").addEventListener("click", () => {
  const instruction = $("edit-instruction").value.trim();
  if (instruction) runEdit("edit", instruction);
});
$("remove-bg").addEventListener("click", () => runEdit("bg"));

$("upload-input").addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (!file) return;
  if (!ALLOWED_IMAGE_TYPES.includes(file.type)) {
    setStatus($("edit-status"), "Unsupported image type. Use PNG, JPEG, WebP or GIF.", "error");
    e.target.value = "";
    return;
  }
  const reader = new FileReader();
  reader.onload = () => {
    const [, mime, b64] = reader.result.match(/^data:(.+?);base64,(.+)$/) || [];
    if (b64 && ALLOWED_IMAGE_TYPES.includes(mime)) {
      sendToEditor({ data_b64: b64, mime_type: mime }, `Upload: ${file.name}`);
      api("/api/assets/upload", {
        image_b64: b64, mime_type: mime, label: `Upload: ${file.name}`, project_id: state.projectId,
      }).catch((err) => setStatus($("edit-status"), `Could not save upload: ${err.message}`, "error"));
    }
  };
  reader.readAsDataURL(file);
  e.target.value = "";
});

$("download-image").addEventListener("click", () => {
  if (!state.currentImage) return;
  const a = document.createElement("a");
  a.href = imgSrc(state.currentImage);
  a.download = `asset.${state.currentImage.mime_type.split("/")[1] || "png"}`;
  a.click();
});

async function generateSheet() {
  if (!state.currentImage || state.busy.sheet) return;
  state.busy.sheet = true;
  const status = $("sheet-status");
  setStatus(status, "Generating turnaround + expression sheet (Nano Banana 2, reference-conditioned)...");
  $("sheet-grid").innerHTML = "";
  try {
    const { images, failed } = await api("/api/characters/sheet", {
      image_b64: state.currentImage.data_b64,
      mime_type: state.currentImage.mime_type,
      project_id: state.projectId,
    });
    images.forEach((image) => $("sheet-grid").append(sheetCard(image)));
    const note = failed ? ` (${failed} view(s) failed - quota; try again shortly)` : "";
    setStatus(status, `${images.length} view(s) ready${note}.`, "ok");
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    state.busy.sheet = false;
  }
}

function sheetCard(image) {
  const card = document.createElement("div");
  card.className = "card";
  const img = document.createElement("img");
  img.src = imgSrc(image);
  const bar = document.createElement("div");
  bar.className = "card-bar";
  const label = document.createElement("span");
  label.textContent = image.label || "View";
  const btn = document.createElement("button");
  btn.textContent = "Use";
  btn.addEventListener("click", () => sendToEditor(image, image.label));
  bar.append(label, btn);
  card.append(img, bar);
  return card;
}

$("generate-sheet").addEventListener("click", generateSheet);

// ---------------------------------------------------------------- voice

async function generateVoices(text, gender) {
  if (state.busy.voice || !text.trim()) return;
  gender = gender === "male" ? "male" : gender === "female" ? "female" : state.voiceGender;
  state.busy.voice = true;
  switchTab("voice");
  $("voice-text").value = text;
  setVoiceGender(gender);
  const status = $("voice-status");
  setStatus(status, `Generating 3 ${gender} voices (Gemini Native Audio)...`);
  $("voice-grid").innerHTML = "";
  try {
    const { clips } = await api("/api/voice/generate", { text, gender, project_id: state.projectId });
    renderVoices(clips, text);
    setStatus(status, `${clips.length} voice(s) ready.`, "ok");
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    state.busy.voice = false;
  }
}

function setVoiceGender(gender) {
  state.voiceGender = gender;
  document.querySelectorAll("#voice-gender .seg").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.gender === gender));
}

document.querySelectorAll("#voice-gender .seg").forEach((btn) =>
  btn.addEventListener("click", () => setVoiceGender(btn.dataset.gender)));

function renderVoices(clips, text) {
  const grid = $("voice-grid");
  grid.innerHTML = "";
  clips.forEach((clip) => {
    const card = document.createElement("div");
    card.className = "voice-card";
    const title = document.createElement("h3");
    title.textContent = clip.voice;
    const line = document.createElement("div");
    line.className = "voice-line";
    line.textContent = `"${text}"`;
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = `data:audio/wav;base64,${clip.wav_b64}`;

    const bindRow = document.createElement("div");
    bindRow.className = "bind-row";
    const bindInput = document.createElement("input");
    bindInput.type = "text";
    bindInput.placeholder = "Bind to character name...";
    const bindBtn = document.createElement("button");
    bindBtn.textContent = "Bind";
    const bindNote = document.createElement("div");
    bindNote.className = "bind-note";
    bindBtn.addEventListener("click", async () => {
      const character = bindInput.value.trim();
      if (!character) return;
      try {
        await api("/api/voices/bind", { character, voice: clip.voice, gender: state.voiceGender });
        bindNote.textContent = `Bound to "${character}".`;
      } catch (err) {
        bindNote.textContent = err.message;
        bindNote.style.color = "var(--error)";
      }
    });
    bindRow.append(bindInput, bindBtn);

    card.append(title, line, audio, bindRow, bindNote);
    grid.append(card);
  });
}

$("generate-voice").addEventListener("click", () => generateVoices($("voice-text").value, state.voiceGender));
$("voice-text").addEventListener("keydown", (e) => {
  if (e.key === "Enter") generateVoices($("voice-text").value, state.voiceGender);
});

// ---------------------------------------------------------------- batch dialogue

function parseDialogueRows(text) {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const idx = line.indexOf(",");
      if (idx < 0) return null;
      const character = line.slice(0, idx).trim();
      const dialogueLine = line.slice(idx + 1).trim();
      return character && dialogueLine ? { character, line: dialogueLine } : null;
    })
    .filter(Boolean);
}

async function generateBatch() {
  if (state.busy.batch) return;
  const rows = parseDialogueRows($("batch-dialogue-text").value);
  const status = $("batch-status");
  if (!rows.length) {
    setStatus(status, "Add at least one row: Character, Line to speak", "error");
    return;
  }
  state.busy.batch = true;
  setStatus(status, `Generating ${rows.length} line(s)...`);
  $("batch-grid").innerHTML = "";
  try {
    const { clips, errors } = await api("/api/voice/batch", { rows, project_id: state.projectId });
    clips.forEach((clip) => $("batch-grid").append(batchCard(clip)));
    const errNote = errors.length ? ` (${errors.length} failed)` : "";
    setStatus(status, `${clips.length} line(s) generated${errNote}.`, errors.length ? "error" : "ok");
  } catch (err) {
    setStatus(status, err.message, "error");
  } finally {
    state.busy.batch = false;
  }
}

function batchCard(clip) {
  const card = document.createElement("div");
  card.className = "voice-card";
  const title = document.createElement("h3");
  title.textContent = `${clip.character} (${clip.voice})`;
  const line = document.createElement("div");
  line.className = "voice-line";
  line.textContent = `"${clip.line}"`;
  const audio = document.createElement("audio");
  audio.controls = true;
  audio.src = `data:audio/wav;base64,${clip.wav_b64}`;
  card.append(title, line, audio);
  return card;
}

$("generate-batch").addEventListener("click", generateBatch);

// ---------------------------------------------------------------- gallery

async function loadGallery() {
  const status = $("gallery-status");
  const grid = $("gallery-grid");
  setStatus(status, "Loading assets...");
  try {
    const { assets } = await request(`/api/assets?project_id=${encodeURIComponent(state.projectId)}`);
    grid.innerHTML = "";
    if (!assets.length) {
      setStatus(status, "No assets yet. Everything you generate, edit or upload lands here.", "ok");
      return;
    }
    setStatus(status, `${assets.length} asset(s).`, "ok");
    assets.forEach((asset) => grid.append(galleryCard(asset)));
  } catch (err) {
    setStatus(status, err.message, "error");
  }
}

function galleryCard(asset) {
  const card = document.createElement("div");
  card.className = "card";
  const url = `/assets/${asset.filename}`;

  if (asset.mime_type.startsWith("image/")) {
    const img = document.createElement("img");
    img.src = url;
    img.title = asset.label;
    card.append(img);
  } else {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = url;
    audio.style.margin = "16px 10px";
    card.append(audio);
  }

  const bar = document.createElement("div");
  bar.className = "card-bar";
  const label = document.createElement("span");
  label.className = "asset-label";
  label.textContent = `${asset.kind} · ${asset.label}`;
  label.title = `${asset.label} (${asset.created})`;
  const actions = document.createElement("span");
  actions.className = "card-actions";

  if (asset.mime_type.startsWith("image/")) {
    const editBtn = document.createElement("button");
    editBtn.textContent = "Edit";
    editBtn.addEventListener("click", async () => {
      const blob = await (await fetch(url)).blob();
      const reader = new FileReader();
      reader.onload = () => {
        const [, mime, b64] = reader.result.match(/^data:(.+?);base64,(.+)$/) || [];
        if (b64) sendToEditor({ data_b64: b64, mime_type: mime }, asset.label);
      };
      reader.readAsDataURL(blob);
    });
    actions.append(editBtn);
  }

  const delBtn = document.createElement("button");
  delBtn.textContent = "Delete";
  delBtn.className = "danger";
  delBtn.addEventListener("click", async () => {
    try {
      await request(`/api/assets/${encodeURIComponent(asset.id)}`, "DELETE");
      card.remove();
      const left = document.querySelectorAll("#gallery-grid .card").length;
      setStatus($("gallery-status"), left ? `${left} asset(s).` : "No assets yet.", "ok");
    } catch (err) {
      setStatus($("gallery-status"), err.message, "error");
    }
  });
  actions.append(delBtn);

  bar.append(label, actions);
  card.append(bar);
  return card;
}

// ---------------------------------------------------------------- chat

function addMessage(role, text) {
  const div = document.createElement("div");
  div.className = `msg ${role}`;
  div.textContent = text;
  $("chat-messages").append(div);
  $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
}

async function runChatAction(action) {
  switch (action.name) {
    case "generate_characters":
      addMessage("system", "Generating characters...");
      await generateCharacters(action.args.prompt || "");
      break;
    case "edit_image":
      if (!state.currentImage) {
        addMessage("model", "No image is selected in the Editing tab yet - generate a character or upload an image first.");
        return;
      }
      addMessage("system", "Editing image...");
      $("edit-instruction").value = action.args.instruction || "";
      await runEdit("edit", action.args.instruction || "");
      break;
    case "remove_background":
      if (!state.currentImage) {
        addMessage("model", "No image is selected in the Editing tab yet - generate a character or upload an image first.");
        return;
      }
      addMessage("system", "Removing background...");
      await runEdit("bg");
      break;
    case "generate_voices":
      addMessage("system", "Generating voices...");
      await generateVoices(action.args.text || "", action.args.gender);
      break;
  }
}

$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const message = input.value.trim();
  if (!message || state.busy.chat) return;
  input.value = "";
  addMessage("user", message);
  state.busy.chat = true;
  try {
    const data = await api("/api/chat", {
      message,
      history: state.chatHistory.slice(-20),
      has_image: !!state.currentImage,
    });
    state.chatHistory.push({ role: "user", text: message });
    if (data.reply) {
      addMessage("model", data.reply);
      state.chatHistory.push({ role: "model", text: data.reply });
    }
    if (data.action) await runChatAction(data.action);
  } catch (err) {
    addMessage("model", `Error: ${err.message}`);
  } finally {
    state.busy.chat = false;
  }
});

loadProjects();
