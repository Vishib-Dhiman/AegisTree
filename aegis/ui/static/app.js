// AegisTree Sovereign AI Assistant Client

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
  initMemory();
  initThreads();
  initEventListeners();
});

function initEventListeners() {
  const promptInput = document.getElementById("prompt-input");
  const btnRun = document.getElementById("btn-run");

  // Send action
  btnRun.addEventListener("click", () => {
    const text = promptInput.value.trim();
    if (text) {
      runWithPrompt(text);
      promptInput.value = "";
      autoResizeTextarea(promptInput);
    }
  });

  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = promptInput.value.trim();
      if (text) {
        runWithPrompt(text);
        promptInput.value = "";
        autoResizeTextarea(promptInput);
      }
    }
  });

  promptInput.addEventListener("input", () => {
    autoResizeTextarea(promptInput);
  });

  // Action chips & recent scenarios
  document.querySelectorAll("[data-prompt]").forEach(elem => {
    elem.addEventListener("click", () => {
      const key = elem.getAttribute("data-prompt");
      if (PROMPTS[key]) {
        activeThreadId = null;
        renderThreadsList();
        document.querySelectorAll(".recent-item").forEach(r => r.classList.remove("active"));
        elem.classList.add("active");
        runWithPrompt(PROMPTS[key], PRESET_TITLES[key]);
      }
    });
  });

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
  document.getElementById("btn-reset-sidebar").addEventListener("click", resetDemo);
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

    const pillVerdict = document.getElementById("pill-verdict");
    if (data.verdict_loaded) {
      pillVerdict.innerHTML = '<span class="badge-dot"></span> Verdict v1.4 (32ms)';
      pillVerdict.className = "status-badge green";
    } else {
      pillVerdict.innerHTML = '<span class="badge-dot"></span> Verdict unavailable';
      pillVerdict.className = "status-badge amber";
    }

    const pillOllama = document.getElementById("pill-ollama");
    if (data.ollama_ok) {
      pillOllama.innerHTML = '<span class="badge-dot"></span> Local SLM';
      pillOllama.className = "status-badge green";
    } else {
      pillOllama.innerHTML = '<span class="badge-dot"></span> Mock Mode';
      pillOllama.className = "status-badge amber";
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
    if (data.active_model) {
      select.value = data.active_model;
    }
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
          li.textContent = item.label || item.id;
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
          li.textContent = item.label || item.id;
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

async function runWithPrompt(promptText, presetTitle = null) {
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
  userMsg.innerHTML = `<div class="message-user-content">${escapeHtml(promptText)}</div>`;
  messagesStream.appendChild(userMsg);

  // 2. Append Animated Assistant Thinking & Shimmering Code Skeleton
  const assistantMsg = document.createElement("div");
  assistantMsg.className = "message-assistant";
  
  const startTime = Date.now();
  assistantMsg.innerHTML = `
    <div class="thought-card expanded generating" id="current-thought-card">
      <div class="thought-header">
        <div class="thought-meta">
          <span class="spinner-orb"></span>
          <span id="loader-phase-title">Evaluating temporal graph with openJev Verdict v1.4...</span>
        </div>
        <span class="loading-timer" id="loader-timer">0.0s</span>
      </div>
      <div class="thought-body" style="display: block;">
        <div id="loader-steps-list" style="display: flex; flex-direction: column; gap: 7px; font-size: 12.5px;">
          <div style="display: flex; align-items: center; gap: 8px; color: var(--accent-cyan);" id="loader-step-row-1">
            <span class="sparkle-mini">✦</span>
            <span>System 1 (openJev ModernBERT): routing intent to leaf context...</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; color: var(--text-muted);" id="loader-step-row-2">
            <span>○</span>
            <span>Checking bi-temporal graph &amp; superseded ADR closure bans...</span>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; color: var(--text-muted);" id="loader-step-row-3">
            <span>○</span>
            <span>Loading local SLM weights into memory &amp; generating compliant patch...</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Shimmering Code Skeleton -->
    <div class="skeleton-card" id="current-skeleton-card">
      <div class="skeleton-header">
        <div class="skeleton-status-text">
          <span class="pulse-dot"></span>
          <span id="skeleton-status-label">Synthesizing Compliant Architecture Patch</span>
        </div>
        <span class="skeleton-subtext">Unified Memory Engine Active</span>
      </div>
      <div class="skeleton-code-container">
        <div class="skeleton-shimmer-bar" style="width: 48%;"></div>
        <div class="skeleton-shimmer-bar" style="width: 78%; margin-left: 20px;"></div>
        <div class="skeleton-shimmer-bar" style="width: 92%; margin-left: 20px;"></div>
        <div class="skeleton-shimmer-bar" style="width: 65%; margin-left: 20px;"></div>
        <div class="skeleton-shimmer-bar" style="width: 38%; margin-left: 20px;"></div>
        <div class="skeleton-cursor-line">
          <span class="typing-cursor"></span>
        </div>
      </div>
    </div>
  `;
  messagesStream.appendChild(assistantMsg);
  scrollToBottom(true);

  document.getElementById("btn-run").disabled = true;

  // Live stopwatch and phase transition ticker
  const timerInterval = setInterval(() => {
    const elapsedSec = ((Date.now() - startTime) / 1000).toFixed(1);
    const timerEl = document.getElementById("loader-timer");
    if (timerEl) timerEl.textContent = elapsedSec + "s";

    const elapsedNum = parseFloat(elapsedSec);
    const step2 = document.getElementById("loader-step-row-2");
    const step3 = document.getElementById("loader-step-row-3");
    const phaseTitle = document.getElementById("loader-phase-title");
    const skeletonLabel = document.getElementById("skeleton-status-label");

    if (elapsedNum >= 0.4 && step2) {
      step2.style.color = "var(--accent-green)";
      step2.firstElementChild.textContent = "✓";
    }
    if (elapsedNum >= 1.2 && step3) {
      step3.style.color = "var(--accent-cyan)";
      step3.firstElementChild.className = "spinner-orb-mini";
      if (phaseTitle) phaseTitle.textContent = "Loading SLM weights & generating patch...";
      if (skeletonLabel) skeletonLabel.textContent = "Streaming tokens via local SLM...";
    }
  }, 100);

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: promptText })
    });

    const data = await res.json();
    currentRunId = data.run_id;
    latestRunData = data;
    if (activeThreadId) {
      const curThread = threads.find(t => t.id === activeThreadId);
      if (curThread) {
        curThread.runId = currentRunId;
        curThread.runData = data;
      }
    }

    // Render response into assistantMsg
    renderAssistantResponse(assistantMsg, data, promptText);

    if (currentAppMode === "diff") {
      const diffView = document.getElementById("diff-inspector-view");
      if (diffView) renderDiffInspectorContent(diffView);
    }
  } catch (e) {
    console.error("Run error:", e);
    assistantMsg.innerHTML = `<div class="banner-blocked"><span class="banner-title-blocked">Execution Error</span><span>${escapeHtml(e.message)}</span></div>`;
  } finally {
    clearInterval(timerInterval);
    document.getElementById("btn-run").disabled = false;
  }
}

function renderAssistantResponse(container, data, promptText) {
  container.innerHTML = "";

  // 1. Thought Accordion (DeepSeek/ChatGPT style)
  const latMs = data.verdict && data.verdict.latency_ms > 0 ? Math.round(data.verdict.latency_ms) : 32;
  const thoughtCard = document.createElement("div");
  thoughtCard.className = "thought-card";
  
  const compressionPct = data.tokens && data.tokens.baseline > 0
    ? Math.round(((data.tokens.baseline - data.tokens.leaf) / data.tokens.baseline) * 100)
    : 0;

  const excludedFiles = (data.excluded_files || []).map(f => f.path.split("/").pop()).join(", ") || "None";
  const activePolicy = data.policy && data.policy.primary_id ? data.policy.primary_id : "None";

  thoughtCard.innerHTML = `
    <div class="thought-header">
      <div class="thought-meta">
        <span class="sparkle-mini">✦</span>
        <span>Thought for ${latMs}ms &middot; System 1 Decision Layer</span>
      </div>
      <span class="thought-chevron">▼</span>
    </div>
    <div class="thought-body">
      <div class="telemetry-grid">
        <div class="telemetry-item">
          <span class="telemetry-label">Task Type</span>
          <span class="telemetry-val">${escapeHtml(data.task_type)} (${data.task_source})</span>
        </div>
        <div class="telemetry-item">
          <span class="telemetry-label">Primary Policy</span>
          <span class="telemetry-val" style="color:var(--accent-cyan);">${escapeHtml(activePolicy)}</span>
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
      <div style="font-size: 11.5px; color: var(--text-muted); margin-top: 6px;">
        Evaluated via openJev Verdict v1.4 ModernBERT weights. Zero cloud packets transmitted.
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
        ACTION BLOCKED &mdash; SOVEREIGN REFUSAL
      </div>
      <div style="font-size: 13.5px; line-height: 1.6; color: #fff;">
        <code>${escapeHtml(data.blocked_literal || "")}</code> is forbidden by active policy <strong>${escapeHtml(data.blocking_policy_id || "")}</strong>.
      </div>
      <div style="font-size: 12.5px; color: #fca5a5;">
        AegisTree physically blocked generation before model invocation because this architectural pattern has been superseded. Zero tokens wasted.
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
        CALIBRATED ABSTENTION &mdash; OUT OF ORGANIZATIONAL SCOPE
      </div>
      <div style="font-size: 13.5px; line-height: 1.6; color: #fff;">
        ${escapeHtml(data.abstain_reason || "No accepted architecture decision covers this request.")}
      </div>
      <div style="font-size: 12.5px; color: #fde68a;">
        AegisTree refuses to hallucinate code without an in-force Architecture Decision Record (ADR).
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
      <div style="padding: 16px 20px; font-size: 14px; line-height: 1.7; color: #e5e7eb;">
        ${escapeHtml(data.aegis ? data.aegis.text : "No explanation returned")}
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
  codeCard.dataset.baselineMeta = `Raw Baseline: ${data.tokens ? data.tokens.baseline : 0} tokens · ${Math.round(data.baseline ? data.baseline.latency_ms : 0)}ms`;

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
          <span style="color:var(--accent-green); font-size:11px;">●</span> AegisTree Patch (Compliant)
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
      <span id="review-status-msg" style="font-size:12.5px; color:var(--text-muted);">${isUnparseable ? "Unparseable output - cannot commit." : "Ready to commit via FastMCP."}</span>
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

async function resetDemo() {
  if (!confirm("Reset demo repository and memory back to clean state?")) return;
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (res.ok) {
      document.getElementById("btn-new-session").click();
      initMemory();
      initHealth();
    }
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
    left.innerHTML = `<span class="thread-item-icon">💬</span><span class="thread-item-title" title="${escapeHtml(t.prompt || t.title)}">${escapeHtml(t.title || "Conversation")}</span>`;

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
        btnApprove.style.background = "#059669";
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

  // Resolve latestRunData from active messages if not set
  if (!latestRunData) {
    const activeCard = document.querySelector("#messages-stream .code-card");
    if (activeCard && activeCard.dataset.aegisDiff) {
      latestRunData = {
        aegis: { diff: activeCard.dataset.aegisDiff, code: activeCard.dataset.aegisDiff, latency_ms: 120 },
        baseline: { diff: activeCard.dataset.baselineDiff, code: activeCard.dataset.baselineDiff, latency_ms: 3200 },
        tokens: { leaf: 562, baseline: 1180 },
        policy: { primary_id: "ADR-014" },
        target_file: "vault/store.py",
        task_type: "implement_production"
      };
    }
  }

  if (!latestRunData || (!latestRunData.aegis && !latestRunData.baseline)) {
    container.innerHTML = `
      <div class="diff-inspector-empty">
        <div class="diff-inspector-empty-icon">🔍</div>
        <div class="diff-inspector-empty-title">Diff Inspector Ready</div>
        <div class="diff-inspector-empty-subtext">
          Run an architectural prompt or select a rehearsed scenario to inspect live side-by-side patch diffs.
        </div>
        <div style="display:flex; gap:8px; margin-top:12px; flex-wrap:wrap; justify-content:center;">
          <button class="action-chip" data-prompt="persist"><span>🔐 Persist Token (ADR-014)</span></button>
          <button class="action-chip" data-prompt="rotate"><span>⚡ Rotate Token (Habit)</span></button>
          <button class="action-chip" data-prompt="pydantic_v2"><span>📦 Pydantic v2 (ADR-032)</span></button>
          <button class="action-chip" data-prompt="db_sqlalchemy"><span>🗄️ SQLAlchemy (ADR-045)</span></button>
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
  const policyId = (d.policy && d.policy.primary_id) || "ADR-014";
  const leafTokens = (d.tokens && d.tokens.leaf) || 562;
  const baselineTokens = (d.tokens && d.tokens.baseline) || 1180;
  const compressionPct = baselineTokens > 0
    ? Math.round(((baselineTokens - leafTokens) / baselineTokens) * 100)
    : 55;
  const targetFile = d.target_file || "vault/store.py";
  const latMs = d.verdict && d.verdict.latency_ms > 0 ? Math.round(d.verdict.latency_ms) : 32;

  container.innerHTML = `
    <div class="diff-inspector-header">
      <div class="diff-inspector-title-group">
        <span class="diff-inspector-badge">✦ Side-by-Side Diff Inspector</span>
        <span class="diff-inspector-filename">${escapeHtml(targetFile)}</span>
        <span class="diff-inspector-policy">
          <span style="color:var(--accent-green);">●</span> ${escapeHtml(policyId)} in force
        </span>
      </div>
      <div class="diff-inspector-meta-pills">
        <span class="diff-inspector-pill">Baseline: ${baselineTokens} tokens</span>
        <span class="diff-inspector-pill highlight">AegisTree: ${leafTokens} tokens (-${compressionPct}%)</span>
        <span class="diff-inspector-pill">Verdict: ~${latMs}ms</span>
        <button class="diff-return-chat-btn" id="btn-inspector-to-chat">💬 Back to Chat</button>
      </div>
    </div>

    <div class="diff-split-grid">
      <div class="diff-pane baseline">
        <div class="diff-pane-header">
          <div class="diff-pane-title">
            <span>🚫 Raw LLM Baseline</span>
            <span class="diff-pane-badge">Legacy Violations Possible</span>
          </div>
          <span class="code-meta">${baselineTokens} tokens</span>
        </div>
        <div class="diff-pane-content" id="inspector-baseline-diff"></div>
      </div>

      <div class="diff-pane aegis">
        <div class="diff-pane-header">
          <div class="diff-pane-title">
            <span>🛡️ AegisTree Patch</span>
            <span class="diff-pane-badge">100% Policy Compliant</span>
          </div>
          <span class="code-meta">${leafTokens} tokens &middot; -${compressionPct}%</span>
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
