// AegisTree Sovereign Second Brain Dashboard Client

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
  initButtons();
});

function initButtons() {
  const promptInput = document.getElementById("prompt-input");

  document.getElementById("btn-run").addEventListener("click", () => {
    const text = promptInput.value.trim();
    if (text) {
      runWithPrompt(text);
    }
  });

  promptInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = promptInput.value.trim();
      if (text) {
        runWithPrompt(text);
      }
    }
  });

  // Vault
  document.getElementById("btn-persist").addEventListener("click", () => runWithPrompt(PROMPTS.persist));
  document.getElementById("btn-rotate").addEventListener("click", () => runWithPrompt(PROMPTS.rotate));
  document.getElementById("btn-force-legacy").addEventListener("click", () => runWithPrompt(PROMPTS.force_legacy));

  // PyCA Cryptography
  document.getElementById("btn-pyca-oaep").addEventListener("click", () => runWithPrompt(PROMPTS.pyca_oaep));
  document.getElementById("btn-pyca-pkcs").addEventListener("click", () => runWithPrompt(PROMPTS.pyca_pkcs));

  // Pydantic
  document.getElementById("btn-pydantic-v2").addEventListener("click", () => runWithPrompt(PROMPTS.pydantic_v2));
  document.getElementById("btn-pydantic-v1").addEventListener("click", () => runWithPrompt(PROMPTS.pydantic_v1));

  // Database / SQLAlchemy
  document.getElementById("btn-db-sqlalchemy").addEventListener("click", () => runWithPrompt(PROMPTS.db_sqlalchemy));
  document.getElementById("btn-db-engine").addEventListener("click", () => runWithPrompt(PROMPTS.db_engine));

  // Governance
  document.getElementById("btn-explain").addEventListener("click", () => runWithPrompt(PROMPTS.explain));
  document.getElementById("btn-kyber").addEventListener("click", () => runWithPrompt(PROMPTS.kyber));

  document.getElementById("btn-reset").addEventListener("click", resetDemo);
  document.getElementById("btn-approve").addEventListener("click", approveCurrentRun);
}

async function initHealth() {
  try {
    const res = await fetch("/api/health");
    if (!res.ok) return;
    const data = await res.json();

    const pillVerdict = document.getElementById("pill-verdict");
    if (data.verdict_loaded) {
      pillVerdict.textContent = "Verdict loaded";
      pillVerdict.className = "pill pill-green";
    } else {
      pillVerdict.textContent = "Verdict unavailable";
      pillVerdict.className = "pill pill-amber";
    }

    const pillOllama = document.getElementById("pill-ollama");
    if (data.ollama_ok) {
      pillOllama.textContent = "Ollama ok";
      pillOllama.className = "pill pill-green";
    } else {
      pillOllama.textContent = "Ollama down";
      pillOllama.className = "pill pill-red";
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
    inForceList.innerHTML = "";
    (data.in_force || []).forEach(item => {
      const li = document.createElement("li");
      li.textContent = item.label || item.id;
      inForceList.appendChild(li);
    });

    const supersededList = document.getElementById("memory-superseded");
    supersededList.innerHTML = "";
    (data.superseded || []).forEach(item => {
      const li = document.createElement("li");
      li.className = "memory-item-superseded";
      li.textContent = item.label || item.id;
      supersededList.appendChild(li);
    });

    const notesList = document.getElementById("memory-notes");
    notesList.innerHTML = "";
    (data.notes || []).forEach(item => {
      const li = document.createElement("li");
      li.innerHTML = `<strong>${escapeHtml(item.label)}</strong>: ${escapeHtml(item.description || "")}`;
      notesList.appendChild(li);
    });
  } catch (e) {
    console.error("Memory fetch error:", e);
  }
}

async function runWithPrompt(promptText) {
  const input = document.getElementById("prompt-input");
  input.value = promptText;

  setLoadingState(true);
  clearError();

  try {
    const res = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: promptText })
    });

    const data = await res.json();
    currentRunId = data.run_id;

    renderRunResponse(data);
  } catch (e) {
    console.error("Run error:", e);
    alert("Error executing run: " + e.message);
  } finally {
    setLoadingState(false);
  }
}

function renderRunResponse(data) {
  const columnsContainer = document.getElementById("columns-container");
  const abstainBox = document.getElementById("abstain-box");
  const approveSection = document.getElementById("approve-section");
  const forbiddenBox = document.getElementById("forbidden-box");

  // Update Decision Card header items
  const taskSourceText = data.verdict && data.verdict.latency_ms > 0
    ? `${data.task_source} (${Math.round(data.verdict.latency_ms)} ms)`
    : data.task_source;
  document.getElementById("card-task-type").textContent = `${data.task_type} · ${taskSourceText}`;

  const policyText = data.policy && data.policy.primary_id
    ? `${data.policy.primary_id} (${data.policy.source})`
    : "None";
  document.getElementById("card-policy").textContent = policyText;

  const excludedText = (data.excluded_files || []).map(f => f.path.split("/").pop()).join(", ") || "None";
  document.getElementById("card-excluded").textContent = excludedText;

  // Tool log
  const toolLogElem = document.getElementById("tool-log");
  toolLogElem.innerHTML = "";
  (data.tool_log || []).forEach(t => {
    const span = document.createElement("span");
    span.className = "tool-tag";
    span.textContent = `${t.tool}: ${t.status}`;
    toolLogElem.appendChild(span);
  });

  // Forbidden literals list
  const forbiddenListElem = document.getElementById("forbidden-list");
  forbiddenListElem.innerHTML = "";
  const allBanned = [];
  (data.negative || []).forEach(neg => {
    (neg.literals || []).forEach(lit => {
      allBanned.push({ literal: lit, origin: neg.id });
    });
  });

  if (allBanned.length > 0) {
    forbiddenBox.style.display = "block";
    allBanned.forEach(item => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="forbidden-pill">${escapeHtml(item.literal)}</span> <span style="font-size:12px; color:var(--text-muted);">(from ${escapeHtml(item.origin)})</span>`;
      forbiddenListElem.appendChild(li);
    });
  } else {
    forbiddenBox.style.display = "none";
  }

  // Leaf prompt preview
  const leafPreview = document.getElementById("leaf-prompt-preview");
  if (data.aegis && data.aegis.leaf) {
    leafPreview.textContent = data.aegis.leaf;
    document.getElementById("details-leaf-container").style.display = "block";
  } else {
    document.getElementById("details-leaf-container").style.display = "none";
  }

  const blockedBox = document.getElementById("blocked-box");

  // Handle BLOCKED status (Sovereign Refusal)
  if (data.status === "blocked") {
    columnsContainer.style.display = "grid";
    approveSection.style.display = "none";
    abstainBox.style.display = "none";
    if (blockedBox) {
      blockedBox.style.display = "block";
      blockedBox.innerHTML = `
        <div style="font-weight: 700; color: var(--danger-red); margin-bottom: 6px; font-size: 15px; letter-spacing: 0.5px;">ACTION BLOCKED &mdash; SOVEREIGN REFUSAL</div>
        <div style="line-height: 1.6; color: var(--text-primary);">
          <code>${escapeHtml(data.blocked_literal || "legacy_wrap")}</code> is forbidden by active policy <strong>${escapeHtml(data.blocking_policy_id || "adr:014-aegis-seal")}</strong>.<br>
          Superseded pattern from ADR-003 cannot be used in production code.<br>
          <span style="color: var(--text-muted); font-size: 13px;">No generator call was made. No patch was proposed.</span>
        </div>
      `;
    }
    document.getElementById("aegis-column-title").textContent = "AegisTree — Sovereign Guard";
    document.getElementById("baseline-meta").textContent = "0 ms · 0 chars/4 estimate";
    document.getElementById("aegis-meta").textContent = "0 ms · 0 chars/4 estimate";
    document.getElementById("baseline-diff").textContent = "Generation halted: request contains forbidden literal.";
    document.getElementById("aegis-diff").textContent = "Action blocked deterministically by Router before model invocation.";
    return;
  }
  if (blockedBox) {
    blockedBox.style.display = "none";
  }

  // Handle ABSTAINED status (e.g. Kyber prompt, out-of-scope prompt)
  if (data.status === "abstained") {
    columnsContainer.style.display = "grid";
    approveSection.style.display = "none";
    abstainBox.style.display = "block";
    abstainBox.innerHTML = `
      <div style="font-weight: 700; color: var(--warning-amber); margin-bottom: 6px; font-size: 15px; letter-spacing: 0.5px;">ABSTENTION &mdash; OUT OF ORGANIZATIONAL SCOPE</div>
      <div style="line-height: 1.6; color: var(--text-primary);">
        ${escapeHtml(data.abstain_reason || "No accepted decision in the repository covers this request.")}<br>
        <span style="color: var(--text-muted); font-size: 13px;">AegisTree refuses to hallucinate code without an in-force Architecture Decision Record (ADR).</span>
      </div>
    `;
    document.getElementById("aegis-column-title").textContent = "AegisTree — Abstained";
    document.getElementById("baseline-meta").textContent = "0 ms · 0 chars/4 estimate";
    document.getElementById("aegis-meta").textContent = "0 ms · 0 chars/4 estimate";
    document.getElementById("baseline-diff").textContent = "Generation halted: unapproved decision.";
    document.getElementById("aegis-diff").textContent = "Abstained: No active architectural decision covers this request in demo_vault/docs/adr.";
    return;
  }

  // Handle WRITE ADR
  if (data.task_type === "write_adr") {
    columnsContainer.style.display = "grid";
    abstainBox.style.display = "none";
    approveSection.style.display = "none";

    document.getElementById("aegis-column-title").textContent = "Proposed ADR Draft";
    document.getElementById("baseline-meta").textContent = "0 ms · 0 chars/4 estimate";
    document.getElementById("aegis-meta").textContent = "0 ms · 0 chars/4 estimate";

    renderDiff(document.getElementById("baseline-diff"), "ADR drafting does not invoke code generation.", false);
    renderDiff(document.getElementById("aegis-diff"), data.draft_adr || "No draft generated", false);
    return;
  }

  // Handle EXPLAIN ONLY
  if (data.task_type === "explain_only") {
    columnsContainer.style.display = "grid";
    abstainBox.style.display = "none";
    approveSection.style.display = "none";

    document.getElementById("aegis-column-title").textContent = "Explanation";
    document.getElementById("baseline-meta").textContent = `${data.baseline ? Math.round(data.baseline.latency_ms) : 0} ms · ${data.tokens ? data.tokens.baseline : 0} chars/4 estimate`;
    document.getElementById("aegis-meta").textContent = `${data.aegis ? Math.round(data.aegis.latency_ms) : 0} ms · ${data.tokens ? data.tokens.leaf : 0} chars/4 estimate`;

    renderDiff(document.getElementById("baseline-diff"), data.baseline ? (data.baseline.diff || data.baseline.text) : "No output", data.baseline && data.baseline.unparseable);
    renderDiff(document.getElementById("aegis-diff"), data.aegis ? (data.aegis.text || "No explanation") : "No output", false);
    return;
  }

  // Handle IMPLEMENT PRODUCTION / EDIT TESTS
  columnsContainer.style.display = "grid";
  abstainBox.style.display = "none";
  document.getElementById("aegis-column-title").textContent = "AegisTree — active decisions only";

  document.getElementById("baseline-meta").textContent = `${data.baseline ? Math.round(data.baseline.latency_ms) : 0} ms · ${data.tokens ? data.tokens.baseline : 0} chars/4 estimate`;
  document.getElementById("aegis-meta").textContent = `${data.aegis ? Math.round(data.aegis.latency_ms) : 0} ms · ${data.tokens ? data.tokens.leaf : 0} chars/4 estimate`;

  renderDiff(document.getElementById("baseline-diff"), data.baseline ? (data.baseline.diff || data.baseline.text) : "No output", data.baseline && data.baseline.unparseable);
  renderDiff(document.getElementById("aegis-diff"), data.aegis ? (data.aegis.diff || data.aegis.text) : "No output", data.aegis && data.aegis.unparseable);

  // Setup Approve Row
  if (data.aegis && data.aegis.code && !data.aegis.unparseable) {
    approveSection.style.display = "block";
    document.getElementById("approve-editor").value = data.aegis.code;
    document.getElementById("btn-approve").disabled = false;
  } else {
    approveSection.style.display = "none";
  }
}

function renderDiff(elem, text, isUnparseable) {
  elem.innerHTML = "";
  if (isUnparseable) {
    const badge = document.createElement("span");
    badge.className = "badge-unparseable";
    badge.textContent = "unparseable";
    elem.appendChild(badge);
    elem.appendChild(document.createTextNode("\n\n" + (text || "")));
    return;
  }

  const lines = (text || "").split("\n");
  lines.forEach(line => {
    const div = document.createElement("div");
    if (line.startsWith("+") && !line.startsWith("+++")) {
      div.className = "diff-line-add";
    } else if (line.startsWith("-") && !line.startsWith("---")) {
      div.className = "diff-line-del";
    }
    div.textContent = line || " ";
    elem.appendChild(div);
  });
}

async function approveCurrentRun() {
  if (!currentRunId) return;
  const approvedCode = document.getElementById("approve-editor").value;
  clearError();

  const btn = document.getElementById("btn-approve");
  btn.disabled = true;

  try {
    const res = await fetch("/api/approve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: currentRunId,
        approved_code: approvedCode
      })
    });

    const data = await res.json();

    if (res.status === 400) {
      showError(data.detail || "Refused: forbidden literal present.");
      btn.disabled = false;
      return;
    }

    if (res.status === 409) {
      showError("Run expired. Press Run again.");
      btn.disabled = false;
      return;
    }

    if (!res.ok) {
      showError(data.detail || "Failed to approve.");
      btn.disabled = false;
      return;
    }

    // Success
    btn.textContent = "Approved & Committed ✓";
    setTimeout(() => {
      btn.textContent = "Approve & Commit";
      btn.disabled = false;
    }, 2000);

    // Refresh memory view to show new habit
    initMemory();
  } catch (e) {
    showError("Network error: " + e.message);
    btn.disabled = false;
  }
}

async function resetDemo() {
  if (!confirm("Reset demo vault and memory back to clean state?")) return;
  try {
    const res = await fetch("/api/reset", { method: "POST" });
    if (res.ok) {
      document.getElementById("prompt-input").value = "";
      document.getElementById("baseline-diff").textContent = "Ready";
      document.getElementById("aegis-diff").textContent = "Ready";
      document.getElementById("approve-section").style.display = "none";
      document.getElementById("abstain-box").style.display = "none";
      const bb = document.getElementById("blocked-box");
      if (bb) bb.style.display = "none";
      document.getElementById("card-task-type").textContent = "—";
      document.getElementById("card-policy").textContent = "—";
      document.getElementById("card-excluded").textContent = "—";
      initMemory();
      initHealth();
    }
  } catch (e) {
    alert("Reset failed: " + e.message);
  }
}

function setLoadingState(loading) {
  const btns = document.querySelectorAll(".prompt-buttons button");
  btns.forEach(b => b.disabled = loading);
  if (loading) {
    const bb = document.getElementById("blocked-box");
    if (bb) bb.style.display = "none";
    const ab = document.getElementById("abstain-box");
    if (ab) ab.style.display = "none";
    document.getElementById("baseline-diff").textContent = "Generating baseline response...";
    document.getElementById("aegis-diff").textContent = "Compiling leaf and generating AegisTree response...";
  }
}

function showError(msg) {
  const errElem = document.getElementById("approve-error");
  errElem.textContent = msg;
  errElem.style.display = "block";
}

function clearError() {
  const errElem = document.getElementById("approve-error");
  errElem.textContent = "";
  errElem.style.display = "none";
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
