# ClearSky

A coding assistant that runs entirely on your own machine and follows your team's
architecture decisions.

Local models don't know which patterns your team has retired. If the repository still
contains `legacy_wrap` in old jobs and tests, a local model will happily write it into new
production code. ClearSky reads your Architecture Decision Records (ADRs) into a dated
decision graph. A small local decision model (System 1) then decides, before any code is
generated, whether a request is allowed and which decisions govern it. Only then does the
local code model (System 2) get a short, governed prompt.

Built for ASYNC'26, Track 1: Sovereign AI.

## How a request flows

```
request
  │
  ▼
System 1: openJev Verdict (151M-parameter ModernBERT classifier, CPU, ~40 ms per decision)
  ├─ what kind of task is this?          (implement / explain / write an ADR / edit tests)
  ├─ which decision governs it?          (or abstain: no approved decision covers it)
  ├─ does it ask for a retired pattern?  (exact forbidden literal, or a paraphrase of one)
  └─ which function should change?       (named in the request, matched in the code, or new)
  │
  ├─ blocked / abstained ──► explained to the user; the code model never runs
  ▼
leaf prompt: active decisions, forbidden literals, learned habits, the one function to edit,
             and signatures of the helpers the decision requires (hundreds of tokens)
  │
  ▼
System 2: a local Ollama model over 127.0.0.1 (default qwen3-vl:8b-instruct)
  │
  ▼
review: the diff is checked for forbidden literals, then a person approves or edits it
  │
  ▼
apply + learn: the edited argument values a reviewer sets become habits for next time
```

Other features: chat history, PDF and screenshot input, speech-to-text (Whisper running
locally), optional web search with an offline fallback, a "no workspace" mode for plain
chat, multiple users with email sign-in codes, and shared folders, which let a remote
user's browser answer the model's file reads from their own device.

## Measured numbers

Measured on an Apple M4 (16 GB RAM), CPU only for System 1. To reproduce:
`.venv/bin/python scripts/calibrate_system1.py` and `scripts/calibrate_system1.py --retrieval`.
The evaluation prompts are in `scripts/data/`. The test split was held out while thresholds
were chosen on the dev split.

| What | Result (held-out test split) |
| :--- | :--- |
| Task routing, Verdict plus keyword fallback | 17/19 correct (keyword rules alone: 11/19) |
| Governing-decision retrieval, 4 workspaces | 22/27 correct or correctly abstained (previous overlap router: 15/27) |
| Abstentions when no decision applies | 4/4 |
| Paraphrased requests for a retired pattern, caught | 6/10, with 0/17 false blocks |
| Requests containing a forbidden literal | refused before generation (deterministic string check) |
| One Verdict decision | 38–46 ms median |
| All of System 1 for one request (all four questions) | 85–420 ms across the 11 demo scenarios (varies with load) |

Prompt size for the demo scenarios (estimated as characters ÷ 4):

| Workspace | ClearSky prompt | Repository source and docs |
| :--- | ---: | ---: |
| demo_vault | ~490 tokens | ~1,850 tokens |
| cryptography | ~370 tokens | ~2.5M tokens |
| pydantic | ~460 tokens | ~1.8M tokens |
| sqlalchemy | ~480 tokens | ~6.2M tokens |

The Diff Inspector can also run the same request through the same model **without**
ClearSky: the repository files nearest the target that fit in about 15k tokens, and no
decision graph. It shows that model output next to the governed patch. This comparison is a
real model run, made on request; it is never a pre-written example.

What these numbers don't show: 2 of 19 task decisions and 5 of 27 retrieval decisions are
still wrong, and 4 of 10 paraphrased revival requests get through the semantic check. That
is why every patch still passes a literal check and needs human approval.

## Setup

Needs macOS or Linux, git, Python 3.11+ and [Ollama](https://ollama.com).
You need internet access once, for downloads.

```bash
./scripts/setup.sh            # venv, Verdict weights, dependencies, demo repos, speech model, tests
ollama pull qwen3-vl:8b-instruct
./scripts/demo.sh             # http://127.0.0.1:8080, this machine only
./scripts/demo.sh --lan       # other devices on your network, over HTTPS (self-signed)
./scripts/demo.sh tui         # terminal interface
```

`setup.sh` fetches sqlalchemy, pydantic and cryptography at pinned commits into `repos/` and
adds the demo ADRs to each. `scripts/reset_demo.py` restores the demo vault and memory.

Sign-in codes are emailed when `CLEARSKY_SMTP_HOST`, `CLEARSKY_SMTP_PORT`,
`CLEARSKY_SMTP_USER`, `CLEARSKY_SMTP_PASSWORD` and `CLEARSKY_SMTP_FROM` are set. Otherwise
(or when offline) the code is printed in the server console.

Tests: `.venv/bin/python -m pytest tests -q`

## Demo script (3 minutes)

Pick these from **Demo scenarios** in the sidebar.

1. **Persist Token (ADR-014).** The repository still uses `legacy_wrap` in three places.
   ClearSky routes to ADR-014 and sends a prompt of about 490 tokens. The patch calls
   `aegis_seal` with `kek-2026` and `timeout_s=5.0`. Open the Diff Inspector and press
   **Run without ClearSky** to see what the same model writes from the raw repository. On
   this small vault it is often right too, because every ADR fits in its context. On the
   real repositories the source alone is millions of tokens.
2. **Edit, then approve.** Change an argument (for example `retries`) before approving.
   Then run **Rotate Token**: the leaf prompt now carries that value as a learned habit.
3. **Force Legacy.** The request asks for `legacy_wrap` and is refused before the model
   runs, citing ADR-014.
4. **PyCA RSA OAEP**, then **PyCA Force PKCS1.** The same governance applies on a real
   repository (cryptography). It picks the right function from roughly 250 Python files.
5. **Migrate Kyber.** No approved decision covers it, so ClearSky abstains and offers to draft
   an ADR instead of guessing.

## Security model

- **Network.** The server listens on 127.0.0.1 by default. `--lan` serves HTTPS only. The
  models run through Ollama on loopback. Outbound traffic happens only for:
  - web search (on by default; it can be switched off, and runs fall back offline);
  - sign-in emails, when SMTP is configured;
  - the web fonts the pages load from Google Fonts.
- **Accounts.**
  - Email one-time codes, with rate limits and expiry.
  - Session cookies.
  - An Origin check on every state-changing request.
  - One generation per user at a time.
  - Each user has their own workspace and memory graph.
- **Files.**
  - Patches are confined to the workspace root.
  - "Computer" access (reading and listing files on the host) is available only to requests
    from the host itself, never to remote users.
  - Shared folders are read-only. Files are read in the sharing user's browser, and a deny
    list keeps credential files and folders such as `.ssh` and `.env` out.
- **Code.** Nothing is written without human approval, and approved code is checked again for
  forbidden literals.

## Layout

| Path | What |
| :--- | :--- |
| `aegis/system1/` | router, retrieval, policy guard, leaf prompt (System 1) |
| `aegis/system2/` | Ollama client, prompts, tool use (System 2) |
| `aegis/mcp/` | propose/apply patch, habit learning; FastMCP server (`python -m aegis.mcp.server`) |
| `aegis/ui/` | FastAPI server, web UI, terminal UI |
| `clearsky/` | edit-target selection, sign-in, per-user memory, PDFs, speech, shared folders |
| `demo_vault/`, `repos/` | demo workspaces with ADRs |
| `scripts/` | setup, demo, calibration and evaluation |
