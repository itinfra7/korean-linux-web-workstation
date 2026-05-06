(function () {
  const TOAST_KEY = "workstation.toast";
  const PREPARE_LABEL_KEY = "workstation.prepare.label";
  const PREPARE_DETAIL_KEY = "workstation.prepare.detail";
  const FAILURE_MESSAGE = "미안합니다.";
  const WELCOME_MESSAGE = "환영합니다.";

  function showToast(message) {
    const root = document.getElementById("toast-root");
    if (!root || !message) {
      return;
    }
    const toast = document.createElement("div");
    toast.className = "toast";
    toast.textContent = message;
    root.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add("toast-visible"));
    window.setTimeout(() => {
      toast.classList.remove("toast-visible");
      window.setTimeout(() => toast.remove(), 220);
    }, 1800);
  }

  function consumeStoredToast() {
    const message = window.sessionStorage.getItem(TOAST_KEY);
    if (!message) {
      return;
    }
    window.sessionStorage.removeItem(TOAST_KEY);
    showToast(message);
  }

  function applyPrepareState() {
    const labelNode = document.getElementById("prepare-phase-label");
    const detailNode = document.getElementById("prepare-phase-detail");
    if (!labelNode || !detailNode) {
      return;
    }
    const storedLabel = window.sessionStorage.getItem(PREPARE_LABEL_KEY);
    const storedDetail = window.sessionStorage.getItem(PREPARE_DETAIL_KEY);
    if (storedLabel) {
      labelNode.textContent = storedLabel;
    }
    if (storedDetail) {
      detailNode.textContent = storedDetail;
    }
  }

  function clearPrepareState() {
    window.sessionStorage.removeItem(PREPARE_LABEL_KEY);
    window.sessionStorage.removeItem(PREPARE_DETAIL_KEY);
  }

  function storeWelcomeAndRedirect(payload) {
    const message = payload.message || WELCOME_MESSAGE;
    showToast(message);
    window.sessionStorage.setItem(TOAST_KEY, message);
    window.setTimeout(() => {
      window.location.assign(payload.redirect || "/workspace/prepare");
    }, 420);
  }

  async function handleLoginSubmit(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const submitButtons = Array.from(form.querySelectorAll("button"));
    submitButtons.forEach((button) => {
      button.disabled = true;
    });

    try {
      const response = await fetch("/api/login", {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
      });
      const payload = await response.json();
      if (!payload.ok) {
        showToast(FAILURE_MESSAGE);
        const passwordInput = form.querySelector('input[name="password"]');
        if (passwordInput) {
          passwordInput.value = "";
          passwordInput.focus();
        }
        return;
      }

      storeWelcomeAndRedirect(payload);
    } catch (_error) {
      showToast(FAILURE_MESSAGE);
    } finally {
      window.setTimeout(() => {
        submitButtons.forEach((button) => {
          button.disabled = false;
        });
      }, 500);
    }
  }

  async function pollWorkspaceStatus() {
    try {
      const response = await fetch("/api/workspace-status", {
        credentials: "same-origin",
        cache: "no-store",
      });
      const payload = await response.json();
      if (payload.ok && payload.status === "ready") {
        clearPrepareState();
        window.location.replace(payload.redirect || "/workspace/");
        return true;
      }
      if (!payload.ok) {
        clearPrepareState();
        showToast(payload.message || FAILURE_MESSAGE);
        window.sessionStorage.setItem(TOAST_KEY, payload.message || FAILURE_MESSAGE);
        window.setTimeout(() => {
          window.location.replace(payload.redirect || "/");
        }, 650);
        return true;
      }
    } catch (_error) {
      clearPrepareState();
      showToast(FAILURE_MESSAGE);
      window.sessionStorage.setItem(TOAST_KEY, FAILURE_MESSAGE);
      window.setTimeout(() => {
        window.location.replace("/");
      }, 650);
      return true;
    }
    return false;
  }

  function formatCountdown(totalSeconds) {
    const safe = Math.max(0, Number(totalSeconds) || 0);
    const minutes = Math.floor(safe / 60);
    const seconds = safe % 60;
    return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }

  function bootEmailLogin() {
    const openButton = document.getElementById("email-login-open");
    const overlay = document.getElementById("email-login-overlay");
    if (!openButton || !overlay) {
      return;
    }

    const closeButton = document.getElementById("email-login-close");
    const requestPanel = document.getElementById("email-login-request-panel");
    const requestForm = document.getElementById("email-login-request-form");
    const requestSubmit = document.getElementById("email-login-request-submit");
    const usernameInput = document.getElementById("email-login-id");
    const verifyPanel = document.getElementById("email-login-verify-panel");
    const verifyForm = document.getElementById("email-login-verify-form");
    const verifySubmit = document.getElementById("email-login-verify-submit");
    const codeInput = document.getElementById("email-login-code");
    const resendButton = document.getElementById("email-login-resend");
    const statusNode = document.getElementById("email-login-status");
    const expiryNode = document.getElementById("email-login-expiry");
    const resendMetaNode = document.getElementById("email-login-resend-meta");

    const state = {
      username: "",
      expiresAtMs: 0,
      cooldownUntilMs: 0,
      timerId: 0,
    };

    function stopTimer() {
      if (state.timerId) {
        window.clearInterval(state.timerId);
        state.timerId = 0;
      }
    }

    function resetState() {
      stopTimer();
      state.username = "";
      state.expiresAtMs = 0;
      state.cooldownUntilMs = 0;
      requestPanel.hidden = false;
      verifyPanel.hidden = true;
      if (requestForm) {
        requestForm.reset();
      }
      if (verifyForm) {
        verifyForm.reset();
      }
      if (statusNode) {
        statusNode.textContent = "인증 번호를 입력하십시오.";
      }
      if (expiryNode) {
        expiryNode.textContent = "남은 시간 10:00";
      }
      if (resendMetaNode) {
        resendMetaNode.textContent = "다시 보내기 가능 00:30";
      }
      if (usernameInput) {
        usernameInput.disabled = false;
      }
      if (verifySubmit) {
        verifySubmit.disabled = false;
      }
      if (resendButton) {
        resendButton.disabled = true;
      }
    }

    function closeOverlay() {
      overlay.hidden = true;
      resetState();
    }

    function openOverlay() {
      overlay.hidden = false;
      resetState();
      if (usernameInput) {
        usernameInput.focus();
      }
    }

    function updateTimerUi() {
      const now = Date.now();
      const expiresIn = Math.max(0, Math.ceil((state.expiresAtMs - now) / 1000));
      const resendIn = Math.max(0, Math.ceil((state.cooldownUntilMs - now) / 1000));

      if (expiryNode) {
        expiryNode.textContent = `남은 시간 ${formatCountdown(expiresIn)}`;
      }
      if (resendMetaNode) {
        resendMetaNode.textContent =
          resendIn > 0 ? `다시 보내기 가능 ${formatCountdown(resendIn)}` : "다시 보내기 가능";
      }
      if (resendButton) {
        resendButton.disabled = !state.username || resendIn > 0;
      }
      if (verifySubmit) {
        verifySubmit.disabled = expiresIn <= 0;
      }
      if (statusNode) {
        statusNode.textContent =
          expiresIn > 0 ? "인증 번호를 입력하십시오." : "인증 번호를 다시 요청하십시오.";
      }
      if (expiresIn <= 0 && resendIn <= 0) {
        stopTimer();
      }
    }

    function beginVerifyStep(username, expiresInSeconds, resendAvailableInSeconds) {
      state.username = String(username || "").trim();
      state.expiresAtMs = Date.now() + Math.max(0, Number(expiresInSeconds) || 0) * 1000;
      state.cooldownUntilMs = Date.now() + Math.max(0, Number(resendAvailableInSeconds) || 0) * 1000;
      requestPanel.hidden = true;
      verifyPanel.hidden = false;
      if (usernameInput) {
        usernameInput.value = state.username;
        usernameInput.disabled = true;
      }
      if (codeInput) {
        codeInput.value = "";
        codeInput.focus();
      }
      stopTimer();
      updateTimerUi();
      state.timerId = window.setInterval(updateTimerUi, 1000);
    }

    async function requestEmailCode(loginId) {
      const formData = new FormData();
      formData.set("login_id", String(loginId || ""));
      const response = await fetch("/api/login/email/request", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      });
      return response.json();
    }

    openButton.addEventListener("click", openOverlay);
    closeButton.addEventListener("click", closeOverlay);

    requestForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const loginId = String(usernameInput.value || "").trim();
      if (!loginId) {
        showToast(FAILURE_MESSAGE);
        usernameInput.focus();
        return;
      }
      requestSubmit.disabled = true;
      try {
        const payload = await requestEmailCode(loginId);
        if (!payload.ok) {
          showToast(FAILURE_MESSAGE);
          usernameInput.focus();
          return;
        }
        showToast(payload.message || "인증 번호를 보냈습니다.");
        beginVerifyStep(
          payload.username || loginId,
          payload.expires_in_seconds || Number(overlay.dataset.otpTtl) || 600,
          payload.resend_available_in_seconds || Number(overlay.dataset.resendCooldown) || 30
        );
      } catch (_error) {
        showToast(FAILURE_MESSAGE);
      } finally {
        requestSubmit.disabled = false;
      }
    });

    resendButton.addEventListener("click", async () => {
      if (!state.username || resendButton.disabled) {
        return;
      }
      resendButton.disabled = true;
      try {
        const payload = await requestEmailCode(state.username);
        if (!payload.ok) {
          showToast(FAILURE_MESSAGE);
          updateTimerUi();
          return;
        }
        showToast(payload.message || "인증 번호를 보냈습니다.");
        beginVerifyStep(
          payload.username || state.username,
          payload.expires_in_seconds || Number(overlay.dataset.otpTtl) || 600,
          payload.resend_available_in_seconds || Number(overlay.dataset.resendCooldown) || 30
        );
      } catch (_error) {
        showToast(FAILURE_MESSAGE);
        updateTimerUi();
      }
    });

    verifyForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      verifySubmit.disabled = true;
      try {
        const formData = new FormData();
        formData.set("code", String(codeInput.value || ""));
        const response = await fetch("/api/login/email/verify", {
          method: "POST",
          body: formData,
          credentials: "same-origin",
        });
        const payload = await response.json();
        if (!payload.ok) {
          showToast(FAILURE_MESSAGE);
          if (codeInput) {
            codeInput.select();
            codeInput.focus();
          }
          return;
        }
        closeOverlay();
        storeWelcomeAndRedirect(payload);
      } catch (_error) {
        showToast(FAILURE_MESSAGE);
      } finally {
        verifySubmit.disabled = false;
      }
    });
  }

  function bootLoginForm() {
    const form = document.getElementById("login-form");
    if (!form) {
      return;
    }
    form.addEventListener("submit", handleLoginSubmit);
  }

  function bootPreparePage() {
    if (document.body.dataset.workspacePrepare !== "1") {
      return;
    }
    applyPrepareState();
    let stopped = false;
    const tick = async () => {
      if (stopped) {
        return;
      }
      const finished = await pollWorkspaceStatus();
      if (!finished) {
        window.setTimeout(tick, 900);
      }
    };
    tick();
  }

  function boot() {
    consumeStoredToast();
    bootLoginForm();
    bootEmailLogin();
    bootPreparePage();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
