// ClearSky sign-in: email -> 6-digit code -> session cookie -> app
(function () {
  const $ = (id) => document.getElementById(id);
  const stepEmail = $("step-email");
  const stepCode = $("step-code");
  const emailInput = $("email");
  const codeInput = $("code");
  let email = "";
  let resendTimer = null;

  function show(msgEl, text, kind) {
    msgEl.textContent = text || "";
    msgEl.className = "cs-msg" + (kind ? " " + kind : "");
  }

  async function post(url, body) {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify(body),
    });
    let data = {};
    try { data = await res.json(); } catch (e) {}
    return { res, data };
  }

  function startResendCountdown(seconds) {
    const btn = $("btn-resend");
    clearInterval(resendTimer);
    let left = seconds;
    btn.disabled = true;
    btn.textContent = `Resend in ${left}s`;
    resendTimer = setInterval(() => {
      left -= 1;
      if (left <= 0) {
        clearInterval(resendTimer);
        btn.disabled = false;
        btn.textContent = "Resend code";
      } else {
        btn.textContent = `Resend in ${left}s`;
      }
    }, 1000);
  }

  async function requestCode(msgEl) {
    const { res, data } = await post("/api/auth/request-code", { email });
    if (res.status === 429) {
      const wait = parseInt(res.headers.get("Retry-After") || "60", 10);
      show(msgEl, data.detail || "Please wait before requesting another code.", "error");
      if (wait <= 120) startResendCountdown(wait);
      return false;
    }
    if (!res.ok) {
      show(msgEl, data.detail || "Couldn't send a code. Try again.", "error");
      return false;
    }
    email = data.email || email;
    $("code-email").textContent = email;
    show($("msg-code"),
      data.delivery === "outbox"
        ? "Email isn't set up or this machine is offline, so the code went to the host's console. Ask them for it."
        : "", data.delivery === "outbox" ? "note" : "");
    startResendCountdown(60);
    return true;
  }

  stepEmail.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("msg-email");
    email = emailInput.value.trim();
    if (!email || !email.includes("@")) {
      show(msg, "Enter your email address.", "error");
      return;
    }
    const btn = $("btn-send");
    btn.disabled = true;
    show(msg, "");
    try {
      if (await requestCode(msg)) {
        stepEmail.hidden = true;
        stepCode.hidden = false;
        codeInput.value = "";
        codeInput.focus();
      }
    } catch (err) {
      show(msg, "Can't reach ClearSky. Check your connection to the host.", "error");
    } finally {
      btn.disabled = false;
    }
  });

  // Accept pasted codes like "123 456" or "Your code is 123456"
  codeInput.addEventListener("input", () => {
    const digits = codeInput.value.replace(/\D/g, "").slice(0, 6);
    codeInput.value = digits;
    if (digits.length === 6) stepCode.requestSubmit();
  });

  stepCode.addEventListener("submit", async (e) => {
    e.preventDefault();
    const msg = $("msg-code");
    const code = codeInput.value.replace(/\D/g, "");
    if (code.length !== 6) {
      show(msg, "Enter the 6-digit code.", "error");
      return;
    }
    const btn = $("btn-verify");
    btn.disabled = true;
    try {
      const { res, data } = await post("/api/auth/verify", { email, code });
      if (res.ok) {
        const next = new URLSearchParams(location.search).get("next");
        location.replace(next && next.startsWith("/") && !next.startsWith("//") ? next : "/");
        return;
      }
      show(msg, data.detail || "That code didn't work.", "error");
      codeInput.select();
    } catch (err) {
      show(msg, "Can't reach ClearSky. Check your connection to the host.", "error");
    } finally {
      btn.disabled = false;
    }
  });

  $("btn-resend").addEventListener("click", async () => {
    try { await requestCode($("msg-code")); } catch (err) {
      show($("msg-code"), "Can't reach ClearSky. Check your connection to the host.", "error");
    }
  });

  $("btn-change").addEventListener("click", () => {
    clearInterval(resendTimer);
    stepCode.hidden = true;
    stepEmail.hidden = false;
    show($("msg-code"), "");
    emailInput.focus();
  });

  // Already signed in? Go straight to the app.
  fetch("/api/auth/me", { credentials: "same-origin" })
    .then((r) => { if (r.ok) location.replace("/"); })
    .catch(() => {});
  emailInput.focus();
})();
