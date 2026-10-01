# ClearSky: a local coding assistant that follows your architecture decisions
**Hackathon:** ASYNC'26
**Track:** Track 1, Sovereign AI
**Runs on:** one laptop (measured on an Apple M4, 16 GB). Models are served by Ollama over loopback, and the server binds to 127.0.0.1 by default.

---

## 1. Summary

Local code models protect your source code, but they don't know your history. When a team
retires a pattern (a weak cipher, an old key, a deprecated API), the old pattern usually
survives in backup jobs, tests and legacy modules, and a local model copies it into new
production code.

ClearSky puts a small, fast decision model in front of the code model:

1. **System 1: openJev Verdict.** A 151M-parameter ModernBERT classifier
   (`Verdict-open-jev/artifacts/v2`) that runs on the CPU at about 40 ms per decision. For
   each request it answers four questions:
   - what kind of task this is;
   - which architecture decision (ADR) governs it, or whether none does, in which case it
     abstains;
   - whether the request asks for a retired pattern, either as an exact forbidden literal or
     as a paraphrase;
   - which function in the code should change.
2. **Decision graph.** ADRs are read into a dated graph (`valid_from`, `superseded_at`). A
   superseded decision becomes forbidden literals. Edits a reviewer makes before approving
   become habits. Each user has their own graph per workspace.
3. **System 2: a local Ollama model** (default `qwen3-vl:8b-instruct`). It receives a leaf
   prompt of a few hundred tokens: the governing decisions, what is forbidden, learned
   habits, the one function to edit, and the signatures of the helpers the decision requires.
4. **Review gate.** Every patch is shown as a diff and checked again for forbidden literals.
   It is written only after a person approves it, and apply_patch keeps it inside the
   workspace. The same tools are exposed over FastMCP.

---

## 2. Architecture

```
request ─► System 1 (Verdict, CPU) ─┬─► blocked: retired pattern requested ─► explained, no generation
                                    ├─► abstained: no decision covers it  ─► offer to draft an ADR
                                    └─► ready: governing decision + target function
                                              │
                                              ▼
                                   leaf prompt (≈370–490 tokens)
                                              │
                                              ▼
                              System 2: Ollama on 127.0.0.1:11434
                                              │
                                              ▼
                     diff + forbidden-literal check ─► human approval ─► write + learn habits
```

---

## 3. Measured results

All numbers come from scripts in this repository (`scripts/calibrate_system1.py`,
`--retrieval`), on held-out prompts that were not used to choose thresholds.

| Metric | Result | Comparison |
| :--- | :--- | :--- |
| Task routing (test split) | 17/19 correct | keyword rules alone: 11/19 |
| Governing-decision retrieval, 4 workspaces (test split) | 22/27 correct or correctly abstained | previous overlap router: 15/27 |
| Abstention when no decision applies | 4/4 | |
| Paraphrased requests for a retired pattern | 6/10 caught, 0/17 false blocks | literal check alone: 4/10 |
| Requests that contain a forbidden literal | refused before any generation | deterministic string check |
| One Verdict decision | 38–46 ms median | |
| All of System 1 for one request | 85–420 ms across the 11 demo scenarios (varies with load) | |
| Leaf prompt for the demo scenarios | ≈370–490 tokens | repository source and docs: ≈1.8k (demo vault) to ≈6.2M (sqlalchemy) |

Known limits: 2/19 task and 5/27 retrieval decisions are wrong, and 4/10 paraphrased
revivals get past the semantic check. Generated code is therefore always literal-checked
and human-approved, never applied automatically.

The Diff Inspector's "without ClearSky" pane is a real run of the same model, on request,
with the repository files nearest the target (up to about 15k tokens) and no decision graph.
It is not a pre-written example.

---

## 4. Pitch script (3 minutes)

### [0:00–0:40] The problem
*"Teams that can't send code to the cloud run models locally. But a local model doesn't know
that we retired `legacy_wrap` in ADR-014. Four legacy modules in our repository still call
it, so that's what the model copies. ClearSky puts a 40-millisecond decision model in
front of the code model, so the team's decisions are enforced before any code is written."*

### [0:40–1:30] Governed generation
- Run **Persist Token (ADR-014)** in the demo vault.
- Show:
  - the task type, the governing decision and the System 1 timing;
  - the ~490-token leaf prompt;
  - the patch, which calls `aegis_seal` with `kek-2026` and `timeout_s=5.0`.
- Open the **Diff Inspector** and press **Run without ClearSky**. On this small vault the model
  often gets it right too, because the whole repository (about 1,800 tokens, ADR files included)
  fits in its context. Say so. Then make the point: on the cryptography repository, the source
  and docs are about 2.5M tokens. No local model can read the ADRs from there, but ClearSky's
  prompt stays under 500 tokens, and its refusals don't depend on the model reading anything.

### [1:30–2:10] Learning from the reviewer
- Before approving, change an argument (for example `retries`), then approve.
- Run **Rotate Token**. The leaf prompt now lists the habit `aegis_seal must set retries=…`,
  and the new patch follows it.

### [2:10–2:40] Refusal and abstention
- **Force Legacy:** refused before generation, citing ADR-014.
- **PyCA Force PKCS1** on the real cryptography repository: refused under ADR-021. This shows
  the same governance working across about 250 Python files.
- **Migrate Kyber:** no approved decision covers it, so ClearSky abstains and offers to draft
  an ADR.

### [2:40–3:00] Close
*"Everything you saw ran on this laptop. The decisions come from your own ADRs, refusals happen
before any tokens are generated, and nothing is written without a person approving it. We
publish our accuracy, including the cases where System 1 is still wrong."*

---

## 5. Commands

```bash
./scripts/setup.sh                 # one-time setup (needs internet once)
./scripts/demo.sh                  # web UI at http://127.0.0.1:8080
./scripts/demo.sh --lan            # HTTPS for other devices on your network
./scripts/demo.sh tui              # terminal UI
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/reset_demo.py
.venv/bin/python scripts/calibrate_system1.py [--retrieval]
```

See `README.md` for the security model and the project layout.
