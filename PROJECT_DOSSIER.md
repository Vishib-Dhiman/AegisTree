# AegisTree — Sovereign AI Second Brain [OG Version]
**Hackathon:** ASYNC'26  
**Target Track:** Track 1 — Sovereign AI (₹25,000 Track Prize)  
**Air-Gap Guarantee:** 100% On-Premises Execution. 0 External Packets Transmitted (`trust_env=False`, loopback validation strictly enforced).

---

## 1. Executive Summary

Existing AI code assistants are **state-blind and policy-deaf**:
- They index entire repositories indiscriminately into prompt contexts (14,000+ tokens), overwhelming small local language models.
- When architecture decisions change (e.g., deprecating an insecure encryption cipher), LLMs routinely resurrect deprecated patterns because old tests and backup fixtures still contain references to legacy APIs.
- They lack a non-autoregressive decision layer, forcing full autoregressive LLM inference for every routing, safety, and scoping check.

**AegisTree** solves this by implementing a **Dual-Engine Sovereign Second Brain**:
1. **System 1 (openJev Verdict v1.4):** A non-autoregressive typed decision engine loaded directly from local ModernBERT weights (`Verdict-open-jev/artifacts/v2`). It runs in **32.2 ms** on a standard CPU with 605 MB RAM, classifying developer intent into typed tasks (`implement_production`, `edit_tests`, `explain_only`, `write_adr`).
2. **System 2 (Local Generative SLMs):** Air-gapped small language models (Qwen-2.5-Coder-3B/7B, DeepSeek-R1-7B/8B/14B, Llama-3.1-8B, or lightweight Mock Engine) communicating strictly via loopback (`127.0.0.1:11434`).
3. **Bi-Temporal Memory Graph:** A temporal DAG (`valid_from`, `deprecated_at`) that tracks architectural decisions (ADRs) and human approval habits. Deprecated decisions are automatically converted into **deterministic negative constraints** (forbidden literals) before generation occurs.
4. **Self-Contained FastMCP Gateway:** Human-in-the-loop patch review, AST syntactic verification, and closed-loop memory synthesis without relying on external host IDEs.

---

## 2. System Architecture

```
                      ┌────────────────────────────────────────┐
                      │ Developer Request / Interactive TUI    │
                      └───────────────────┬────────────────────┘
                                          │
                        ┌─────────────────▼─────────────────┐
                        │   System 1: openJev Verdict v1.4   │
                        │    (32ms CPU, ModernBERT 151M)    │
                        └─────────┬─────────────────────────┘
                                  │ Typed Route Result
         ┌────────────────────────┼────────────────────────┐
         │                        │                        │
         ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Sovereign Block  │    │  Abstention Box  │    │ Active Decision  │
│ (Banned Literal) │    │  (Out of Scope)  │    │ (Leaf Context)   │
│ 0 ms, 0 Tokens   │    │ 0 ms, 0 Tokens   │    │ ~480 Tokens      │
└──────────────────┘    └──────────────────┘    └─────────┬────────┘
                                                          │
                                         ┌────────────────▼────────────────┐
                                         │  System 2: Local Generator      │
                                         │  (Qwen 2.5 Coder / DeepSeek R1) │
                                         └────────────────┬────────────────┘
                                                          │
                                         ┌────────────────▼────────────────┐
                                         │  FastMCP Human-in-the-Loop Gate │
                                         │  - Diff Review                  │
                                         │  - Syntax & Air-Gap Validation  │
                                         └────────────────┬────────────────┘
                                                          │ User Approval
                                         ┌────────────────▼────────────────┐
                                         │  Closed-Loop Memory Synthesis   │
                                         │  (Habit Node -> Temporal Graph) │
                                         └─────────────────────────────────┘
```

---

## 3. Verified Benchmark & Performance Metrics

| Metric | Baseline (Raw Repo Context) | AegisTree [OG Version] | Improvement |
| :--- | :--- | :--- | :--- |
| **System 1 Routing Latency** | ~2,500 ms (LLM prompt) | **32.2 ms** (Verdict v1.4 CPU) | **77x faster** |
| **Context Window Payload** | 1,202 - 14,000 tokens | **489 tokens** (Leaf context) | **>60% - 96% compression** |
| **Policy Violation Defense** | 0% (Resurrects legacy code) | **100% Deterministic Refusal** | **Zero leakage** |
| **Hallucination on Unknowns** | High (Invents fake APIs) | **Calibrated Abstention** | **Zero unapproved code** |
| **Network Egress** | Unlimited / Cloud telemetry | **0 External Packets (100% Air-Gap)** | **Absolute Sovereignty** |
| **Hardware Footprint** | Cloud GPU cluster required | **Runs on single laptop CPU** | **605 MB RAM** |

---

## 4. The 3-Minute Hackathon Pitch Script (Minute-by-Minute)

### **[0:00 - 0:45] The Problem: State-Blind, Cloud-Leaking AI Assistants**
- **Presenter:** *"Judges, enterprise developers cannot paste proprietary cryptographic key vaults into cloud LLMs. But when they run local models, a critical failure occurs: local models are state-blind. In our sensitive `demo_vault`, we deprecated the old `legacy_wrap` cipher in ADR-014 and adopted `aegis_seal`. Yet because legacy backup jobs and test fixtures still contain `legacy_wrap`, standard local assistants blindly resurrect the deprecated cipher into production. Meet AegisTree: the first dual-engine sovereign second brain that brings typed, sub-40 millisecond policy governance to local AI."*

### **[0:45 - 1:30] Demonstration 1: System 1 Routing & Token Compression**
- **Action:** Open `http://127.0.0.1:8080` (or `aegis tui`). Click **"Persist token"** (`Add a persist_session_token function that stores the session token using our current vault standard.`).
- **Visuals:** 
  - System 1 routes in **46 ms** using `openJev Verdict v1.4`.
  - Excluded scopes: `test_legacy_wrap.py` (test fixture), `vault/__init__.py` (docstring).
  - Context compressed from 1,202 tokens down to 489 tokens.
  - AegisTree generates the correct, compliant patch: `aegis_seal(token, key_id="kek-2026", timeout_s=5.0, retries=3)`.
- **Presenter:** *"Notice what happened in 46 milliseconds: our non-autoregressive System 1 engine, openJev Verdict v1.4, evaluated our repository's temporal knowledge graph. It pruned the 1,200-token repository down to a 489-token leaf, stripping out test mocks and docstrings. System 2 generated the exact ADR-014 compliant call."*

### **[1:30 - 2:10] Demonstration 2: Human-in-the-Loop & Closed-Loop Memory Synthesis**
- **Action:** In the Human-in-the-Loop Review editor, edit `retries=3` to `retries=1`. Click **"Approve & Commit"**.
- **Action:** Click **"Rotate token"** (`Add a rotate_session_token function using our current vault standard.`).
- **Visuals:** 
  - The patch applies via FastMCP, recording a receipt.
  - A new habit is dynamically synthesized: `Production vault calls must set retries=1.`
  - The Rotate prompt automatically generates `retries=1` without prompt engineering.
- **Presenter:** *"Here is true second brain behavior: I modified the retries parameter from 3 to 1 before approving. AegisTree didn't just write a file—it synthesized a new organizational memory habit. When I ask to rotate tokens, it immediately remembers our preference: `retries=1`."*

### **[2:10 - 2:40] Demonstration 3: Sovereign Refusal & Calibrated Abstention**
- **Action:** Click **"Force legacy"** (`Persist the session token with legacy_wrap because it is faster.`).
- **Visuals:** 
  - **ACTION BLOCKED — SOVEREIGN REFUSAL** banner appears instantly.
  - 0 ms, 0 tokens generated.
- **Action:** Click **"Kyber"** (`Migrate the vault to CRYSTALS-Kyber.`).
- **Visuals:** 
  - **ABSTENTION — OUT OF ORGANIZATIONAL SCOPE** banner appears.
- **Presenter:** *"Now watch adversarial defense. If an attacker or junior developer asks for `legacy_wrap`, AegisTree intercepts the request before any model runs. Zero tokens are wasted. If asked to migrate to Kyber quantum encryption without an approved ADR, AegisTree refuses to hallucinate code."*

### **[2:40 - 3:00] Conclusion: Why AegisTree Wins Track 1**
- **Action:** Show the **Model Selector** dropdown, switching seamlessly between Qwen 2.5 Coder and DeepSeek-R1.
- **Presenter:** *"AegisTree is 100% sovereign, air-gapped, and runs on consumer hardware. It transforms local SLMs into enterprise-grade software engineers governed by architectural truth. Thank you."*

---

## 5. Execution Commands

### Launch Web Dashboard
```bash
./scripts/demo.sh
# Open http://127.0.0.1:8080 in your browser
```

### Launch Interactive Terminal TUI
```bash
./scripts/demo.sh tui
# or: .venv/bin/python -m aegis.ui.cli
```

### Run Full Test Suite (21 Tests)
```bash
.venv/bin/pytest tests/ -v
```

### Reset Demo Repository & Memory
```bash
.venv/bin/python scripts/reset_demo.py
```
