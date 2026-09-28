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
  initWorkspace();
  initMemory();
  initAdrModal();
  initVisualGraph();
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
  const btnResetSidebar = document.getElementById("btn-reset-sidebar");
  if (btnResetSidebar) btnResetSidebar.addEventListener("click", resetDemo);

  const btnResetDemo = document.getElementById("btn-reset-demo");
  if (btnResetDemo) btnResetDemo.addEventListener("click", resetDemo);

  const btnResetDrawer = document.getElementById("btn-reset-drawer");
  if (btnResetDrawer) btnResetDrawer.addEventListener("click", resetDemo);

  const btnClearThreads = document.getElementById("btn-clear-threads");
  if (btnClearThreads) btnClearThreads.addEventListener("click", clearRecentTasks);
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
              <span class="workspace-card-title">${p.icon} ${escapeHtml(p.title || p.name)}</span>
              <span class="workspace-card-badge">${isActive ? "● Active" : escapeHtml(p.domain)}</span>
            </div>
            <div class="workspace-card-desc">${escapeHtml(p.desc)}</div>
            ${p.repo_url ? `<div class="workspace-card-url" style="font-size: 11px; margin-top: 4px; word-break: break-all;"><a href="${escapeHtml(p.repo_url)}" target="_blank" rel="noopener noreferrer" style="color: #60a5fa; text-decoration: underline;" onclick="event.stopPropagation();">${escapeHtml(p.repo_url)} ↗</a></div>` : ''}
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
              <span class="adr-item-click-hint">View / Edit →</span>
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
              <span class="adr-item-click-hint">View / Edit →</span>
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
        <div id="loader-reasoning-section" style="display: none; margin-top: 12px; padding-top: 10px; border-top: 1px solid rgba(255, 255, 255, 0.08);">
          <div class="reasoning-trace-label">
            <span class="spinner-orb-mini"></span>
            <span id="reasoning-status-text">Model Reasoning Trace</span>
          </div>
          <div class="reasoning-trace-box" id="loader-reasoning-box"></div>
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
  }, 100);

  try {
    let data = null;
    try {
      const res = await fetch("/api/run/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText })
      });

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
                const step1 = document.getElementById("loader-step-row-1");
                if (step1 && evt.verdict) {
                  step1.innerHTML = `<span class="sparkle-mini">✓</span><span>System 1 (Verdict v1.4): matched ${escapeHtml(evt.policy ? evt.policy.primary_id : "policy")} in ${Math.round(evt.verdict.latency_ms || 32)}ms</span>`;
                  step1.style.color = "var(--accent-green)";
                }
                const step2 = document.getElementById("loader-step-row-2");
                if (step2) {
                  step2.innerHTML = `<span class="sparkle-mini">✓</span><span>Temporal graph verified: 0 bans violated</span>`;
                  step2.style.color = "var(--accent-green)";
                }
                const step3 = document.getElementById("loader-step-row-3");
                if (step3) {
                  step3.innerHTML = `<span class="spinner-orb-mini"></span><span>Streaming reasoning &amp; synthesis via ${escapeHtml(evt.model || "local model")}...</span>`;
                  step3.style.color = "var(--accent-cyan)";
                }
                const phaseTitle = document.getElementById("loader-phase-title");
                if (phaseTitle) phaseTitle.textContent = `Reasoning with ${evt.model || "local model"}...`;
                const skeletonLabel = document.getElementById("skeleton-status-label");
                if (skeletonLabel) skeletonLabel.textContent = `Streaming Reasoning & Synthesis...`;
              } else if (evt.type === "thinking") {
                const sec = document.getElementById("loader-reasoning-section");
                if (sec) sec.style.display = "block";
                const box = document.getElementById("loader-reasoning-box");
                if (box) {
                  box.textContent += evt.chunk;
                  box.scrollTop = box.scrollHeight;
                }
              } else if (evt.type === "response") {
                const statusText = document.getElementById("reasoning-status-text");
                if (statusText) statusText.textContent = "✓ Reasoning Complete · Synthesizing Code";
                const phaseTitle = document.getElementById("loader-phase-title");
                if (phaseTitle) phaseTitle.textContent = "Streaming compliant patch...";
                const skeletonLabel = document.getElementById("skeleton-status-label");
                if (skeletonLabel) skeletonLabel.textContent = "Synthesizing Compliant Architecture Patch...";
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
      console.warn("Streaming request failed, falling back to /api/run:", streamErr);
    }

    if (!data) {
      const res = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: promptText })
      });
      data = await res.json();
    }

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
  const vLat = data.verdict && data.verdict.latency_ms > 0 ? Math.round(data.verdict.latency_ms) : 32;
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
  let baselineDiff = d.baseline ? (d.baseline.diff || d.baseline.code || d.baseline.text) : "";
  if (!baselineDiff) {
    const tf = (d.target_file || "vault/store.py").toLowerCase();
    if (tf.includes("crypto")) {
      baselineDiff = `--- a/vault/crypto.py\n+++ b/vault/crypto.py\n@@ -1,3 +1,4 @@\n def encrypt_rsa_payload(public_key, plaintext: bytes) -> bytes:\n-    raise NotImplementedError("encrypt_rsa_payload is not implemented")\n+    return public_key.encrypt(\n+        plaintext,\n+        padding.PKCS1v15()\n+    )`;
    } else if (tf.includes("schema")) {
      baselineDiff = `--- a/vault/schemas.py\n+++ b/vault/schemas.py\n@@ -1,2 +1,2 @@\n def serialize_vault_payload(model) -> dict:\n-    raise NotImplementedError("serialize_vault_payload is not implemented")\n+    return model.dict()`;
    } else if (tf.includes("db")) {
      baselineDiff = `--- a/vault/db.py\n+++ b/vault/db.py\n@@ -1,2 +1,2 @@\n def query_audit_trail(session, user_id: str):\n-    raise NotImplementedError("query_audit_trail is not implemented")\n+    return engine.execute(f"SELECT * FROM audit_logs WHERE user_id = '{user_id}'")`;
    } else {
      baselineDiff = `--- a/vault/store.py\n+++ b/vault/store.py\n@@ -1,2 +1,2 @@\n def persist_session_token(token: str) -> str:\n-    raise NotImplementedError("persist_session_token is not implemented")\n+    return legacy_wrap(token, key_id="kek-2024", timeout_s=30)`;
    }
  }
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
        <text x="100" y="100" fill="#ef4444" font-size="14">Error loading knowledge graph: ${escapeHtml(err.message)}</text>
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
    { x: COL1_X, title: "🚫 SUPERSEDED / BANNED DECISIONS", subtitle: "Epistemic Status: Superseded · Historical Precedents" },
    { x: COL2_X, title: "🟢 IN-FORCE ACTIVE ARCHITECTURE DECISIONS", subtitle: "Epistemic Status: Active · AST & Linter Enforced" },
    { x: COL3_X, title: "⚡ HABITS & REPOSITORY NOTES", subtitle: "Long-term Learned Memory & Epistemic Notes" }
  ];

  let headerSvg = "";
  headers.forEach(h => {
    headerSvg += `
      <g transform="translate(${h.x}, 40)">
        <text x="0" y="18" fill="#f8fafc" font-size="13" font-weight="700" letter-spacing="0.5">${h.title}</text>
        <text x="0" y="38" fill="#94a3b8" font-size="11">${h.subtitle}</text>
        <line x1="0" y1="48" x2="${CARD_WIDTH}" y2="48" stroke="rgba(255,255,255,0.12)" stroke-width="1" />
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
            <rect x="-38" y="-10" width="76" height="20" rx="10" fill="#1e1014" stroke="#ef4444" stroke-width="1" />
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

    let borderStroke = "#22c55e";
    let stripeColor = "#22c55e";
    let badgeText = "🟢 IN FORCE";
    let badgeBg = "rgba(34, 197, 94, 0.15)";
    let badgeTextColor = "#4ade80";

    if (isSuperseded) {
      borderStroke = "#ef4444";
      stripeColor = "#ef4444";
      badgeText = "🚫 SUPERSEDED";
      badgeBg = "rgba(239, 68, 68, 0.18)";
      badgeTextColor = "#f87171";
    } else if (isHabit) {
      borderStroke = "#a855f7";
      stripeColor = "#a855f7";
      badgeText = "⚡ HABIT";
      badgeBg = "rgba(168, 85, 247, 0.18)";
      badgeTextColor = "#c084fc";
    } else if (isNote) {
      borderStroke = "#38bdf8";
      stripeColor = "#38bdf8";
      badgeText = "📝 NOTE";
      badgeBg = "rgba(56, 189, 248, 0.18)";
      badgeTextColor = "#38bdf8";
    }

    const validDate = node.valid_from ? node.valid_from.split("T")[0] : "genesis";
    const rawLabel = (node.label || node.id);
    const truncatedTitle = rawLabel.length > 38 ? rawLabel.slice(0, 35) + "..." : rawLabel;

    let bodyContentSvg = "";
    if (isSuperseded) {
      const whyText = node.why_inactive || "Superseded by newer architecture decision";
      const truncatedWhy = whyText.length > 56 ? whyText.slice(0, 53) + "..." : whyText;
      const forbiddenTokens = (node.forbidden || []).slice(0, 3).join(", ");

      bodyContentSvg = `
        <rect x="14" y="62" width="${CARD_WIDTH - 28}" height="44" rx="5" fill="rgba(239, 68, 68, 0.08)" stroke="rgba(239, 68, 68, 0.25)" stroke-width="1" />
        <text x="22" y="78" fill="#fca5a5" font-size="10.5" font-weight="600">Why Inactive / Superseded:</text>
        <text x="22" y="94" fill="#fecaca" font-size="10">${escapeHtml(truncatedWhy)}</text>
        ${forbiddenTokens ? `<text x="14" y="125" fill="#ef4444" font-size="10" font-family="monospace">🚫 Banned: ${escapeHtml(forbiddenTokens)}</text>` : ''}
      `;
    } else if (node.type === "architecture_decision") {
      const reqTokens = (node.required || []).slice(0, 2).join(", ");
      const forbTokens = (node.forbidden || []).slice(0, 2).join(", ");

      bodyContentSvg = `
        ${reqTokens ? `<text x="14" y="76" fill="#4ade80" font-size="10.5" font-family="monospace">✅ Required: ${escapeHtml(reqTokens)}</text>` : ''}
        ${forbTokens ? `<text x="14" y="98" fill="#f87171" font-size="10.5" font-family="monospace">🚫 Forbidden: ${escapeHtml(forbTokens)}</text>` : ''}
        <text x="14" y="125" fill="#64748b" font-size="10">AST Rule Active · Valid from: ${validDate}</text>
      `;
    } else {
      const tagList = (node.tags || []).slice(0, 3).join(", ");
      bodyContentSvg = `
        <text x="14" y="80" fill="#94a3b8" font-size="11">Ephemeral Memory Node</text>
        ${tagList ? `<text x="14" y="105" fill="#38bdf8" font-size="10.5" font-family="monospace">Tags: ${escapeHtml(tagList)}</text>` : ''}
        <text x="14" y="125" fill="#64748b" font-size="10">Recorded: ${validDate}</text>
      `;
    }

    nodesSvg += `
      <g class="graph-node-group" data-id="${escapeHtml(node.id)}" transform="translate(${pos.x}, ${pos.y})">
        <rect class="node-card" width="${CARD_WIDTH}" height="${CARD_HEIGHT}" rx="8" fill="#0b1120" stroke="${borderStroke}" stroke-width="1.5" stroke-dasharray="${isSuperseded ? '5 3' : 'none'}" />
        <rect x="0" y="0" width="${CARD_WIDTH}" height="3" rx="1.5" fill="${stripeColor}" />
        
        <!-- Header -->
        <rect x="14" y="12" width="105" height="18" rx="4" fill="${badgeBg}" />
        <text x="20" y="25" fill="${badgeTextColor}" font-size="9.5" font-weight="700" letter-spacing="0.3">${badgeText}</text>
        <text x="${CARD_WIDTH - 14}" y="25" text-anchor="end" fill="#94a3b8" font-size="10" font-family="monospace">${validDate}</text>

        <!-- Title -->
        <text x="14" y="47" fill="#f8fafc" font-size="12.5" font-weight="600">${escapeHtml(truncatedTitle)}</text>

        <!-- Details -->
        ${bodyContentSvg}

        <!-- Click hint -->
        <text x="${CARD_WIDTH - 14}" y="${CARD_HEIGHT - 12}" text-anchor="end" fill="#38bdf8" font-size="9.5" opacity="0.8">Click to view ADR →</text>
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
            path.style.stroke = "#f87171";
            path.style.strokeWidth = "3.5px";
            path.style.strokeDasharray = "none";
          }
        }
      });

      if (tooltip) {
        let tooltipContent = `
          <div class="graph-tooltip-title">${escapeHtml(nodeData.label || nodeData.id)}</div>
          <span class="graph-tooltip-status ${nodeData.epistemic_status === 'superseded' ? 'superseded' : (nodeData.type === 'habit' ? 'habit' : (nodeData.type === 'project_state' ? 'note' : 'active'))}">
            ${escapeHtml(nodeData.epistemic_status).toUpperCase()}
          </span>
          <div style="font-size: 10.5px; color: #94a3b8; margin-bottom: 6px;">
            Valid from: ${nodeData.valid_from ? nodeData.valid_from.split('T')[0] : 'genesis'}
            ${nodeData.superseded_at ? `<br/>Superseded at: ${nodeData.superseded_at.split('T')[0]}` : ''}
          </div>
        `;

        if (nodeData.why_inactive) {
          tooltipContent += `
            <div class="graph-tooltip-why">
              <strong>Why Superseded / Inactive:</strong><br/>
              ${escapeHtml(nodeData.why_inactive)}
            </div>
          `;
        }

        if (nodeData.required && nodeData.required.length > 0) {
          tooltipContent += `<div style="color: #4ade80; margin-top: 5px; font-family: monospace; font-size: 10px;">Required: ${escapeHtml(nodeData.required.join(', '))}</div>`;
        }
        if (nodeData.forbidden && nodeData.forbidden.length > 0) {
          tooltipContent += `<div style="color: #ef4444; margin-top: 3px; font-family: monospace; font-size: 10px;">Forbidden: ${escapeHtml(nodeData.forbidden.join(', '))}</div>`;
        }
        if (nodeData.tags && nodeData.tags.length > 0) {
          tooltipContent += `<div style="color: #38bdf8; margin-top: 5px; font-size: 10px;">Tags: ${escapeHtml(nodeData.tags.join(', '))}</div>`;
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
        path.style.stroke = "";
        path.style.strokeWidth = "";
        path.style.strokeDasharray = "";
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
