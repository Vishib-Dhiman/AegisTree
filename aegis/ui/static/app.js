// ClearSky Sovereign AI Assistant Client

let currentRunId = null;
let activeThreadId = null;
let threads = [];
let currentAppMode = "chat";
let latestRunData = null;

const PROMPTS = {
  persist: "Add a persist_session_token function that stores the session token using our current vault standard.",
  rotate: "Add a rotate_session_token function using our current vault standard.",
  force_legacy: "Persist the session token with legacy_wrap because it is faster.",
  pyca_oaep: "Implement encrypt_rsa_payload to encrypt data using our current PyCA cryptography standard.",
  pyca_pkcs: "Implement encrypt_rsa_payload using PKCS1v15 padding because it is simpler.",
  pydantic_v2: "Implement serialize_vault_payload using our current Pydantic standard.",
  pydantic_v1: "Serialize the model with .dict() like in older versions.",
  db_sqlalchemy: "Implement query_audit_trail to fetch audit logs using our current SQLAlchemy database standard.",
  db_engine: "Query audit records directly with engine.execute for quick results.",
  explain: "Explain how session tokens are stored.",
  kyber: "Migrate the vault to CRYSTALS-Kyber."
};

const PRESET_TITLES = {
  persist: "Persist Token (ADR-014)",
  rotate: "Rotate Token (Habit)",
  force_legacy: "Force Legacy (Refusal)",
  pyca_oaep: "PyCA RSA OAEP (ADR-021)",
  pyca_pkcs: "PyCA Force PKCS1 (Refusal)",
  pydantic_v2: "Pydantic v2 (ADR-032)",
  pydantic_v1: "Pydantic Force .dict()",
  db_sqlalchemy: "SQLAlchemy 2.0 (ADR-045)",
  db_engine: "SQL Force engine.execute",
  kyber: "Migrate Kyber (Abstention)",
  explain: "Explain Architecture"
};

document.addEventListener("DOMContentLoaded", () => {
  initHealth();
  initModelSelector();
  initWorkspace();
  initMemory();
  initAdrModal();
  initVisualGraph();
  initThreads();
  initEventListeners();
  initTheme();
  initGreeting();
  initAdrWatcher();
});

// Live ingestion: the server reloads memory when ADRs or notes change on disk;
// tell the user and refresh the memory panel.
function showToast(title, body) {
  let stack = document.getElementById("toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.id = "toast-stack";
    stack.style.cssText = "position:fixed; right:20px; bottom:20px; z-index:9999; display:flex; flex-direction:column; gap:8px; max-width:360px;";
    document.body.appendChild(stack);
  }
  const toast = document.createElement("div");
  toast.style.cssText = "background:var(--surface, #fff); color:var(--text-primary, #111); border:1px solid var(--border, rgba(0,0,0,0.12)); border-left:3px solid var(--accent-cyan, #22d3ee); border-radius:10px; padding:10px 14px; box-shadow:0 8px 24px rgba(0,0,0,0.12); font-size:13px; line-height:1.45; transition:opacity .3s;";
  toast.innerHTML = `<div style="font-weight:600; margin-bottom:2px;">${escapeHtml(title)}</div><div style="color:var(--text-muted, #666); word-break:break-all;">${body}</div>`;
  stack.appendChild(toast);
  setTimeout(() => { toast.style.opacity = "0"; setTimeout(() => toast.remove(), 350); }, 6000);
}

function initAdrWatcher() {
  let lastSeq = null;
  const describe = (e) => {
    const parts = [];
    (e.added || []).forEach(f => parts.push(`+ ${escapeHtml(f)}`));
    (e.modified || []).forEach(f => parts.push(`~ ${escapeHtml(f)}`));
    (e.removed || []).forEach(f => parts.push(`&minus; ${escapeHtml(f)}`));
    return parts.join("<br>");
  };
  const poll = async () => {
    try {
      const res = await fetch(`/api/memory/changes?since=${lastSeq ?? 0}`);
      if (!res.ok) return;
      const data = await res.json();
      if (lastSeq === null) { lastSeq = data.seq; return; }  // ignore changes from before this page load
      if (!data.events.length) return;
      lastSeq = data.seq;
      data.events.forEach(e => {
        if (e.error) showToast("Memory reload failed", escapeHtml(e.error));
        else showToast(`Memory updated · ${e.workspace}`, describe(e) + "<br>Next request uses the new decisions.");
      });
      if (typeof initMemory === "function") initMemory();
    } catch (err) { /* server restarting; try again next tick */ }
  };
  poll();
  setInterval(poll, 2000);
}

// Welcome greeting: picks a fresh, time-aware line on every load
const GREETINGS = {
  morning: ["Good morning, {name}.", "Morning, {name}. Clear skies ahead.", "Rise and ship, {name}.", "Fresh coffee, fresh code, {name}."],
  afternoon: ["Good afternoon, {name}.", "Hey {name}, what are we building?", "Afternoon, {name}. Keep it rolling."],
  evening: ["Good evening, {name}.", "Evening, {name}. Let's wrap one up.", "Golden hour, {name}. Time to ship."],
  night: ["Burning the midnight oil, {name}?", "Hello, night owl.", "Still up, {name}? Let's make it count."],
  any: ["Hello there, {name}.", "Hi {name}, what's on the list?", "Welcome back, {name}.", "Ready when you are, {name}.", "Hey there, {name}."]
};
const GREETING_SUBS = [
  "What should we build today?",
  "Describe a change and I'll check it against your decisions first.",
  "Pick up where you left off, or start something new.",
  "Ask for a function, a refactor, or an explanation.",
  "Everything stays on this machine. Let's get to work.",
  "Your architecture is loaded. What's next?"
];

function initGreeting() {
  const titleEl = document.getElementById("hero-greeting");
  const subEl = document.getElementById("hero-greeting-sub");
  if (!titleEl || !subEl) return;

  const nameEl = document.querySelector(".user-name");
  const name = (nameEl && nameEl.textContent.trim()) || "there";
  const h = new Date().getHours();
  const slot = h >= 5 && h < 12 ? "morning" : h >= 12 && h < 17 ? "afternoon" : h >= 17 && h < 22 ? "evening" : "night";
  const pool = GREETINGS[slot].concat(GREETINGS.any);

  // Avoid showing the same line twice in a row
  let last = "";
  try { last = localStorage.getItem("clearsky_last_greeting") || ""; } catch (e) {}
  const choices = pool.filter(g => g !== last);
  const line = choices[Math.floor(Math.random() * choices.length)];
  try { localStorage.setItem("clearsky_last_greeting", line); } catch (e) {}
  const sub = GREETING_SUBS[Math.floor(Math.random() * GREETING_SUBS.length)];

  // Split into words; the user's name gets the sky gradient
  const parts = line.split("{name}");
  let i = 0;
  const wordSpans = (text, accent) => text.split(/(\s+)/).filter(Boolean).map(w =>
    /^\s+$/.test(w) ? " " : `<span class="greet-word${accent ? " accent" : ""}" style="--i:${i++}">${escapeHtml(w)}</span>`
  ).join("");
  titleEl.innerHTML = parts.map((p, idx) =>
    wordSpans(p, false) + (idx < parts.length - 1 ? wordSpans(name, true) : "")
  ).join("");
  subEl.textContent = sub;
  subEl.style.setProperty("--delay", `${0.25 + i * 0.07}s`);
}

function initTheme() {
  const btn = document.getElementById("btn-theme-toggle");
  if (!btn) return;
  btn.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "night" ? "day" : "night";
    document.documentElement.setAttribute("data-theme", next);
    try { localStorage.setItem("clearsky_theme", next); } catch (e) {}
  });
}

function initEventListeners() {
  const promptInput = document.getElementById("prompt-input");
  const btnRun = document.getElementById("btn-run");

  // Send action: text, screenshots, or both
  const sendCurrent = () => {
    const text = promptInput.value.trim();
    if ((!text && !pendingImages.length) || btnRun.disabled) return;
    const images = pendingImages;
    pendingImages = [];
    renderAttachTray();
    runWithPrompt(text || "Describe this screenshot.", null, images);
    promptInput.value = "";
    autoResizeTextarea(promptInput);
  };
  btnRun.addEventListener("click", sendCurrent);

  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendCurrent();
    }
  });

  initAttachments();

  promptInput.addEventListener("input", () => {
    autoResizeTextarea(promptInput);
  });

  // Action chips & recent scenarios
  const SCENARIO_REPO_MAP = {
    persist: "demo_vault",
    rotate: "demo_vault",
    force_legacy: "demo_vault",
    pyca_oaep: "cryptography",
    pyca_pkcs: "cryptography",
    pyca_pkcs1: "cryptography",
    pydantic_v2: "pydantic",
    pydantic_v1: "pydantic",
    db_sqlalchemy: "sqlalchemy",
    db_engine: "sqlalchemy",
  };

  document.querySelectorAll("[data-prompt]").forEach(elem => {
    elem.addEventListener("click", async () => {
      const key = elem.getAttribute("data-prompt");
      if (PROMPTS[key]) {
        const scenariosMenu = document.getElementById("scenarios-dropdown-menu");
        const btnScenarios = document.getElementById("btn-scenarios-dropdown");
        if (scenariosMenu) {
          scenariosMenu.style.display = "none";
          if (btnScenarios) btnScenarios.classList.remove("active");
        }

        const targetRepo = SCENARIO_REPO_MAP[key];
        if (targetRepo && targetRepo !== currentWorkspaceName) {
          try {
            await switchToWorkspace(targetRepo);
          } catch (e) {
            console.warn("Auto repo switch warning:", e);
          }
        }
        activeThreadId = null;
        renderThreadsList();
        document.querySelectorAll(".recent-item").forEach(r => r.classList.remove("active"));
        elem.classList.add("active");
        runWithPrompt(PROMPTS[key], PRESET_TITLES[key]);
      }
    });
  });

  // Scenarios footer dropdown toggle
  const btnScenarios = document.getElementById("btn-scenarios-dropdown");
  const scenariosMenu = document.getElementById("scenarios-dropdown-menu");
  const scenariosContainer = document.getElementById("scenarios-dropdown-container");

  if (btnScenarios && scenariosMenu) {
    btnScenarios.addEventListener("click", (e) => {
      e.stopPropagation();
      const isVisible = scenariosMenu.style.display !== "none";
      scenariosMenu.style.display = isVisible ? "none" : "flex";
      btnScenarios.classList.toggle("active", !isVisible);
    });

    document.addEventListener("click", (e) => {
      if (scenariosContainer && !scenariosContainer.contains(e.target)) {
        scenariosMenu.style.display = "none";
        btnScenarios.classList.remove("active");
      }
    });

    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && scenariosMenu.style.display !== "none") {
        scenariosMenu.style.display = "none";
        btnScenarios.classList.remove("active");
      }
    });
  }

  // Sidebar toggle
  const sidebar = document.getElementById("sidebar");
  const btnToggleSidebar = document.getElementById("btn-toggle-sidebar");
  const btnExpandSidebar = document.getElementById("btn-expand-sidebar");

  if (btnToggleSidebar) {
    btnToggleSidebar.addEventListener("click", () => {
      sidebar.classList.add("collapsed");
      btnExpandSidebar.style.display = "flex";
    });
  }
  if (btnExpandSidebar) {
    btnExpandSidebar.addEventListener("click", () => {
      sidebar.classList.remove("collapsed");
      btnExpandSidebar.style.display = "none";
    });
    btnExpandSidebar.style.display = "none";
  }
  if (btnToggleSidebar && window.matchMedia("(max-width: 760px)").matches) {
    btnToggleSidebar.click();
  }

  // Mode switcher (Chat vs Diff Inspector)
  const btnModeChat = document.getElementById("btn-mode-chat");
  const btnToggleDiff = document.getElementById("btn-toggle-diff-mode");
  if (btnModeChat) {
    btnModeChat.addEventListener("click", () => setAppMode("chat"));
  }
  if (btnToggleDiff) {
    btnToggleDiff.addEventListener("click", () => setAppMode("diff"));
  }

  // New session button
  document.getElementById("btn-new-session").addEventListener("click", () => {
    activeThreadId = null;
    latestRunData = null;
    setAppMode("chat");
    renderThreadsList();
    document.querySelectorAll(".recent-item").forEach(r => r.classList.remove("active"));
    document.getElementById("hero-view").style.display = "flex";
    document.getElementById("messages-stream").style.display = "none";
    document.getElementById("messages-stream").innerHTML = "";
    promptInput.value = "";
    currentRunId = null;
    initGreeting();
  });

  // Memory drawer toggle
  const memoryDrawer = document.getElementById("memory-drawer");
  document.getElementById("nav-memory").addEventListener("click", () => {
    memoryDrawer.classList.toggle("open");
    initMemory();
  });
  document.getElementById("btn-close-drawer").addEventListener("click", () => {
    memoryDrawer.classList.remove("open");
  });

  // Reset demo
  const btnResetSidebar = document.getElementById("btn-reset-sidebar");
  if (btnResetSidebar) btnResetSidebar.addEventListener("click", resetDemo);

  const btnResetDemo = document.getElementById("btn-reset-demo");
  if (btnResetDemo) btnResetDemo.addEventListener("click", resetDemo);

  const btnResetDrawer = document.getElementById("btn-reset-drawer");
  if (btnResetDrawer) btnResetDrawer.addEventListener("click", resetDemo);

  const btnClearThreads = document.getElementById("btn-clear-threads");
  if (btnClearThreads) btnClearThreads.addEventListener("click", clearRecentTasks);

  // ⌘K / Ctrl+K starts a new task
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      document.getElementById("btn-new-session").click();
      promptInput.focus();
    }
  });
}

// Screenshot attachments: sent to the vision model with the next message
const MAX_ATTACHMENTS = 4;
const MAX_IMAGE_EDGE = 1280;
const KEEP_ORIGINAL_BYTES = 1.5 * 1024 * 1024;
let pendingImages = []; // { id, name, base64, thumb, width, height }
let visionAvailable = true;

function readAsDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error(`Could not read ${file.name || "the image"}`));
    reader.readAsDataURL(file);
  });
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("That file is not a readable image"));
    img.src = src;
  });
}

function drawScaled(img, maxEdge, type, quality) {
  const scale = Math.min(1, maxEdge / Math.max(img.naturalWidth, img.naturalHeight));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
  canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; // JPEG has no alpha
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL(type, quality);
}

async function prepareImage(file) {
  const original = await readAsDataURL(file);
  const img = await loadImage(original);
  const longest = Math.max(img.naturalWidth, img.naturalHeight);
  // Small PNG/JPEG go as-is (sharp text); everything else is downscaled to keep prefill fast
  const keep = (file.type === "image/png" || file.type === "image/jpeg")
    && file.size <= KEEP_ORIGINAL_BYTES && longest <= MAX_IMAGE_EDGE;
  const dataUrl = keep ? original : drawScaled(img, MAX_IMAGE_EDGE, "image/jpeg", 0.9);
  return {
    id: "img_" + Math.random().toString(36).slice(2, 9),
    name: file.name || "screenshot",
    base64: dataUrl.slice(dataUrl.indexOf(",") + 1),
    thumb: drawScaled(img, 160, "image/jpeg", 0.8),
    width: img.naturalWidth,
    height: img.naturalHeight,
  };
}

function flashAttachNote(message) {
  const tray = document.getElementById("attach-tray");
  if (!tray) return;
  tray.hidden = false;
  let note = tray.querySelector(".attach-note");
  if (!note) {
    note = document.createElement("div");
    note.className = "attach-note";
    tray.appendChild(note);
  }
  note.textContent = message;
  clearTimeout(flashAttachNote._t);
  flashAttachNote._t = setTimeout(renderAttachTray, 3500);
}

async function addImageFiles(fileList) {
  const files = Array.from(fileList || []).filter(f => f.type && f.type.startsWith("image/"));
  if (!files.length) return;
  if (!visionAvailable) {
    flashAttachNote("Screenshots need the vision model. Run: ollama pull qwen3-vl:8b-instruct");
    return;
  }
  for (const file of files) {
    if (pendingImages.length >= MAX_ATTACHMENTS) {
      flashAttachNote(`Up to ${MAX_ATTACHMENTS} screenshots per message.`);
      break;
    }
    try {
      pendingImages.push(await prepareImage(file));
    } catch (err) {
      flashAttachNote(err.message);
    }
  }
  renderAttachTray();
  document.getElementById("prompt-input").focus();
}

function renderAttachTray() {
  const tray = document.getElementById("attach-tray");
  if (!tray) return;
  tray.hidden = pendingImages.length === 0;
  tray.innerHTML = pendingImages.map(img => `
    <div class="attach-chip" data-id="${img.id}" title="${escapeHtml(img.name)} · ${img.width}×${img.height}">
      <img src="${img.thumb}" alt="${escapeHtml(img.name)}" />
      <button type="button" class="attach-remove" aria-label="Remove screenshot">&times;</button>
    </div>`).join("") +
    (pendingImages.length ? `<span class="attach-count">${pendingImages.length}/${MAX_ATTACHMENTS} · sent to the vision model</span>` : "");
  tray.querySelectorAll(".attach-remove").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.closest(".attach-chip").dataset.id;
      pendingImages = pendingImages.filter(i => i.id !== id);
      renderAttachTray();
    });
  });
}

function updateImageButton() {
  const btn = document.getElementById("btn-add-image");
  if (!btn) return;
  btn.classList.toggle("unavailable", !visionAvailable);
  btn.title = visionAvailable
    ? "Attach screenshots (or paste / drop them)"
    : "Screenshots need the vision model: ollama pull qwen3-vl:8b-instruct";
}

function initAttachments() {
  const btn = document.getElementById("btn-add-image");
  const input = document.getElementById("image-input");
  const promptInput = document.getElementById("prompt-input");
  const capsule = document.querySelector(".input-capsule");

  if (btn && input) {
    btn.addEventListener("click", () => input.click());
    input.addEventListener("change", () => {
      addImageFiles(input.files);
      input.value = "";
    });
  }

  // Paste a screenshot straight from the clipboard (e.g. Cmd+Shift+Ctrl+4, then Cmd+V)
  promptInput.addEventListener("paste", (e) => {
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []).filter(f => f.type.startsWith("image/"));
    if (files.length) {
      e.preventDefault();
      addImageFiles(files);
    }
  });

  // Drag and drop onto the composer
  const hasFiles = (e) => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files");
  let dragDepth = 0;
  if (capsule) {
    capsule.addEventListener("dragenter", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth++;
      capsule.classList.add("dragging");
    });
    capsule.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
    capsule.addEventListener("dragleave", () => {
      dragDepth = Math.max(0, dragDepth - 1);
      if (!dragDepth) capsule.classList.remove("dragging");
    });
    capsule.addEventListener("drop", (e) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      dragDepth = 0;
      capsule.classList.remove("dragging");
      addImageFiles(e.dataTransfer.files);
    });
  }
  // A file dropped anywhere else should not navigate away from the dashboard
  window.addEventListener("dragover", (e) => { if (hasFiles(e)) e.preventDefault(); });
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    if (!capsule || !capsule.contains(e.target)) addImageFiles(e.dataTransfer.files);
  });
  updateImageButton();
}

function autoResizeTextarea(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 140) + "px";
}

async function initHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return;
    const data = await res.json();

    webSearchAllowed = data.web_search_allowed !== false;
    computerAllowed = data.computer_access_allowed !== false;
    visionAvailable = data.vision_available !== false;
    updateImageButton();
    updateComposerMode();

    const pillVerdict = document.getElementById("pill-verdict");
    if (data.verdict_loaded) {
      pillVerdict.innerHTML = '<span class="badge-dot"></span> Verdict v1.4 · local';
      pillVerdict.className = "status-badge green";
    } else {
      pillVerdict.innerHTML = '<span class="badge-dot"></span> Verdict unavailable';
      pillVerdict.className = "status-badge amber";
      pillVerdict.title = data.verdict_error || "";
    }

    const pillOllama = document.getElementById("pill-ollama");
    if (data.ollama_ok) {
      pillOllama.innerHTML = '<span class="badge-dot"></span> Local SLM';
      pillOllama.className = "status-badge green";
      pillOllama.title = `Model ${data.model} is ready in local Ollama`;
    } else if (data.model === "mock-offline-fast") {
      pillOllama.innerHTML = '<span class="badge-dot"></span> Mock Mode';
      pillOllama.className = "status-badge amber";
      pillOllama.title = "Running mock generative engine";
    } else {
      pillOllama.innerHTML = '<span class="badge-dot"></span> Model Not Installed';
      pillOllama.className = "status-badge amber";
      pillOllama.title = `Model '${data.model}' is not installed in local Ollama. Run 'ollama pull ${data.model}'`;
    }

    const selectModel = document.getElementById("select-model");
    if (selectModel && data.model) {
      selectModel.value = data.model;
    }
  } catch (e) {
    console.error("Health check error:", e);
  }
}

async function initModelSelector() {
  const select = document.getElementById("select-model");
  if (!select) return;
  try {
    const res = await fetch("/api/models");
    if (!res.ok) return;
    const data = await res.json();
    const models = data.models || {};
    const active = data.active_model;

    // Populate dropdown with clean model names only
    select.innerHTML = "";
    for (const [id, m] of Object.entries(models)) {
      const opt = document.createElement("option");
      opt.value = id;
      opt.textContent = m.name || id;
      if (id === active) opt.selected = true;
      select.appendChild(opt);
    }

    if (active) select.value = active;

    select.addEventListener("change", async () => {
      const chosen = select.value;
      try {
        await fetch("/api/models", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ model_id: chosen })
        });
        await initHealth();
      } catch (err) {
        console.error("Failed to change model:", err);
      }
    });
  } catch (e) {
    console.error("Model selector error:", e);
  }
}

let currentWorkspaceName = "demo_vault";

// Web search: No-workspace mode only, off unless the user turns it on
let webSearchAllowed = true;
let webSearchOn = false;
try { webSearchOn = localStorage.getItem("clearsky_web_search") === "1"; } catch (e) {}

function isFreeMode() {
  return currentWorkspaceName === "No workspace";
}

function webSearchActive() {
  return isFreeMode() && webSearchAllowed && webSearchOn;
}

// Computer access: read-only tools on this machine, No-workspace mode only, off by default
let computerAllowed = true;
let computerOn = false;
try { computerOn = localStorage.getItem("clearsky_computer") === "1"; } catch (e) {}

function computerActive() {
  return isFreeMode() && computerAllowed && computerOn;
}

function composerToggle(id, iconSvg, label, onClick, insertAfter) {
  let btn = document.getElementById(id);
  if (!btn && insertAfter) {
    btn = document.createElement("button");
    btn.id = id;
    btn.className = "input-action-btn composer-toggle";
    btn.type = "button";
    btn.innerHTML = `${iconSvg}<span class="composer-toggle-label">${label}</span>`;
    btn.addEventListener("click", onClick);
    insertAfter.parentNode.insertBefore(btn, insertAfter.nextSibling);
  }
  return btn;
}

function updateComposerMode() {
  const free = isFreeMode();
  const pillText = document.getElementById("policy-pill-text");
  if (pillText) pillText.textContent = free ? "Policy gate off" : "Policy gate on";

  let btn = document.getElementById("btn-web-search");
  const pill = document.getElementById("policy-pill");
  if (!btn && pill) {
    btn = document.createElement("button");
    btn.id = "btn-web-search";
    btn.className = "input-action-btn";
    btn.type = "button";
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15 15 0 0 1 0 20M12 2a15 15 0 0 0 0 20"/></svg><span id="btn-web-search-label">Web</span>';
    btn.addEventListener("click", () => {
      webSearchOn = !webSearchOn;
      try { localStorage.setItem("clearsky_web_search", webSearchOn ? "1" : "0"); } catch (e) {}
      updateComposerMode();
    });
    pill.parentNode.insertBefore(btn, pill.nextSibling);
  }
  if (btn) {
    btn.style.display = free && webSearchAllowed ? "" : "none";
    btn.setAttribute("aria-pressed", webSearchOn ? "true" : "false");
    btn.title = webSearchOn
      ? "Web search on: your message is sent to a search engine"
      : "Web search off: answers come only from the local model";
    btn.style.color = webSearchOn ? "var(--accent-cyan, #22d3ee)" : "";
    btn.style.borderColor = webSearchOn ? "var(--accent-cyan, #22d3ee)" : "";
    const label = document.getElementById("btn-web-search-label");
    if (label) label.textContent = webSearchOn ? "Web on" : "Web";
  }

  const compBtn = composerToggle(
    "btn-computer",
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg>',
    "Computer",
    () => {
      computerOn = !computerOn;
      try { localStorage.setItem("clearsky_computer", computerOn ? "1" : "0"); } catch (e) {}
      updateComposerMode();
    },
    btn || pill
  );
  if (compBtn) {
    compBtn.style.display = free && computerAllowed ? "" : "none";
    compBtn.setAttribute("aria-pressed", computerOn ? "true" : "false");
    compBtn.classList.toggle("on", computerOn);
    compBtn.title = computerOn
      ? "Computer access on: the model can run read-only commands and read files on this Mac (keys, passwords and browser data are blocked)"
      : "Computer access off: turn on to let the model look things up on this Mac";
    compBtn.querySelector(".composer-toggle-label").textContent = computerOn ? "Computer on" : "Computer";
  }

  const note = document.getElementById("input-footer-note");
  if (note) {
    note.textContent = !free
      ? "Runs entirely on this machine. No prompts, code, or telemetry reach a cloud API."
      : webSearchActive()
        ? "Web search on: your message is sent to a search engine (DuckDuckGo, then Wikipedia). Repository code and ADRs never leave this machine."
        : computerActive()
          ? "Computer access on: the model can run read-only commands and read files here. Keys, passwords and browser data stay blocked."
          : "No workspace: policy checks are off. Everything still runs on this machine.";
  }
}

async function switchToWorkspace(targetPath) {
  try {
    const res = await fetch("/api/workspace", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: targetPath })
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Failed to switch workspace");
    }
    const data = await res.json();
    currentWorkspaceName = data.name;
    updateComposerMode();
    const labelEl = document.getElementById("workspace-label");
    if (labelEl) labelEl.textContent = data.name;
    const pathInput = document.getElementById("workspace-path-input");
    if (pathInput) pathInput.value = data.workspace_root;
    const statusInfo = document.getElementById("workspace-status-info");
    if (statusInfo) {
      statusInfo.textContent = `Active: ${data.workspace_root} (${data.adr_count} ADRs, ${data.note_count} Notes)`;
    }
    await initMemory();
    return data;
  } catch (err) {
    console.error("Workspace switch error:", err);
    throw err;
  }
}

async function initWorkspace() {
  const btnAttach = document.getElementById("btn-attach");
  const labelEl = document.getElementById("workspace-label");
  const backdrop = document.getElementById("workspace-modal-backdrop");
  const btnClose = document.getElementById("btn-workspace-close");
  const btnCancel = document.getElementById("btn-workspace-cancel");
  const btnSwitch = document.getElementById("btn-workspace-switch");
  const pathInput = document.getElementById("workspace-path-input");
  const statusInfo = document.getElementById("workspace-status-info");
  const presetsContainer = document.getElementById("workspace-presets-container");

  async function fetchCurrentWorkspace() {
    try {
      const res = await fetch("/api/workspaces");
      if (!res.ok) return;
      const data = await res.json();
      currentWorkspaceName = data.active;
      updateComposerMode();
      if (labelEl) labelEl.textContent = data.active || "workspace";
      if (pathInput) pathInput.value = data.active_path || "demo_vault";
      if (statusInfo) {
        statusInfo.textContent = `Active: ${data.active_path}`;
      }

      if (presetsContainer && data.presets) {
        presetsContainer.innerHTML = "";
        data.presets.forEach(p => {
          const card = document.createElement("div");
          const isActive = p.name === data.active;
          card.className = "workspace-card" + (isActive ? " active" : "");
          card.innerHTML = `
            <div class="workspace-card-header">
              <span class="workspace-card-title">${escapeHtml(p.title || p.name)}</span>
              <span class="workspace-card-badge">${isActive ? "● Active" : escapeHtml(p.domain)}</span>
            </div>
            <div class="workspace-card-desc">${escapeHtml(p.desc)}</div>
            ${p.repo_url ? `<div class="workspace-card-url" style="font-size: 11px; word-break: break-all;"><a href="${escapeHtml(p.repo_url)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation();">${escapeHtml(p.repo_url)} ↗</a></div>` : ''}
            <div class="workspace-card-meta">
              <span class="workspace-card-adrs">${p.adrs.join(" &middot; ")}</span>
            </div>
          `;
          card.addEventListener("click", async () => {
            if (isActive) {
              closeWorkspaceModal();
              return;
            }
            try {
              await switchToWorkspace(p.path || p.id);
              closeWorkspaceModal();
            } catch (err) {
              alert("Failed to switch: " + err.message);
            }
          });
          presetsContainer.appendChild(card);
        });
      }
    } catch (e) {
      console.warn("Failed to load workspace info:", e);
    }
  }

  function openWorkspaceModal() {
    if (backdrop) {
      backdrop.style.display = "flex";
      fetchCurrentWorkspace();
      setTimeout(() => pathInput && pathInput.focus(), 50);
    }
  }

  function closeWorkspaceModal() {
    if (backdrop) backdrop.style.display = "none";
  }

  if (btnAttach) btnAttach.addEventListener("click", openWorkspaceModal);
  if (btnClose) btnClose.addEventListener("click", closeWorkspaceModal);
  if (btnCancel) btnCancel.addEventListener("click", closeWorkspaceModal);
  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeWorkspaceModal();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && backdrop && backdrop.style.display !== "none") {
      closeWorkspaceModal();
    }
  });

  if (btnSwitch) {
    btnSwitch.addEventListener("click", async () => {
      const targetPath = (pathInput ? pathInput.value : "").trim();
      if (!targetPath) {
        alert("Please enter a valid directory path.");
        return;
      }
      btnSwitch.disabled = true;
      btnSwitch.textContent = "Switching...";

      try {
        await switchToWorkspace(targetPath);
        closeWorkspaceModal();
      } catch (err) {
        alert("Cannot switch workspace: " + err.message);
      } finally {
        btnSwitch.disabled = false;
        btnSwitch.textContent = "Switch";
      }
    });
  }

  await fetchCurrentWorkspace();
}

let currentModalAdrId = null;
let currentModalAdrData = null;
let isAdrModalCreateMode = false;
let isGeneratingAdr = false;

function updateAdrPromptBadge() {
  const badge = document.getElementById("adr-prompt-badge");
  const contentInput = document.getElementById("adr-edit-content");
  const modelSelect = document.getElementById("select-model");
  const modelName = modelSelect && modelSelect.options[modelSelect.selectedIndex] ? modelSelect.options[modelSelect.selectedIndex].text : "Local SLM";
  if (!badge || !contentInput) return;

  const val = contentInput.value;
  const idx = val.indexOf("/prompt");
  if (idx !== -1) {
    const textAfter = val.slice(idx + 7).trim();
    badge.classList.add("active");
    if (textAfter) {
      badge.innerHTML = `<span class="adr-prompt-sparkle">✨</span> Press <strong>Enter</strong> to generate with <strong>${escapeHtml(modelName)}</strong>`;
    } else {
      badge.innerHTML = `<span class="adr-prompt-sparkle">✨</span> Type instruction after <code>/prompt</code> + Enter`;
    }
  } else {
    badge.classList.remove("active");
    badge.innerHTML = `<span class="adr-prompt-sparkle">✨</span> Type <code>/prompt &lt;instruction&gt;</code> + Enter to AI generate`;
  }
}

async function triggerAdrGeneration(instruction) {
  if (isGeneratingAdr) return;
  const contentInput = document.getElementById("adr-edit-content");
  const filenameInput = document.getElementById("adr-edit-filename");
  const statusEl = document.getElementById("adr-generating-status");
  const statusText = document.getElementById("adr-generating-status-text");
  const btnSave = document.getElementById("btn-adr-save");
  const modelSelect = document.getElementById("select-model");
  const selectedModel = modelSelect ? modelSelect.value : null;
  const modelName = modelSelect && modelSelect.options[modelSelect.selectedIndex] ? modelSelect.options[modelSelect.selectedIndex].text : "Local SLM";

  isGeneratingAdr = true;
  if (btnSave) btnSave.disabled = true;
  if (contentInput) {
    contentInput.disabled = true;
    contentInput.value = "";
  }
  if (statusEl) statusEl.style.display = "flex";
  if (statusText) statusText.textContent = `Reasoning with ${modelName}...`;

  try {
    const res = await fetch("/api/adr/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt: instruction,
        model_id: selectedModel
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "ADR generation failed");
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let accumulatedText = "";
    let sseBuffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      sseBuffer += decoder.decode(value, { stream: true });

      const lines = sseBuffer.split("\n");
      sseBuffer = lines.pop();

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          const rawJson = line.slice(6).trim();
          if (!rawJson) continue;
          try {
            const data = JSON.parse(rawJson);
            if (data.type === "thinking") {
              if (statusText) {
                const preview = data.chunk.trim().slice(-60);
                statusText.textContent = preview ? `Reasoning: ${preview}` : `Reasoning with ${modelName}...`;
              }
            } else if (data.type === "response") {
              accumulatedText += data.chunk;
              if (contentInput) contentInput.value = accumulatedText;
              if (statusText) statusText.textContent = `Generating ADR specification with ${modelName}...`;
            } else if (data.type === "finished") {
              if (contentInput) contentInput.value = data.content;
              if (filenameInput && data.filename && isAdrModalCreateMode) {
                filenameInput.value = data.filename;
              }
            } else if (data.type === "error") {
              throw new Error(data.detail);
            }
          } catch (pe) {
            console.warn("SSE parse error:", pe, rawJson);
          }
        }
      }
    }
  } catch (err) {
    alert("Error generating ADR: " + err.message);
  } finally {
    isGeneratingAdr = false;
    if (contentInput) {
      contentInput.disabled = false;
      contentInput.focus();
    }
    if (btnSave) btnSave.disabled = false;
    if (statusEl) statusEl.style.display = "none";
    updateAdrPromptBadge();
  }
}

function initAdrModal() {
  const backdrop = document.getElementById("adr-modal-backdrop");
  const btnClose = document.getElementById("btn-adr-close");
  const btnToggleEdit = document.getElementById("btn-adr-toggle-edit");
  const btnDelete = document.getElementById("btn-adr-delete");
  const btnCancelEdit = document.getElementById("btn-adr-cancel-edit");
  const btnSave = document.getElementById("btn-adr-save");
  const btnAddAdr = document.getElementById("btn-add-adr");
  const contentInput = document.getElementById("adr-edit-content");
  const promptBadge = document.getElementById("adr-prompt-badge");

  if (btnAddAdr) {
    btnAddAdr.addEventListener("click", () => openAdrModal(null, true));
  }

  if (btnClose) {
    btnClose.addEventListener("click", closeAdrModal);
  }

  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeAdrModal();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && backdrop && backdrop.style.display !== "none") {
      closeAdrModal();
    }
  });

  if (contentInput) {
    contentInput.addEventListener("input", updateAdrPromptBadge);
    contentInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        const val = contentInput.value;
        const idx = val.indexOf("/prompt");
        if (idx !== -1) {
          const instruction = val.slice(idx + 7).trim();
          if (instruction) {
            e.preventDefault();
            triggerAdrGeneration(instruction);
          }
        }
      }
    });
  }

  if (promptBadge) {
    promptBadge.addEventListener("click", () => {
      if (!contentInput) return;
      const val = contentInput.value;
      const idx = val.indexOf("/prompt");
      if (idx !== -1) {
        const instruction = val.slice(idx + 7).trim();
        if (instruction) {
          triggerAdrGeneration(instruction);
          return;
        }
      } else {
        contentInput.value = "/prompt " + (val.trim() ? val.trim() : "");
      }
      contentInput.focus();
      updateAdrPromptBadge();
    });
  }

  if (btnToggleEdit) {
    btnToggleEdit.addEventListener("click", () => {
      const viewEl = document.getElementById("adr-modal-view");
      const editEl = document.getElementById("adr-modal-edit");
      if (editEl.style.display === "none") {
        viewEl.style.display = "none";
        editEl.style.display = "flex";
        btnToggleEdit.textContent = "Preview";
        document.getElementById("adr-edit-content").focus();
        updateAdrPromptBadge();
      } else {
        editEl.style.display = "none";
        viewEl.style.display = "flex";
        btnToggleEdit.textContent = "Edit";
      }
    });
  }

  if (btnCancelEdit) {
    btnCancelEdit.addEventListener("click", () => {
      if (isAdrModalCreateMode) {
        closeAdrModal();
      } else {
        const viewEl = document.getElementById("adr-modal-view");
        const editEl = document.getElementById("adr-modal-edit");
        editEl.style.display = "none";
        viewEl.style.display = "flex";
        if (btnToggleEdit) btnToggleEdit.textContent = "Edit";
      }
    });
  }

  if (btnSave) {
    btnSave.addEventListener("click", async () => {
      const content = document.getElementById("adr-edit-content").value.trim();
      if (!content) {
        alert("ADR content cannot be empty.");
        return;
      }

      btnSave.disabled = true;
      btnSave.textContent = "Saving...";

      try {
        if (isAdrModalCreateMode) {
          const filename = document.getElementById("adr-edit-filename").value.trim();
          if (!filename) {
            alert("Please specify a filename (e.g. 046-my-decision.md).");
            btnSave.disabled = false;
            btnSave.textContent = "Save ADR";
            return;
          }
          const res = await fetch("/api/adr", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ filename, content })
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to create ADR");
          }
          await initMemory();
          closeAdrModal();
        } else {
          const res = await fetch(`/api/adr/${encodeURIComponent(currentModalAdrId)}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ content })
          });
          if (!res.ok) {
            const err = await res.json();
            throw new Error(err.detail || "Failed to update ADR");
          }
          await initMemory();
          await openAdrModal(currentModalAdrId, false);
        }
      } catch (err) {
        alert("Error saving ADR: " + err.message);
      } finally {
        btnSave.disabled = false;
        btnSave.textContent = "Save ADR";
      }
    });
  }

  if (btnDelete) {
    btnDelete.addEventListener("click", async () => {
      if (!currentModalAdrId) return;
      const title = currentModalAdrData ? currentModalAdrData.title : currentModalAdrId;
      if (!confirm(`Are you sure you want to delete ${title}?\n\nThis will remove the file from docs/adr/ and rebuild the temporal memory graph.`)) {
        return;
      }

      btnDelete.disabled = true;
      btnDelete.textContent = "Deleting...";

      try {
        const res = await fetch(`/api/adr/${encodeURIComponent(currentModalAdrId)}`, {
          method: "DELETE"
        });
        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Failed to delete ADR");
        }
        await initMemory();
        closeAdrModal();
      } catch (err) {
        alert("Error deleting ADR: " + err.message);
      } finally {
        btnDelete.disabled = false;
        btnDelete.textContent = "Delete";
      }
    });
  }
}

function closeAdrModal() {
  const backdrop = document.getElementById("adr-modal-backdrop");
  if (backdrop) backdrop.style.display = "none";
  currentModalAdrId = null;
  currentModalAdrData = null;
  isAdrModalCreateMode = false;
}

async function openAdrModal(adrId, isCreate = false) {
  const backdrop = document.getElementById("adr-modal-backdrop");
  const titleEl = document.getElementById("adr-modal-title");
  const badgeEl = document.getElementById("adr-modal-badge");
  const viewEl = document.getElementById("adr-modal-view");
  const editEl = document.getElementById("adr-modal-edit");
  const btnToggleEdit = document.getElementById("btn-adr-toggle-edit");
  const btnDelete = document.getElementById("btn-adr-delete");
  const filenameRow = document.getElementById("adr-create-filename-row");
  const filenameInput = document.getElementById("adr-edit-filename");
  const contentInput = document.getElementById("adr-edit-content");

  if (!backdrop) return;

  isAdrModalCreateMode = isCreate;
  currentModalAdrId = adrId;

  if (isCreate) {
    titleEl.textContent = "Create New Architecture Decision (ADR)";
    badgeEl.textContent = "New (Draft)";
    badgeEl.className = "status-badge blue";
    if (btnToggleEdit) btnToggleEdit.style.display = "none";
    if (btnDelete) btnDelete.style.display = "none";
    if (filenameRow) filenameRow.style.display = "flex";

    const dateStr = new Date().toISOString().split("T")[0];
    filenameInput.value = "046-new-architecture-decision.md";
    contentInput.value = "";
    contentInput.placeholder = "Type /prompt <instructions> and press Enter (e.g. /prompt Enforce that all HTTP clients use httpx with verify=True)... or write ADR markdown";
    updateAdrPromptBadge();

    viewEl.style.display = "none";
    editEl.style.display = "flex";
    backdrop.style.display = "flex";
    setTimeout(() => contentInput.focus(), 50);
    return;
  }

  // Load existing ADR
  if (btnToggleEdit) {
    btnToggleEdit.style.display = "inline-block";
    btnToggleEdit.textContent = "Edit";
  }
  if (btnDelete) {
    btnDelete.style.display = "inline-block";
  }
  if (filenameRow) {
    filenameRow.style.display = "none";
  }

  viewEl.style.display = "flex";
  editEl.style.display = "none";

  titleEl.textContent = "Loading ADR...";
  backdrop.style.display = "flex";

  try {
    const res = await fetch(`/api/adr/${encodeURIComponent(adrId)}`);
    if (!res.ok) throw new Error("ADR not found");
    const data = await res.json();
    currentModalAdrData = data;

    titleEl.textContent = data.title || data.filename;
    
    if (data.epistemic_status === "superseded") {
      badgeEl.textContent = "Superseded (Banned)";
      badgeEl.className = "status-badge red";
    } else {
      badgeEl.textContent = "In Force (Active)";
      badgeEl.className = "status-badge green";
    }

    document.getElementById("adr-view-file").textContent = `docs/adr/${data.filename}`;
    document.getElementById("adr-view-date").textContent = data.date || "None";
    document.getElementById("adr-view-tags").textContent = (data.tags && data.tags.length > 0) ? data.tags.join(", ") : "None";
    document.getElementById("adr-view-decision").textContent = data.description || "No decision statement found.";

    const supersededBox = document.getElementById("adr-view-superseded-box");
    const supersededReasonEl = document.getElementById("adr-view-superseded-reason");
    if (data.epistemic_status === "superseded" || data.why_inactive) {
      if (supersededBox) supersededBox.style.display = "block";
      if (supersededReasonEl) {
        supersededReasonEl.textContent = data.why_inactive || "This decision has been superseded by a newer architectural standard. Its patterns are strictly forbidden in production code.";
      }
    } else {
      if (supersededBox) supersededBox.style.display = "none";
    }

    const reqContainer = document.getElementById("adr-view-required");
    reqContainer.innerHTML = "";
    if (data.required && data.required.length > 0) {
      data.required.forEach(item => {
        const span = document.createElement("span");
        span.className = "adr-token-pill required";
        span.textContent = item;
        reqContainer.appendChild(span);
      });
    } else {
      reqContainer.innerHTML = '<span style="color:var(--text-muted); font-size:12px;">None</span>';
    }

    const forbContainer = document.getElementById("adr-view-forbidden");
    forbContainer.innerHTML = "";
    if (data.forbidden && data.forbidden.length > 0) {
      data.forbidden.forEach(item => {
        const span = document.createElement("span");
        span.className = "adr-token-pill forbidden";
        span.textContent = item;
        forbContainer.appendChild(span);
      });
    } else {
      forbContainer.innerHTML = '<span style="color:var(--text-muted); font-size:12px;">None</span>';
    }

    document.getElementById("adr-view-raw").textContent = data.content || "";
    contentInput.value = data.content || "";
    updateAdrPromptBadge();

  } catch (err) {
    titleEl.textContent = "Error loading ADR";
    document.getElementById("adr-view-decision").textContent = err.message;
  }
}

async function initMemory() {
  try {
    const res = await fetch("/api/memory");
    if (!res.ok) return;
    const data = await res.json();

    const inForceList = document.getElementById("memory-in-force");
    if (inForceList) {
      inForceList.innerHTML = "";
      (data.in_force || [])
        .filter(item => item.type === "architecture_decision")
        .forEach(item => {
          const li = document.createElement("li");
          li.className = "memory-adr-item";
          li.dataset.adrId = item.id;
          li.innerHTML = `
            <span>${escapeHtml(item.label || item.id)}</span>
            <div class="adr-item-meta">
              <span class="adr-item-click-hint">Open →</span>
            </div>
          `;
          li.addEventListener("click", () => openAdrModal(item.id));
          inForceList.appendChild(li);
        });
    }

    const supersededList = document.getElementById("memory-superseded");
    if (supersededList) {
      supersededList.innerHTML = "";
      (data.superseded || [])
        .filter(item => item.type === "architecture_decision")
        .forEach(item => {
          const li = document.createElement("li");
          li.className = "memory-adr-item";
          li.dataset.adrId = item.id;
          li.innerHTML = `
            <span>${escapeHtml(item.label || item.id)}</span>
            <div class="adr-item-meta">
              <span class="adr-item-click-hint">Open →</span>
            </div>
          `;
          li.addEventListener("click", () => openAdrModal(item.id));
          supersededList.appendChild(li);
        });
    }

    const notesList = document.getElementById("memory-notes");
    if (notesList) {
      notesList.innerHTML = "";
      (data.notes || []).forEach(item => {
        const li = document.createElement("li");
        li.innerHTML = `<strong>${escapeHtml(item.label)}</strong>: ${escapeHtml(item.description || "")}`;
        notesList.appendChild(li);
      });
    }

    const habitsList = document.getElementById("memory-habits");
    const habitsCount = (data.in_force || []).filter(item => item.type === "habit").length;
    document.getElementById("badge-habits-count").textContent = habitsCount;

    if (habitsList) {
      habitsList.innerHTML = "";
      (data.in_force || []).filter(item => item.type === "habit").forEach(item => {
        const li = document.createElement("li");
        li.textContent = item.label;
        habitsList.appendChild(li);
      });
      if (habitsCount === 0) {
        habitsList.innerHTML = '<li style="color:var(--text-muted); text-decoration:none;">No learned habits yet. Edit and approve a patch to synthesize a habit.</li>';
      }
    }
  } catch (e) {
    console.error("Memory fetch error:", e);
  }
}

// Conversation memory per thread: sent with each request so follow-ups
// ("now in C++") are understood. The server uses it in No-workspace mode.
const HISTORY_TURN_CHARS = 4000;

function activeThread() {
  return activeThreadId ? threads.find(t => t.id === activeThreadId) : null;
}

function threadHistory() {
  const t = activeThread();
  return t && Array.isArray(t.history) ? t.history.slice(-12) : [];
}

function summarizeRun(data) {
  const a = data.aegis || {};
  if (data.status === "free") return a.text || "";
  if (data.status === "blocked") return `Blocked: ${data.block_reason || data.abstain_reason || "forbidden by an active decision"}`;
  if (data.status === "abstained") return `Declined: ${data.abstain_reason || "no decision covers this request"}`;
  if (data.task_type === "explain_only") return a.text || "";
  if (a.code) return `Proposed patch for ${data.target_file || "the workspace"}:\n\`\`\`python\n${a.code}\n\`\`\``;
  return a.text || "";
}

function recordTurn(promptText, data) {
  const t = activeThread();
  if (!t) return;
  if (!Array.isArray(t.history)) t.history = [];
  const reply = summarizeRun(data).slice(0, HISTORY_TURN_CHARS);
  t.history.push({ role: "user", content: promptText.slice(0, HISTORY_TURN_CHARS) });
  if (reply) t.history.push({ role: "assistant", content: reply });
  t.history = t.history.slice(-24);
  saveThreads();
}

async function runWithPrompt(promptText, presetTitle = null, images = []) {
  document.getElementById("hero-view").style.display = "none";
  const messagesStream = document.getElementById("messages-stream");
  messagesStream.style.display = "flex";

  // Register thread if new session
  if (!activeThreadId) {
    activeThreadId = "thread_" + Date.now();
    const title = presetTitle || generateThreadTitle(promptText);
    const newThread = {
      id: activeThreadId,
      title: title,
      prompt: promptText,
      timestamp: Date.now(),
      runId: null,
      messagesHtml: ""
    };
    threads.unshift(newThread);
    if (threads.length > 25) threads.pop();
    saveThreads();
    renderThreadsList();
  }

  // 1. Append User Message Bubble
  const userMsg = document.createElement("div");
  userMsg.className = "message-user";
  const thumbs = images.length
    ? `<div class="message-user-images">${images.map(i => `<img src="${i.thumb}" alt="${escapeHtml(i.name)}" title="${escapeHtml(i.name)} · ${i.width}×${i.height}" />`).join("")}</div>`
    : "";
  userMsg.innerHTML = `${thumbs}<div class="message-user-content">${escapeHtml(promptText)}</div>`;
  messagesStream.appendChild(userMsg);

  // 2. Live run card: steps, reasoning and output stream in as they happen
  const assistantMsg = document.createElement("div");
  assistantMsg.className = "message-assistant";

  const startTime = Date.now();
  assistantMsg.innerHTML = `
    <div class="live-run" data-phase="route">
      <div class="live-head">
        <div class="live-title">
          <span class="live-orb"></span>
          <span class="live-phase" data-live="phase">Routing with Verdict v1.4…</span>
        </div>
        <div class="live-stats">
          <span class="live-stat" data-live="tokens" hidden></span>
          <span class="live-stat" data-live="rate" hidden></span>
          <span class="live-stat live-timer" data-live="timer">0.0s</span>
          <button class="live-stop" data-live="stop" title="Stop generating (Esc)">
            <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor"><rect x="5" y="5" width="14" height="14" rx="3"/></svg>
            Stop
          </button>
        </div>
      </div>
      <ol class="live-steps">
        <li class="live-step active" data-step="1"><span class="live-step-dot"></span><span class="live-step-body"><span class="live-step-title">Route</span><span class="live-step-detail">Classifying intent</span></span></li>
        <li class="live-step" data-step="2"><span class="live-step-dot"></span><span class="live-step-body"><span class="live-step-title">Govern</span><span class="live-step-detail">Checking decisions &amp; bans</span></span></li>
        <li class="live-step" data-step="3"><span class="live-step-dot"></span><span class="live-step-body"><span class="live-step-title">Generate</span><span class="live-step-detail">Waiting for the model</span></span></li>
      </ol>
      <div class="live-thinking" data-live="think-wrap" hidden>
        <button class="live-thinking-toggle" data-live="think-toggle" type="button">
          <span class="live-think-dot"></span>
          <span data-live="think-label">Thinking…</span>
          <span class="live-think-chev">▾</span>
        </button>
        <div class="live-thinking-box" data-live="think"></div>
      </div>
      <ol class="live-tools" data-live="tools" hidden></ol>
      <div class="live-output">
        <div class="live-output-head">
          <span data-live="out-label">Output</span>
          <span class="live-output-file" data-live="file"></span>
        </div>
        <pre class="live-output-body" data-live="out"><span class="live-wait"><i></i><i></i><i></i><span>waiting for the first token</span></span></pre>
      </div>
    </div>
  `;
  messagesStream.appendChild(assistantMsg);
  scrollToBottom(true);

  document.getElementById("btn-run").disabled = true;

  const live = assistantMsg.querySelector(".live-run");
  const $live = (key) => assistantMsg.querySelector(`[data-live="${key}"]`);
  const setPhase = (phase, label) => {
    live.dataset.phase = phase;
    if (label) $live("phase").textContent = label;
  };
  const setStep = (n, state, detail) => {
    const li = live.querySelector(`[data-step="${n}"]`);
    if (!li) return;
    li.className = `live-step ${state}`;
    if (detail != null) li.querySelector(".live-step-detail").textContent = detail;
  };

  // Keep following the stream unless the user has scrolled up to read
  const viewport = document.getElementById("chat-viewport");
  const followStream = () => {
    if (viewport && viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight < 160) {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "auto" });
    }
  };

  let modelName = "local model";
  let thinkText = "";
  let rawOut = "";
  let tokenCount = 0;
  let firstTokenAt = 0;
  let lastTokenAt = 0;
  let thinkStartedAt = 0;
  let thinkEndedAt = 0;
  let renderQueued = false;

  const thinkWrap = $live("think-wrap");
  const thinkBox = $live("think");
  const outBox = $live("out");
  $live("think-toggle").addEventListener("click", () => thinkWrap.classList.toggle("collapsed"));

  // Visible output: hide <think> blocks and markdown fences, keep everything else verbatim
  const visibleOutput = (text) => text
    .replace(/<think>[\s\S]*?(<\/think>|$)/g, "")
    .replace(/<tool>[\s\S]*?(<\/tool>|$)/g, "")
    .replace(/^\s*```[\w+#.-]*\s*$/gm, "")
    .replace(/^\n+/, "")
    .replace(/\s+$/, "");

  const paint = () => {
    renderQueued = false;
    if (thinkText) {
      const nearEnd = thinkBox.scrollHeight - thinkBox.scrollTop - thinkBox.clientHeight < 40;
      thinkBox.textContent = thinkText;
      if (nearEnd) thinkBox.scrollTop = thinkBox.scrollHeight;
    }
    const shown = visibleOutput(rawOut);
    if (shown) {
      const nearEnd = outBox.scrollHeight - outBox.scrollTop - outBox.clientHeight < 40;
      outBox.textContent = shown;
      const caret = document.createElement("span");
      caret.className = "live-caret";
      outBox.appendChild(caret);
      if (nearEnd) outBox.scrollTop = outBox.scrollHeight;
    }
    followStream();
  };
  const queuePaint = () => {
    if (!renderQueued) {
      renderQueued = true;
      requestAnimationFrame(paint);
    }
  };

  const countToken = () => {
    tokenCount++;
    lastTokenAt = Date.now();
    if (!firstTokenAt) firstTokenAt = lastTokenAt;
  };

  const startThinking = () => {
    if (thinkStartedAt) return;
    thinkStartedAt = Date.now();
    thinkWrap.hidden = false;
    setPhase("think", `Thinking with ${modelName}…`);
    setStep(3, "active", "Reasoning before it writes");
  };

  const startWriting = () => {
    if (live.dataset.phase === "write") return;
    if (thinkStartedAt && !thinkEndedAt) {
      thinkEndedAt = Date.now();
      $live("think-label").textContent = `Thought for ${((thinkEndedAt - thinkStartedAt) / 1000).toFixed(1)}s`;
      thinkWrap.classList.add("collapsed", "done");
    }
    setPhase("write", live.dataset.free ? `Answering with ${modelName}…` : `Writing the patch with ${modelName}…`);
    setStep(3, "active", "Streaming output");
  };

  // Tool calls (computer access): one row per call, updated when it finishes
  const toolsList = $live("tools");
  const renderLiveTool = (evt) => {
    toolsList.hidden = false;
    let row = toolsList.querySelector(`[data-tool="${evt.id}"]`);
    if (!row) {
      row = document.createElement("li");
      row.className = "live-tool running";
      row.dataset.tool = evt.id;
      row.innerHTML = `<span class="live-tool-dot"></span><code class="live-tool-cmd">${escapeHtml(describeToolCall(evt))}</code><span class="live-tool-result">running…</span>`;
      toolsList.appendChild(row);
      // The text that carried the tool call is not part of the answer
      rawOut = "";
      outBox.innerHTML = '<span class="live-wait"><i></i><i></i><i></i><span>reading the result</span></span>';
      live.dataset.phase = "tool";
      $live("phase").textContent = `Looking it up: ${describeToolCall(evt)}`;
      setStep(3, "active", `Running ${evt.name === "run_command" ? "a command" : evt.name.replace("_", " ")}`);
    }
    if (evt.status === "done") {
      row.className = `live-tool ${evt.ok ? "ok" : "fail"}`;
      const firstLine = (evt.ok ? evt.output : evt.error || "failed").split("\n")[0];
      row.querySelector(".live-tool-result").textContent = firstLine.length > 90 ? firstLine.slice(0, 87) + "…" : firstLine;
      setPhase("wait", `Reading the result with ${modelName}…`);
    }
    followStream();
  };

  // Live stopwatch, token counter and speed
  const timerInterval = setInterval(() => {
    $live("timer").textContent = ((Date.now() - startTime) / 1000).toFixed(1) + "s";
    if (tokenCount) {
      const tokEl = $live("tokens");
      tokEl.hidden = false;
      tokEl.textContent = `${tokenCount} tok`;
      const secs = (lastTokenAt - firstTokenAt) / 1000;
      if (secs > 0.5) {
        const rateEl = $live("rate");
        rateEl.hidden = false;
        rateEl.textContent = `${(tokenCount / secs).toFixed(1)} tok/s`;
      }
    }
  }, 100);

  // Stop button (and Esc) cancels the stream and keeps whatever arrived
  const controller = new AbortController();
  let stopped = false;
  const stopRun = () => {
    if (stopped) return;
    stopped = true;
    controller.abort();
  };
  $live("stop").addEventListener("click", stopRun);
  const onEsc = (e) => { if (e.key === "Escape" && !document.querySelector(".modal-backdrop[style*='flex']")) stopRun(); };
  document.addEventListener("keydown", onEsc);

  try {
    let data = null;
    try {
      const res = await fetch("/api/run/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText, history: threadHistory(), web_search: webSearchActive(), computer: computerActive(), images: images.map(i => i.base64) }),
        signal: controller.signal
      });

      if (res.status === 400) {
        // Rejected input (e.g. a bad screenshot): show why instead of retrying
        const err = await res.json().catch(() => ({}));
        const rejected = new Error(err.detail || "The request was rejected.");
        rejected.rejected = true;
        throw rejected;
      }

      if (res.ok && res.body) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (!trimmed.startsWith("data: ")) continue;
            try {
              const evt = JSON.parse(trimmed.slice(6));
              if (evt.type === "init") {
                modelName = evt.model || modelName;
                if (evt.free) {
                  live.dataset.free = "1";
                  setStep(1, "done skipped", "No workspace attached");
                  const extras = [
                    evt.web_search ? "web search on" : "",
                    evt.computer === "on" ? "computer access on" : "",
                    evt.computer === "remote" ? "computer access is local-only" : "",
                    evt.history_turns ? `${evt.history_turns} earlier turns` : "",
                  ].filter(Boolean).join(" · ");
                  setStep(2, "done skipped", `Checks off${extras ? ` · ${extras}` : ""}`);
                  $live("out-label").textContent = "Answer";
                  outBox.classList.add("prose");
                } else {
                  const policy = evt.policy && evt.policy.primary_id ? evt.policy.primary_id.replace(/^adr:/, "") : "no decision";
                  const s1 = evt.verdict && evt.verdict.system1_ms ? ` · ${Math.round(evt.verdict.system1_ms)}ms` : "";
                  setStep(1, "done", `Matched ${policy}${s1}`);
                  const negs = evt.negative || [];
                  const bans = negs.reduce((n, neg) => n + ((neg.literals || []).length), 0);
                  setStep(2, "done", bans ? `Clear of ${bans} banned patterns` : "No bans in scope");
                  $live("out-label").textContent = "Patch draft";
                  if (evt.target_file) $live("file").textContent = evt.target_file;
                }
                if (evt.images) {
                  const noun = evt.images === 1 ? "screenshot" : `${evt.images} screenshots`;
                  setStep(3, "active", `Reading ${noun} with ${modelName}${evt.vision_routed ? " (vision)" : ""}`);
                } else {
                  setStep(3, "active", `Loading ${modelName}`);
                }
                setPhase("wait", `Waiting for ${modelName}…`);
              } else if (evt.type === "search") {
                const msg = {
                  searching: "Searching the web…",
                  ok: `${evt.count} web results via ${evt.provider}`,
                  offline: "Offline · answering locally",
                  unavailable: "Search unavailable · answering locally",
                  disabled: "Search disabled · answering locally",
                }[evt.status] || "Web search finished";
                setStep(2, evt.status === "searching" ? "active" : "done", msg);
              } else if (evt.type === "thinking") {
                countToken();
                startThinking();
                thinkText += evt.chunk;
                queuePaint();
              } else if (evt.type === "response") {
                countToken();
                rawOut += evt.chunk;
                // Models that inline <think> tags: route that text to the thinking panel
                const openThink = rawOut.lastIndexOf("<think>") > rawOut.lastIndexOf("</think>");
                if (openThink) {
                  startThinking();
                  const m = rawOut.match(/<think>([\s\S]*)$/);
                  thinkText = m ? m[1] : thinkText;
                } else if (visibleOutput(rawOut).trim()) {
                  if (rawOut.includes("</think>") && !thinkText) {
                    const m = rawOut.match(/<think>([\s\S]*?)<\/think>/);
                    if (m) { startThinking(); thinkText = m[1]; }
                  }
                  startWriting();
                }
                queuePaint();
              } else if (evt.type === "tool") {
                renderLiveTool(evt);
              } else if (evt.type === "finished") {
                data = evt;
              }
            } catch (err) {
              console.warn("SSE parse error", err);
            }
          }
        }
      }
    } catch (streamErr) {
      if (streamErr.rejected) throw streamErr;
      if (!stopped) console.warn("Streaming request failed, falling back to /api/run:", streamErr);
    }

    if (stopped && !data) {
      live.classList.add("stopped");
      setPhase("stopped", "Stopped");
      setStep(3, "done skipped", tokenCount ? `Stopped after ${tokenCount} tokens` : "Stopped before output");
      const caret = outBox.querySelector(".live-caret");
      if (caret) caret.remove();
      if (!visibleOutput(rawOut)) outBox.innerHTML = '<span class="live-empty">Nothing was generated.</span>';
      $live("stop").remove();
      snapshotActiveThread();
      return;
    }

    if (!data) {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText, history: threadHistory(), web_search: webSearchActive(), computer: computerActive(), images: images.map(i => i.base64) })
      });
      data = await res.json();
    }

    currentRunId = data.run_id;
    latestRunData = data.status === "free" ? null : data;
    if (activeThreadId) {
      const curThread = threads.find(t => t.id === activeThreadId);
      if (curThread) {
        curThread.runId = currentRunId;
        curThread.runData = data;
      }
    }

    // Render response into assistantMsg
    renderAssistantResponse(assistantMsg, data, promptText);
    recordTurn(images.length ? `[${images.length} screenshot${images.length === 1 ? "" : "s"} attached] ${promptText}` : promptText, data);

    if (currentAppMode === "diff") {
      const diffView = document.getElementById("diff-inspector-view");
      if (diffView) renderDiffInspectorContent(diffView);
    }
  } catch (e) {
    console.error("Run error:", e);
    assistantMsg.innerHTML = `<div class="banner-blocked"><span class="banner-title-blocked">${e.rejected ? "Couldn't send that" : "Execution Error"}</span><span class="banner-body">${escapeHtml(e.message)}</span></div>`;
  } finally {
    clearInterval(timerInterval);
    document.removeEventListener("keydown", onEsc);
    document.getElementById("btn-run").disabled = false;
  }
}

// Minimal Markdown for model answers. Everything is escaped first, then only
// fences, inline code, headings, bold and list bullets are turned into markup.
function renderMarkdownLite(text) {
  const parts = String(text || "").split(/```([\w+#.-]*)[^\n]*\n?([\s\S]*?)(?:```|$)/g);
  let html = "";
  for (let i = 0; i < parts.length; i += 3) {
    let prose = escapeHtml(parts[i] || "");
    prose = prose
      .replace(/^#{1,6}\s+(.+)$/gm, '<strong style="display:block; margin:10px 0 2px;">$1</strong>')
      .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`\n]+)`/g, '<code style="font-family:var(--font-mono); font-size:0.92em; padding:1px 5px; border-radius:5px; background:var(--code-file-bg, rgba(0,0,0,0.06));">$1</code>')
      .replace(/^\s*[-*]\s+/gm, "• ");
    html += prose;
    if (i + 2 < parts.length) {
      const lang = parts[i + 1] ? `<div style="font-size:11px; color:var(--text-muted); margin-bottom:4px;">${escapeHtml(parts[i + 1])}</div>` : "";
      html += `<div style="margin:10px 0;">${lang}<pre style="margin:0; padding:12px 14px; border-radius:10px; overflow-x:auto; white-space:pre; font-family:var(--font-mono); font-size:13px; line-height:1.55; background:var(--code-file-bg, rgba(0,0,0,0.05));"><code>${escapeHtml((parts[i + 2] || "").replace(/\n$/, ""))}</code></pre></div>`;
    }
  }
  return html;
}

function renderWebSources(web) {
  if (!web || !web.requested) return "";
  const note = {
    ok: `Searched the web via ${escapeHtml(web.provider || "search")}`,
    offline: "Offline: no internet connection, so this answer comes from the local model only.",
    unavailable: "Web search was unavailable, so this answer comes from the local model only.",
    disabled: "Web search is disabled in .aegis/config.json, so this answer comes from the local model only.",
  }[web.status] || "";
  const items = (web.results || []).map((r, i) => {
    const url = /^https?:\/\//i.test(r.url || "") ? r.url : "";
    const title = escapeHtml(r.title || url);
    return `<li style="margin:3px 0;">[${i + 1}] ${url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noopener noreferrer">${title}</a>` : title}</li>`;
  }).join("");
  return `
    <div style="margin:0 20px 14px; padding:10px 12px; border-radius:10px; font-size:12.5px; color:var(--text-muted); background:var(--code-file-bg, rgba(0,0,0,0.04));">
      <div style="font-weight:600; margin-bottom:${items ? "4px" : "0"};">${note}</div>
      ${items ? `<ol style="margin:0; padding-left:0; list-style:none; word-break:break-all;">${items}</ol>` : ""}
    </div>`;
}

function describeToolCall(t) {
  const args = t.args || {};
  if (t.name === "run_command") return `$ ${args.command || ""}`;
  if (t.name === "read_file") return `read ${args.path || ""}`;
  if (t.name === "list_dir") return `ls ${args.path || "~"}`;
  return `${t.name} ${JSON.stringify(args)}`;
}

function renderComputerTools(computer) {
  if (!computer || !computer.tools || !computer.tools.length) return "";
  const rows = computer.tools.map(t => `
    <details class="tool-log-item ${t.ok ? "ok" : "fail"}">
      <summary><span class="live-tool-dot"></span><code>${escapeHtml(describeToolCall(t))}</code><span class="tool-log-ms">${Math.round(t.latency_ms || 0)}ms</span></summary>
      <pre>${escapeHtml(t.ok ? t.output : t.error)}</pre>
    </details>`).join("");
  return `
    <div class="tool-log">
      <div class="tool-log-title">Looked up on this computer · ${computer.tools.length} ${computer.tools.length === 1 ? "step" : "steps"} · read-only</div>
      ${rows}
    </div>`;
}

function renderFreeResponse(container, data) {
  const a = data.aegis || {};
  const card = document.createElement("div");
  card.className = "code-card";
  const reasoning = a.thinking ? `
    <div class="reasoning-trace-container" style="margin: 0 20px 12px;">
      <div class="reasoning-trace-label"><span class="sparkle-mini">✦</span><span>Model Reasoning Trace</span></div>
      <div class="reasoning-trace-box">${escapeHtml(a.thinking)}</div>
    </div>` : "";
  card.innerHTML = `
    <div class="code-card-header">
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="font-weight:600; font-size:13px; color:var(--text-primary);">Local model answer</span>
        <span class="file-badge">No workspace · policy checks off</span>
      </div>
      <span class="code-meta">${escapeHtml(data.model || "local model")} &middot; ${Math.round(a.latency_ms || 0)}ms</span>
    </div>
    ${reasoning}
    <div class="explain-body">${a.text ? renderMarkdownLite(a.text) : "No answer returned"}</div>
    ${renderComputerTools(data.computer)}
    ${renderWebSources(data.web)}
    <div class="unified-card-footer">
      <span style="font-size:12.5px; color:var(--text-muted);">
        No ADRs, bans or habits were applied and nothing was written to disk${data.web && data.web.status === "ok" ? "; your message was sent to a search engine" : ""}${data.computer && data.computer.status === "remote" ? ". Computer access only works from this machine's own browser" : ""}. Attach a workspace to turn governance back on.
      </span>
    </div>
  `;
  container.appendChild(card);
}

function renderAssistantResponse(container, data, promptText) {
  container.innerHTML = "";

  if (data.status === "free") {
    renderFreeResponse(container, data);
    snapshotActiveThread();
    scrollToBottom(true);
    return;
  }

  // 1. Thought Accordion (DeepSeek/ChatGPT style)
  const vLat = data.verdict ? Math.round(data.verdict.system1_ms || data.verdict.latency_ms || 0) : 0;
  const aLat = data.aegis && data.aegis.latency_ms > 0 ? Math.round(data.aegis.latency_ms) : 0;
  const totalMs = vLat + aLat;
  const thoughtTimeStr = totalMs >= 1000 ? (totalMs / 1000).toFixed(1) + "s" : `${totalMs}ms`;

  const thoughtCard = document.createElement("div");
  thoughtCard.className = "thought-card";
  
  const compressionPct = data.tokens && data.tokens.baseline > 0
    ? Math.round(((data.tokens.baseline - data.tokens.leaf) / data.tokens.baseline) * 100)
    : 0;

  const excludedFiles = (data.excluded_files || []).map(f => f.path.split("/").pop()).join(", ") || "None";
  const activePolicy = data.policy && data.policy.primary_id ? data.policy.primary_id : "None";
  const retrieval = (data.policy && data.policy.retrieval) || {};
  // Say why the task type came from where it did, including what Verdict thought
  const v = data.verdict || {};
  const vTaskP = typeof v.confidence === "number" ? v.confidence.toFixed(2) : null;
  const vNeed = typeof v.threshold === "number" ? v.threshold.toFixed(2) : null;
  const taskSourceText = data.task_source === "verdict"
    ? `Verdict, p=${vTaskP}`
    : !v.loaded
      ? "keyword rule (Verdict unavailable)"
      : v.selected_id
        ? `keyword rule · Verdict leaned ${v.selected_id} at p=${vTaskP}${vNeed ? `, needs ${vNeed}` : ""}`
        : "keyword rule";
  const retrievalText = retrieval.source === "verdict"
    ? `Verdict pick${retrieval.pick && retrieval.pick !== data.policy.primary_id ? ` (${retrieval.pick} → successor)` : ""}, p=${(retrieval.confidence || 0).toFixed(2)}`
    : retrieval.source === "overlap" ? "keyword overlap" : "none";

  const reasoningHtml = (data.aegis && data.aegis.thinking) ? `
    <div class="reasoning-trace-container">
      <div class="reasoning-trace-label">
        <span class="sparkle-mini">✦</span>
        <span>Model Reasoning Trace (${escapeHtml(data.model || "Local SLM")})</span>
      </div>
      <div class="reasoning-trace-box">${escapeHtml(data.aegis.thinking)}</div>
    </div>
  ` : '';

  thoughtCard.innerHTML = `
    <div class="thought-header">
      <div class="thought-meta">
        <span class="sparkle-mini">✦</span>
        <span>Thought for ${thoughtTimeStr} &middot; System 1 &amp; System 2 Reasoning</span>
      </div>
      <span class="thought-chevron">▼</span>
    </div>
    <div class="thought-body">
      <div class="telemetry-grid">
        <div class="telemetry-item">
          <span class="telemetry-label">Task Type</span>
          <span class="telemetry-val">${escapeHtml(data.task_type)}</span>
          <span class="telemetry-label" style="margin-top:2px;">via ${escapeHtml(taskSourceText)}</span>
        </div>
        <div class="telemetry-item">
          <span class="telemetry-label">Primary Policy</span>
          <span class="telemetry-val" style="color:var(--accent-cyan);">${escapeHtml(activePolicy)}</span>
          <span class="telemetry-label" style="margin-top:2px;">via ${escapeHtml(retrievalText)}</span>
        </div>
        <div class="telemetry-item">
          <span class="telemetry-label">Token Compression</span>
          <span class="telemetry-val" style="color:var(--accent-green);">${data.tokens ? data.tokens.leaf : 0} tokens (-${compressionPct}%)</span>
        </div>
        <div class="telemetry-item">
          <span class="telemetry-label">Excluded Scopes</span>
          <span class="telemetry-val">${escapeHtml(excludedFiles)}</span>
        </div>
      </div>
      ${reasoningHtml}
      <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 8px;">
        Evaluated via openJev Verdict v1.4 ModernBERT weights &amp; local air-gapped SLM. Zero cloud egress.
      </div>
    </div>
  `;

  thoughtCard.querySelector(".thought-header").addEventListener("click", () => {
    thoughtCard.classList.toggle("expanded");
  });
  container.appendChild(thoughtCard);

  // 2. Handle BLOCKED status (Sovereign Refusal)
  if (data.status === "blocked") {
    const banner = document.createElement("div");
    banner.className = "banner-blocked";
    banner.innerHTML = `
      <div class="banner-title-blocked">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
        Blocked &middot; sovereign refusal
      </div>
      <div class="banner-body">
        ${data.block_method === "semantic"
          ? `Request asks for superseded decision <code>${escapeHtml(data.revived_policy_id || "")}</code>, replaced by active policy <strong>${escapeHtml(data.blocking_policy_id || "")}</strong>. <span class="banner-meta">(System 1 revival check, p=${(data.block_confidence || 0).toFixed(2)})</span>`
          : `<code>${escapeHtml(data.blocked_literal || "")}</code> is forbidden by active policy <strong>${escapeHtml(data.blocking_policy_id || "")}</strong>.`}
      </div>
      <div class="banner-note">
        ClearSky physically blocked generation before model invocation because this architectural pattern has been superseded. Zero tokens wasted.
      </div>
    `;
    container.appendChild(banner);
    snapshotActiveThread();
    return;
  }

  // 3. Handle ABSTAINED status (Calibrated Abstention)
  if (data.status === "abstained") {
    const banner = document.createElement("div");
    banner.className = "banner-abstained";
    banner.innerHTML = `
      <div class="banner-title-abstained">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        Abstained &middot; outside organizational scope
      </div>
      <div class="banner-body">
        ${escapeHtml(data.abstain_reason || "No accepted architecture decision covers this request.")}
      </div>
      <div class="banner-note">
        ClearSky refuses to hallucinate code without an in-force Architecture Decision Record (ADR).
      </div>
    `;
    container.appendChild(banner);
    snapshotActiveThread();
    return;
  }

  // 4. Handle EXPLAIN ONLY
  if (data.task_type === "explain_only") {
    const explainCard = document.createElement("div");
    explainCard.className = "code-card";
    explainCard.innerHTML = `
      <div class="code-card-header">
        <span style="font-weight:600; font-size:13px;">Architecture Explanation</span>
        <span class="code-meta">${Math.round(data.aegis ? data.aegis.latency_ms : 0)} ms</span>
      </div>
      <div class="explain-body">
        ${data.aegis && data.aegis.text ? renderMarkdownLite(data.aegis.text) : "No explanation returned"}
      </div>
    `;
    container.appendChild(explainCard);
    snapshotActiveThread();
    return;
  }

  // 5. Unified Inline Diff & Review Card (Human-in-the-Loop Gate)
  const codeCard = document.createElement("div");
  codeCard.className = "code-card unified-review-card";

  const aegisDiff = data.aegis ? (data.aegis.diff || data.aegis.code || data.aegis.text) : "";
  const baselineDiff = data.baseline ? (data.baseline.diff || data.baseline.code || data.baseline.text) : "";
  const targetFileLabel = data.target_file || "vault/store.py";
  const isUnparseable = data.aegis && data.aegis.unparseable;

  codeCard.dataset.aegisDiff = aegisDiff;
  codeCard.dataset.baselineDiff = baselineDiff;
  codeCard.dataset.aegisMeta = `Aegis: ${data.tokens ? data.tokens.leaf : 0} tokens · ${Math.round(data.aegis ? data.aegis.latency_ms : 0)}ms`;
  codeCard.dataset.baselineMeta = data.baseline && data.baseline.source === "model"
    ? `Raw Baseline: ${data.tokens ? data.tokens.baseline : "n/a"} tokens · ${Math.round(data.baseline.latency_ms || 0)}ms`
    : `Legacy pattern (illustrative) · full-repo prompt ${data.tokens ? data.tokens.baseline : "n/a"} tokens`;

  const chunks = parseDiffToChunks(aegisDiff, data.aegis ? data.aegis.code : "");

  let editorHtml = `<div class="unified-diff-editor">`;
  chunks.forEach(chunk => {
    if (chunk.type === "del") {
      chunk.lines.forEach(delLine => {
        editorHtml += `
          <div class="diff-chunk-wrapper diff-chunk-del">
            <div class="diff-gutter-col">
              <div class="diff-gutter-sym">-</div>
            </div>
            <div class="diff-del-code-line">${escapeHtml(delLine)}</div>
          </div>
        `;
      });
    } else if (chunk.type === "add") {
      const syms = chunk.lines.map(() => `<div class="diff-gutter-sym">+</div>`).join("");
      editorHtml += `
        <div class="diff-chunk-wrapper diff-chunk-add" data-chunk-sym="+">
          <div class="diff-gutter-col">${syms}</div>
          <textarea class="inline-code-chunk diff-chunk-textarea diff-chunk-add-input" spellcheck="false">${escapeHtml(chunk.lines.join("\n"))}</textarea>
        </div>
      `;
    } else {
      const syms = chunk.lines.map(() => `<div class="diff-gutter-sym">&nbsp;</div>`).join("");
      editorHtml += `
        <div class="diff-chunk-wrapper diff-chunk-context" data-chunk-sym="&nbsp;">
          <div class="diff-gutter-col">${syms}</div>
          <textarea class="inline-code-chunk diff-chunk-textarea diff-chunk-context-input" spellcheck="false">${escapeHtml(chunk.lines.join("\n"))}</textarea>
        </div>
      `;
    }
  });
  editorHtml += `</div>`;

  codeCard.innerHTML = `
    <div class="code-card-header">
      <div style="display:flex; align-items:center; gap:8px;">
        <span style="font-weight:600; font-size:13px; color:var(--text-primary); display:flex; align-items:center; gap:6px;">
          <span style="color:var(--accent-green); font-size:11px;">●</span> ClearSky Patch (Compliant)
        </span>
        <span class="file-badge">${escapeHtml(targetFileLabel)}</span>
        <span class="review-hint" style="font-size:11.5px; color:var(--text-muted); margin-left:4px;">Tip: edit retries or timeout_s to train organizational memory</span>
      </div>
      <div style="display:flex; align-items:center; gap:8px;">
        <span class="code-meta" id="code-meta-text">Aegis: ${data.tokens ? data.tokens.leaf : 0} tokens &middot; ${Math.round(data.aegis ? data.aegis.latency_ms : 0)}ms</span>
      </div>
    </div>
    ${editorHtml}
    <div class="unified-card-footer">
      <span id="review-status-msg" style="font-size:12.5px; color:var(--text-muted);">${isUnparseable ? "Unparseable output - cannot commit." : "Ready to commit with apply_patch, the same tool the MCP server exposes."}</span>
      <button class="btn-approve" id="btn-approve-action" ${isUnparseable ? "disabled" : ""}>Approve &amp; Commit</button>
    </div>
  `;

  setupInlineEditor(codeCard);

  const btnApprove = codeCard.querySelector("#btn-approve-action");
  const statusMsg = codeCard.querySelector("#review-status-msg");

  if (btnApprove && !btnApprove.disabled) {
    attachApproveHandler(codeCard, btnApprove, statusMsg);
  }

  container.appendChild(codeCard);

  snapshotActiveThread();
  scrollToBottom(true);
}

function scrollToBottom(smooth = true) {
  const viewport = document.getElementById("chat-viewport");
  if (!viewport) return;
  setTimeout(() => {
    viewport.scrollTo({
      top: viewport.scrollHeight,
      behavior: smooth ? "smooth" : "auto"
    });
  }, 40);
}

function renderDiffLines(container, text) {
  container.innerHTML = "";
  const lines = (text || "").split("\n");
  lines.forEach(line => {
    const div = document.createElement("div");
    if (line.startsWith("+") && !line.startsWith("+++")) {
      div.className = "diff-add";
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      div.className = "diff-del";
    }
    div.textContent = line || " ";
    container.appendChild(div);
  });
}

function clearRecentTasks() {
  if (!threads || threads.length === 0) return;
  if (!confirm("Clear all recent chat tasks?")) return;
  threads = [];
  localStorage.removeItem("aegis_threads");
  activeThreadId = null;
  latestRunData = null;
  currentRunId = null;
  renderThreadsList();
  document.getElementById("btn-new-session").click();
}

async function resetDemo() {
  const confirmed = confirm(
    "Reset demo repository and memory back to clean state?\n\n" +
    "This will:\n" +
    "• Delete all recent chats and task history\n" +
    "• Erase all learned organizational memory habits\n" +
    "• Restore all Architecture Decisions (ADRs) to original seed state\n" +
    "• Reset vault code back to clean starting state\n" +
    "• Rebuild the temporal memory graph from scratch"
  );
  if (!confirmed) return;

  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Reset failed");
    }

    // 1. Wipe all local storage chats and recent task threads
    threads = [];
    localStorage.removeItem("aegis_threads");
    activeThreadId = null;
    latestRunData = null;
    currentRunId = null;

    // 2. Reset mode to chat and update UI
    setAppMode("chat");
    renderThreadsList();
    document.querySelectorAll(".recent-item").forEach(r => r.classList.remove("active"));

    const heroView = document.getElementById("hero-view");
    const messagesStream = document.getElementById("messages-stream");
    const diffInspectorView = document.getElementById("diff-inspector-view");
    const promptInput = document.getElementById("prompt-input");

    if (heroView) heroView.style.display = "flex";
    if (messagesStream) {
      messagesStream.style.display = "none";
      messagesStream.innerHTML = "";
    }
    if (diffInspectorView) {
      diffInspectorView.style.display = "none";
      diffInspectorView.innerHTML = "";
    }
    if (promptInput) {
      promptInput.value = "";
    }

    // 3. Re-initialize memory graph and health
    await initMemory();
    await initHealth();

    // 4. Close any open drawers or modals
    const memoryDrawer = document.getElementById("memory-drawer");
    if (memoryDrawer) memoryDrawer.classList.remove("open");
    closeAdrModal();

  } catch (e) {
    alert("Reset failed: " + e.message);
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function snapshotActiveThread() {
  if (activeThreadId) {
    const curThread = threads.find(t => t.id === activeThreadId);
    if (curThread) {
      curThread.messagesHtml = document.getElementById("messages-stream").innerHTML;
      saveThreads();
    }
  }
}

function initThreads() {
  try {
    const raw = localStorage.getItem("aegis_threads");
    if (raw) {
      threads = JSON.parse(raw);
    }
  } catch (e) {
    console.error("Failed to load threads from localStorage:", e);
    threads = [];
  }
  renderThreadsList();
}

function saveThreads() {
  try {
    localStorage.setItem("aegis_threads", JSON.stringify(threads));
  } catch (e) {
    console.error("Failed to save threads to localStorage:", e);
  }
}

function generateThreadTitle(prompt) {
  if (!prompt) return "New Task";
  let clean = prompt.trim();
  clean = clean.replace(/^(hello|hi|hey|greetings|please|pls|can\s+you|could\s+you|would\s+you|i\s+want\s+to|i\s+need\s+to|help\s+me\s+to|tell\s+me\s+about)\s+/gi, "");
  clean = clean.replace(/^(please|pls)\s+/gi, "");
  clean = clean.replace(/^(add\s+a\s+|create\s+a\s+|implement\s+a\s+|write\s+a\s+)/gi, "Add ");
  clean = clean.trim();
  if (!clean) clean = prompt.trim();
  clean = clean.charAt(0).toUpperCase() + clean.slice(1);
  if (clean.length > 28) {
    clean = clean.slice(0, 26).trim() + "…";
  }
  return clean;
}

function renderThreadsList() {
  const container = document.getElementById("threads-list");
  const sectionTitle = document.getElementById("threads-section-title");
  if (!container) return;

  container.innerHTML = "";
  if (!threads || threads.length === 0) {
    if (sectionTitle) sectionTitle.style.display = "none";
    return;
  }

  if (sectionTitle) sectionTitle.style.display = "block";

  threads.forEach(t => {
    const item = document.createElement("div");
    item.className = "thread-item" + (t.id === activeThreadId ? " active" : "");
    item.dataset.threadId = t.id;

    const left = document.createElement("div");
    left.className = "thread-item-left";
    left.innerHTML = `<span class="thread-item-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z"/></svg></span><span class="thread-item-title" title="${escapeHtml(t.prompt || t.title)}">${escapeHtml(t.title || "Conversation")}</span>`;

    const delBtn = document.createElement("button");
    delBtn.className = "thread-item-delete";
    delBtn.innerHTML = "&times;";
    delBtn.title = "Delete thread";
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      deleteThread(t.id);
    });

    item.appendChild(left);
    item.appendChild(delBtn);

    item.addEventListener("click", () => {
      loadThread(t.id);
    });

    container.appendChild(item);
  });
}

function loadThread(threadId) {
  const target = threads.find(t => t.id === threadId);
  if (!target) return;

  activeThreadId = threadId;
  currentRunId = target.runId || null;
  if (target.runData) {
    latestRunData = target.runData;
  } else {
    latestRunData = null;
  }
  renderThreadsList();

  document.querySelectorAll(".recent-item").forEach(r => r.classList.remove("active"));

  if (currentAppMode === "diff") {
    document.getElementById("hero-view").style.display = "none";
    document.getElementById("messages-stream").style.display = "none";
    const diffView = document.getElementById("diff-inspector-view");
    if (diffView) {
      diffView.style.display = "flex";
      renderDiffInspectorContent(diffView);
    }
  } else {
    document.getElementById("hero-view").style.display = "none";
    const diffView = document.getElementById("diff-inspector-view");
    if (diffView) diffView.style.display = "none";
    const messagesStream = document.getElementById("messages-stream");
    messagesStream.style.display = "flex";
    messagesStream.innerHTML = target.messagesHtml || "";

    rebindThreadCards(messagesStream);
    scrollToBottom(false);
  }
}

function deleteThread(threadId) {
  threads = threads.filter(t => t.id !== threadId);
  saveThreads();

  if (activeThreadId === threadId) {
    document.getElementById("btn-new-session").click();
  } else {
    renderThreadsList();
  }
}

function parseDiffToChunks(diffText, fallbackCode) {
  if (!diffText || typeof diffText !== "string" || !diffText.includes("@@")) {
    const raw = (fallbackCode || diffText || "").trim();
    return [{ type: "context", lines: raw ? raw.split("\n") : [] }];
  }
  const lines = diffText.split("\n");
  const hunks = [];
  let inHunk = false;
  let currentGroup = null;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (line.startsWith("---") || line.startsWith("+++")) continue;
    if (line.startsWith("@@")) {
      inHunk = true;
      continue;
    }
    if (!inHunk) continue;

    let type = "context";
    let content = line;
    if (line.startsWith("-")) {
      type = "del";
      content = line.slice(1);
    } else if (line.startsWith("+")) {
      type = "add";
      content = line.slice(1);
    } else if (line.startsWith(" ")) {
      type = "context";
      content = line.slice(1);
    } else if (line === "") {
      continue;
    }

    if (!currentGroup || currentGroup.type !== type) {
      currentGroup = { type, lines: [content] };
      hunks.push(currentGroup);
    } else {
      currentGroup.lines.push(content);
    }
  }

  return hunks.length > 0 ? hunks : [{ type: "context", lines: (fallbackCode || "").split("\n") }];
}

function setupInlineEditor(card) {
  card.querySelectorAll(".diff-chunk-wrapper").forEach(wrapper => {
    const ta = wrapper.querySelector(".inline-code-chunk");
    const gutter = wrapper.querySelector(".diff-gutter-col");
    const sym = wrapper.dataset.chunkSym || "&nbsp;";

    if (ta && gutter) {
      function syncGutterAndHeight() {
        ta.style.height = "auto";
        ta.style.height = Math.max(22, ta.scrollHeight) + "px";

        const lineCount = (ta.value.match(/\n/g) || []).length + 1;
        let symHtml = "";
        for (let i = 0; i < lineCount; i++) {
          symHtml += `<div class="diff-gutter-sym">${sym}</div>`;
        }
        gutter.innerHTML = symHtml;
      }

      ta.addEventListener("input", syncGutterAndHeight);
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Tab") {
          e.preventDefault();
          const start = ta.selectionStart;
          const end = ta.selectionEnd;
          ta.value = ta.value.substring(0, start) + "    " + ta.value.substring(end);
          ta.selectionStart = ta.selectionEnd = start + 4;
          syncGutterAndHeight();
        }
      });

      setTimeout(syncGutterAndHeight, 15);
    }
  });
}

function getCardApprovedCode(card) {
  const textareas = card.querySelectorAll(".inline-code-chunk");
  if (textareas.length === 0) {
    const single = card.querySelector(".review-textarea, .unified-code-editor");
    return single ? single.value : "";
  }
  return Array.from(textareas).map(ta => ta.value).join("\n");
}

function attachApproveHandler(card, btnApprove, statusMsg) {
  if (!btnApprove || btnApprove.disabled) return;

  btnApprove.onclick = async () => {
    btnApprove.disabled = true;
    btnApprove.textContent = "Committing...";

    const approvedCode = getCardApprovedCode(card);

    try {
      const resp = await fetch("/api/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: currentRunId,
          approved_code: approvedCode
        })
      });

      const resData = await resp.json();

      if (resp.ok && resData.applied) {
        btnApprove.textContent = "Approved ✓";
        btnApprove.classList.add("approved");
        if (statusMsg) {
          statusMsg.innerHTML = `<span style="color:var(--accent-green); font-weight:600;">✓ Patch Committed &middot; Receipt #${resData.receipt_id}</span>`;
        }

        if (resData.habit_label) {
          const habitAlert = document.createElement("div");
          habitAlert.className = "habit-badge-alert";
          habitAlert.innerHTML = `
            <span class="sparkle-mini">✦</span>
            <span><strong>New Habit Synthesized:</strong> ${escapeHtml(resData.habit_label)}</span>
          `;
          card.appendChild(habitAlert);
          scrollToBottom(true);
        }
        initMemory();
        snapshotActiveThread();
      } else {
        if (statusMsg) {
          statusMsg.innerHTML = `<span style="color:var(--accent-red);">${escapeHtml(resData.detail || resData.reason || "Refused")}</span>`;
        }
        btnApprove.disabled = false;
        btnApprove.textContent = "Approve & Commit";
      }
    } catch (err) {
      if (statusMsg) {
        statusMsg.innerHTML = `<span style="color:var(--accent-red);">${escapeHtml(err.message)}</span>`;
      }
      btnApprove.disabled = false;
      btnApprove.textContent = "Approve & Commit";
    }
  };
}

function rebindThreadCards(container) {
  if (!container) return;

  // 1. Rebind Thought Accordions
  container.querySelectorAll(".thought-card").forEach(card => {
    const header = card.querySelector(".thought-header");
    if (header) {
      header.onclick = () => card.classList.toggle("expanded");
    }
  });

  // 2. Rebind Code Cards and Diff Tabs
  container.querySelectorAll(".code-card").forEach(card => {
    const tabAegis = card.querySelector("#tab-aegis, .code-tab-btn:first-child");
    const tabBaseline = card.querySelector("#tab-baseline, .code-tab-btn:nth-child(2)");
    const diffView = card.querySelector(".diff-display");
    const metaText = card.querySelector(".code-meta");

    if (tabAegis && tabBaseline && diffView) {
      tabAegis.onclick = () => {
        tabAegis.classList.add("active");
        tabBaseline.classList.remove("active");
        if (card.dataset.aegisDiff !== undefined) {
          renderDiffLines(diffView, card.dataset.aegisDiff);
        }
        if (card.dataset.aegisMeta && metaText) {
          metaText.textContent = card.dataset.aegisMeta;
        }
      };

      tabBaseline.onclick = () => {
        tabBaseline.classList.add("active");
        tabAegis.classList.remove("active");
        if (card.dataset.baselineDiff !== undefined) {
          renderDiffLines(diffView, card.dataset.baselineDiff);
        }
        if (card.dataset.baselineMeta && metaText) {
          metaText.textContent = card.dataset.baselineMeta;
        }
      };
    }

    setupInlineEditor(card);

    // Rebind Unified Review Card inside code-card
    const btnApprove = card.querySelector(".btn-approve");
    const statusMsg = card.querySelector("#review-status-msg");
    if (btnApprove && !btnApprove.disabled) {
      attachApproveHandler(card, btnApprove, statusMsg);
    }
  });

  // Rebind legacy code-inspector-link if present in old cached threads
  container.querySelectorAll(".code-inspector-link").forEach(btn => {
    btn.onclick = () => setAppMode("diff");
  });

  // 3. Rebind Legacy Review Panels (for threads saved before unification)
  container.querySelectorAll(".review-panel").forEach(panel => {
    const btnApprove = panel.querySelector(".btn-approve");
    const statusMsg = panel.querySelector("#review-status-msg");
    if (btnApprove && !btnApprove.disabled) {
      attachApproveHandler(panel, btnApprove, statusMsg);
    }
  });

  // 4. Auto-size legacy review textareas
  container.querySelectorAll(".review-textarea").forEach(ta => {
    ta.style.height = "auto";
    ta.style.height = Math.max(110, ta.scrollHeight + 8) + "px";
  });
}

function setAppMode(mode) {
  currentAppMode = mode;
  const btnChat = document.getElementById("btn-mode-chat");
  const btnDiff = document.getElementById("btn-toggle-diff-mode");
  const heroView = document.getElementById("hero-view");
  const messagesStream = document.getElementById("messages-stream");
  const diffView = document.getElementById("diff-inspector-view");

  if (mode === "diff") {
    if (btnChat) btnChat.classList.remove("active");
    if (btnDiff) btnDiff.classList.add("active");
    if (heroView) heroView.style.display = "none";
    if (messagesStream) messagesStream.style.display = "none";
    if (diffView) {
      diffView.style.display = "flex";
      renderDiffInspectorContent(diffView);
    }
  } else {
    if (btnChat) btnChat.classList.add("active");
    if (btnDiff) btnDiff.classList.remove("active");
    if (diffView) diffView.style.display = "none";

    const hasMessages = messagesStream && messagesStream.children.length > 0;
    if (hasMessages) {
      messagesStream.style.display = "flex";
      if (heroView) heroView.style.display = "none";
    } else {
      if (heroView) heroView.style.display = "flex";
      if (messagesStream) messagesStream.style.display = "none";
    }
  }
}

function renderDiffInspectorContent(container) {
  if (!container) return;

  if (!latestRunData || (!latestRunData.aegis && !latestRunData.baseline)) {
    container.innerHTML = `
      <div class="diff-inspector-empty">
        <div class="diff-inspector-empty-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="8" height="16" rx="2"/><rect x="13" y="4" width="8" height="16" rx="2"/><path d="M6 9h2M6 13h2M16 9h2M16 13h2"/></svg></div>
        <div class="diff-inspector-empty-title">Nothing to compare yet</div>
        <div class="diff-inspector-empty-subtext">
          Run a task and ClearSky's governed patch appears here next to what an ungoverned model would have written.
        </div>
        <div style="display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; justify-content:center;">
          <button class="action-chip" data-prompt="persist"><span>Persist token · ADR-014</span></button>
          <button class="action-chip" data-prompt="rotate"><span>Rotate token · habit</span></button>
          <button class="action-chip" data-prompt="pydantic_v2"><span>Pydantic v2 · ADR-032</span></button>
          <button class="action-chip" data-prompt="db_sqlalchemy"><span>SQLAlchemy · ADR-045</span></button>
        </div>
      </div>
    `;
    container.querySelectorAll("[data-prompt]").forEach(elem => {
      elem.addEventListener("click", () => {
        const key = elem.getAttribute("data-prompt");
        if (PROMPTS[key]) {
          setAppMode("chat");
          runWithPrompt(PROMPTS[key], PRESET_TITLES[key]);
        }
      });
    });
    return;
  }

  const d = latestRunData;
  const aegisDiff = d.aegis ? (d.aegis.diff || d.aegis.code || d.aegis.text) : "";
  const baselineDiff = d.baseline ? (d.baseline.diff || d.baseline.code || d.baseline.text) : "";
  const baselineIsTemplate = !d.baseline || d.baseline.source !== "model";
  const policyId = (d.policy && d.policy.primary_id) || "no decision";
  const leafTokens = d.tokens && d.tokens.leaf ? d.tokens.leaf : null;
  const baselineTokens = d.tokens && d.tokens.baseline ? d.tokens.baseline : null;
  const compressionPct = leafTokens && baselineTokens
    ? Math.round(((baselineTokens - leafTokens) / baselineTokens) * 100)
    : null;
  const targetFile = d.target_file || "(no target)";
  const s1Ms = d.verdict ? Math.round(d.verdict.system1_ms || d.verdict.latency_ms || 0) : 0;
  const tok = (n) => (n ? `${n} tokens` : "n/a");

  container.innerHTML = `
    <div class="diff-inspector-header">
      <div class="diff-inspector-title-group">
        <span class="diff-inspector-badge">Diff inspector</span>
        <span class="diff-inspector-filename">${escapeHtml(targetFile)}</span>
        <span class="diff-inspector-policy">
          <span style="color:var(--accent-green);">●</span> ${escapeHtml(policyId)} in force
        </span>
      </div>
      <div class="diff-inspector-meta-pills">
        <span class="diff-inspector-pill">Full-repo prompt: ${tok(baselineTokens)}</span>
        <span class="diff-inspector-pill highlight">ClearSky prompt: ${tok(leafTokens)}${compressionPct !== null ? ` (-${compressionPct}%)` : ""}</span>
        <span class="diff-inspector-pill">System 1: ${s1Ms ? `${s1Ms}ms` : "n/a"}</span>
        <button class="diff-return-chat-btn" id="btn-inspector-to-chat">← Back to chat</button>
      </div>
    </div>

    <div class="diff-split-grid">
      <div class="diff-pane baseline">
        <div class="diff-pane-header">
          <div class="diff-pane-title">
            <span>${baselineIsTemplate ? "Legacy pattern" : "Ungoverned baseline"}</span>
            <span class="diff-pane-badge">${baselineIsTemplate ? "Illustrative, not a model run" : "Model output, full repo context"}</span>
          </div>
          <span class="code-meta">${tok(baselineTokens)}</span>
        </div>
        <div class="diff-pane-content" id="inspector-baseline-diff"></div>
      </div>

      <div class="diff-pane aegis">
        <div class="diff-pane-header">
          <div class="diff-pane-title">
            <span>ClearSky patch</span>
            <span class="diff-pane-badge">Policy compliant</span>
          </div>
          <span class="code-meta">${tok(leafTokens)}${compressionPct !== null ? ` &middot; -${compressionPct}%` : ""}</span>
        </div>
        <div class="diff-pane-content" id="inspector-aegis-diff"></div>
      </div>
    </div>
  `;

  const baseContainer = container.querySelector("#inspector-baseline-diff");
  const aegisContainer = container.querySelector("#inspector-aegis-diff");
  if (baseContainer) renderDiffLines(baseContainer, baselineDiff);
  if (aegisContainer) renderDiffLines(aegisContainer, aegisDiff);

  const btnBack = container.querySelector("#btn-inspector-to-chat");
  if (btnBack) {
    btnBack.addEventListener("click", () => setAppMode("chat"));
  }
}

/* ==============================================================================
   Interactive Bitemporal Graph Visualizer
   ============================================================================== */

let graphTransform = { x: 40, y: 40, scale: 0.85 };
let isGraphPanning = false;
let graphPanStart = { x: 0, y: 0 };
let currentGraphData = { nodes: [], edges: [] };

function initVisualGraph() {
  const btnToggleTop = document.getElementById("btn-toggle-graph-view");
  const btnOpenDrawer = document.getElementById("btn-open-visual-graph");
  const btnClose = document.getElementById("btn-graph-close");
  const btnReset = document.getElementById("btn-graph-reset-zoom");
  const backdrop = document.getElementById("graph-modal-backdrop");
  const svg = document.getElementById("memory-graph-svg");

  if (btnToggleTop) {
    btnToggleTop.addEventListener("click", () => openVisualGraphModal());
  }

  if (btnOpenDrawer) {
    btnOpenDrawer.addEventListener("click", () => openVisualGraphModal());
  }

  if (btnClose) {
    btnClose.addEventListener("click", closeVisualGraphModal);
  }

  if (btnReset) {
    btnReset.addEventListener("click", resetGraphView);
  }

  if (backdrop) {
    backdrop.addEventListener("click", (e) => {
      if (e.target === backdrop) closeVisualGraphModal();
    });
  }

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && backdrop && backdrop.style.display !== "none") {
      closeVisualGraphModal();
    }
  });

  if (svg) {
    svg.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      if (e.target.closest(".graph-node-group")) return;
      isGraphPanning = true;
      graphPanStart = { x: e.clientX - graphTransform.x, y: e.clientY - graphTransform.y };
      svg.style.cursor = "grabbing";
    });

    window.addEventListener("mousemove", (e) => {
      if (!isGraphPanning) return;
      graphTransform.x = e.clientX - graphPanStart.x;
      graphTransform.y = e.clientY - graphPanStart.y;
      updateGraphTransform();
    });

    window.addEventListener("mouseup", () => {
      if (isGraphPanning) {
        isGraphPanning = false;
        if (svg) svg.style.cursor = "grab";
      }
    });

    svg.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        const zoomFactor = e.deltaY < 0 ? 1.08 : 0.92;
        const newScale = Math.min(Math.max(graphTransform.scale * zoomFactor, 0.25), 2.5);

        const rect = svg.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        graphTransform.x = mouseX - (mouseX - graphTransform.x) * (newScale / graphTransform.scale);
        graphTransform.y = mouseY - (mouseY - graphTransform.y) * (newScale / graphTransform.scale);
        graphTransform.scale = newScale;
        updateGraphTransform();
      },
      { passive: false }
    );
  }
}

function updateGraphTransform() {
  const vp = document.getElementById("graph-viewport");
  if (vp) {
    vp.setAttribute("transform", `translate(${graphTransform.x}, ${graphTransform.y}) scale(${graphTransform.scale})`);
  }
}

function resetGraphView() {
  graphTransform = { x: 40, y: 40, scale: 0.85 };
  updateGraphTransform();
}

async function openVisualGraphModal() {
  const backdrop = document.getElementById("graph-modal-backdrop");
  if (!backdrop) return;
  backdrop.style.display = "flex";
  await loadAndRenderMemoryGraph();
}

function closeVisualGraphModal() {
  const backdrop = document.getElementById("graph-modal-backdrop");
  if (backdrop) backdrop.style.display = "none";
  const tooltip = document.getElementById("graph-tooltip");
  if (tooltip) tooltip.style.display = "none";
}

async function loadAndRenderMemoryGraph() {
  const badge = document.getElementById("graph-node-count-badge");
  const viewport = document.getElementById("graph-viewport");
  if (badge) badge.textContent = "Loading...";

  try {
    const res = await fetch("/api/memory/graph");
    if (!res.ok) throw new Error("Failed to load memory graph");
    const data = await res.json();
    currentGraphData = data;

    if (badge) {
      badge.textContent = `${data.nodes.length} Nodes · ${data.edges.length} Supersession Edges`;
    }

    renderMemoryGraphSvg(data.nodes, data.edges);
  } catch (err) {
    console.error("Error loading graph:", err);
    if (badge) badge.textContent = "Error";
    if (viewport) {
      viewport.innerHTML = `
        <text x="100" y="100" class="node-forbidden" font-size="14">Error loading knowledge graph: ${escapeHtml(err.message)}</text>
      `;
    }
  }
}

function renderMemoryGraphSvg(nodes, edges) {
  const viewport = document.getElementById("graph-viewport");
  const tooltip = document.getElementById("graph-tooltip");
  if (!viewport) return;

  viewport.innerHTML = "";

  const CARD_WIDTH = 400;
  const CARD_HEIGHT = 145;
  const GAP_Y = 30;
  const START_Y = 110;

  const COL1_X = 60;   // Superseded / Banned
  const COL2_X = 580;  // Active In-Force
  const COL3_X = 1100; // Habits & Notes

  // 1. Column headers
  const headers = [
    { x: COL1_X, kind: "kind-superseded", title: "SUPERSEDED · BANNED", subtitle: "Historical decisions, enforced as deterministic bans" },
    { x: COL2_X, kind: "kind-active", title: "IN FORCE", subtitle: "Active architecture decisions · AST enforced" },
    { x: COL3_X, kind: "kind-habit", title: "HABITS & NOTES", subtitle: "Learned from approvals · repository context" }
  ];

  let headerSvg = "";
  headers.forEach(h => {
    headerSvg += `
      <g class="graph-node-group-header ${h.kind}" transform="translate(${h.x}, 40)" style="--kind: var(${h.kind === "kind-superseded" ? "--accent-red" : h.kind === "kind-habit" ? "--accent-violet" : "--accent-green"})">
        <circle cx="5" cy="13" r="5" style="fill: var(--kind)" />
        <text x="18" y="18" class="graph-col-title">${h.title}</text>
        <text x="0" y="38" class="graph-col-sub">${h.subtitle}</text>
        <line x1="0" y1="50" x2="${CARD_WIDTH}" y2="50" class="graph-col-rule" />
      </g>
    `;
  });
  viewport.innerHTML += headerSvg;

  // 2. Separate nodes
  const supersededNodes = nodes.filter(n => n.epistemic_status === "superseded" || n.superseded_at);
  const activeNodes = nodes.filter(n => n.type === "architecture_decision" && n.epistemic_status !== "superseded" && !n.superseded_at);
  const otherNodes = nodes.filter(n => n.type !== "architecture_decision");

  // Map edges to find pairs: active (source) -> superseded (target)
  const edgePairMap = new Map(); // targetId -> sourceId
  edges.forEach(e => {
    if (e.relation === "supersedes") {
      edgePairMap.set(e.target, e.source);
    }
  });

  const nodePositions = new Map(); // id -> { x, y }

  // Align superseded and active nodes by pairing
  let rowIndex = 0;
  const processedActive = new Set();
  const processedSuperseded = new Set();

  supersededNodes.forEach(supNode => {
    const activeSrcId = edgePairMap.get(supNode.id);
    const activeNode = activeNodes.find(a => a.id === activeSrcId);

    const y = START_Y + rowIndex * (CARD_HEIGHT + GAP_Y);
    nodePositions.set(supNode.id, { x: COL1_X, y });
    processedSuperseded.add(supNode.id);

    if (activeNode && !processedActive.has(activeNode.id)) {
      nodePositions.set(activeNode.id, { x: COL2_X, y });
      processedActive.add(activeNode.id);
    }
    rowIndex++;
  });

  // Remaining active nodes
  activeNodes.forEach(actNode => {
    if (!processedActive.has(actNode.id)) {
      const y = START_Y + rowIndex * (CARD_HEIGHT + GAP_Y);
      nodePositions.set(actNode.id, { x: COL2_X, y });
      processedActive.add(actNode.id);
      rowIndex++;
    }
  });

  // Other nodes (habits, notes)
  let otherRowIndex = 0;
  otherNodes.forEach(otherNode => {
    const y = START_Y + otherRowIndex * (CARD_HEIGHT + GAP_Y);
    nodePositions.set(otherNode.id, { x: COL3_X, y });
    otherRowIndex++;
  });

  // 3. Render Edges (render before nodes so lines sit underneath cards)
  let edgesSvg = '<g class="graph-edges-layer">';
  edges.forEach((edge, idx) => {
    const srcPos = nodePositions.get(edge.source);
    const tgtPos = nodePositions.get(edge.target);

    if (srcPos && tgtPos) {
      const x1 = srcPos.x;
      const y1 = srcPos.y + CARD_HEIGHT / 2;
      const x2 = tgtPos.x + CARD_WIDTH;
      const y2 = tgtPos.y + CARD_HEIGHT / 2;

      const dx = Math.abs(x1 - x2) * 0.45;
      const cx1 = x1 - dx;
      const cy1 = y1;
      const cx2 = x2 + dx;
      const cy2 = y2;

      const pathData = `M ${x1} ${y1} C ${cx1} ${cy1}, ${cx2} ${cy2}, ${x2} ${y2}`;
      const midX = (x1 + x2) / 2;
      const midY = (y1 + y2) / 2;

      edgesSvg += `
        <g class="graph-edge-group" data-edge-idx="${idx}" data-source="${escapeHtml(edge.source)}" data-target="${escapeHtml(edge.target)}">
          <path d="${pathData}" class="graph-edge-path" marker-end="url(#arrow-supersedes)" id="edge-${idx}" />
          <g transform="translate(${midX}, ${midY})">
            <rect x="-40" y="-10" width="80" height="20" rx="10" class="graph-edge-pill" />
            <text x="0" y="3.5" class="graph-edge-label">supersedes</text>
          </g>
        </g>
      `;
    }
  });
  edgesSvg += '</g>';
  viewport.innerHTML += edgesSvg;

  // 4. Render Nodes
  let nodesSvg = '<g class="graph-nodes-layer">';
  nodes.forEach(node => {
    const pos = nodePositions.get(node.id) || { x: COL2_X, y: START_Y };
    const isSuperseded = node.epistemic_status === "superseded" || Boolean(node.superseded_at);
    const isHabit = node.type === "habit";
    const isNote = node.type === "project_state";

    let kindClass = "kind-active";
    let badgeText = "IN FORCE";
    if (isSuperseded) {
      kindClass = "kind-superseded";
      badgeText = "SUPERSEDED";
    } else if (isHabit) {
      kindClass = "kind-habit";
      badgeText = "HABIT";
    } else if (isNote) {
      kindClass = "kind-note";
      badgeText = "NOTE";
    }

    const validDate = node.valid_from ? node.valid_from.split("T")[0] : "genesis";
    const rawLabel = (node.label || node.id);
    const truncatedTitle = rawLabel.length > 46 ? rawLabel.slice(0, 43) + "..." : rawLabel;

    let bodyContentSvg = "";
    if (isSuperseded) {
      const whyText = node.why_inactive || "Superseded by newer architecture decision";
      const truncatedWhy = whyText.length > 60 ? whyText.slice(0, 57) + "..." : whyText;
      const forbiddenTokens = (node.forbidden || []).slice(0, 3).join(", ");

      bodyContentSvg = `
        <rect x="14" y="60" width="${CARD_WIDTH - 28}" height="44" rx="7" class="node-why-bg" />
        <text x="24" y="77" class="node-why-label">Why it was superseded</text>
        <text x="24" y="93" class="node-why-text">${escapeHtml(truncatedWhy)}</text>
        ${forbiddenTokens ? `<text x="14" y="125" class="node-mono node-forbidden">banned: ${escapeHtml(forbiddenTokens)}</text>` : ''}
      `;
    } else if (node.type === "architecture_decision") {
      const reqTokens = (node.required || []).slice(0, 2).join(", ");
      const forbTokens = (node.forbidden || []).slice(0, 2).join(", ");

      bodyContentSvg = `
        ${reqTokens ? `<text x="14" y="78" class="node-mono node-required">+ required: ${escapeHtml(reqTokens)}</text>` : ''}
        ${forbTokens ? `<text x="14" y="98" class="node-mono node-forbidden">− forbidden: ${escapeHtml(forbTokens)}</text>` : ''}
        <text x="14" y="126" class="node-foot">AST rule active · valid from ${validDate}</text>
      `;
    } else {
      const tagList = (node.tags || []).slice(0, 3).join(", ");
      bodyContentSvg = `
        <text x="14" y="80" class="node-foot">${isHabit ? "Learned from an approved edit" : "Repository context note"}</text>
        ${tagList ? `<text x="14" y="102" class="node-mono node-tags">tags: ${escapeHtml(tagList)}</text>` : ''}
        <text x="14" y="126" class="node-foot">Recorded ${validDate}</text>
      `;
    }

    nodesSvg += `
      <g class="graph-node-group ${kindClass}" data-id="${escapeHtml(node.id)}" transform="translate(${pos.x}, ${pos.y})">
        <rect class="node-card" width="${CARD_WIDTH}" height="${CARD_HEIGHT}" rx="12" />
        <rect x="0" y="16" width="3" height="${CARD_HEIGHT - 32}" rx="1.5" class="node-stripe" />

        <rect x="14" y="13" width="${badgeText.length * 7 + 16}" height="18" rx="9" class="node-badge-bg" />
        <text x="22" y="25.5" class="node-badge-text">${badgeText}</text>
        <text x="${CARD_WIDTH - 14}" y="25.5" text-anchor="end" class="node-date">${validDate}</text>

        <text x="14" y="49" class="node-title">${escapeHtml(truncatedTitle)}</text>

        ${bodyContentSvg}

        ${node.id.startsWith("adr:") ? `<text x="${CARD_WIDTH - 14}" y="${CARD_HEIGHT - 12}" text-anchor="end" class="node-hint">Open ADR →</text>` : ''}
      </g>
    `;
  });
  nodesSvg += '</g>';
  viewport.innerHTML += nodesSvg;

  // 5. Attach event listeners to node groups
  viewport.querySelectorAll(".graph-node-group").forEach(el => {
    const nodeId = el.getAttribute("data-id");
    const nodeData = nodes.find(n => n.id === nodeId);
    if (!nodeData) return;

    el.addEventListener("mouseenter", (e) => {
      viewport.querySelectorAll(".graph-edge-group").forEach(edgeEl => {
        const src = edgeEl.getAttribute("data-source");
        const tgt = edgeEl.getAttribute("data-target");
        const path = edgeEl.querySelector(".graph-edge-path");
        if (src === nodeId || tgt === nodeId) {
          if (path) {
            path.style.strokeWidth = "3px";
            path.style.opacity = "1";
          }
        }
      });

      if (tooltip) {
        let tooltipContent = `
          <div class="graph-tooltip-title">${escapeHtml(nodeData.label || nodeData.id)}</div>
          <span class="graph-tooltip-status ${nodeData.epistemic_status === 'superseded' ? 'superseded' : (nodeData.type === 'habit' ? 'habit' : (nodeData.type === 'project_state' ? 'note' : 'active'))}">
            ${escapeHtml(nodeData.epistemic_status).toUpperCase()}
          </span>
          <div class="graph-tooltip-meta">
            Valid from: ${nodeData.valid_from ? nodeData.valid_from.split('T')[0] : 'genesis'}
            ${nodeData.superseded_at ? `<br/>Superseded at: ${nodeData.superseded_at.split('T')[0]}` : ''}
          </div>
        `;

        if (nodeData.why_inactive) {
          tooltipContent += `
            <div class="graph-tooltip-why">
              <strong>Why it was superseded</strong><br/>
              ${escapeHtml(nodeData.why_inactive)}
            </div>
          `;
        }

        if (nodeData.required && nodeData.required.length > 0) {
          tooltipContent += `<div class="graph-tooltip-line req">Required: ${escapeHtml(nodeData.required.join(', '))}</div>`;
        }
        if (nodeData.forbidden && nodeData.forbidden.length > 0) {
          tooltipContent += `<div class="graph-tooltip-line forb">Forbidden: ${escapeHtml(nodeData.forbidden.join(', '))}</div>`;
        }
        if (nodeData.tags && nodeData.tags.length > 0) {
          tooltipContent += `<div class="graph-tooltip-line tags">Tags: ${escapeHtml(nodeData.tags.join(', '))}</div>`;
        }

        tooltip.innerHTML = tooltipContent;
        tooltip.style.display = "block";
      }
    });

    el.addEventListener("mousemove", (e) => {
      if (tooltip && tooltip.style.display !== "none") {
        const modalBody = document.querySelector(".graph-modal-body");
        if (modalBody) {
          const rect = modalBody.getBoundingClientRect();
          let left = e.clientX - rect.left + 16;
          let top = e.clientY - rect.top + 16;

          if (left + 360 > rect.width) {
            left = e.clientX - rect.left - 360;
          }
          if (top + 220 > rect.height) {
            top = e.clientY - rect.top - 200;
          }

          tooltip.style.left = `${Math.max(10, left)}px`;
          tooltip.style.top = `${Math.max(10, top)}px`;
        }
      }
    });

    el.addEventListener("mouseleave", () => {
      viewport.querySelectorAll(".graph-edge-path").forEach(path => {
        path.style.strokeWidth = "";
        path.style.opacity = "";
      });
      if (tooltip) tooltip.style.display = "none";
    });

    el.addEventListener("click", () => {
      if (nodeData.id.startsWith("adr:")) {
        openAdrModal(nodeData.id.replace("adr:", ""));
      }
    });
  });

  updateGraphTransform();
}
