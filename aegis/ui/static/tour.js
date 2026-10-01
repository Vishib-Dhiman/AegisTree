/* ClearSky guided tour: a spotlight walkthrough that tells the project's story by running it.
 *
 * Each step highlights one control (everything else is dimmed and click-blocked) and shows a
 * card beside it. Live steps type a demo prompt and wait for the person to press Send, then
 * point at what ClearSky did. "Skip tour" is on every card; Esc skips too.
 * The tour never approves a patch or writes anything; it only uses actions a person could.
 * Drives the page through window.ClearSky (defined in app.js).
 */
(function () {
  "use strict";

  const DEMO_WORKSPACE = "demo_vault";
  const WAIT_HINT_MS = 90000;
  const TYPE_START_MS = 350; // lets the spotlight settle on the prompt box first
  const TYPE_CHAR_MS = 16;
  const seenKey = (user) => `clearsky_tour_seen_${user && user.id != null ? user.id : "anon"}`;
  const app = () => window.ClearSky || {};
  const $ = (sel, root = document) => root.querySelector(sel);
  const visible = (el) => !!(el && el.getClientRects().length && getComputedStyle(el).visibility !== "hidden");
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function nextRunFinished() {
    return new Promise((resolve) => {
      window.addEventListener("clearsky:run-finished", (e) => resolve(e.detail || {}), { once: true });
    });
  }

  // The tour opens a collapsed sidebar for sidebar steps, and closes it again afterwards
  let sidebarOpenedByTour = false;
  function expandSidebar() {
    const sidebar = $("#sidebar");
    if (sidebar && sidebar.classList.contains("collapsed")) {
      const btn = $("#btn-expand-sidebar");
      if (btn) { btn.click(); sidebarOpenedByTour = true; }
    }
  }
  function restoreSidebar() {
    if (!sidebarOpenedByTour) return;
    sidebarOpenedByTour = false;
    const btn = $("#btn-toggle-sidebar");
    if (btn) btn.click();
  }

  // ---------------------------------------------------------------------------------------
  // The story. Fields:
  //   chapter, title, body (HTML), target (selector or () => element; none = centered card)
  //   action: "click" waits for a click on the target instead of offering Next
  //   wait: async (tour) => resolves when the step is done (no Next button meanwhile)
  //   before / after: async hooks; skip: () => true to leave the step out
  //   fallback: () => text shown (centered) when the target can't be found
  //   typing: { target, run } types the demo prompt under the spotlight before the step is offered
  //   noBack: Back jumps over this step (live sends and waits can't be replayed)
  // ---------------------------------------------------------------------------------------
  const CHAPTERS = [
    { id: "intro", name: "What ClearSky is" },
    { id: "govern", name: "Governed code, live" },
    { id: "refuse", name: "Refusals and abstentions" },
    { id: "memory", name: "Its memory" },
    { id: "work", name: "Using it on your own work" },
    { id: "you", name: "Your account and this tour" },
  ];

  function sendStep(chapter, promptKey, title, body) {
    return {
      chapter, title, body, noBack: true,
      target: "#btn-run",
      action: "click",
      before: async (tour) => {
        await tour.ensureDemoWorkspace();
        setPrompt("");
        tour.pendingRun = nextRunFinished();
      },
      // Shown under the spotlight before the Send button is offered
      typing: {
        target: composerBox,
        run: (alive) => typePrompt((app().prompts && app().prompts()[promptKey]) || "", alive),
      },
    };
  }

  function setPrompt(text) {
    const input = $("#prompt-input");
    if (!input) return;
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.scrollTop = input.scrollHeight;
  }

  // The smallest box holding both the prompt field and the Send button
  function composerBox() {
    const input = $("#prompt-input");
    const send = $("#btn-run");
    let box = input && input.parentElement;
    while (box && send && !box.contains(send)) box = box.parentElement;
    return box || input;
  }

  // Fill the prompt box a few characters at a time, like someone typing. `alive` turns false
  // when the tour moves on or closes; the box then gets the whole prompt at once.
  async function typePrompt(text, alive) {
    const reduced = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || !text) { setPrompt(text); return; }
    await new Promise((r) => setTimeout(r, TYPE_START_MS));
    for (let i = 1; i <= text.length && alive(); i++) {
      setPrompt(text.slice(0, i));
      const ch = text[i - 1];
      const pause = ch === " " ? TYPE_CHAR_MS * 1.6 : /[,.]/.test(ch) ? TYPE_CHAR_MS * 5 : TYPE_CHAR_MS;
      await new Promise((r) => setTimeout(r, pause + Math.random() * TYPE_CHAR_MS));
    }
    setPrompt(text);
  }

  function waitStep(chapter, title, body) {
    return {
      chapter, title, body, noBack: true,
      target: () => {
        const msgs = document.querySelectorAll("#messages-stream .message-assistant");
        return msgs[msgs.length - 1] || $("#messages-stream");
      },
      wait: async (tour) => { tour.lastRun = await tour.pendingRun; },
    };
  }

  // Memory chapter: a decision's row in the drawer, and the dialog that opens when it's clicked
  const memoryItem = (list, slug) => () => $(`${list} li[data-adr-id$="${slug}"]`);
  const adrDialog = () => $("#adr-modal-backdrop .adr-modal-dialog");
  function openDrawerOnly() {
    if (app().closeAdr) app().closeAdr();
    if (app().setDrawer) app().setDrawer(true);
  }

  const inRun = (sel) => (tour) => tour.lastRun && tour.lastRun.element ? tour.lastRun.element.querySelector(sel) : null;
  const runData = (tour) => (tour.lastRun && tour.lastRun.data) || {};

  const STEPS = [
    {
      chapter: "intro",
      title: "Welcome to ClearSky",
      body: `<p>ClearSky is a coding assistant that runs entirely on this machine and follows your team's
        <b>architecture decisions</b> (ADRs): which libraries, keys and patterns are in force, and which were retired.</p>
        <p>In about three minutes you'll watch it write governed code, refuse a retired pattern, and learn from your edits.
        The tour runs real requests; it never approves or changes files for you.</p>`,
      primary: "Take the tour",
      welcome: true,
    },
    {
      chapter: "intro",
      title: "The problem it solves",
      body: `<p>Local models keep your code private, but they don't know your history. When a team retires something,
        say an old cipher, the old code usually lives on in backup jobs and tests, and the model copies it into new code.</p>
        <p>ClearSky puts a small, fast <b>decision model</b> in front of the code model, so the team's decisions are
        checked <i>before</i> anything is written.</p>`,
    },
    {
      chapter: "intro",
      target: "#btn-attach",
      title: "This is the repository you're working in",
      body: `<p>You're in <code>demo_vault</code>, a small sample repo. Its team retired <code>legacy_wrap</code>
        (ADR-003) and now seals tokens with <code>aegis_seal</code> (ADR-014). Four old modules still call
        <code>legacy_wrap</code>, which is exactly what misleads a local model.</p>`,
      before: (tour) => tour.ensureDemoWorkspace(),
    },
    {
      chapter: "intro",
      target: ".status-cluster",
      title: "Two models, both on this machine",
      body: `<p><b>System 1</b> (openJev Verdict, a 151M-parameter classifier) decides in about 40 ms what kind of
        request this is, which decision governs it, and whether it asks for something retired.</p>
        <p><b>System 2</b> is a local code model (through Ollama) that writes the code, but only after System 1 says yes.</p>`,
    },
    {
      chapter: "intro",
      target: "#policy-pill",
      title: "The policy gate is on",
      body: `<p>In a repository, every request goes through the decisions first. Switch to <b>No workspace</b> and the
        gate turns off, for ordinary chat.</p>`,
    },

    // ---- Governed generation, live ----
    sendStep("govern", "persist", "Ask it for some code",
      `<p>Here's a request, typed into the box for you, in plain words: save a user's sign-in token "the approved way". It names no function and no rule; System 1 has to work out which ones apply.</p>
       <p><b>Press Send</b> to run it.</p>`),
    waitStep("govern", "Working on this machine…",
      `<p>System 1 is choosing the task type, the governing decision and the function to edit. The local model then
       gets a prompt of a few hundred tokens instead of the whole repository.</p>
       <p class="cs-tour-muted">Writing the code takes a few seconds on a laptop.</p>`),
    {
      chapter: "govern",
      target: inRun(".thought-card"),
      before: (tour) => {
        // Open the card so its decision details are visible under the spotlight
        const card = inRun(".thought-card")(tour);
        if (card) card.classList.add("expanded");
      },
      title: "What System 1 decided",
      body: `<p>Before any code was generated, System 1 classified the request, picked <b>ADR-014</b> as the governing
        decision, and built a small prompt (see the token count), leaving out test fixtures that still use the old cipher.</p>
        <p class="cs-tour-muted">Click the card's header any time to see the details.</p>`,
      fallback: (tour) => runData(tour).status === "blocked" || runData(tour).status === "abstained"
        ? "System 1 stopped this request before generation; the next chapter shows why that happens."
        : "This run didn't produce a decision card (see the message in the chat). Continue to see the rest of the tour.",
    },
    {
      chapter: "govern",
      target: inRun(".unified-review-card"),
      title: "A patch, waiting for a person",
      body: `<p>The patch calls <code>aegis_seal</code> with the key and timeout ADR-014 requires. Nothing is written
        to disk until someone presses approve.</p>
        <p>You can edit the code first. If you change an argument (say <code>retries</code>) and approve, ClearSky
        remembers it as a <b>habit</b> for next time. The tour won't approve anything.</p>`,
      skip: (tour) => { const a = runData(tour).aegis; return !a || a.unparseable || !a.diff; },
      skipNote: "The local code model didn't return a patch this time (the chat says why: usually Ollama isn't running or the model isn't installed). System 1's decision above still happened, and refusals (next) don't need the code model at all.",
    },
    {
      chapter: "govern",
      target: "#btn-toggle-diff-mode",
      title: "Compare it with no ClearSky",
      body: `<p>The <b>Diff inspector</b> puts this patch next to the same model run <i>without</i> ClearSky: the raw
        repository files and no decision graph. Try it after the tour with <b>Run without ClearSky</b>.</p>`,
    },

    // ---- Refusal and abstention ----
    sendStep("refuse", "force_legacy", "Now ask for something retired",
      `<p>This one asks to "go back to how we wrapped tokens before the sealing change". It never says <code>legacy_wrap</code>, so a word filter wouldn't catch it. <b>Press Send.</b></p>`),
    waitStep("refuse", "Checking it against the decisions…",
      `<p>This one doesn't need the code model, so it's quick.</p>`),
    {
      chapter: "refuse",
      target: inRun(".banner-blocked"),
      title: "Refused before the model ran",
      body: `<p>System 1 recognised that "the old way of wrapping tokens" means <code>legacy_wrap</code>, which ADR-014 replaced,
        so ClearSky refused and said which decision is in force. <b>No tokens were generated</b>, and this works even with
        the code model switched off.</p>
        <p class="cs-tour-muted">The banner shows how sure System 1 was. Requests that name the old helper outright are caught by an exact check too.</p>`,
      fallback: () => "This request wasn't refused this time (see the chat). Refusals happen when a request asks for a retired pattern.",
    },
    sendStep("refuse", "kyber", "And something nobody has decided",
      `<p>"Make the vault safe against future quantum computers". There's no approved decision about that. <b>Press Send.</b></p>`),
    waitStep("refuse", "Looking for a governing decision…", `<p>One moment.</p>`),
    {
      chapter: "refuse",
      target: inRun(".banner-abstained"),
      title: "It abstains instead of guessing",
      body: `<p>No decision covers this, so ClearSky won't invent one. You can draft an ADR for it instead, and once it's
        approved, requests like this become governed.</p>`,
      fallback: () => "ClearSky answered this one differently (see the chat). It abstains when no decision covers a request.",
    },

    // ---- Memory ----
    {
      chapter: "memory",
      target: "#nav-memory",
      title: "Where the decisions live",
      body: `<p>The <b>memory graph</b> holds this repository's decisions, with dates: what's in force, what it replaced,
        and the habits learned from reviews. It's built from the ADR files in the repo, and it updates when they change.</p>`,
      before: async (tour) => { await tour.ensureDemoWorkspace(); expandSidebar(); },
      after: () => app().setDrawer && app().setDrawer(true),
    },
    // Open the retired decision, then the one that replaced it, to see how a ban comes about
    {
      chapter: "memory",
      target: memoryItem("#memory-superseded", "003-legacy-wrap"),
      action: "click",
      title: "Open the retired decision",
      body: `<p>This list holds decisions the team has <b>retired</b>. Each one is now enforced as a ban.</p>
        <p><b>Click ADR-003</b>, the old <code>legacy_wrap</code> decision, to see what it said.</p>`,
      before: () => openDrawerOnly(),
      fallback: () => "ADR-003 isn't in this repository's retired list any more (it may have been edited). Retired decisions appear in this section, and each is enforced as a ban.",
    },
    {
      chapter: "memory",
      target: adrDialog,
      title: "ADR-003: retired, so now banned",
      body: `<p>The red badge says <b>Superseded</b>. In 2024 this decision <i>required</i> <code>legacy_wrap</code>;
        the note under "Why it was superseded" says why the team moved on.</p>
        <p>Once a decision is retired, what it required moves to the <b>forbidden</b> side. That is the ban that
        refused your <code>legacy_wrap</code> request earlier.</p>`,
    },
    {
      chapter: "memory",
      target: memoryItem("#memory-in-force", "014-aegis-seal"),
      action: "click",
      title: "Now open what replaced it",
      body: `<p>These decisions are <b>in force</b> today. One of them took ADR-003's place.</p>
        <p><b>Click ADR-014</b> to see it.</p>`,
      before: () => openDrawerOnly(),
      fallback: () => "ADR-014 isn't in this repository's in-force list any more (it may have been edited). The decision that replaces a retired one appears in this section.",
    },
    {
      chapter: "memory",
      target: adrDialog,
      title: "ADR-014: the decision in force",
      body: `<p>Green badge: <b>In force</b>. Its text says it supersedes ADR-003. It <i>requires</i>
        <code>aegis_seal</code> and <i>forbids</i> <code>legacy_wrap</code>.</p>
        <p>That one link explains both runs you saw: the required literals went into the prompt for the patch, and the
        forbidden one stopped the second request before any code was written.</p>`,
    },
    {
      chapter: "memory",
      target: ".drawer-section.kind-habit",
      title: "Habits learned from reviews",
      body: `<p>When a reviewer changes an argument before approving, the new value is stored here and handed to the
        model next time. Nobody has to write a rule for it.</p>`,
      before: () => openDrawerOnly(),
    },
    {
      chapter: "memory",
      target: "#btn-add-adr",
      title: "Add your own decisions",
      body: `<p>Write a new ADR here, or describe it and let the local model draft it. Once saved, it governs requests
        straight away.</p>`,
      after: () => app().setDrawer && app().setDrawer(false),
    },

    // ---- Your own work ----
    {
      chapter: "work",
      target: "#btn-attach",
      title: "Switch repositories, or turn governance off",
      body: `<p>Pick another repository (the demo includes real copies of cryptography, pydantic and sqlalchemy), or
        choose <b>No workspace</b> for ordinary chat. There, the <b>Tools</b> menu adds web search, read-only access to
        this computer, and <b>Share a folder</b>, which lets someone on another device let the model read files from
        their own machine.</p>`,
      before: () => app().setDrawer && app().setDrawer(false),
    },
    {
      chapter: "work",
      target: "#tools-menu",
      title: "Tools",
      body: `<p>Web search, Computer (read-only, this machine only) and Share a folder (your own device, read-only).
        Each is off until you turn it on, and every file the model reads is listed in its answer.</p>`,
      skip: () => !visible($("#tools-menu")),
    },
    {
      chapter: "work",
      target: "#btn-add-image",
      title: "Screenshots and PDFs",
      body: `<p>Attach, paste or drop images and PDFs. They're read on this machine; scanned pages go to the local
        vision model.</p>`,
    },
    {
      chapter: "work",
      target: "#btn-mic",
      title: "Talk instead of typing",
      body: `<p>Speech is transcribed by a Whisper model running here; the audio never leaves the machine.</p>`,
    },
    {
      chapter: "work",
      target: "#btn-scenarios-dropdown",
      title: "More to try",
      body: `<p>Rehearsed scenarios across all four repositories: governed patches, refusals, a habit in action, and an
        abstention. Each one switches to the right repository for you.</p>`,
      before: () => expandSidebar(),
    },

    // ---- You ----
    {
      chapter: "you",
      target: ".user-profile",
      title: "Your account",
      body: `<p>Everyone signs in with an emailed code and gets their own workspace, memory and chats. Use the pencil to
        change the name others see.</p>`,
      before: () => expandSidebar(),
    },
    {
      chapter: "you",
      target: "#btn-help-tour",
      title: "Come back any time",
      body: `<p>This button replays the tour, or jumps to one chapter.</p>`,
    },
    {
      chapter: "you",
      title: "You're set",
      body: `<p>Try a scenario from the sidebar, or describe a change in your own words. If a request breaks a
        decision, ClearSky will say which one. If no decision covers it, ClearSky will say so instead of guessing.</p>`,
      primary: "Finish",
    },
  ];

  // ---------------------------------------------------------------------------------------
  // Engine
  // ---------------------------------------------------------------------------------------
  class Tour {
    constructor(steps) {
      this.steps = steps;
      this.index = -1;
      this.active = false;
      this.lastRun = null;
      this.pendingRun = null;
      this.originalWorkspace = null;
      this.only = null; // chapter id when replaying one chapter
      this._token = 0;
      this._onKey = this._onKey.bind(this);
      this._reposition = this._reposition.bind(this);
    }

    // ---- lifecycle ----
    async start({ chapter = null } = {}) {
      if (this.active) this.end(false, true);
      this.active = true;
      this.only = chapter;
      this.lastRun = null;
      this.originalWorkspace = app().workspace ? app().workspace() : null;
      this._build();
      document.addEventListener("keydown", this._onKey, true);
      window.addEventListener("resize", this._reposition);
      window.addEventListener("scroll", this._reposition, true);
      this._follow = setInterval(this._reposition, 250);
      const first = chapter ? this.steps.findIndex((s) => s.chapter === chapter) : 0;
      await this.go(Math.max(0, first), 1);
    }

    end(finished, quiet = false) {
      if (!this.active) return;
      this.active = false;
      this._token += 1;
      clearInterval(this._follow);
      document.removeEventListener("keydown", this._onKey, true);
      window.removeEventListener("resize", this._reposition);
      window.removeEventListener("scroll", this._reposition, true);
      if (this.root) this.root.remove();
      this.root = null;
      document.documentElement.classList.remove("cs-tour-on");
      if (app().closeAdr) app().closeAdr();
      if (app().setDrawer) app().setDrawer(false);
      restoreSidebar();
      this._markSeen();
      this._restoreWorkspace();
      if (!finished && !quiet && app().toast) app().toast("Tour closed", "Replay it any time from the ? button in the top bar.");
    }

    _markSeen() {
      try { localStorage.setItem(seenKey(app().user && app().user()), "1"); } catch (e) { /* storage unavailable */ }
    }

    async ensureDemoWorkspace() {
      if (!app().workspace || app().workspace() === DEMO_WORKSPACE) return;
      try { await app().switchWorkspace(DEMO_WORKSPACE); } catch (e) { /* the steps explain what they find */ }
    }

    async _restoreWorkspace() {
      const back = this.originalWorkspace;
      if (!back || !app().workspace || app().workspace() === back) return;
      try {
        const res = await fetch("/api/workspaces");
        const data = await res.json();
        const preset = (data.presets || []).find((p) => p.name === back);
        if (preset) await app().switchWorkspace(preset.path || preset.id);
      } catch (e) { /* stay where the tour left off */ }
    }

    // ---- navigation ----
    _isLast() {
      return this.index >= this.steps.length - 1 ||
        (this.only && !this.steps.slice(this.index + 1).some((s) => s.chapter === this.only));
    }

    async go(i, dir) {
      const token = ++this._token;
      while (i >= 0 && i < this.steps.length) {
        const s = this.steps[i];
        if (this.only && s.chapter !== this.only) { i = dir > 0 ? this.steps.length : -1; break; }
        if (dir < 0 && s.noBack) { i += dir; continue; }
        break;
      }
      if (i < 0) { i = this.index; }
      if (i >= this.steps.length || (this.only && this.steps[i].chapter !== this.only)) { this.end(true); return; }
      this.index = i;
      const step = this.steps[i];

      if (step.before) {
        this._render(step, { busy: true, text: "One moment…" });
        try { await step.before(this); } catch (e) { console.warn("tour step setup", e); }
        if (token !== this._token) return;
      }
      if (step.skip && step.skip(this)) {
        if (step.skipNote) {
          this._render({ ...step, target: null, title: step.title, body: `<p>${esc(step.skipNote)}</p>` }, {});
          return;
        }
        return this.go(i + dir, dir);
      }

      let el = this._resolve(step.target);
      if (step.target && !el) {
        // Give late-rendering targets up to 4 s (drawers animate, lists re-fetch, cards render after a run)
        for (let t = 0; t < 40 && !el && token === this._token; t++) {
          await new Promise((r) => setTimeout(r, 100));
          el = this._resolve(step.target);
        }
        if (token !== this._token) return;
      }
      if (step.target && !el) {
        const why = step.fallback ? step.fallback(this) : null;
        if (!why) return this.go(i + dir, dir);
        this._render({ ...step, target: null, body: `<p>${esc(why)}</p>` }, {});
        return;
      }

      // On narrow screens an open sidebar covers the page: close it unless this step is in it
      if (sidebarOpenedByTour && window.innerWidth <= 760 && !(el && el.closest("#sidebar"))) restoreSidebar();
      if (el) el.scrollIntoView({ block: "nearest", inline: "nearest" });
      if (step.typing && el) {
        // Spotlight the prompt box while the request is typed in, then move to the target
        this._render(step, { el: this._resolve(step.typing.target) || el, waiting: true });
        await step.typing.run(() => token === this._token);
        if (token !== this._token) return;
      }
      this._render(step, { el, waiting: !!step.wait, action: step.action });

      this.currentStep = step;
      if (step.action === "click" && el) this._armClick(el, token);
      if (step.wait) {
        const hint = setTimeout(() => token === this._token && this._showWaitHint(), WAIT_HINT_MS);
        try { await step.wait(this); } finally { clearTimeout(hint); }
        if (token !== this._token) return;
        this.next();
      }
    }

    // Advance when the highlighted element is clicked (after the page's own handler runs)
    _armClick(el, token = this._token) {
      this._clearAction();
      const onClick = () => {
        el.removeEventListener("click", onClick, true);
        setTimeout(() => { if (token === this._token) this.next(); }, 0);
      };
      el.addEventListener("click", onClick, true);
      this._cleanupAction = () => el.removeEventListener("click", onClick, true);
    }

    next() { this._clearAction(); this.go(this.index + 1, 1); }
    back() { this._clearAction(); this.go(this.index - 1, -1); }
    _clearAction() { if (this._cleanupAction) { this._cleanupAction(); this._cleanupAction = null; } }

    _resolve(target) {
      if (!target) return null;
      const el = typeof target === "function" ? target(this) : $(target);
      return el && visible(el) ? el : null;
    }

    // ---- DOM ----
    _build() {
      const root = document.createElement("div");
      root.className = "cs-tour";
      root.innerHTML = `
        <div class="cs-tour-block" data-side="top"></div>
        <div class="cs-tour-block" data-side="bottom"></div>
        <div class="cs-tour-block" data-side="left"></div>
        <div class="cs-tour-block" data-side="right"></div>
        <div class="cs-tour-ring" aria-hidden="true"></div>
        <div class="cs-tour-card" role="dialog" aria-modal="true" aria-labelledby="cs-tour-title">
          <div class="cs-tour-top">
            <span class="cs-tour-chapter"></span>
            <button type="button" class="cs-tour-skip">Skip tour</button>
          </div>
          <h3 id="cs-tour-title" class="cs-tour-title"></h3>
          <div class="cs-tour-body" aria-live="polite"></div>
          <div class="cs-tour-foot">
            <span class="cs-tour-progress"></span>
            <div class="cs-tour-buttons">
              <button type="button" class="cs-tour-back">Back</button>
              <button type="button" class="cs-tour-next">Next</button>
            </div>
          </div>
        </div>`;
      document.body.appendChild(root);
      document.documentElement.classList.add("cs-tour-on");
      this.root = root;
      this.card = $(".cs-tour-card", root);
      this.ring = $(".cs-tour-ring", root);
      this.blocks = [...root.querySelectorAll(".cs-tour-block")];
      this._forwardScroll(this.ring);
      $(".cs-tour-skip", root).addEventListener("click", () => this.end(false));
      $(".cs-tour-back", root).addEventListener("click", () => this.back());
      $(".cs-tour-next", root).addEventListener("click", () => (this._isLast() ? this.end(true) : this.next()));
    }

    _render(step, { el = null, busy = false, waiting = false, action = null, text = "" }) {
      if (!this.root) return;
      this.currentEl = el;
      const chapterIdx = CHAPTERS.findIndex((c) => c.id === step.chapter);
      $(".cs-tour-chapter", this.root).textContent = chapterIdx >= 0 ? `${chapterIdx + 1}/${CHAPTERS.length} · ${CHAPTERS[chapterIdx].name}` : "";
      $(".cs-tour-title", this.root).textContent = step.title || "";
      $(".cs-tour-body", this.root).innerHTML = busy ? `<p class="cs-tour-muted">${esc(text)}</p>` : (step.body || "");
      // Count what a person sees: waiting steps and steps that don't apply aren't numbered
      const counted = (s) => !s.wait && !(s.skip && !s.skipNote && s.skip(this));
      const scope = (this.only ? this.steps.filter((s) => s.chapter === this.only) : this.steps).filter(counted);
      const current = this.steps[this.index];
      const pos = current.wait ? null : scope.indexOf(current) + 1;
      $(".cs-tour-progress", this.root).textContent = pos ? `Step ${pos} of ${scope.length}` : "";

      const back = $(".cs-tour-back", this.root);
      const canBack = this.steps.slice(0, this.index).some((s, i) => !s.noBack && (!this.only || s.chapter === this.only));
      back.hidden = !canBack || busy || step.welcome;
      const next = $(".cs-tour-next", this.root);
      const isLast = this._isLast();
      next.hidden = busy || waiting || action === "click";
      next.textContent = step.primary || (isLast ? "Finish" : "Next");
      this.card.classList.toggle("is-waiting", waiting || action === "click");
      $(".cs-tour-skip", this.root).textContent = step.welcome ? "Skip" : "Skip tour";

      this.root.classList.toggle("is-centered", !el);
      this.root.classList.toggle("is-interactive", action === "click");
      this._reposition();
      const focusTarget = !next.hidden ? next : $(".cs-tour-skip", this.root);
      if (focusTarget && !busy) focusTarget.focus({ preventScroll: true });
    }

    _showWaitHint() {
      if (!this.root) return;
      const body = $(".cs-tour-body", this.root);
      if ($(".cs-tour-hint", body)) return;
      const p = document.createElement("p");
      p.className = "cs-tour-hint";
      p.innerHTML = `Taking a while? The local model may be busy or off. <button type="button" class="cs-tour-link">Skip this step</button>`;
      $(".cs-tour-link", p).addEventListener("click", () => { this._token += 1; this.next(); });
      body.appendChild(p);
    }

    _reposition() {
      if (!this.root) return;
      let el = this.currentEl && document.contains(this.currentEl) ? this.currentEl : null;
      // The page re-rendered the highlighted element (e.g. a list refreshed): find it again
      if (this.currentEl && !el && this.currentStep && this.currentStep.target) {
        el = this._resolve(this.currentStep.target);
        if (el) {
          this.currentEl = el;
          if (this.currentStep.action === "click") this._armClick(el);
        }
      }
      const vw = window.innerWidth, vh = window.innerHeight;
      const card = this.card;
      if (!el) {
        this.ring.style.display = "none";
        this._setBlocks(null, vw, vh);
        card.style.left = ""; card.style.top = "";
        return;
      }
      const pad = 6;
      const r = el.getBoundingClientRect();
      const hole = {
        left: Math.max(0, r.left - pad), top: Math.max(0, r.top - pad),
        right: Math.min(vw, r.right + pad), bottom: Math.min(vh, r.bottom + pad),
      };
      Object.assign(this.ring.style, {
        display: "block",
        left: `${hole.left}px`, top: `${hole.top}px`,
        width: `${Math.max(0, hole.right - hole.left)}px`, height: `${Math.max(0, hole.bottom - hole.top)}px`,
      });
      this._setBlocks(hole, vw, vh);

      if (vw <= 640) {
        // A sheet along the bottom, or along the top when the target is in the lower half
        card.style.left = ""; card.style.top = "";
        this.root.classList.toggle("is-sheet-top", r.top + r.height / 2 > vh / 2);
        return;
      }
      const cw = card.offsetWidth, ch = card.offsetHeight, gap = 14, margin = 12;
      const options = [
        { side: "right", x: hole.right + gap, y: r.top + r.height / 2 - ch / 2, fits: vw - hole.right - gap >= cw + margin },
        { side: "left", x: hole.left - gap - cw, y: r.top + r.height / 2 - ch / 2, fits: hole.left - gap >= cw + margin },
        { side: "bottom", x: r.left + r.width / 2 - cw / 2, y: hole.bottom + gap, fits: vh - hole.bottom - gap >= ch + margin },
        { side: "top", x: r.left + r.width / 2 - cw / 2, y: hole.top - gap - ch, fits: hole.top - gap >= ch + margin },
      ];
      const pick = options.find((o) => o.fits) || { x: vw - cw - margin, y: vh - ch - margin };
      card.style.left = `${Math.round(Math.min(Math.max(margin, pick.x), vw - cw - margin))}px`;
      card.style.top = `${Math.round(Math.min(Math.max(margin, pick.y), vh - ch - margin))}px`;
    }

    // Four panels around the highlighted element block clicks everywhere else
    _setBlocks(hole, vw, vh) {
      const [top, bottom, left, right] = this.blocks;
      const set = (b, x, y, w, h) => Object.assign(b.style, { left: `${x}px`, top: `${y}px`, width: `${Math.max(0, w)}px`, height: `${Math.max(0, h)}px` });
      if (!hole) {
        set(top, 0, 0, vw, vh); set(bottom, 0, 0, 0, 0); set(left, 0, 0, 0, 0); set(right, 0, 0, 0, 0);
        top.classList.add("is-dim");
        return;
      }
      top.classList.remove("is-dim");
      set(top, 0, 0, vw, hole.top);
      set(bottom, 0, hole.bottom, vw, vh - hole.bottom);
      set(left, 0, hole.top, hole.left, hole.bottom - hole.top);
      set(right, hole.right, hole.top, vw - hole.right, hole.bottom - hole.top);
      // Only steps that ask for a click let the highlighted element through
      this.ring.classList.toggle("is-pass", this.root.classList.contains("is-interactive"));
    }

    // The ring blocks clicks on look-only steps, which would also swallow scrolling: hand
    // wheel and touch scrolls to whatever scrollable element is underneath the pointer.
    _forwardScroll(ring) {
      const scrollerAt = (x, y) => {
        ring.style.visibility = "hidden";
        let el = document.elementFromPoint(x, y);
        ring.style.visibility = "";
        while (el && el !== document.body) {
          const cs = getComputedStyle(el);
          const canY = /(auto|scroll)/.test(cs.overflowY) && el.scrollHeight > el.clientHeight;
          const canX = /(auto|scroll)/.test(cs.overflowX) && el.scrollWidth > el.clientWidth;
          if (canY || canX) return el;
          el = el.parentElement;
        }
        return document.scrollingElement;
      };
      ring.addEventListener("wheel", (e) => {
        const target = scrollerAt(e.clientX, e.clientY);
        if (!target) return;
        e.preventDefault();
        const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? target.clientHeight : 1;
        target.scrollBy({ left: e.deltaX * unit, top: e.deltaY * unit });
      }, { passive: false });
      let touch = null;
      ring.addEventListener("touchstart", (e) => {
        const t = e.touches[0];
        touch = t ? { x: t.clientX, y: t.clientY, el: scrollerAt(t.clientX, t.clientY) } : null;
      }, { passive: true });
      ring.addEventListener("touchmove", (e) => {
        const t = e.touches[0];
        if (!touch || !t || !touch.el) return;
        e.preventDefault();
        touch.el.scrollBy({ left: touch.x - t.clientX, top: touch.y - t.clientY });
        touch.x = t.clientX; touch.y = t.clientY;
      }, { passive: false });
    }

    _onKey(e) {
      if (!this.active) return;
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.end(false); return; }
      const inCard = this.card && this.card.contains(document.activeElement);
      if (e.key === "Tab" && this.card) {
        const items = [...this.card.querySelectorAll("button:not([hidden])")];
        if (!items.length) return;
        const i = items.indexOf(document.activeElement);
        e.preventDefault();
        items[(i + (e.shiftKey ? -1 : 1) + items.length) % items.length].focus();
        return;
      }
      const next = this.root && $(".cs-tour-next", this.root);
      if (e.key === "ArrowRight" && next && !next.hidden) { e.preventDefault(); next.click(); }
      if (e.key === "ArrowLeft") {
        const back = this.root && $(".cs-tour-back", this.root);
        if (back && !back.hidden) { e.preventDefault(); this.back(); }
      }
      // Keep typing in the page out of reach while the tour is up, except Enter on card buttons
      if (!inCard && e.key === "Enter") e.preventDefault();
    }
  }

  const tour = new Tour(STEPS);

  // ---- Help button menu: full tour or one chapter ----
  function initHelpButton() {
    const btn = document.getElementById("btn-help-tour");
    if (!btn || btn.dataset.ready) return;
    btn.dataset.ready = "1";
    const menu = document.createElement("div");
    menu.className = "cs-tour-menu";
    menu.hidden = true;
    menu.setAttribute("role", "menu");
    menu.innerHTML = `<button type="button" role="menuitem" data-chapter="">Full tour (about 3 minutes)</button>` +
      CHAPTERS.map((c, i) => `<button type="button" role="menuitem" data-chapter="${c.id}">${i + 1}. ${esc(c.name)}</button>`).join("");
    btn.parentNode.insertBefore(menu, btn.nextSibling);
    const close = () => { menu.hidden = true; btn.setAttribute("aria-expanded", "false"); };
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      menu.hidden = !menu.hidden;
      btn.setAttribute("aria-expanded", menu.hidden ? "false" : "true");
    });
    menu.addEventListener("click", (e) => {
      const item = e.target.closest("[data-chapter]");
      if (!item) return;
      close();
      tour.start({ chapter: item.dataset.chapter || null });
    });
    document.addEventListener("click", (e) => { if (!menu.hidden && !menu.contains(e.target)) close(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !menu.hidden) close(); });
  }

  window.ClearSkyTour = {
    start: (opts) => tour.start(opts || {}),
    end: () => tour.end(false),
    maybeAutoStart(user) {
      let seen = false;
      try { seen = localStorage.getItem(seenKey(user)) === "1"; } catch (e) { seen = false; }
      if (seen || tour.active) return;
      // Wait until nothing is running so the live steps start from a quiet page
      const begin = () => {
        if (app().isBusy && app().isBusy()) { setTimeout(begin, 1000); return; }
        tour.start({});
      };
      setTimeout(begin, 600);
    },
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initHelpButton);
  else initHelpButton();
})();
