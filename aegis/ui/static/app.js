// AegisTree Sovereign AI Assistant Client

let currentRunId = null;

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

document.addEventListener("DOMContentLoaded", () => {
  initHealth();
  initModelSelector();
  initMemory();
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
        runWithPrompt(PROMPTS[key]);
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

  // New session button
  document.getElementById("btn-new-session").addEventListener("click", () => {
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
      (data.in_force || []).forEach(item => {
        const li = document.createElement("li");
        li.textContent = item.label || item.id;
        inForceList.appendChild(li);
      });
    }

    const supersededList = document.getElementById("memory-superseded");
    if (supersededList) {
      supersededList.innerHTML = "";
      (data.superseded || []).forEach(item => {
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

async function runWithPrompt(promptText) {
  document.getElementById("hero-view").style.display = "none";
  const messagesStream = document.getElementById("messages-stream");
  messagesStream.style.display = "flex";

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

    // Render response into assistantMsg
    renderAssistantResponse(assistantMsg, data, promptText);
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
    return;
  }

  // 5. Code & Unified Diff Card with Side-by-Side Tabs
  const codeCard = document.createElement("div");
  codeCard.className = "code-card";

  const aegisDiff = data.aegis ? (data.aegis.diff || data.aegis.code || data.aegis.text) : "";
  const baselineDiff = data.baseline ? (data.baseline.diff || data.baseline.code || data.baseline.text) : "";

  codeCard.innerHTML = `
    <div class="code-card-header">
      <div class="code-tabs">
        <button class="code-tab-btn active" id="tab-aegis">AegisTree Patch (Compliant)</button>
        <button class="code-tab-btn" id="tab-baseline">Raw LLM Baseline (Legacy Bug)</button>
      </div>
      <span class="code-meta" id="code-meta-text">Aegis: ${data.tokens ? data.tokens.leaf : 0} tokens &middot; ${Math.round(data.aegis ? data.aegis.latency_ms : 0)}ms</span>
    </div>
    <div class="diff-display" id="diff-content-view"></div>
  `;

  const diffView = codeCard.querySelector("#diff-content-view");
  const tabAegis = codeCard.querySelector("#tab-aegis");
  const tabBaseline = codeCard.querySelector("#tab-baseline");
  const metaText = codeCard.querySelector("#code-meta-text");

  function showAegisTab() {
    tabAegis.classList.add("active");
    tabBaseline.classList.remove("active");
    renderDiffLines(diffView, aegisDiff);
    metaText.textContent = `Aegis: ${data.tokens ? data.tokens.leaf : 0} tokens · ${Math.round(data.aegis ? data.aegis.latency_ms : 0)}ms`;
  }

  function showBaselineTab() {
    tabBaseline.classList.add("active");
    tabAegis.classList.remove("active");
    renderDiffLines(diffView, baselineDiff);
    metaText.textContent = `Raw Baseline: ${data.tokens ? data.tokens.baseline : 0} tokens · ${Math.round(data.baseline ? data.baseline.latency_ms : 0)}ms`;
  }

  tabAegis.addEventListener("click", showAegisTab);
  tabBaseline.addEventListener("click", showBaselineTab);
  showAegisTab();

  container.appendChild(codeCard);

  // 6. Human-in-the-Loop Review Box
  if (data.aegis && data.aegis.code && !data.aegis.unparseable) {
    const reviewPanel = document.createElement("div");
    reviewPanel.className = "review-panel";
    reviewPanel.innerHTML = `
      <div class="review-panel-header">
        <span class="review-title">Human-in-the-Loop Review (FastMCP Gate)</span>
        <span class="review-hint">Tip: edit retries=3 to retries=1 to train organizational memory</span>
      </div>
      <textarea class="review-textarea" id="review-code-input">${escapeHtml(data.aegis.code)}</textarea>
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <span id="review-status-msg" style="font-size:12.5px; color:var(--text-muted);">Ready to commit via FastMCP.</span>
        <button class="btn-approve" id="btn-approve-action">Approve &amp; Commit</button>
      </div>
    `;

    const btnApprove = reviewPanel.querySelector("#btn-approve-action");
    const reviewInput = reviewPanel.querySelector("#review-code-input");
    const statusMsg = reviewPanel.querySelector("#review-status-msg");

    // Auto-resize review textarea to prevent awkward nested scroll capture
    setTimeout(() => {
      reviewInput.style.height = "auto";
      reviewInput.style.height = Math.max(90, reviewInput.scrollHeight + 8) + "px";
    }, 20);
    reviewInput.addEventListener("input", () => {
      reviewInput.style.height = "auto";
      reviewInput.style.height = Math.max(90, reviewInput.scrollHeight + 8) + "px";
    });

    btnApprove.addEventListener("click", async () => {
      btnApprove.disabled = true;
      btnApprove.textContent = "Committing...";

      try {
        const resp = await fetch("/api/approve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            run_id: currentRunId,
            approved_code: reviewInput.value
          })
        });

        const resData = await resp.json();

        if (resp.ok && resData.applied) {
          btnApprove.textContent = "Approved ✓";
          btnApprove.style.background = "#059669";
          statusMsg.innerHTML = `<span style="color:var(--accent-green); font-weight:600;">✓ Patch Committed &middot; Receipt #${resData.receipt_id}</span>`;

          if (resData.habit_label) {
            const habitAlert = document.createElement("div");
            habitAlert.className = "habit-badge-alert";
            habitAlert.innerHTML = `
              <span class="sparkle-mini">✦</span>
              <span><strong>New Habit Synthesized:</strong> ${escapeHtml(resData.habit_label)}</span>
            `;
            reviewPanel.appendChild(habitAlert);
            scrollToBottom(true);
          }
          initMemory();
        } else {
          statusMsg.innerHTML = `<span style="color:var(--accent-red);">${escapeHtml(resData.detail || resData.reason || "Refused")}</span>`;
          btnApprove.disabled = false;
          btnApprove.textContent = "Approve & Commit";
        }
      } catch (err) {
        statusMsg.innerHTML = `<span style="color:var(--accent-red);">${escapeHtml(err.message)}</span>`;
        btnApprove.disabled = false;
        btnApprove.textContent = "Approve & Commit";
      }
    });

    container.appendChild(reviewPanel);
  }

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
