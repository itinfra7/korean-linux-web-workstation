(function () {
  const defaults = {
    enable_ime: "false",
    clipboard_seamless: "true",
    clipboard_up: "true",
    clipboard_down: "true",
    resize: "remote",
    enable_hidpi: "true",
    view_only: "false",
    virtual_keyboard_visible: "false",
    browser_notifications: "true",
  };
  const preparePhaseLabelKey = "workstation.prepare.label";
  const preparePhaseDetailKey = "workstation.prepare.detail";
  const publicLogoutUrl = `${window.location.origin}/`;

  const explorerState = {
    current: "",
    parent: null,
    currentDisplay: "/",
    items: [],
    selectedPath: "",
    visible: false,
  };

  const snapshotState = {
    items: [],
    selectedId: "",
    visible: false,
  };

  const terminalState = {
    visible: false,
    frameLoaded: false,
    frameReady: false,
    frameLoadPromise: null,
    resizeObserver: null,
    bridgeInstalled: false,
  };

  const taskManagerState = {
    visible: false,
    items: [],
    loading: false,
    pollTimer: 0,
    pollIntervalMs: 2500,
    sortKey: "pid",
    sortDirection: "asc",
    killingPid: 0,
    searchQuery: "",
    lastUpdatedText: "",
  };

  const notificationState = {
    enabled: false,
    eventSource: null,
    reconnectTimer: 0,
    reconnectDelayMs: 2500,
    permissionPromptArmed: false,
    permissionPromptHandler: null,
    permissionNoticeShown: false,
  };

  const chatState = {
    visible: false,
    users: [],
    activePeer: "",
    messages: [],
    hasMoreOlder: false,
    loadingConversation: false,
    loadingOlder: false,
    loadingUsers: false,
    sending: false,
    capturingScreenshot: false,
    pollTimer: 0,
    pollIntervalMs: 2500,
    usersRefreshStartedAt: 0,
    unreadTotal: 0,
    unreadLatestId: 0,
    unreadPeers: {},
    unreadPollTimer: 0,
    unreadPollIntervalMs: 2500,
    unreadReady: false,
  };

  const accountState = {
    visible: false,
    registered: false,
    registeredEmail: "",
    canRegister: true,
    canChange: false,
    pending: false,
    pendingEmailMasked: "",
    pendingExpiresInSeconds: 0,
  };

  const actionDialogState = {
    visible: false,
    busy: false,
    title: "",
    body: "",
    detail: "",
    submitLabel: "확인",
    passwordRequired: false,
    passwordLabel: "LDAP 비밀번호",
    passwordPlaceholder: "",
    passwordAutocomplete: "current-password",
    fields: [],
    progressText: "",
    onSubmit: null,
  };
  const windowSurfaceState = {
    activeId: "",
    nextZIndex: 95,
    nextAutoSurfaceId: 1,
    surfaces: new Map(),
    isDimmed: false,
  };
  const windowSurfaceSelector = ".workstation-file-window, .workstation-dialog-window";
  const terminalFrameUrl = "/workspace-terminal-frame";

  let explorerElements = null;
  let explorerDragState = null;
  let snapshotElements = null;
  let snapshotDragState = null;
  let terminalElements = null;
  let terminalDragState = null;
  let taskManagerElements = null;
  let taskManagerDragState = null;
  let chatElements = null;
  let chatDragState = null;
  let accountElements = null;
  let accountDragState = null;
  let actionDialogElements = null;
  let actionDialogDragState = null;
  let lastRichClipboardToken = "";
  let clipboardImagePasteRequest = null;
  let statusTimer = null;
  let activeUploadRequest = null;
  let forcedLogoutRedirectArmed = false;
  let audioContext = null;
  let audioSocket = null;
  let audioProcessor = null;
  let audioNode = null;
  let audioGraphReady = null;
  let audioQueue = [];
  let audioQueueOffset = 0;
  let audioQueuedSamples = 0;
  let audioReconnectTimer = null;
  let audioSampleRate = 48000;
  let audioChannels = 2;
  const audioStats = {
    transport: "idle",
    socketState: "idle",
    streamSampleRate: 48000,
    contextSampleRate: 0,
    channels: 2,
    receivedChunks: 0,
    receivedSamples: 0,
    bufferedSamples: 0,
    bufferedMs: 0,
    maxBufferedMs: 0,
    droppedSamples: 0,
    driftEvents: 0,
    resets: 0,
    reconnects: 0,
    lastMessageAt: 0,
    lastStatsAt: 0,
    lastResetReason: "initial",
  };
  Object.entries(defaults).forEach(([key, value]) => {
    if (window.localStorage.getItem(key) === null) {
      window.localStorage.setItem(key, value);
    }
  });

  const visibleWindowSurfaces = () =>
    Array.from(windowSurfaceState.surfaces.values())
      .filter((surface) => surface.panel && !surface.panel.hidden)
      .sort((left, right) => (Number(left.panel.style.zIndex || 0) - Number(right.panel.style.zIndex || 0)));

  const refreshWindowSurfaceState = () => {
    const visible = visibleWindowSurfaces();
    if (!visible.some((surface) => surface.id === windowSurfaceState.activeId)) {
      const top = visible.at(-1) || null;
      windowSurfaceState.activeId = top ? top.id : "";
    }
    windowSurfaceState.surfaces.forEach((surface) => {
      const active = !!windowSurfaceState.activeId && surface.id === windowSurfaceState.activeId && !surface.panel.hidden;
      if (windowSurfaceState.isDimmed) {
        surface.window.classList.remove("is-active-window");
        surface.window.classList.add("is-inactive-window");
        surface.window.classList.toggle("is-dimmed-window", !surface.panel.hidden);
        return;
      }
      surface.window.classList.remove("is-dimmed-window");
      surface.window.classList.toggle("is-active-window", active);
      surface.window.classList.toggle("is-inactive-window", !active);
    });
  };

  const setWindowSurfacesDimmed = (dimmed) => {
    const next = !!dimmed;
    if (windowSurfaceState.isDimmed === next) {
      return;
    }
    windowSurfaceState.isDimmed = next;
    refreshWindowSurfaceState();
  };

  const hasVisibleWindowSurfaces = () => visibleWindowSurfaces().length > 0;

  const windowSurfaceZIndex = (surface) => Number(surface?.panel?.style?.zIndex || 0);

  const activateWindowSurface = (id) => {
    const surface = windowSurfaceState.surfaces.get(id);
    if (!surface || !surface.panel || surface.panel.hidden) {
      return;
    }
    if (windowSurfaceState.isDimmed) {
      setWindowSurfacesDimmed(false);
    }
    windowSurfaceState.nextZIndex += 1;
    surface.panel.style.zIndex = String(windowSurfaceState.nextZIndex);
    windowSurfaceState.activeId = id;
    refreshWindowSurfaceState();
  };

  const ensureWindowSurfaceId = (id) => {
    const normalized = typeof id === "string" ? id.trim() : "";
    if (normalized) {
      return normalized;
    }
    const nextId = `workstation-window-surface-${String(windowSurfaceState.nextAutoSurfaceId).padStart(4, "0")}`;
    windowSurfaceState.nextAutoSurfaceId += 1;
    return nextId;
  };

  const resolveWindowSurfaceIdFromElement = (element) => {
    if (!(element instanceof Element)) {
      return "";
    }
    const surfaceNode = element.closest(windowSurfaceSelector);
    if (!(surfaceNode instanceof Element)) {
      return "";
    }
    const existingId = typeof surfaceNode.dataset?.workstationWindowSurfaceId === "string"
      ? surfaceNode.dataset.workstationWindowSurfaceId.trim()
      : "";
    if (existingId) {
      return existingId;
    }
    const surface = registerWindowSurfaceFromNode(surfaceNode);
    return surface ? surface.id : "";
  };

  const setWindowSurfaceParent = (id, parentId) => {
    const surface = windowSurfaceState.surfaces.get(id);
    if (!surface) {
      return;
    }
    const nextParentId = typeof parentId === "string" ? parentId.trim() : "";
    surface.parentId = nextParentId && nextParentId !== id ? nextParentId : "";
  };

  const childWindowSurfaces = (parentId) =>
    Array.from(windowSurfaceState.surfaces.values())
      .filter((surface) => surface.parentId === parentId && surface.panel && !surface.panel.hidden)
      .sort((left, right) => windowSurfaceZIndex(right) - windowSurfaceZIndex(left));

  const registerWindowSurface = (id, panel, windowNode, options = {}) => {
    if (!panel || !windowNode) {
      return null;
    }
    const windowId = typeof windowNode.dataset?.workstationWindowSurfaceId === "string" ? windowNode.dataset.workstationWindowSurfaceId.trim() : "";
    const panelId = typeof panel.dataset?.workstationWindowSurfaceId === "string" ? panel.dataset.workstationWindowSurfaceId.trim() : "";
    const requestedId = ensureWindowSurfaceId(id || windowId || panelId);
    const existingByWindowId = windowSurfaceState.surfaces.get(windowId);
    if (existingByWindowId && existingByWindowId.panel === panel && existingByWindowId.window === windowNode) {
      return existingByWindowId;
    }
    const existingByPanelId = windowSurfaceState.surfaces.get(panelId);
    if (existingByPanelId && existingByPanelId.panel === panel && existingByPanelId.window === windowNode) {
      return existingByPanelId;
    }
    const existingByRequestedId = windowSurfaceState.surfaces.get(requestedId);

    const surface = existingByRequestedId || existingByPanelId || existingByWindowId || {
      id: requestedId,
      panel,
      window: windowNode,
      parentId: "",
      onVisibleChange: null,
    };
    if (existingByRequestedId && (existingByRequestedId.panel !== panel || existingByRequestedId.window !== windowNode)) {
      // Keep last registration for the same requested id and detach stale references.
      // Surface IDs are best-effort stable and can be re-used after panel recreation.
      windowSurfaceState.surfaces.delete(requestedId);
    }
    [windowId, panelId].forEach((candidateId) => {
      if (candidateId && candidateId !== requestedId) {
        windowSurfaceState.surfaces.delete(candidateId);
      }
    });

    surface.id = requestedId;
    surface.panel = panel;
    surface.window = windowNode;
    if (Object.prototype.hasOwnProperty.call(options, "parentId")) {
      surface.parentId = typeof options.parentId === "string" ? options.parentId.trim() : "";
    }
    if (typeof options.onVisibleChange === "function") {
      surface.onVisibleChange = options.onVisibleChange;
    }
    windowSurfaceState.surfaces.set(requestedId, surface);
    panel.dataset.workstationWindowSurfaceId = requestedId;
    windowNode.dataset.workstationWindowSurfaceId = requestedId;
    windowNode.classList.add("workstation-window-surface", "is-inactive-window");
    refreshWindowSurfaceState();
    return surface;
  };

  const setWindowSurfaceVisible = (id, visible, meta = {}) => {
    const surface = windowSurfaceState.surfaces.get(id);
    if (!surface) {
      return;
    }
    const nextVisible = !!visible;
    if (!nextVisible) {
      childWindowSurfaces(id).forEach((childSurface) => {
        setWindowSurfaceVisible(childSurface.id, false, {
          cascaded: true,
          sourceParentId: id,
        });
      });
    }
    surface.panel.hidden = !nextVisible;
    if (typeof surface.onVisibleChange === "function") {
      surface.onVisibleChange(nextVisible, meta);
    }
    if (nextVisible) {
      activateWindowSurface(id);
      return;
    }
    refreshWindowSurfaceState();
    if (!hasVisibleWindowSurfaces()) {
      setWindowSurfacesDimmed(false);
    }
  };

  const registerWindowSurfaceFromNode = (node) => {
    if (!(node instanceof Element)) {
      return null;
    }
    const panel = node.closest("section") || node.parentElement;
    if (!panel) {
      return null;
    }
    return registerWindowSurface("", panel, node);
  };

  const installWorkspacePopupFocusHandlers = () => {
    if (!document.body) {
      return;
    }

    const handleWindowSurfacePointerdown = (event) => {
      if (!(event?.target instanceof Element)) {
        return;
      }
      const surfaceNode = event.target.closest(windowSurfaceSelector);
      if (surfaceNode instanceof Element) {
        const surfaceId = surfaceNode.dataset?.workstationWindowSurfaceId || "";
        if (surfaceId) {
          activateWindowSurface(surfaceId);
        } else {
          const surface = registerWindowSurfaceFromNode(surfaceNode);
          if (surface) {
            activateWindowSurface(surface.id);
          }
        }
        return;
      }
      if (!hasVisibleWindowSurfaces()) {
        return;
      }
      setWindowSurfacesDimmed(true);
    };

    document.removeEventListener("pointerdown", handleWindowSurfacePointerdown);
    document.addEventListener("pointerdown", handleWindowSurfacePointerdown, {
      passive: true,
    });

    const observer = new MutationObserver((records) => {
      records.forEach((record) => {
        if (!record?.addedNodes?.length) {
          return;
        }
        record.addedNodes.forEach((node) => {
          if (!(node instanceof Element)) {
            return;
          }
          if (node.matches(windowSurfaceSelector)) {
            registerWindowSurfaceFromNode(node);
            return;
          }
          node.querySelectorAll?.(windowSurfaceSelector).forEach((surfaceNode) => {
            registerWindowSurfaceFromNode(surfaceNode);
          });
        });
      });
    });
    observer.observe(document.body, { childList: true, subtree: true });

    document.querySelectorAll(windowSurfaceSelector).forEach((surfaceNode) => {
      registerWindowSurfaceFromNode(surfaceNode);
    });
  };

  const applyChrome = () => {
    document.documentElement.classList.add("workstation-kasmvnc");
    document.body.classList.add("workstation-kasmvnc");
  };

  const ensureStatusNode = () => {
    let node = document.getElementById("workstation_kasm_status");
    if (node) {
      return node;
    }
    node = document.createElement("div");
    node.id = "workstation_kasm_status";
    document.body.appendChild(node);
    return node;
  };

  const showStatus = (message) => {
    if (!message) {
      return;
    }
    const node = ensureStatusNode();
    node.textContent = message;
    node.classList.add("is-visible");
    window.clearTimeout(statusTimer);
    statusTimer = window.setTimeout(() => {
      node.classList.remove("is-visible");
    }, 2200);
  };

  const shellButton = (id) => document.getElementById(id);

  const isFullscreen = () => !!document.fullscreenElement;

  const setShellButtonSelected = (buttonOrId, selected) => {
    const button = typeof buttonOrId === "string" ? shellButton(buttonOrId) : buttonOrId;
    if (!button) {
      return;
    }
    const active = !!selected;
    button.classList.toggle("is-selected", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  };

  const setShellButtonBadge = (buttonOrId, count) => {
    const button = typeof buttonOrId === "string" ? shellButton(buttonOrId) : buttonOrId;
    if (!button) {
      return;
    }
    const normalizedCount = Math.max(0, Math.floor(Number(count || 0)));
    let badge = button.querySelector(".workstation-bar-badge");
    if (!normalizedCount) {
      if (badge) {
        badge.remove();
      }
      button.removeAttribute("data-badge-count");
      return;
    }
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "workstation-bar-badge";
      button.appendChild(badge);
    }
    badge.textContent = normalizedCount > 99 ? "99+" : String(normalizedCount);
    button.dataset.badgeCount = String(normalizedCount);
  };

  const syncFullscreenButtonState = () => {
    setShellButtonSelected("workstation_fullscreen_button", isFullscreen());
  };

  const browserNotificationSupported = () => (
    typeof window.Notification !== "undefined" && typeof window.EventSource !== "undefined"
  );

  const syncNotificationButtonState = () => {
    setShellButtonSelected("workstation_notifications_button", notificationState.enabled);
  };

  const clearNotificationReconnectTimer = () => {
    if (!notificationState.reconnectTimer) {
      return;
    }
    window.clearTimeout(notificationState.reconnectTimer);
    notificationState.reconnectTimer = 0;
  };

  const clearNotificationPermissionPrompt = () => {
    if (typeof notificationState.permissionPromptHandler === "function") {
      window.removeEventListener("pointerdown", notificationState.permissionPromptHandler, true);
      window.removeEventListener("keydown", notificationState.permissionPromptHandler, true);
    }
    notificationState.permissionPromptHandler = null;
    notificationState.permissionPromptArmed = false;
  };

  const notifyNotificationPermissionNeeded = () => {
    if (notificationState.permissionNoticeShown) {
      return;
    }
    notificationState.permissionNoticeShown = true;
    showStatus("브라우저 알림 권한이 필요합니다.");
  };

  const armNotificationPermissionPrompt = () => {
    if (!notificationState.enabled || !browserNotificationSupported()) {
      return;
    }
    if (window.Notification.permission !== "default" || notificationState.permissionPromptArmed) {
      return;
    }
    const handlePrompt = async () => {
      clearNotificationPermissionPrompt();
      try {
        const permission = await window.Notification.requestPermission();
        if (permission === "granted") {
          notificationState.permissionNoticeShown = false;
          showStatus("브라우저 알림을 허용했습니다.");
          return;
        }
      } catch (_error) {
        // Ignore prompt failures and keep the toggle state unchanged.
      }
      notifyNotificationPermissionNeeded();
    };
    notificationState.permissionPromptHandler = handlePrompt;
    notificationState.permissionPromptArmed = true;
    window.addEventListener("pointerdown", handlePrompt, { once: true, capture: true });
    window.addEventListener("keydown", handlePrompt, { once: true, capture: true });
  };

  const closeNotificationEventSource = () => {
    clearNotificationReconnectTimer();
    if (notificationState.eventSource) {
      notificationState.eventSource.close();
      notificationState.eventSource = null;
    }
  };

  const scheduleNotificationReconnect = () => {
    if (!notificationState.enabled || notificationState.reconnectTimer) {
      return;
    }
    notificationState.reconnectTimer = window.setTimeout(() => {
      notificationState.reconnectTimer = 0;
      ensureNotificationEventSource();
    }, notificationState.reconnectDelayMs);
  };

  const emitBrowserNotification = (payload) => {
    if (!notificationState.enabled || !browserNotificationSupported()) {
      return;
    }
    if (window.Notification.permission !== "granted") {
      notifyNotificationPermissionNeeded();
      armNotificationPermissionPrompt();
      return;
    }
    const appName = typeof payload?.app_name === "string" ? payload.app_name.trim() : "";
    const summary = typeof payload?.summary === "string" ? payload.summary.trim() : "";
    const body = typeof payload?.body === "string" ? payload.body.trim() : "";
    const title = summary || appName || "작업공간 알림";
    const bodyText = body || (!summary || summary === title ? appName : "");
    const tag = typeof payload?.tag === "string" && payload.tag.trim()
      ? payload.tag.trim()
      : `workstation-notification-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
    try {
      const notification = new window.Notification(title, {
        body: bodyText,
        tag,
      });
      notification.addEventListener("click", () => {
        window.focus();
        notification.close();
      });
    } catch (_error) {
      showStatus("브라우저 알림을 표시하지 못했습니다.");
    }
  };

  const handleNotificationStreamMessage = (event) => {
    if (!event?.data) {
      return;
    }
    try {
      const payload = JSON.parse(event.data);
      emitBrowserNotification(payload);
    } catch (_error) {
      // Ignore malformed bridge payloads.
    }
  };

  function ensureNotificationEventSource() {
    if (!notificationState.enabled || !browserNotificationSupported()) {
      return;
    }
    if (notificationState.eventSource) {
      const readyState = notificationState.eventSource.readyState;
      if (readyState === window.EventSource.OPEN || readyState === window.EventSource.CONNECTING) {
        return;
      }
      closeNotificationEventSource();
    }
    const source = new window.EventSource("/api/workspace/notifications/stream");
    source.addEventListener("notification", handleNotificationStreamMessage);
    source.onerror = () => {
      if (notificationState.eventSource !== source) {
        source.close();
        return;
      }
      if (!notificationState.enabled) {
        closeNotificationEventSource();
        return;
      }
      if (source.readyState === window.EventSource.CLOSED) {
        closeNotificationEventSource();
        scheduleNotificationReconnect();
      }
    };
    notificationState.eventSource = source;
    if (window.Notification.permission === "default") {
      armNotificationPermissionPrompt();
    }
  }

  const setNotificationBridgeEnabled = (enabled, { persist = true, announce = false } = {}) => {
    notificationState.enabled = !!enabled;
    if (persist) {
      window.localStorage.setItem("browser_notifications", notificationState.enabled ? "true" : "false");
    }
    syncNotificationButtonState();
    if (!notificationState.enabled) {
      clearNotificationPermissionPrompt();
      closeNotificationEventSource();
      if (announce) {
        showStatus("브라우저 알림을 껐습니다.");
      }
      return;
    }
    if (!browserNotificationSupported()) {
      if (announce) {
        showStatus("이 브라우저는 알림을 지원하지 않습니다.");
      }
      return;
    }
    ensureNotificationEventSource();
    if (announce) {
      if (window.Notification.permission === "granted") {
        showStatus("브라우저 알림을 켰습니다.");
      } else {
        notifyNotificationPermissionNeeded();
      }
    }
  };

  const postForm = async (url, fields = {}) => {
    const form = new FormData();
    Object.entries(fields).forEach(([key, value]) => {
      form.append(key, value == null ? "" : String(value));
    });
    const response = await fetch(url, {
      method: "POST",
      body: form,
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
      cache: "no-store",
    });
    if (handleUnauthorizedResponse(response)) {
      return { response, payload: { ok: false, message: "미안합니다." } };
    }
    const payload = await response.json().catch(() => ({ ok: false }));
    return { response, payload };
  };

  const forcePublicLogoutRedirect = () => {
    if (forcedLogoutRedirectArmed) {
      return;
    }
    forcedLogoutRedirectArmed = true;
    setPrepareProgress("", "");
    window.setTimeout(() => {
      try {
        submitRedirectPost("/logout");
      } catch (_error) {
        window.location.replace(publicLogoutUrl);
      }
    }, 0);
  };

  const handleUnauthorizedResponse = (response) => {
    if (!response || (response.status !== 401 && response.status !== 403)) {
      return false;
    }
    showStatus("로그아웃되었습니다.");
    forcePublicLogoutRedirect();
    return true;
  };

  const noVncDisplayCanvas = () => {
    const selectors = [
      "#noVNC_container canvas#noVNC_canvas",
      "canvas#noVNC_canvas",
      "#noVNC_screen canvas",
      "#noVNC_viewport canvas",
      "#noVNC_container canvas",
    ];
    const seen = new Set();
    const candidates = [];
    selectors.forEach((selector) => {
      document.querySelectorAll(selector).forEach((node) => {
        if (!(node instanceof HTMLCanvasElement) || seen.has(node)) {
          return;
        }
        seen.add(node);
        const rect = node.getBoundingClientRect();
        const pixelArea = Number(node.width || 0) * Number(node.height || 0);
        const visibleArea = Number(rect.width || 0) * Number(rect.height || 0);
        if (pixelArea <= 0 || visibleArea <= 0) {
          return;
        }
        candidates.push({ node, pixelArea, visibleArea });
      });
    });
    candidates.sort((left, right) => (
      right.pixelArea - left.pixelArea || right.visibleArea - left.visibleArea
    ));
    return candidates[0]?.node || null;
  };

  const captureVncScreenshotBlob = async () => {
    const sourceCanvas = noVncDisplayCanvas();
    if (!sourceCanvas) {
      throw new Error("no visible vnc canvas");
    }
    return await canvasBlob(sourceCanvas, "image/png");
  };

  const submitRedirectPost = (url, fields = {}) => {
    const form = document.createElement("form");
    form.method = "POST";
    form.action = url;
    form.style.display = "none";
    Object.entries(fields).forEach(([key, value]) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = key;
      input.value = value == null ? "" : String(value);
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
  };

  const reconnectWorkspace = (redirect) => {
    window.setTimeout(() => {
      window.location.href = redirect || "/workspace/prepare";
    }, 900);
  };

  const setPrepareProgress = (label, detail) => {
    if (label) {
      window.sessionStorage.setItem(preparePhaseLabelKey, label);
    } else {
      window.sessionStorage.removeItem(preparePhaseLabelKey);
    }
    if (detail) {
      window.sessionStorage.setItem(preparePhaseDetailKey, detail);
    } else {
      window.sessionStorage.removeItem(preparePhaseDetailKey);
    }
  };

  const autoconnect = () => {
    const button = document.getElementById("noVNC_connect_button");
    if (!button || button.dataset.workstationAutoconnected === "1") {
      return;
    }
    button.dataset.workstationAutoconnected = "1";
    window.setTimeout(() => {
      try {
        button.click();
      } catch (_error) {
      }
    }, 120);
  };

  const ensureIme = () => {
    window.localStorage.setItem("enable_ime", "false");
  };

  const audioTargetBufferedSamples = () => Math.floor(audioSampleRate * 0.05) * audioChannels;

  const audioMaxBufferedSamples = () => Math.floor(audioSampleRate * 0.12) * audioChannels;

  const audioBufferedMs = (samples) => {
    const frames = Math.max(0, Number(samples) || 0) / Math.max(audioChannels, 1);
    return Math.round((frames / Math.max(audioSampleRate, 1)) * 1000);
  };

  const setAudioBufferedSamples = (samples) => {
    const normalized = Math.max(0, Math.floor(Number(samples) || 0));
    audioStats.bufferedSamples = normalized;
    audioStats.bufferedMs = audioBufferedMs(normalized);
    audioStats.maxBufferedMs = Math.max(audioStats.maxBufferedMs, audioStats.bufferedMs);
  };

  const resetAudioBuffers = (reason) => {
    audioQueue = [];
    audioQueueOffset = 0;
    audioQueuedSamples = 0;
    setAudioBufferedSamples(0);
    audioStats.resets += 1;
    audioStats.lastResetReason = reason || "unknown";
    audioStats.lastStatsAt = performance.now();
    if (audioNode && audioNode.port) {
      try {
        audioNode.port.postMessage({ type: "reset" });
      } catch (_error) {
      }
    }
  };

  const trimFallbackAudioQueue = () => {
    const maxBufferedSamples = audioMaxBufferedSamples();
    const targetBufferedSamples = audioTargetBufferedSamples();
    if (audioQueuedSamples <= maxBufferedSamples) {
      setAudioBufferedSamples(audioQueuedSamples);
      return;
    }

    let toDrop = audioQueuedSamples - targetBufferedSamples;
    toDrop -= toDrop % Math.max(audioChannels, 1);
    let dropped = 0;
    while (toDrop > 0 && audioQueue.length) {
      const current = audioQueue[0];
      const available = current.length - audioQueueOffset;
      if (toDrop >= available) {
        dropped += available;
        toDrop -= available;
        audioQueue.shift();
        audioQueueOffset = 0;
        audioQueuedSamples = Math.max(0, audioQueuedSamples - available);
        continue;
      }
      audioQueueOffset += toDrop;
      dropped += toDrop;
      audioQueuedSamples = Math.max(0, audioQueuedSamples - toDrop);
      toDrop = 0;
      if (audioQueueOffset >= current.length) {
        audioQueue.shift();
        audioQueueOffset = 0;
      }
    }

    if (dropped > 0) {
      audioStats.droppedSamples += dropped;
      audioStats.driftEvents += 1;
    }
    setAudioBufferedSamples(audioQueuedSamples);
  };

  const handleAudioNodeMessage = (event) => {
    const payload = event.data;
    if (!payload || payload.type !== "stats") {
      return;
    }
    audioStats.transport = payload.transport || audioStats.transport;
    audioStats.droppedSamples = Math.max(0, Math.floor(Number(payload.droppedSamples) || 0));
    audioStats.driftEvents = Math.max(0, Math.floor(Number(payload.driftEvents) || 0));
    audioStats.lastStatsAt = performance.now();
    setAudioBufferedSamples(payload.bufferedSamples);
  };

  const exposeAudioStats = () => {
    window.__workstationAudioStats = {
      snapshot: () => ({
        ...audioStats,
        contextState: audioContext ? audioContext.state : "uninitialized",
        contextSampleRate: audioContext ? audioContext.sampleRate : audioStats.contextSampleRate,
        lastMessageAgeMs: audioStats.lastMessageAt ? Math.round(performance.now() - audioStats.lastMessageAt) : null,
        lastStatsAgeMs: audioStats.lastStatsAt ? Math.round(performance.now() - audioStats.lastStatsAt) : null,
      }),
      reset: () => resetAudioBuffers("manual"),
    };
  };

  const ensureAudioGraph = async () => {
    if (audioGraphReady) {
      return audioGraphReady;
    }
    audioGraphReady = (async () => {
      if (!audioContext) {
        const Context = window.AudioContext || window.webkitAudioContext;
        if (!Context) {
          throw new Error("AudioContext unavailable");
        }
        audioContext = new Context({ sampleRate: audioSampleRate, latencyHint: "interactive" });
        audioStats.contextSampleRate = audioContext.sampleRate;
      }
      if (audioNode) {
        return;
      }
      if (audioContext.audioWorklet) {
        const workletSource = `
          class WorkspacePcmPlayer extends AudioWorkletProcessor {
            constructor(options) {
              super();
              const processorOptions = options.processorOptions || {};
              this.channels = Math.max(1, processorOptions.channels || 2);
              this.streamSampleRate = Math.max(1, processorOptions.sampleRate || 48000);
              this.maxBufferedSamples = Math.floor(this.streamSampleRate * 0.12) * this.channels;
              this.targetBufferedSamples = Math.floor(this.streamSampleRate * 0.05) * this.channels;
              this.queue = [];
              this.offset = 0;
              this.bufferedSamples = 0;
              this.droppedSamples = 0;
              this.driftEvents = 0;
              this.statsTick = 0;
              this.reportStats = (force = false) => {
                this.statsTick += 1;
                if (!force && this.statsTick < 24) return;
                this.statsTick = 0;
                this.port.postMessage({
                  type: "stats",
                  transport: "worklet",
                  bufferedSamples: this.bufferedSamples,
                  droppedSamples: this.droppedSamples,
                  driftEvents: this.driftEvents,
                });
              };
              this.discardSamples = (sampleCount) => {
                let remaining = Math.max(0, Math.floor(sampleCount || 0));
                remaining -= remaining % this.channels;
                if (!remaining) return;
                while (remaining > 0 && this.queue.length) {
                  const current = this.queue[0];
                  const available = current.length - this.offset;
                  if (remaining >= available) {
                    remaining -= available;
                    this.droppedSamples += available;
                    this.bufferedSamples = Math.max(0, this.bufferedSamples - available);
                    this.queue.shift();
                    this.offset = 0;
                    continue;
                  }
                  this.offset += remaining;
                  this.droppedSamples += remaining;
                  this.bufferedSamples = Math.max(0, this.bufferedSamples - remaining);
                  remaining = 0;
                  if (this.offset >= current.length) {
                    this.queue.shift();
                    this.offset = 0;
                  }
                }
                this.reportStats(true);
              };
              this.resetQueue = () => {
                this.queue = [];
                this.offset = 0;
                this.bufferedSamples = 0;
                this.reportStats(true);
              };
              this.port.onmessage = (event) => {
                const data = event.data;
                if (!data) return;
                if (data.type === "reset") {
                  this.resetQueue();
                  return;
                }
                const buffer = data.type === "pcm" ? data.buffer : data;
                if (!buffer || !buffer.byteLength) return;
                const chunk = new Int16Array(buffer);
                if (!chunk.length) return;
                this.queue.push(chunk);
                this.bufferedSamples += chunk.length;
                if (this.bufferedSamples > this.maxBufferedSamples) {
                  this.driftEvents += 1;
                  this.discardSamples(this.bufferedSamples - this.targetBufferedSamples);
                }
                this.reportStats();
              };
            }
            process(_inputs, outputs) {
              const output = outputs[0];
              const left = output[0];
              const right = output[1] || output[0];
              for (let i = 0; i < left.length; i += 1) {
                let sampleL = 0;
                let sampleR = 0;
                while (this.queue.length && this.offset + (this.channels - 1) >= this.queue[0].length) {
                  this.queue.shift();
                  this.offset = 0;
                }
                if (this.queue.length) {
                  const current = this.queue[0];
                  sampleL = current[this.offset] / 32768;
                  sampleR = current[this.offset + 1] / 32768;
                  this.offset += this.channels;
                  this.bufferedSamples = Math.max(0, this.bufferedSamples - this.channels);
                  if (this.offset >= current.length) {
                    this.queue.shift();
                    this.offset = 0;
                  }
                }
                left[i] = sampleL;
                right[i] = sampleR;
              }
              this.reportStats();
              return true;
            }
          }
          registerProcessor("workspace-pcm-player", WorkspacePcmPlayer);
        `;
        const moduleUrl = URL.createObjectURL(new Blob([workletSource], { type: "application/javascript" }));
        try {
          await audioContext.audioWorklet.addModule(moduleUrl);
        } finally {
          URL.revokeObjectURL(moduleUrl);
        }
        audioNode = new AudioWorkletNode(audioContext, "workspace-pcm-player", {
          processorOptions: {
            channels: audioChannels,
            sampleRate: audioSampleRate,
          },
          outputChannelCount: [audioChannels],
        });
        audioNode.port.onmessage = handleAudioNodeMessage;
        audioNode.connect(audioContext.destination);
        audioStats.transport = "worklet";
        return;
      }

      audioProcessor = audioContext.createScriptProcessor(256, 0, audioChannels);
      audioStats.transport = "scriptprocessor";
      audioProcessor.onaudioprocess = (event) => {
        const left = event.outputBuffer.getChannelData(0);
        const right = event.outputBuffer.getChannelData(1) || left;
        for (let index = 0; index < left.length; index += 1) {
          if (!audioQueue.length) {
            left[index] = 0;
            right[index] = 0;
            continue;
          }
          const current = audioQueue[0];
          if (audioQueueOffset + 1 >= current.length) {
            audioQueue.shift();
            audioQueueOffset = 0;
            left[index] = 0;
            right[index] = 0;
            continue;
          }
          left[index] = current[audioQueueOffset] / 32768;
          right[index] = current[audioQueueOffset + 1] / 32768;
          audioQueueOffset += audioChannels;
          audioQueuedSamples = Math.max(0, audioQueuedSamples - audioChannels);
          if (audioQueueOffset >= current.length) {
            audioQueue.shift();
            audioQueueOffset = 0;
          }
        }
        setAudioBufferedSamples(audioQueuedSamples);
      };
      audioNode = audioProcessor;
      audioProcessor.connect(audioContext.destination);
    })();
    return audioGraphReady;
  };

  const scheduleAudioReconnect = () => {
    window.clearTimeout(audioReconnectTimer);
    audioStats.socketState = "reconnecting";
    audioStats.reconnects += 1;
    if (document.hidden) {
      return;
    }
    audioReconnectTimer = window.setTimeout(() => {
      connectAudioStream().catch(() => {
      });
    }, 350);
  };

  const enqueuePcm = (arrayBuffer) => {
    const chunk = new Int16Array(arrayBuffer);
    if (!chunk.length) {
      return;
    }
    audioStats.receivedChunks += 1;
    audioStats.receivedSamples += chunk.length;
    audioStats.lastMessageAt = performance.now();
    if (audioNode && audioNode.port) {
      const buffer = chunk.buffer.slice(0);
      audioNode.port.postMessage({ type: "pcm", buffer }, [buffer]);
      return;
    }
    audioQueue.push(chunk);
    audioQueuedSamples += chunk.length;
    trimFallbackAudioQueue();
  };

  const handleAudioMessage = (event) => {
    if (typeof event.data === "string") {
      try {
        const payload = JSON.parse(event.data);
        if (payload && payload.type === "config") {
          const nextSampleRate = Number(payload.sampleRate) || 48000;
          const nextChannels = Number(payload.channels) || 2;
          if (nextSampleRate !== audioSampleRate || nextChannels !== audioChannels) {
            audioSampleRate = nextSampleRate;
            audioChannels = nextChannels;
            resetAudioBuffers("config");
          }
          audioStats.streamSampleRate = audioSampleRate;
          audioStats.channels = audioChannels;
        }
      } catch (_error) {
      }
      return;
    }
    enqueuePcm(event.data);
  };

  const connectAudioStream = async () => {
    await ensureAudioGraph();
    if (audioSocket && (audioSocket.readyState === window.WebSocket.OPEN || audioSocket.readyState === window.WebSocket.CONNECTING)) {
      return;
    }
    resetAudioBuffers("socket-open");
    audioStats.socketState = "connecting";
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const socket = new window.WebSocket(`${proto}://${window.location.host}/api/workspace-audio-ws`);
    socket.binaryType = "arraybuffer";
    socket.onopen = () => {
      audioStats.socketState = "open";
    };
    socket.onmessage = handleAudioMessage;
    socket.onclose = () => {
      if (audioSocket === socket) {
        audioSocket = null;
      }
      audioStats.socketState = "closed";
      scheduleAudioReconnect();
    };
    socket.onerror = () => {
      audioStats.socketState = "error";
      try {
        socket.close();
      } catch (_error) {
      }
    };
    audioSocket = socket;
  };

  const resumeAudio = async () => {
    try {
      await ensureAudioGraph();
      if (audioContext && audioContext.state !== "running") {
        try {
          await audioContext.resume();
        } catch (_error) {
        }
      }
      await connectAudioStream();
    } catch (_error) {
    }
  };

  const pollRichClipboard = async () => {
    try {
      const response = await fetch("/api/clipboard/poll", {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      if (handleUnauthorizedResponse(response)) {
        return;
      }
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok || !payload.changed || !payload.token || payload.token === lastRichClipboardToken) {
        return;
      }
      lastRichClipboardToken = payload.token;
      if (payload.kind === "image" && navigator.clipboard && window.ClipboardItem && navigator.clipboard.write) {
        const imageResponse = await fetch(`/api/clipboard/item/${encodeURIComponent(payload.token)}`, {
          credentials: "same-origin",
        });
        if (handleUnauthorizedResponse(imageResponse)) {
          return;
        }
        if (!imageResponse.ok) {
          return;
        }
        const blob = await imageResponse.blob();
        await navigator.clipboard.write([new ClipboardItem({ [payload.mime || "image/png"]: blob })]);
      }
    } catch (_error) {
    }
  };

  const installClipboardPolling = () => {
    const tick = async () => {
      await pollRichClipboard();
      window.setTimeout(tick, 1800);
    };
    tick();
  };

  const canvasBlob = (canvas, mime) => new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
        return;
      }
      reject(new Error("canvas export failed"));
    }, mime);
  });

  const normalizeClipboardImage = async (blob) => {
    if (!blob) {
      throw new Error("missing image blob");
    }
    if (blob.type === "image/png") {
      return blob;
    }
    if (typeof window.createImageBitmap !== "function") {
      throw new Error("clipboard image must be png");
    }

    const bitmap = await window.createImageBitmap(blob);
    try {
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const context = canvas.getContext("2d", { alpha: true });
      if (!context) {
        throw new Error("canvas context unavailable");
      }
      context.drawImage(bitmap, 0, 0);
      return await canvasBlob(canvas, "image/png");
    } finally {
      if (typeof bitmap.close === "function") {
        bitmap.close();
      }
    }
  };

  const uploadClipboardImagePaste = async (blob) => {
    const pngBlob = await normalizeClipboardImage(blob);
    const form = new FormData();
    form.append("image", pngBlob, "clipboard-image.png");

    const response = await fetch("/api/clipboard/image-paste", {
      method: "POST",
      credentials: "same-origin",
      body: form,
    });
    const payload = await response.json().catch(() => ({ ok: false }));
    if (!response.ok || !payload.ok) {
      throw new Error(payload.message || "image paste failed");
    }
    if (payload.token) {
      lastRichClipboardToken = payload.token;
    }
  };

  const installClipboardImagePaste = () => {
    document.addEventListener("paste", (event) => {
      const items = Array.from((event.clipboardData && event.clipboardData.items) || []);
      const imageItem = items.find((item) => typeof item.type === "string" && item.type.startsWith("image/"));
      if (!imageItem || typeof imageItem.getAsFile !== "function") {
        return;
      }

      const blob = imageItem.getAsFile();
      if (!blob) {
        return;
      }

      event.preventDefault();
      event.stopPropagation();
      if (typeof event.stopImmediatePropagation === "function") {
        event.stopImmediatePropagation();
      }

      if (clipboardImagePasteRequest) {
        return;
      }

      clipboardImagePasteRequest = (async () => {
        showStatus("이미지를 붙여넣는 중입니다.");
        try {
          await uploadClipboardImagePaste(blob);
        } catch (_error) {
          showStatus("이미지 붙여넣기에 실패했습니다.");
        } finally {
          clipboardImagePasteRequest = null;
        }
      })();
    }, true);
  };

  const toggleFullscreen = async () => {
    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await document.documentElement.requestFullscreen({ navigationUI: "hide" });
      }
      syncFullscreenButtonState();
    } catch (_error) {
      showStatus("전체 화면 전환에 실패했습니다.");
    }
  };

  const formatSize = (size) => {
    if (!Number.isFinite(size) || size <= 0) {
      return "0 KB";
    }
    const units = ["B", "KB", "MB", "GB"];
    let value = size;
    let index = 0;
    while (value >= 1024 && index < units.length - 1) {
      value /= 1024;
      index += 1;
    }
    if (index === 0) {
      return `${value} ${units[index]}`;
    }
    return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[index]}`;
  };

  const formatRate = (bytesPerSecond) => {
    if (!Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) {
      return "0 B/s";
    }
    return `${formatSize(bytesPerSecond)}/s`;
  };

  const formatPercent = (value) => {
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) {
      return "0.0%";
    }
    return `${number.toFixed(number >= 10 ? 0 : 1)}%`;
  };

  const selectedItem = () => explorerState.items.find((item) => item.path === explorerState.selectedPath) || null;

  const explorerStatus = (left, right) => {
    if (!explorerElements) {
      return;
    }
    explorerElements.statusLeft.textContent = left || "";
    explorerElements.statusRight.textContent = right || "";
  };

  const explorerDisplayPath = () => explorerState.currentDisplay || "/";

  const syncExplorerVisibleState = (visible) => {
    explorerState.visible = !!visible;
    setShellButtonSelected("workstation_files_button", explorerState.visible);
  };

  const setExplorerVisible = (visible) => {
    syncExplorerVisibleState(visible);
    if (!explorerElements) {
      return;
    }
    setWindowSurfaceVisible(explorerElements.surfaceId, explorerState.visible);
  };

  const updateExplorerButtons = () => {
    if (!explorerElements) {
      return;
    }
    const item = selectedItem();
    explorerElements.up.disabled = explorerState.parent === null;
    explorerElements.download.disabled = !item || item.kind !== "file";
    explorerElements.path.value = explorerDisplayPath();
  };

  const explorerFileIconClass = (item) => {
    if (!item || item.kind === "dir") {
      return "is-dir";
    }

    const name = String(item.name || "").toLowerCase();
    const ext = name.includes(".") ? name.split(".").pop() : "";
    const imageExts = new Set(["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "avif"]);
    const documentExts = new Set([
      "txt",
      "md",
      "rtf",
      "pdf",
      "doc",
      "docx",
      "odt",
      "xls",
      "xlsx",
      "ods",
      "ppt",
      "pptx",
      "odp",
      "csv",
      "log",
      "ini",
      "conf",
      "json",
      "xml",
      "yaml",
      "yml",
      "html",
      "css",
      "js",
      "ts",
      "py",
      "sh",
    ]);

    if (imageExts.has(ext)) {
      return "is-image";
    }
    if (documentExts.has(ext)) {
      return "is-document";
    }
    return "is-file";
  };

  const renderExplorerItems = () => {
    if (!explorerElements) {
      return;
    }
    const list = explorerElements.list;
    list.innerHTML = "";

    if (!explorerState.items.length) {
      const empty = document.createElement("div");
      empty.className = "workstation-file-empty";
      empty.textContent = "이 폴더는 비어 있습니다.";
      list.appendChild(empty);
      explorerStatus(explorerDisplayPath(), "0개 항목");
      updateExplorerButtons();
      return;
    }

    explorerState.items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "workstation-file-row";
      if (item.path === explorerState.selectedPath) {
        row.classList.add("is-selected");
      }

      const name = document.createElement("div");
      name.className = "workstation-file-name";

      const icon = document.createElement("span");
      icon.className = `workstation-file-icon ${explorerFileIconClass(item)}`;
      name.appendChild(icon);

      const label = document.createElement("span");
      label.className = "workstation-file-name-text";
      label.textContent = item.name;
      name.appendChild(label);

      const size = document.createElement("div");
      size.className = "workstation-file-kind";
      size.textContent = item.kind === "dir" ? "파일 폴더" : formatSize(item.size);

      const mtime = document.createElement("div");
      mtime.className = "workstation-file-mtime";
      mtime.textContent = item.mtime || "";

      row.appendChild(name);
      row.appendChild(size);
      row.appendChild(mtime);

      row.addEventListener("click", () => {
        explorerState.selectedPath = item.path;
        renderExplorerItems();
        explorerStatus(item.kind === "dir" ? "폴더 선택됨" : "파일 선택됨", item.kind === "dir" ? "파일 폴더" : formatSize(item.size));
      });

      row.addEventListener("dblclick", () => {
        if (item.kind === "dir") {
          loadExplorer(item.path);
          return;
        }
        downloadSelected();
      });

      list.appendChild(row);
    });

    explorerStatus(explorerDisplayPath(), `${explorerState.items.length}개 항목`);
    updateExplorerButtons();
  };

  const normalizeExplorerPath = (value) => {
    if (!value || value === "/") {
      return "";
    }
    return String(value).replace(/^\/+/, "");
  };

  const loadExplorer = async (path) => {
    if (!explorerElements) {
      return;
    }
    const target = normalizeExplorerPath(path === undefined ? explorerState.current : path);
    explorerElements.list.classList.add("is-loading");
    explorerStatus("불러오는 중...", explorerElements.statusRight.textContent);
    try {
      const params = new URLSearchParams();
      if (target) {
        params.set("path", target);
      }
      const url = params.toString() ? `/api/files/list?${params}` : "/api/files/list";
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok) {
        throw new Error("file list failed");
      }
      explorerState.current = payload.current || "";
      explorerState.currentDisplay = payload.current_display || "/";
      explorerState.parent = payload.parent;
      explorerState.items = payload.items || [];
      explorerState.selectedPath = "";
      renderExplorerItems();
      setExplorerVisible(true);
    } catch (_error) {
      showStatus("탐색기를 불러오지 못했습니다.");
      explorerStatus("탐색기를 불러오지 못했습니다.", "");
    } finally {
      explorerElements.list.classList.remove("is-loading");
    }
  };

  const uploadIntoCurrent = async (fileList) => {
    const files = Array.from(fileList || []).filter(Boolean);
    if (!files.length) {
      return;
    }
    if (activeUploadRequest) {
      showStatus("업로드가 이미 진행 중입니다.");
      return;
    }
    const form = new FormData();
    form.append("path", explorerState.current || "");
    const totalBytes = files.reduce((sum, file) => sum + (Number(file.size) || 0), 0);
    files.forEach((file) => {
      form.append("files", file, file.name || "upload.bin");
    });
    explorerStatus("업로드 중...", `${formatSize(totalBytes)} · 0 B/s · 0%`);
    const startedAt = performance.now();
    const payload = await new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      activeUploadRequest = xhr;
      xhr.open("POST", "/api/files/upload", true);
      xhr.withCredentials = true;
      xhr.setRequestHeader("X-Requested-With", "fetch");
      xhr.responseType = "json";
      xhr.upload.addEventListener("progress", (event) => {
        const total = event.lengthComputable ? event.total : totalBytes;
        const loaded = event.loaded;
        const elapsed = Math.max((performance.now() - startedAt) / 1000, 0.001);
        const speed = loaded / elapsed;
        const percent = total > 0 ? Math.min(100, (loaded / total) * 100) : 0;
        explorerStatus(
          "업로드 중...",
          `${formatSize(loaded)} / ${formatSize(total)} · ${formatRate(speed)} · ${percent.toFixed(percent >= 10 ? 0 : 1)}%`,
        );
      });
      xhr.addEventListener("load", () => {
        activeUploadRequest = null;
        const responsePayload =
          xhr.response && typeof xhr.response === "object"
            ? xhr.response
            : JSON.parse(xhr.responseText || '{"ok":false}');
        if (xhr.status < 200 || xhr.status >= 300 || !responsePayload.ok) {
          reject(new Error("upload failed"));
          return;
        }
        resolve(responsePayload);
      });
      xhr.addEventListener("error", () => {
        activeUploadRequest = null;
        reject(new Error("upload failed"));
      });
      xhr.addEventListener("abort", () => {
        activeUploadRequest = null;
        reject(new Error("upload aborted"));
      });
      xhr.send(form);
    });
    await loadExplorer(explorerState.current || "");
    explorerStatus("업로드 완료", `${formatSize(totalBytes)} / ${formatSize(totalBytes)} · ${(payload.saved || []).length}개 업로드됨 · 100%`);
    showStatus("업로드를 마쳤습니다.");
  };

  const uniqueFiles = (files) => {
    const seen = new Set();
    const result = [];
    Array.from(files || []).forEach((file) => {
      if (!file || typeof file.name !== "string") {
        return;
      }
      const key = [file.name, file.size, file.type, file.lastModified].join("::");
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      result.push(file);
    });
    return result;
  };

  const extractTransferFiles = async (dataTransfer) => {
    const extracted = [];
    if (!dataTransfer) {
      return extracted;
    }

    Array.from(dataTransfer.files || []).forEach((file) => {
      if (file && typeof file.name === "string") {
        extracted.push(file);
      }
    });

    const items = Array.from(dataTransfer.items || []);
    for (const item of items) {
      if (!item || item.kind !== "file") {
        continue;
      }
      const file = item.getAsFile && item.getAsFile();
      if (file && typeof file.name === "string") {
        extracted.push(file);
      }
    }

    return uniqueFiles(extracted);
  };

  const openUploadPicker = () => {
    if (!explorerElements) {
      return;
    }
    explorerElements.uploadInput.value = "";
    if (typeof explorerElements.uploadInput.showPicker === "function") {
      explorerElements.uploadInput.showPicker();
      return;
    }
    explorerElements.uploadInput.click();
  };

  const downloadSelected = () => {
    const item = selectedItem();
    if (!item || item.kind !== "file") {
      return;
    }
    const link = document.createElement("a");
    link.href = `/api/files/download?path=${encodeURIComponent(item.path)}`;
    link.download = "";
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    link.remove();
    explorerStatus("다운로드 시작", item.name);
    showStatus("다운로드를 시작했습니다.");
  };

  const beginExplorerDrag = (event) => {
    if (!explorerElements || event.target.closest("button, input")) {
      return;
    }
    activateWindowSurface(explorerElements.surfaceId);
    const rect = explorerElements.window.getBoundingClientRect();
    explorerDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    explorerElements.window.style.left = `${rect.left}px`;
    explorerElements.window.style.top = `${rect.top}px`;
    explorerElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragExplorerWindow);
    document.addEventListener("pointerup", endExplorerDrag);
  };

  const dragExplorerWindow = (event) => {
    if (!explorerDragState || !explorerElements) {
      return;
    }
    const nextLeft = Math.max(12, Math.min(window.innerWidth - 300, event.clientX - explorerDragState.offsetX));
    const nextTop = Math.max(54, Math.min(window.innerHeight - 180, event.clientY - explorerDragState.offsetY));
    explorerElements.window.style.left = `${nextLeft}px`;
    explorerElements.window.style.top = `${nextTop}px`;
  };

  const endExplorerDrag = () => {
    explorerDragState = null;
    document.removeEventListener("pointermove", dragExplorerWindow);
    document.removeEventListener("pointerup", endExplorerDrag);
  };

  const ensureExplorerShell = () => {
    if (explorerElements) {
      return explorerElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_file_panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-file-window" role="dialog" aria-modal="false" aria-label="파일 전송">
        <div class="workstation-file-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon" aria-hidden="true"></span>
            <span>파일 전송</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-file-toolbar">
          <button type="button" class="workstation-file-btn" data-action="up">위로</button>
          <button type="button" class="workstation-file-btn" data-action="refresh">새로고침</button>
          <button type="button" class="workstation-file-btn" data-action="upload">업로드</button>
          <button type="button" class="workstation-file-btn" data-action="download">다운로드</button>
          <div class="workstation-file-address">
            <label for="workstation_file_path">주소</label>
            <input id="workstation_file_path" type="text" autocomplete="off" spellcheck="false">
          </div>
        </div>
        <div class="workstation-file-body">
          <aside class="workstation-file-sidebar">
            <h3>파일 전송</h3>
            <p>업로드 버튼을 누르거나 오른쪽 파일 목록 영역에 파일을 끌어 놓아 현재 폴더에 넣을 수 있습니다.</p>
            <input class="workstation-file-upload-input" id="workstation_file_upload_input" type="file" multiple aria-hidden="true" tabindex="-1">
          </aside>
          <div class="workstation-file-main">
            <div class="workstation-file-header">
              <div>이름</div>
              <div>종류</div>
              <div>수정한 날짜</div>
            </div>
            <div class="workstation-file-list"></div>
          </div>
        </div>
        <div class="workstation-file-statusbar">
          <div class="workstation-file-pane workstation-file-status-left"></div>
          <div class="workstation-file-pane workstation-file-status-right"></div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-file-window");
    const titlebar = panel.querySelector(".workstation-file-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const upButton = panel.querySelector('[data-action="up"]');
    const refreshButton = panel.querySelector('[data-action="refresh"]');
    const uploadButton = panel.querySelector('[data-action="upload"]');
    const downloadButton = panel.querySelector('[data-action="download"]');
    const pathInput = panel.querySelector("#workstation_file_path");
    const list = panel.querySelector(".workstation-file-list");
    const uploadInput = panel.querySelector("#workstation_file_upload_input");
    const statusLeft = panel.querySelector(".workstation-file-status-left");
    const statusRight = panel.querySelector(".workstation-file-status-right");

    closeButton.addEventListener("click", () => setExplorerVisible(false));
    upButton.addEventListener("click", () => {
      if (explorerState.parent !== null) {
        loadExplorer(explorerState.parent || "");
      }
    });
    refreshButton.addEventListener("click", () => loadExplorer(explorerState.current || ""));
    uploadButton.addEventListener("click", () => {
      openUploadPicker();
    });
    uploadInput.addEventListener("change", async () => {
      try {
        const files = uniqueFiles(uploadInput.files || []);
        uploadInput.value = "";
        if (!files.length) {
          return;
        }
        await uploadIntoCurrent(files);
      } catch (_error) {
        showStatus("업로드에 실패했습니다.");
        explorerStatus("업로드에 실패했습니다.", "");
      }
    });
    downloadButton.addEventListener("click", () => downloadSelected());

    pathInput.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") {
        return;
      }
      event.preventDefault();
      loadExplorer(pathInput.value);
    });

    const activateDrop = (event) => {
      event.preventDefault();
      event.stopPropagation();
      list.classList.add("is-drop-active");
    };
    const clearDrop = () => {
      list.classList.remove("is-drop-active");
    };
    const handleDrop = async (event) => {
      event.preventDefault();
      event.stopPropagation();
      clearDrop();
      try {
        const files = await extractTransferFiles(event.dataTransfer);
        if (!files.length) {
          showStatus("업로드할 파일을 찾지 못했습니다.");
          explorerStatus("업로드할 파일을 찾지 못했습니다.", "");
          return;
        }
        await uploadIntoCurrent(files);
      } catch (_error) {
        showStatus("업로드에 실패했습니다.");
        explorerStatus("업로드에 실패했습니다.", "");
      }
    };

    ["dragenter", "dragover"].forEach((type) => {
      list.addEventListener(type, activateDrop);
    });
    ["dragleave", "dragend"].forEach((type) => {
      list.addEventListener(type, clearDrop);
    });
    list.addEventListener("drop", handleDrop);

    titlebar.addEventListener("pointerdown", beginExplorerDrag);
    registerWindowSurface("explorer", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncExplorerVisibleState(visible);
      },
    });

    explorerElements = {
      surfaceId: "explorer",
      panel,
      window: windowNode,
      list,
      path: pathInput,
      up: upButton,
      refresh: refreshButton,
      upload: uploadButton,
      uploadInput,
      download: downloadButton,
      statusLeft,
      statusRight,
    };
    return explorerElements;
  };

  const terminalStatus = (left, right) => {
    if (!terminalElements) {
      return;
    }
    terminalElements.statusLeft.textContent = left || "";
    terminalElements.statusRight.textContent = right || "";
  };

  const postTerminalFrameMessage = (type, payload = {}) => {
    const frameWindow = terminalElements?.frame?.contentWindow;
    if (!frameWindow) {
      return false;
    }
    frameWindow.postMessage(
      {
        source: "workstation-parent",
        type,
        ...payload,
      },
      window.location.origin,
    );
    return true;
  };

  const notifyTerminalFrameShown = () => {
    if (!terminalState.visible || !terminalState.frameReady) {
      return;
    }
    postTerminalFrameMessage("shown");
    postTerminalFrameMessage("focus");
  };

  const installTerminalFrameBridge = () => {
    if (terminalState.bridgeInstalled) {
      return;
    }
    terminalState.bridgeInstalled = true;
    window.addEventListener("message", (event) => {
      if (event.origin !== window.location.origin) {
        return;
      }
      const data = event.data;
      if (!data || data.source !== "workstation-terminal-frame") {
        return;
      }
      if (data.type === "ready") {
        terminalState.frameReady = true;
        if (terminalElements) {
          terminalElements.empty.hidden = true;
        }
        if (terminalState.visible) {
          window.requestAnimationFrame(() => {
            notifyTerminalFrameShown();
          });
        }
        return;
      }
      if (data.type === "status") {
        terminalStatus(data.left || "", data.right || "");
        return;
      }
      if (data.type === "toast") {
        if (data.message) {
          showStatus(String(data.message));
        }
        return;
      }
      if (data.type === "activate") {
        activateWindowSurface("terminal");
        return;
      }
      if (data.type === "error") {
        if (terminalElements) {
          terminalElements.empty.textContent = data.message || "터미널을 열지 못했습니다.";
          terminalElements.empty.hidden = false;
        }
        terminalStatus("셸 열기 실패", "");
      }
    });
  };

  const syncTerminalVisibleState = (visible) => {
    terminalState.visible = !!visible;
    setShellButtonSelected("workstation_terminal_button", terminalState.visible);
  };

  const setTerminalVisible = (visible) => {
    syncTerminalVisibleState(visible);
    if (!terminalElements) {
      return;
    }
    setWindowSurfaceVisible(terminalElements.surfaceId, terminalState.visible);
    if (!terminalState.visible) {
      return;
    }
    window.requestAnimationFrame(() => {
      notifyTerminalFrameShown();
    });
  };

  const ensureTerminalSession = async () => {
    ensureTerminalShell();
    installTerminalFrameBridge();
    if (terminalState.frameLoaded) {
      notifyTerminalFrameShown();
      return;
    }
    if (!terminalState.frameLoadPromise) {
      terminalState.frameReady = false;
      terminalElements.empty.textContent = "터미널 화면을 준비하는 중입니다.";
      terminalElements.empty.hidden = false;
      terminalStatus("셸 준비 중...", "");
      terminalState.frameLoadPromise = new Promise((resolve, reject) => {
        const frame = terminalElements.frame;
        const handleLoad = () => {
          terminalState.frameLoaded = true;
          terminalState.frameLoadPromise = null;
          frame.removeEventListener("error", handleError);
          resolve();
          if (terminalState.visible) {
            window.requestAnimationFrame(() => {
              notifyTerminalFrameShown();
            });
          }
        };
        const handleError = () => {
          terminalState.frameLoaded = false;
          terminalState.frameReady = false;
          terminalState.frameLoadPromise = null;
          frame.removeEventListener("load", handleLoad);
          terminalElements.empty.textContent = "터미널 화면을 불러오지 못했습니다.";
          terminalElements.empty.hidden = false;
          terminalStatus("셸 열기 실패", "");
          reject(new Error("terminal frame load failed"));
        };
        frame.addEventListener("load", handleLoad, { once: true });
        frame.addEventListener("error", handleError, { once: true });
        frame.src = terminalFrameUrl;
      });
    }
    await terminalState.frameLoadPromise;
  };

  const beginTerminalDrag = (event) => {
    if (!terminalElements || event.target.closest("button, input, textarea")) {
      return;
    }
    activateWindowSurface(terminalElements.surfaceId);
    const rect = terminalElements.window.getBoundingClientRect();
    terminalDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    };
    terminalElements.window.style.left = `${rect.left}px`;
    terminalElements.window.style.top = `${rect.top}px`;
    terminalElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragTerminalWindow);
    document.addEventListener("pointerup", endTerminalDrag);
  };

  const dragTerminalWindow = (event) => {
    if (!terminalDragState || !terminalElements) {
      return;
    }
    const nextLeft = Math.max(
      12,
      Math.min(window.innerWidth - terminalDragState.width - 12, event.clientX - terminalDragState.offsetX),
    );
    const nextTop = Math.max(
      54,
      Math.min(window.innerHeight - terminalDragState.height - 12, event.clientY - terminalDragState.offsetY),
    );
    terminalElements.window.style.left = `${nextLeft}px`;
    terminalElements.window.style.top = `${nextTop}px`;
  };

  const endTerminalDrag = () => {
    terminalDragState = null;
    document.removeEventListener("pointermove", dragTerminalWindow);
    document.removeEventListener("pointerup", endTerminalDrag);
  };

  const ensureTerminalShell = () => {
    if (terminalElements) {
      return terminalElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_terminal_panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-file-window workstation-terminal-window" role="dialog" aria-modal="false" aria-label="터미널">
        <div class="workstation-file-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon workstation-terminal-title-icon" aria-hidden="true"></span>
            <span>터미널</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-file-body workstation-terminal-body">
          <div class="workstation-terminal-main">
            <div class="workstation-terminal-host">
              <iframe class="workstation-terminal-frame" title="터미널" referrerpolicy="same-origin" allow="clipboard-read; clipboard-write"></iframe>
              <div class="workstation-terminal-empty">터미널 화면을 준비하는 중입니다.</div>
            </div>
          </div>
        </div>
        <div class="workstation-file-statusbar">
          <div class="workstation-file-pane workstation-file-status-left"></div>
          <div class="workstation-file-pane workstation-file-status-right"></div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-terminal-window");
    const titlebar = panel.querySelector(".workstation-file-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const host = panel.querySelector(".workstation-terminal-host");
    const frame = panel.querySelector(".workstation-terminal-frame");
    const empty = panel.querySelector(".workstation-terminal-empty");
    const statusLeft = panel.querySelector(".workstation-file-status-left");
    const statusRight = panel.querySelector(".workstation-file-status-right");

    closeButton.addEventListener("click", () => setTerminalVisible(false));
    titlebar.addEventListener("pointerdown", beginTerminalDrag);
    host.addEventListener("pointerdown", () => {
      activateWindowSurface("terminal");
    });
    frame.addEventListener("focus", () => {
      activateWindowSurface("terminal");
      postTerminalFrameMessage("focus");
    });

    registerWindowSurface("terminal", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncTerminalVisibleState(visible);
      },
    });
    installTerminalFrameBridge();

    terminalState.resizeObserver = new ResizeObserver(() => {
      if (!terminalState.visible) {
        return;
      }
      postTerminalFrameMessage("resize");
    });
    terminalState.resizeObserver.observe(windowNode);

    terminalElements = {
      surfaceId: "terminal",
      panel,
      window: windowNode,
      host,
      frame,
      empty,
      statusLeft,
      statusRight,
    };
    terminalStatus("셸 준비 전", "");
    return terminalElements;
  };

  const taskManagerStatus = (left, right) => {
    if (!taskManagerElements) {
      return;
    }
    taskManagerElements.statusLeft.textContent = left || "";
    taskManagerElements.statusRight.textContent = right || "";
  };

  const taskManagerNormalizedQuery = () => String(taskManagerState.searchQuery || "").trim().toLocaleLowerCase();

  const taskManagerFilteredItems = () => {
    const query = taskManagerNormalizedQuery();
    const items = sortedTaskManagerItems();
    if (!query) {
      return items;
    }
    return items.filter((item) => {
      const searchText = [
        item?.name || "",
        item?.command || "",
        item?.pid || "",
        item?.ppid || "",
        item?.pgid || "",
        item?.state || "",
        item?.state_label || "",
        item?.started_at || "",
      ]
        .map((value) => String(value || "").trim())
        .filter(Boolean)
        .join(" ")
        .trim()
        .toLocaleLowerCase();
      return searchText.includes(query);
    });
  };

  const updateTaskManagerSummaryStatus = (right = taskManagerState.lastUpdatedText || "") => {
    const totalCount = taskManagerState.items.length;
    const filteredCount = taskManagerFilteredItems().length;
    const left = taskManagerNormalizedQuery()
      ? `검색 결과 ${filteredCount}개 / 전체 ${totalCount}개`
      : `프로세스 ${totalCount}개`;
    taskManagerStatus(left, right);
  };

  const clearTaskManagerPolling = () => {
    if (!taskManagerState.pollTimer) {
      return;
    }
    window.clearTimeout(taskManagerState.pollTimer);
    taskManagerState.pollTimer = 0;
  };

  const syncTaskManagerVisibleState = (visible) => {
    taskManagerState.visible = !!visible;
    setShellButtonSelected("workstation_task_manager_button", taskManagerState.visible);
    if (!taskManagerState.visible) {
      clearTaskManagerPolling();
    }
  };

  const setTaskManagerVisible = (visible) => {
    syncTaskManagerVisibleState(visible);
    if (!taskManagerElements) {
      return;
    }
    setWindowSurfaceVisible(taskManagerElements.surfaceId, taskManagerState.visible);
    if (taskManagerState.visible) {
      scheduleTaskManagerPolling();
    }
  };

  const taskManagerSortValue = (item, key) => {
    switch (key) {
      case "pid":
        return Number(item.pid) || 0;
      case "state":
        return String(item.state_label || item.state || "");
      case "cpu_percent":
        return Number(item.cpu_percent) || 0;
      case "memory_percent":
        return Number(item.memory_percent) || 0;
      case "started_at":
        return Number(item.started_timestamp) || 0;
      case "command":
      default:
        return String(item.command || item.name || "");
    }
  };

  const sortedTaskManagerItems = () => {
    const factor = taskManagerState.sortDirection === "desc" ? -1 : 1;
    return [...taskManagerState.items].sort((left, right) => {
      const leftValue = taskManagerSortValue(left, taskManagerState.sortKey);
      const rightValue = taskManagerSortValue(right, taskManagerState.sortKey);
      if (typeof leftValue === "string" || typeof rightValue === "string") {
        return String(leftValue).localeCompare(String(rightValue), "ko") * factor;
      }
      if (leftValue === rightValue) {
        return (Number(left.pid) - Number(right.pid)) * factor;
      }
      return (Number(leftValue) - Number(rightValue)) * factor;
    });
  };

  const updateTaskManagerSortButtons = () => {
    if (!taskManagerElements) {
      return;
    }
    Object.entries(taskManagerElements.sortButtons).forEach(([key, button]) => {
      const label = button.dataset.label || button.textContent || "";
      const active = taskManagerState.sortKey === key;
      const arrow = active ? (taskManagerState.sortDirection === "asc" ? " ▲" : " ▼") : "";
      button.textContent = `${label}${arrow}`;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
  };

  const renderTaskManagerProcesses = () => {
    if (!taskManagerElements) {
      return;
    }
    const list = taskManagerElements.list;
    const rows = taskManagerElements.rows;
    const previousScrollTop = list.scrollTop;
    rows.innerHTML = "";
    updateTaskManagerSortButtons();

    const items = taskManagerFilteredItems();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "workstation-file-empty";
      if (taskManagerState.loading) {
        empty.textContent = "프로세스 목록을 불러오는 중입니다.";
      } else if (taskManagerNormalizedQuery()) {
        empty.textContent = "검색 결과가 없습니다.";
      } else {
        empty.textContent = "표시할 프로세스가 없습니다.";
      }
      rows.appendChild(empty);
      list.scrollTop = previousScrollTop;
      return;
    }

    items.forEach((item) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "workstation-task-manager-row";
      row.disabled = Number(item.pid) === taskManagerState.killingPid;

      const name = document.createElement("div");
      name.className = "workstation-task-manager-name";

      const icon = document.createElement("span");
      icon.className = "workstation-file-icon workstation-task-manager-icon";
      name.appendChild(icon);

      const text = document.createElement("div");
      text.className = "workstation-task-manager-text";

      const primary = document.createElement("div");
      primary.className = "workstation-task-manager-command";
      primary.textContent = item.name || item.command || `PID ${item.pid}`;
      text.appendChild(primary);

      const meta = document.createElement("div");
      meta.className = "workstation-task-manager-meta";
      meta.textContent = item.command || item.name || "";
      text.appendChild(meta);
      name.appendChild(text);

      const pid = document.createElement("div");
      pid.className = "workstation-task-manager-number";
      pid.textContent = String(item.pid || "");

      const state = document.createElement("div");
      state.className = "workstation-task-manager-state";
      state.textContent = item.state_label || item.state || "-";

      const cpu = document.createElement("div");
      cpu.className = "workstation-task-manager-number";
      cpu.textContent = formatPercent(item.cpu_percent);

      const memory = document.createElement("div");
      memory.className = "workstation-task-manager-number";
      memory.textContent = formatPercent(item.memory_percent);

      const started = document.createElement("div");
      started.className = "workstation-task-manager-started";
      started.textContent = item.started_at || "-";

      row.appendChild(name);
      row.appendChild(pid);
      row.appendChild(state);
      row.appendChild(cpu);
      row.appendChild(memory);
      row.appendChild(started);

      row.addEventListener("click", () => {
        activateWindowSurface(taskManagerElements.surfaceId);
        openActionDialog({
          title: "프로세스 강제 종료",
          body: `"${item.name || item.command || `PID ${item.pid}`}" 프로세스를 강제 종료합니다.`,
          detail: `PID ${item.pid} · 상태 ${item.state_label || item.state || "-"} · CPU ${formatPercent(item.cpu_percent)} · 메모리 ${formatPercent(item.memory_percent)} · 이 동작은 현재 로그인한 사용자의 해당 프로세스에 즉시 SIGKILL 을 보냅니다.`,
          submitLabel: "강제 종료",
          passwordRequired: false,
          anchorElement: row,
          onSubmit: async () => {
            taskManagerState.killingPid = Number(item.pid);
            renderTaskManagerProcesses();
            try {
              const { response, payload } = await postForm("/api/workspace/processes/kill", {
                pid: String(item.pid),
              });
              if (!response.ok || !payload.ok) {
                throw new Error(payload.message || "미안합니다.");
              }
              actionDialogElements.closeDialog();
              showStatus(payload.message || "프로세스를 강제 종료했습니다.");
              await loadTaskManagerProcesses({ silent: true, preserveScroll: true });
            } finally {
              taskManagerState.killingPid = 0;
              renderTaskManagerProcesses();
            }
          },
        });
      });

      rows.appendChild(row);
    });

    list.scrollTop = previousScrollTop;
  };

  const setTaskManagerSort = (key) => {
    const normalized = typeof key === "string" ? key.trim() : "";
    if (!normalized) {
      return;
    }
    if (taskManagerState.sortKey === normalized) {
      taskManagerState.sortDirection = taskManagerState.sortDirection === "asc" ? "desc" : "asc";
    } else {
      taskManagerState.sortKey = normalized;
      taskManagerState.sortDirection = normalized === "command" || normalized === "state" ? "asc" : "desc";
    }
    renderTaskManagerProcesses();
    updateTaskManagerSummaryStatus();
  };

  const loadTaskManagerProcesses = async ({ silent = false, preserveScroll = false } = {}) => {
    if (!taskManagerElements || taskManagerState.loading) {
      return;
    }
    const list = taskManagerElements.list;
    const previousScrollTop = preserveScroll ? list.scrollTop : 0;
    taskManagerState.loading = true;
    list.classList.add("is-loading");
    if (!silent) {
      taskManagerStatus("프로세스 목록을 불러오는 중입니다.", taskManagerState.lastUpdatedText);
    }

    try {
      const response = await fetch("/api/workspace/processes", {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "미안합니다.");
      }
      taskManagerState.items = Array.isArray(payload.items) ? payload.items : [];
      taskManagerState.lastUpdatedText = `마지막 갱신 ${new Date().toLocaleTimeString("ko-KR", { hour12: false })}`;
      renderTaskManagerProcesses();
      if (preserveScroll) {
        list.scrollTop = previousScrollTop;
      }
      updateTaskManagerSummaryStatus();
    } catch (_error) {
      renderTaskManagerProcesses();
      taskManagerStatus("프로세스 목록을 불러오지 못했습니다.", "");
      showStatus("작업 관리자를 불러오지 못했습니다.");
    } finally {
      taskManagerState.loading = false;
      list.classList.remove("is-loading");
      if (taskManagerState.visible) {
        scheduleTaskManagerPolling();
      }
    }
  };

  const scheduleTaskManagerPolling = () => {
    if (!taskManagerState.visible || taskManagerState.pollTimer) {
      return;
    }
    taskManagerState.pollTimer = window.setTimeout(async () => {
      taskManagerState.pollTimer = 0;
      if (!taskManagerState.visible) {
        return;
      }
      await loadTaskManagerProcesses({ silent: true, preserveScroll: true });
    }, taskManagerState.pollIntervalMs);
  };

  const beginTaskManagerDrag = (event) => {
    if (!taskManagerElements || event.target.closest("button, input, textarea")) {
      return;
    }
    activateWindowSurface(taskManagerElements.surfaceId);
    const rect = taskManagerElements.window.getBoundingClientRect();
    taskManagerDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    };
    taskManagerElements.window.style.left = `${rect.left}px`;
    taskManagerElements.window.style.top = `${rect.top}px`;
    taskManagerElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragTaskManagerWindow);
    document.addEventListener("pointerup", endTaskManagerDrag);
  };

  const dragTaskManagerWindow = (event) => {
    if (!taskManagerDragState || !taskManagerElements) {
      return;
    }
    const nextLeft = Math.max(
      12,
      Math.min(window.innerWidth - taskManagerDragState.width - 12, event.clientX - taskManagerDragState.offsetX),
    );
    const nextTop = Math.max(
      54,
      Math.min(window.innerHeight - taskManagerDragState.height - 12, event.clientY - taskManagerDragState.offsetY),
    );
    taskManagerElements.window.style.left = `${nextLeft}px`;
    taskManagerElements.window.style.top = `${nextTop}px`;
  };

  const endTaskManagerDrag = () => {
    taskManagerDragState = null;
    document.removeEventListener("pointermove", dragTaskManagerWindow);
    document.removeEventListener("pointerup", endTaskManagerDrag);
  };

  const ensureTaskManagerShell = () => {
    if (taskManagerElements) {
      return taskManagerElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_task_manager_panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-file-window workstation-task-manager-window" role="dialog" aria-modal="false" aria-label="작업 관리자">
        <div class="workstation-file-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon workstation-task-manager-title-icon" aria-hidden="true"></span>
            <span>작업 관리자</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-file-toolbar workstation-task-manager-toolbar">
          <button type="button" class="workstation-file-btn workstation-toolbar-btn" data-action="refresh"><span class="workstation-toolbar-icon workstation-toolbar-icon-refresh" aria-hidden="true"></span><span class="workstation-toolbar-label">새로고침</span></button>
          <label class="workstation-task-manager-search" for="workstation_task_manager_search">
            <span class="workstation-task-manager-search-label">프로세스 검색</span>
            <input id="workstation_task_manager_search" class="workstation-task-manager-search-input" type="search" spellcheck="false" autocomplete="off" placeholder="이름, 명령어, PID, 상태 검색">
          </label>
          <div class="workstation-task-manager-toolbar-note">현재 로그인한 사용자 프로세스를 2.5초마다 자동 갱신합니다.</div>
        </div>
        <div class="workstation-file-body workstation-task-manager-body">
          <aside class="workstation-file-sidebar workstation-task-manager-sidebar">
            <h3>작업 관리자</h3>
            <p>현재 로그인한 LDAP 사용자의 프로세스만 표시합니다.</p>
            <p>원하는 프로세스 행을 누르면 즉시 강제 종료 확인 창이 열립니다.</p>
            <p>열 제목을 누르면 정렬 기준을 바꿀 수 있고, 상단 검색은 이름, 명령어, PID, 상태 기준으로 즉시 적용됩니다.</p>
          </aside>
          <div class="workstation-file-main">
            <div class="workstation-file-list workstation-task-manager-list">
              <div class="workstation-task-manager-header">
                <button type="button" class="workstation-task-manager-sort" data-sort="command" data-label="프로세스">프로세스</button>
                <button type="button" class="workstation-task-manager-sort" data-sort="pid" data-label="PID">PID</button>
                <button type="button" class="workstation-task-manager-sort" data-sort="state" data-label="상태">상태</button>
                <button type="button" class="workstation-task-manager-sort" data-sort="cpu_percent" data-label="CPU">CPU</button>
                <button type="button" class="workstation-task-manager-sort" data-sort="memory_percent" data-label="메모리">메모리</button>
                <button type="button" class="workstation-task-manager-sort" data-sort="started_at" data-label="시작 시각">시작 시각</button>
              </div>
              <div class="workstation-task-manager-rows"></div>
            </div>
          </div>
        </div>
        <div class="workstation-file-statusbar">
          <div class="workstation-file-pane workstation-file-status-left"></div>
          <div class="workstation-file-pane workstation-file-status-right"></div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-task-manager-window");
    const titlebar = panel.querySelector(".workstation-file-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const refreshButton = panel.querySelector('[data-action="refresh"]');
    const searchInput = panel.querySelector("#workstation_task_manager_search");
    const list = panel.querySelector(".workstation-task-manager-list");
    const rows = panel.querySelector(".workstation-task-manager-rows");
    const statusLeft = panel.querySelector(".workstation-file-status-left");
    const statusRight = panel.querySelector(".workstation-file-status-right");
    const sortButtons = Object.fromEntries(
      Array.from(panel.querySelectorAll(".workstation-task-manager-sort")).map((button) => [button.dataset.sort, button]),
    );

    closeButton.addEventListener("click", () => setTaskManagerVisible(false));
    refreshButton.addEventListener("click", () => {
      loadTaskManagerProcesses({ silent: false, preserveScroll: true });
    });
    searchInput.addEventListener("input", () => {
      taskManagerState.searchQuery = searchInput.value || "";
      renderTaskManagerProcesses();
      updateTaskManagerSummaryStatus();
    });
    searchInput.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && searchInput.value) {
        searchInput.value = "";
        taskManagerState.searchQuery = "";
        renderTaskManagerProcesses();
        updateTaskManagerSummaryStatus();
      }
    });
    titlebar.addEventListener("pointerdown", beginTaskManagerDrag);
    windowNode.addEventListener("pointerdown", () => {
      activateWindowSurface("task-manager");
    });
    Object.entries(sortButtons).forEach(([key, button]) => {
      button.addEventListener("click", () => {
        setTaskManagerSort(key);
      });
    });

    registerWindowSurface("task-manager", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncTaskManagerVisibleState(visible);
      },
    });

    taskManagerElements = {
      surfaceId: "task-manager",
      panel,
      window: windowNode,
      list,
      rows,
      refreshButton,
      searchInput,
      sortButtons,
      statusLeft,
      statusRight,
    };
    updateTaskManagerSortButtons();
    updateTaskManagerSummaryStatus("");
    return taskManagerElements;
  };

  const sortChatUsers = () => {
    chatState.users.sort((left, right) => {
      const leftId = Number(left?.last_message_id || 0);
      const rightId = Number(right?.last_message_id || 0);
      if (leftId !== rightId) {
        return rightId - leftId;
      }
      return String(left?.username || "").localeCompare(String(right?.username || ""), "ko");
    });
  };

  const findChatUser = (username) =>
    chatState.users.find((item) => item.username === String(username || "").trim().toLowerCase()) || null;

  const activeChatUser = () => findChatUser(chatState.activePeer);

  const chatBusy = () => !!(chatState.sending || chatState.capturingScreenshot);

  const chatStatus = (left, right) => {
    if (!chatElements) {
      return;
    }
    chatElements.statusLeft.textContent = left || "";
    chatElements.statusRight.textContent = right || "";
  };

  const updateChatHeader = () => {
    if (!chatElements) {
      return;
    }
    const activeUser = activeChatUser();
    if (!activeUser) {
      chatElements.headerPrimary.textContent = "대화 상대를 선택하십시오.";
      chatElements.headerSecondary.textContent = chatState.users.length ? "왼쪽 목록에서 사용자를 선택하십시오." : "대화 가능한 사용자가 없습니다.";
      return;
    }
    chatElements.headerPrimary.textContent = activeUser.display_name || activeUser.username;
    if (chatState.loadingConversation) {
      chatElements.headerSecondary.textContent = "대화를 불러오는 중입니다.";
      return;
    }
    if (!chatState.messages.length) {
      chatElements.headerSecondary.textContent = "아직 주고받은 메시지가 없습니다.";
      return;
    }
    const latest = chatState.messages[chatState.messages.length - 1];
    chatElements.headerSecondary.textContent = `최신 메시지 ${latest.created_at_display || ""}`;
  };

  const chatScrolledNearBottom = () => {
    const node = chatElements?.messages;
    if (!node) {
      return true;
    }
    return node.scrollHeight - node.clientHeight - node.scrollTop < 48;
  };

  const syncChatComposerState = () => {
    if (!chatElements) {
      return;
    }
    const busy = chatBusy();
    chatElements.send.disabled = busy;
    chatElements.screenshot.disabled = busy;
  };

  const chatUnreadPeerCount = (username) => {
    const peer = String(username || "").trim().toLowerCase();
    const direct = Number(chatState.unreadPeers?.[peer]?.unread_count || 0);
    if (direct > 0) {
      return direct;
    }
    const user = findChatUser(peer);
    return Math.max(0, Math.floor(Number(user?.unread_count || 0)));
  };

  const syncChatUnreadButtonBadge = () => {
    setShellButtonBadge("workstation_chat_button", chatState.unreadTotal);
  };

  const shouldNotifyChatUnread = (peers) => {
    const entries = Object.entries(peers || {}).filter(([, value]) => Number(value?.unread_count || 0) > 0);
    if (!entries.length) {
      return false;
    }
    if (!chatState.visible || !chatState.activePeer) {
      return true;
    }
    return entries.some(([peer]) => peer !== chatState.activePeer);
  };

  const emitChatUnreadNotification = () => {
    emitBrowserNotification({
      summary: "새 채팅",
      body: "확인하지 않은 채팅 또는 스크린샷이 있습니다.",
      tag: "workstation-chat-unread",
    });
  };

  const syncChatUnreadState = (payload, { notify = false, render = true } = {}) => {
    const previousLatestId = Number(chatState.unreadLatestId || 0);
    const peers = payload?.peers || payload?.unread_peers || {};
    chatState.unreadTotal = Math.max(0, Math.floor(Number(payload?.total_unread || 0)));
    chatState.unreadLatestId = Math.max(0, Math.floor(Number(payload?.latest_unread_id || 0)));
    chatState.unreadPeers = peers && typeof peers === "object" ? peers : {};

    chatState.users.forEach((user) => {
      const peer = String(user?.username || "").trim().toLowerCase();
      const unread = chatState.unreadPeers[peer] || {};
      user.unread_count = Math.max(0, Math.floor(Number(unread.unread_count || 0)));
      user.latest_unread_id = Math.max(0, Math.floor(Number(unread.latest_unread_id || 0)));
    });

    syncChatUnreadButtonBadge();
    if (notify && chatState.unreadReady && chatState.unreadLatestId > previousLatestId && shouldNotifyChatUnread(chatState.unreadPeers)) {
      emitChatUnreadNotification();
    }
    chatState.unreadReady = true;
    if (render && chatElements) {
      renderChatUsers();
    }
  };

  const loadChatUnread = async ({ notify = true } = {}) => {
    const response = await fetch("/api/workspace/chat/unread", {
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({ ok: false }));
    if (!response.ok || !payload.ok) {
      throw new Error("chat unread load failed");
    }
    syncChatUnreadState(payload, { notify });
  };

  const runChatUnreadPolling = async () => {
    window.clearTimeout(chatState.unreadPollTimer);
    chatState.unreadPollTimer = 0;
    try {
      await loadChatUnread({ notify: true });
    } catch (_error) {
      // Keep unread polling best-effort so the workspace UI stays responsive.
    } finally {
      chatState.unreadPollTimer = window.setTimeout(runChatUnreadPolling, chatState.unreadPollIntervalMs);
    }
  };

  const scheduleChatUnreadPolling = ({ immediate = false } = {}) => {
    window.clearTimeout(chatState.unreadPollTimer);
    chatState.unreadPollTimer = window.setTimeout(runChatUnreadPolling, immediate ? 0 : chatState.unreadPollIntervalMs);
  };

  const markChatPeerRead = async (peer, { render = true } = {}) => {
    const targetPeer = String(peer || "").trim().toLowerCase();
    if (!targetPeer) {
      return false;
    }
    const { response, payload } = await postForm("/api/workspace/chat/read", { peer: targetPeer });
    if (!response.ok || !payload.ok) {
      throw new Error("chat read marker failed");
    }
    const user = findChatUser(targetPeer);
    if (user) {
      user.unread_count = 0;
      user.latest_unread_id = 0;
    }
    syncChatUnreadState(payload, { notify: false, render });
    return true;
  };

  const renderChatUsers = () => {
    if (!chatElements) {
      return;
    }
    const list = chatElements.users;
    list.replaceChildren();
    sortChatUsers();
    if (!chatState.users.length) {
      const empty = document.createElement("div");
      empty.className = "workstation-file-empty";
      empty.textContent = "대화 가능한 사용자가 없습니다.";
      list.appendChild(empty);
      chatStatus("대화 상대 없음", "");
      updateChatHeader();
      return;
    }

    chatState.users.forEach((item) => {
      const unreadCount = chatUnreadPeerCount(item.username);
      const row = document.createElement("div");
      row.className = "workstation-file-row workstation-chat-user-row";
      if (item.username === chatState.activePeer) {
        row.classList.add("is-selected");
      }
      if (unreadCount > 0) {
        row.classList.add("has-unread");
      }

      const name = document.createElement("div");
      name.className = "workstation-file-name workstation-chat-user-name";

      const icon = document.createElement("span");
      icon.className = "workstation-file-icon workstation-chat-user-icon";
      name.appendChild(icon);

      const text = document.createElement("div");
      text.className = "workstation-snapshot-text workstation-chat-user-text";

      const label = document.createElement("span");
      label.className = "workstation-file-name-text workstation-chat-user-title";
      label.textContent = item.display_name || item.username;
      text.appendChild(label);

      if (unreadCount > 0) {
        const unreadBadge = document.createElement("span");
        unreadBadge.className = "workstation-chat-user-unread";
        unreadBadge.textContent = unreadCount > 99 ? "99+" : String(unreadCount);
        unreadBadge.setAttribute("aria-label", `읽지 않은 항목 ${unreadCount}개`);
        text.appendChild(unreadBadge);
      }

      const preview = document.createElement("span");
      preview.className = "workstation-snapshot-meta workstation-chat-user-meta";
      preview.textContent = item.last_message_created_at_display || "메시지 없음";
      text.appendChild(preview);

      name.appendChild(text);
      row.appendChild(name);

      row.addEventListener("click", async () => {
        chatState.activePeer = item.username;
        activateWindowSurface("chat");
        renderChatUsers();
        await loadChatConversation(item.username, { mode: "replace", markRead: true });
      });

      list.appendChild(row);
    });

    chatStatus(`대화 상대 ${chatState.users.length}명`, chatState.activePeer || "");
    updateChatHeader();
  };

  const renderChatMessages = ({
    stickToBottom = false,
    preserveTopOffset = false,
    previousScrollHeight = 0,
    previousScrollTop = 0,
  } = {}) => {
    if (!chatElements) {
      return;
    }
    const transcript = chatElements.messages;
    transcript.replaceChildren();

    if (!chatState.activePeer) {
      const empty = document.createElement("div");
      empty.className = "workstation-file-empty workstation-chat-empty";
      empty.textContent = "왼쪽에서 대화 상대를 선택하십시오.";
      transcript.appendChild(empty);
      updateChatHeader();
      return;
    }

    if (!chatState.messages.length) {
      const empty = document.createElement("div");
      empty.className = "workstation-file-empty workstation-chat-empty";
      empty.textContent = "아직 메시지가 없습니다.";
      transcript.appendChild(empty);
      updateChatHeader();
      return;
    }

    chatState.messages.forEach((item) => {
      const row = document.createElement("div");
      row.className = `workstation-chat-message ${item.is_self ? "is-self" : "is-peer"}`;

      const meta = document.createElement("div");
      meta.className = "workstation-chat-message-meta";
      meta.textContent = `${item.display_name || item.sender} · ${item.created_at_display || ""}`;

      row.appendChild(meta);
      if (item.message_type === "image" && item.media_url) {
        row.classList.add("is-image");
        const link = document.createElement("a");
        link.className = "workstation-chat-message-image-link";
        link.href = item.media_url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = "원본 PNG 열기";

        const image = document.createElement("img");
        image.className = "workstation-chat-message-image";
        image.src = item.media_url;
        image.alt = `${item.display_name || item.sender} 스크린샷`;
        image.loading = "lazy";
        image.decoding = "async";
        if (Number(item.media_width || 0) > 0) {
          image.width = Number(item.media_width);
        }
        if (Number(item.media_height || 0) > 0) {
          image.height = Number(item.media_height);
        }
        link.appendChild(image);
        row.appendChild(link);
      } else {
        const bubble = document.createElement("div");
        bubble.className = "workstation-chat-message-bubble";
        bubble.textContent = item.body || "";
        row.appendChild(bubble);
      }
      transcript.appendChild(row);
    });

    if (preserveTopOffset) {
      transcript.scrollTop = transcript.scrollHeight - previousScrollHeight + previousScrollTop;
    } else if (stickToBottom) {
      transcript.scrollTop = transcript.scrollHeight;
    }
    updateChatHeader();
  };

  const mergeChatMessages = (items) => {
    const seen = new Set(chatState.messages.map((item) => Number(item.id)));
    const additions = [];
    (items || []).forEach((item) => {
      const id = Number(item?.id || 0);
      if (!id || seen.has(id)) {
        return;
      }
      seen.add(id);
      additions.push(item);
    });
    if (!additions.length) {
      return false;
    }
    chatState.messages = [...chatState.messages, ...additions];
    return true;
  };

  const applyChatUserSummaryFromMessage = (item) => {
    const peer = item.is_self ? item.recipient : item.sender;
    const user = findChatUser(peer);
    if (!user) {
      return;
    }
    user.last_message_id = Number(item.id || 0);
    user.last_message_created_at_display = item.created_at_display || "";
    user.last_message_preview = item.message_type === "image" ? "[스크린샷]" : (item.body || "").slice(0, 72);
    sortChatUsers();
  };

  const syncChatVisibleState = (visible) => {
    chatState.visible = !!visible;
    setShellButtonSelected("workstation_chat_button", chatState.visible);
    if (!chatState.visible) {
      window.clearTimeout(chatState.pollTimer);
      chatState.pollTimer = 0;
    }
  };

  const setChatVisible = (visible) => {
    syncChatVisibleState(visible);
    if (!chatElements) {
      return;
    }
    setWindowSurfaceVisible(chatElements.surfaceId, chatState.visible);
    if (!chatState.visible) {
      return;
    }
    scheduleChatPolling();
  };

  const loadChatConversation = async (peer, { mode = "replace", markRead = false } = {}) => {
    if (!chatElements) {
      return;
    }
    const targetPeer = String(peer || "").trim().toLowerCase();
    if (!targetPeer) {
      return;
    }
    const transcript = chatElements.messages;
    const previousScrollHeight = transcript.scrollHeight;
    const previousScrollTop = transcript.scrollTop;
    const beforeId = mode === "prepend" && chatState.messages.length ? chatState.messages[0].id : "";
    if (mode === "prepend") {
      if (chatState.loadingOlder || !chatState.hasMoreOlder) {
        return;
      }
      chatState.loadingOlder = true;
      chatStatus("이전 메시지 불러오는 중...", targetPeer);
    } else {
      chatState.loadingConversation = true;
      chatStatus("대화를 불러오는 중...", targetPeer);
      updateChatHeader();
    }

    try {
      const params = new URLSearchParams();
      params.set("peer", targetPeer);
      params.set("limit", "30");
      if (beforeId) {
        params.set("before_id", String(beforeId));
      }
      const response = await fetch(`/api/workspace/chat/messages?${params.toString()}`, {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok) {
        throw new Error("chat conversation load failed");
      }

      const items = Array.isArray(payload.messages) ? payload.messages : [];
      chatState.activePeer = targetPeer;
      chatState.hasMoreOlder = !!payload.has_more;
      if (mode === "prepend") {
        if (items.length) {
          chatState.messages = [...items, ...chatState.messages];
          renderChatMessages({
            preserveTopOffset: true,
            previousScrollHeight,
            previousScrollTop,
          });
        }
      } else {
        chatState.messages = items;
        renderChatMessages({ stickToBottom: true });
      }
      if (mode !== "prepend" && markRead) {
        try {
          await markChatPeerRead(targetPeer, { render: false });
        } catch (_error) {
          // A read-marker failure must not prevent the conversation from opening.
        }
      }
      renderChatUsers();
      chatStatus(targetPeer, `${chatState.messages.length}개 메시지`);
    } catch (_error) {
      showStatus("대화를 불러오지 못했습니다.");
      chatStatus("대화를 불러오지 못했습니다.", targetPeer);
    } finally {
      chatState.loadingOlder = false;
      chatState.loadingConversation = false;
      updateChatHeader();
    }
  };

  const loadChatUsers = async ({ refreshConversation = false, selectDefault = false } = {}) => {
    if (chatState.loadingUsers) {
      return;
    }
    chatState.loadingUsers = true;
    try {
      const response = await fetch("/api/workspace/chat/users", {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok) {
        throw new Error("chat users load failed");
      }
      const previousPeer = chatState.activePeer;
      chatState.users = Array.isArray(payload.users) ? payload.users : [];
      syncChatUnreadState(payload, { notify: false, render: false });
      sortChatUsers();
      const hasPreviousPeer = chatState.users.some((item) => item.username === previousPeer);
      const nextPeer = hasPreviousPeer ? previousPeer : (selectDefault ? (chatState.users[0]?.username || "") : "");
      chatState.activePeer = nextPeer;
      renderChatUsers();
      chatState.usersRefreshStartedAt = Date.now();
      if (!nextPeer) {
        chatState.messages = [];
        chatState.hasMoreOlder = false;
        renderChatMessages();
        return;
      }
      if (refreshConversation || (selectDefault && (previousPeer !== nextPeer || !chatState.messages.length))) {
        await loadChatConversation(nextPeer, { mode: "replace", markRead: false });
      }
    } catch (_error) {
      showStatus("채팅 사용자 목록을 불러오지 못했습니다.");
      chatStatus("채팅 사용자 목록을 불러오지 못했습니다.", "");
    } finally {
      chatState.loadingUsers = false;
    }
  };

  const pollChatConversation = async () => {
    if (!chatState.visible || !chatState.activePeer || !chatElements) {
      return;
    }
    const latestMessage = chatState.messages[chatState.messages.length - 1];
    const afterId = Number(latestMessage?.id || 0);
    const params = new URLSearchParams();
    params.set("peer", chatState.activePeer);
    params.set("limit", "100");
    if (afterId > 0) {
      params.set("after_id", String(afterId));
    }
    const nearBottom = chatScrolledNearBottom();
    const response = await fetch(`/api/workspace/chat/messages?${params.toString()}`, {
      credentials: "same-origin",
      headers: { "X-Requested-With": "fetch" },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({ ok: false }));
    if (!response.ok || !payload.ok) {
      throw new Error("chat poll failed");
    }
    const items = Array.isArray(payload.messages) ? payload.messages : [];
    if (!items.length) {
      return;
    }
    if (mergeChatMessages(items)) {
      items.forEach((item) => applyChatUserSummaryFromMessage(item));
      if (items.some((item) => !item.is_self)) {
        try {
          await markChatPeerRead(chatState.activePeer, { render: false });
        } catch (_error) {
          // Keep polling alive even if the read marker update is temporarily unavailable.
        }
      }
      renderChatUsers();
      renderChatMessages({ stickToBottom: nearBottom || items.some((item) => item.is_self) });
      chatStatus(chatState.activePeer, `${chatState.messages.length}개 메시지`);
    }
  };

  const runChatPolling = async () => {
    if (!chatState.visible) {
      return;
    }
    try {
      if (!chatState.loadingUsers && (!chatState.usersRefreshStartedAt || Date.now() - chatState.usersRefreshStartedAt >= 10000)) {
        await loadChatUsers({ refreshConversation: false });
      }
      await pollChatConversation();
    } catch (_error) {
    } finally {
      if (chatState.visible) {
        chatState.pollTimer = window.setTimeout(runChatPolling, chatState.pollIntervalMs);
      }
    }
  };

  const scheduleChatPolling = () => {
    window.clearTimeout(chatState.pollTimer);
    chatState.pollTimer = 0;
    if (!chatState.visible) {
      return;
    }
    chatState.pollTimer = window.setTimeout(runChatPolling, chatState.pollIntervalMs);
  };

  const sendChatMessage = async () => {
    if (!chatElements || chatBusy()) {
      return;
    }
    const peer = chatState.activePeer;
    const body = String(chatElements.input.value || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
    if (!peer) {
      showStatus("먼저 대화 상대를 선택하십시오.");
      return;
    }
    if (!body) {
      showStatus("보낼 메시지를 입력하십시오.");
      return;
    }

    chatState.sending = true;
    syncChatComposerState();
    chatStatus("메시지를 보내는 중...", peer);
    try {
      const { response, payload } = await postForm("/api/workspace/chat/messages/send", {
        peer,
        body,
      });
      if (!response.ok || !payload.ok || !payload.item) {
        throw new Error(payload.message || "chat send failed");
      }
      chatElements.input.value = "";
      if (mergeChatMessages([payload.item])) {
        applyChatUserSummaryFromMessage(payload.item);
        renderChatUsers();
        renderChatMessages({ stickToBottom: true });
      }
      chatStatus(peer, `${chatState.messages.length}개 메시지`);
      showStatus(payload.message || "메시지를 보냈습니다.");
    } catch (_error) {
      showStatus("메시지를 보내지 못했습니다.");
      chatStatus("메시지를 보내지 못했습니다.", peer);
    } finally {
      chatState.sending = false;
      syncChatComposerState();
      scheduleChatPolling();
    }
  };

  const sendChatScreenshot = async () => {
    if (!chatElements || chatBusy()) {
      return;
    }
    const peer = chatState.activePeer;
    if (!peer) {
      showStatus("먼저 대화 상대를 선택하십시오.");
      return;
    }

    chatState.capturingScreenshot = true;
    syncChatComposerState();
    chatStatus("스크린샷을 캡처하는 중...", peer);
    try {
      const blob = await captureVncScreenshotBlob();
      const form = new FormData();
      form.append("peer", peer);
      form.append("image", blob, `workspace-${new Date().toISOString().replace(/[:.]/g, "-")}.png`);

      const response = await fetch("/api/workspace/chat/messages/screenshot", {
        method: "POST",
        body: form,
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok || !payload.item) {
        throw new Error(payload.message || "chat screenshot send failed");
      }

      if (mergeChatMessages([payload.item])) {
        applyChatUserSummaryFromMessage(payload.item);
        renderChatUsers();
        renderChatMessages({ stickToBottom: true });
      }
      chatStatus(peer, `${chatState.messages.length}개 메시지`);
      showStatus(payload.message || "스크린샷을 보냈습니다.");
    } catch (_error) {
      showStatus("스크린샷을 보내지 못했습니다.");
      chatStatus("스크린샷을 보내지 못했습니다.", peer);
    } finally {
      chatState.capturingScreenshot = false;
      syncChatComposerState();
      scheduleChatPolling();
    }
  };

  const beginChatDrag = (event) => {
    if (!chatElements || event.target.closest("button, input, textarea")) {
      return;
    }
    activateWindowSurface(chatElements.surfaceId);
    const rect = chatElements.window.getBoundingClientRect();
    chatDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      width: rect.width,
      height: rect.height,
    };
    chatElements.window.style.left = `${rect.left}px`;
    chatElements.window.style.top = `${rect.top}px`;
    chatElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragChatWindow);
    document.addEventListener("pointerup", endChatDrag);
  };

  const dragChatWindow = (event) => {
    if (!chatDragState || !chatElements) {
      return;
    }
    const nextLeft = Math.max(
      12,
      Math.min(window.innerWidth - chatDragState.width - 12, event.clientX - chatDragState.offsetX),
    );
    const nextTop = Math.max(
      54,
      Math.min(window.innerHeight - chatDragState.height - 12, event.clientY - chatDragState.offsetY),
    );
    chatElements.window.style.left = `${nextLeft}px`;
    chatElements.window.style.top = `${nextTop}px`;
  };

  const endChatDrag = () => {
    chatDragState = null;
    document.removeEventListener("pointermove", dragChatWindow);
    document.removeEventListener("pointerup", endChatDrag);
  };

  const ensureChatShell = () => {
    if (chatElements) {
      return chatElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_chat_panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-file-window workstation-chat-window" role="dialog" aria-modal="false" aria-label="채팅">
        <div class="workstation-file-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon workstation-chat-title-icon" aria-hidden="true"></span>
            <span>채팅</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-file-body workstation-chat-body">
          <aside class="workstation-file-sidebar workstation-chat-sidebar">
            <h3>사용자</h3>
            <p>작업공간이 있는 LDAP 사용자만 표시됩니다.</p>
            <div class="workstation-chat-user-list"></div>
          </aside>
          <div class="workstation-chat-main">
            <div class="workstation-chat-header">
              <div class="workstation-chat-header-primary">대화 상대를 선택하십시오.</div>
              <div class="workstation-chat-header-secondary">왼쪽 목록에서 사용자를 선택하십시오.</div>
            </div>
            <div class="workstation-chat-messages" aria-live="polite"></div>
            <div class="workstation-chat-composer">
              <label for="workstation_chat_input">메시지</label>
              <textarea id="workstation_chat_input" class="workstation-chat-input" spellcheck="true" placeholder="메시지를 입력하십시오."></textarea>
              <button type="button" class="workstation-file-btn workstation-chat-screenshot">스크린샷</button>
              <button type="button" class="workstation-file-btn workstation-chat-send">보내기</button>
            </div>
          </div>
        </div>
        <div class="workstation-file-statusbar">
          <div class="workstation-file-pane workstation-file-status-left"></div>
          <div class="workstation-file-pane workstation-file-status-right"></div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-chat-window");
    const titlebar = panel.querySelector(".workstation-file-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const users = panel.querySelector(".workstation-chat-user-list");
    const headerPrimary = panel.querySelector(".workstation-chat-header-primary");
    const headerSecondary = panel.querySelector(".workstation-chat-header-secondary");
    const messages = panel.querySelector(".workstation-chat-messages");
    const input = panel.querySelector("#workstation_chat_input");
    const screenshot = panel.querySelector(".workstation-chat-screenshot");
    const send = panel.querySelector(".workstation-chat-send");
    const statusLeft = panel.querySelector(".workstation-file-status-left");
    const statusRight = panel.querySelector(".workstation-file-status-right");

    closeButton.addEventListener("click", () => setChatVisible(false));
    titlebar.addEventListener("pointerdown", beginChatDrag);
    windowNode.addEventListener("pointerdown", () => {
      activateWindowSurface("chat");
    });
    messages.addEventListener("scroll", () => {
      if (messages.scrollTop > 32 || !chatState.hasMoreOlder || chatState.loadingOlder || !chatState.activePeer) {
        return;
      }
      loadChatConversation(chatState.activePeer, { mode: "prepend" });
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        event.preventDefault();
        sendChatMessage();
      }
    });
    send.addEventListener("click", () => {
      sendChatMessage();
    });
    screenshot.addEventListener("click", () => {
      sendChatScreenshot();
    });

    registerWindowSurface("chat", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncChatVisibleState(visible);
      },
    });

    chatElements = {
      surfaceId: "chat",
      panel,
      window: windowNode,
      users,
      headerPrimary,
      headerSecondary,
      messages,
      input,
      screenshot,
      send,
      statusLeft,
      statusRight,
    };
    syncChatComposerState();
    renderChatUsers();
    renderChatMessages();
    return chatElements;
  };

  const accountStatus = (left, right) => {
    if (!accountElements) {
      return;
    }
    accountElements.statusLeft.textContent = left || "";
    accountElements.statusRight.textContent = right || "";
  };

  const renderAccountEmailState = () => {
    if (!accountElements) {
      return;
    }
    if (accountState.registered) {
      accountElements.emailSummary.textContent = `현재 등록된 외부 이메일: ${accountState.registeredEmail}`;
      accountElements.emailDetail.textContent =
        "다른 외부 이메일로 바꾸려면 현재 LDAP 비밀번호 확인 후 다시 인증 번호를 받아야 합니다.";
    } else if (accountState.pending && accountState.pendingEmailMasked) {
      accountElements.emailSummary.textContent = `인증 대기 중인 이메일: ${accountState.pendingEmailMasked}`;
      accountElements.emailDetail.textContent =
        "인증 번호는 10분 동안 유효합니다. 다시 등록을 누르면 새 인증 메일을 보냅니다.";
    } else {
      accountElements.emailSummary.textContent = "등록된 외부 이메일이 없습니다.";
      accountElements.emailDetail.textContent =
        "내부 메일 도메인이 아닌 이메일만 등록할 수 있으며, 인증 번호는 10분 동안만 유효합니다.";
    }
    accountElements.registerEmailButton.disabled = !accountState.canRegister;
    accountElements.changeEmailButton.disabled = !accountState.canChange;
  };

  const applyAccountEmailPayload = (payload) => {
    accountState.registered = !!payload.registered;
    accountState.registeredEmail = payload.registered_email || "";
    accountState.canRegister = !!payload.can_register;
    accountState.canChange = !!payload.can_change;
    accountState.pending = !!payload.pending;
    accountState.pendingEmailMasked = payload.pending_email_masked || "";
    accountState.pendingExpiresInSeconds = Number(payload.pending_expires_in_seconds || 0);
    renderAccountEmailState();
  };

  const loadAccountEmailState = async () => {
    ensureAccountShell();
    try {
      const response = await fetch("/api/workspace/account/email", {
        credentials: "same-origin",
        cache: "no-store",
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) {
        throw new Error(payload.message || "미안합니다.");
      }
      applyAccountEmailPayload(payload);
      accountStatus("사용자 설정", payload.registered ? "외부 이메일 등록됨" : "LDAP 계정");
    } catch (_error) {
      accountStatus("사용자 설정", "LDAP 계정");
      if (accountElements) {
        accountElements.emailSummary.textContent = "외부 이메일 정보를 불러오지 못했습니다.";
        accountElements.emailDetail.textContent = "잠시 후 다시 시도하십시오.";
      }
    }
  };

  const syncAccountVisibleState = (visible) => {
    accountState.visible = !!visible;
    setShellButtonSelected("workstation_account_button", accountState.visible);
  };

  const setAccountVisible = (visible) => {
    syncAccountVisibleState(visible);
    if (!accountElements) {
      return;
    }
    setWindowSurfaceVisible(accountElements.surfaceId, accountState.visible);
    if (accountState.visible) {
      loadAccountEmailState();
    }
  };

  const beginAccountDrag = (event) => {
    if (!accountElements || event.target.closest("button, input, textarea")) {
      return;
    }
    activateWindowSurface(accountElements.surfaceId);
    const rect = accountElements.window.getBoundingClientRect();
    accountDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    accountElements.window.style.left = `${rect.left}px`;
    accountElements.window.style.top = `${rect.top}px`;
    accountElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragAccountWindow);
    document.addEventListener("pointerup", endAccountDrag);
  };

  const dragAccountWindow = (event) => {
    if (!accountDragState || !accountElements) {
      return;
    }
    const nextLeft = Math.max(12, Math.min(window.innerWidth - 420, event.clientX - accountDragState.offsetX));
    const nextTop = Math.max(54, Math.min(window.innerHeight - 260, event.clientY - accountDragState.offsetY));
    accountElements.window.style.left = `${nextLeft}px`;
    accountElements.window.style.top = `${nextTop}px`;
  };

  const endAccountDrag = () => {
    accountDragState = null;
    document.removeEventListener("pointermove", dragAccountWindow);
    document.removeEventListener("pointerup", endAccountDrag);
  };

  const openPasswordChangeDialog = (anchorElement = null) => {
    openActionDialog({
      title: "비밀번호 변경",
      body: "현재 LDAP 비밀번호를 확인한 뒤 새 비밀번호로 바꿉니다.",
      detail: "변경이 완료되면 현재 작업공간 쪽 비밀 저장소도 새 비밀번호 기준으로 다시 맞춥니다.",
      submitLabel: "변경",
      passwordRequired: {
        label: "현재 비밀번호",
        placeholder: "현재 LDAP 비밀번호",
        autocomplete: "current-password",
      },
      fields: [
        {
          name: "new_password",
          label: "새 비밀번호",
          type: "password",
          placeholder: "새 비밀번호",
          autocomplete: "new-password",
        },
        {
          name: "confirm_password",
          label: "새 비밀번호 확인",
          type: "password",
          placeholder: "새 비밀번호를 다시 입력",
          autocomplete: "new-password",
        },
      ],
      progressText: "비밀번호를 변경하는 중입니다.",
      anchorElement,
      onSubmit: async ({ password, fields }) => {
        const currentPassword = String(password || "");
        const newPassword = String(fields.new_password || "");
        const confirmPassword = String(fields.confirm_password || "");
        if (!currentPassword || !newPassword || !confirmPassword) {
          throw new Error("모든 항목을 입력하십시오.");
        }
        if (newPassword !== confirmPassword) {
          throw new Error("새 비밀번호 확인이 일치하지 않습니다.");
        }
        if (currentPassword === newPassword) {
          throw new Error("새 비밀번호를 현재 비밀번호와 다르게 입력하십시오.");
        }
        const { response, payload } = await postForm("/api/workspace/account/password", {
          current_password: currentPassword,
          new_password: newPassword,
          confirm_password: confirmPassword,
        });
        if (!response.ok || !payload.ok) {
          throw new Error(payload.message || "비밀번호를 변경하지 못했습니다.");
        }
        actionDialogElements.closeDialog();
        accountStatus("비밀번호 변경 완료", "동기화 반영");
        showStatus(payload.message || "비밀번호를 변경했습니다.");
      },
    });
  };

  const openExternalEmailVerifyDialog = ({ anchorElement = null, maskedEmail = "" } = {}) => {
    openActionDialog({
      title: "외부 이메일 인증",
      body: maskedEmail
        ? `${maskedEmail} 로 보낸 6자리 인증 번호를 입력하십시오.`
        : "메일로 보낸 6자리 인증 번호를 입력하십시오.",
      detail: "10분 안에 인증하지 않으면 진행 중인 등록이 취소됩니다.",
      submitLabel: "인증 완료",
      passwordRequired: false,
      fields: [
        {
          name: "code",
          label: "인증 번호",
          placeholder: "6자리 숫자",
          autocomplete: "one-time-code",
        },
      ],
      progressText: "외부 이메일을 등록하는 중입니다.",
      anchorElement,
      onSubmit: async ({ fields }) => {
        const code = String(fields.code || "").trim();
        if (!code) {
          throw new Error("인증 번호를 입력하십시오.");
        }
        const { response, payload } = await postForm("/api/workspace/account/email/verify", {
          code,
        });
        if (!response.ok || !payload.ok) {
          throw new Error(payload.message || "외부 이메일을 등록하지 못했습니다.");
        }
        actionDialogElements.closeDialog();
        applyAccountEmailPayload(payload);
        accountStatus("외부 이메일 등록 완료", payload.registered_email || "");
        showStatus(payload.message || "외부 이메일을 등록했습니다.");
      },
    });
  };

  const openExternalEmailRequestDialog = ({ mode, anchorElement = null } = {}) => {
    const changing = mode === "change";
    openActionDialog({
      title: changing ? "외부 이메일 변경" : "외부 이메일 등록",
      body: changing
        ? "등록된 외부 이메일을 다른 주소로 바꿉니다."
        : "내부 메일 도메인이 아닌 외부 이메일을 등록합니다.",
      detail: "인증 번호는 10분 동안 유효하며, 이미 다른 계정에 등록된 주소는 사용할 수 없습니다.",
      submitLabel: "인증 메일 보내기",
      passwordRequired: changing
        ? {
            label: "현재 LDAP 비밀번호",
            placeholder: "현재 LDAP 비밀번호",
            autocomplete: "current-password",
          }
        : false,
      fields: [
        {
          name: "email",
          label: "외부 이메일",
          type: "email",
          placeholder: "name@example.com",
          autocomplete: "email",
        },
      ],
      progressText: "인증 메일을 보내는 중입니다.",
      anchorElement,
      onSubmit: async ({ password, fields }) => {
        const email = String(fields.email || "").trim();
        if (!email) {
          throw new Error("외부 이메일을 입력하십시오.");
        }
        const form = {
          mode: changing ? "change" : "register",
          email,
        };
        if (changing) {
          form.current_password = String(password || "");
        }
        const { response, payload } = await postForm("/api/workspace/account/email/request", form);
        if (!response.ok || !payload.ok) {
          throw new Error(payload.message || "인증 메일을 보내지 못했습니다.");
        }
        actionDialogElements.closeDialog();
        accountStatus("인증 메일 발송", payload.masked_email || "");
        showStatus(payload.message || "인증 메일을 보냈습니다.");
        openExternalEmailVerifyDialog({
          anchorElement,
          maskedEmail: payload.masked_email || "",
        });
      },
    });
  };

  const ensureAccountShell = () => {
    if (accountElements) {
      return accountElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_account_panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-file-window workstation-account-window" role="dialog" aria-modal="false" aria-label="사용자 설정">
        <div class="workstation-file-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon workstation-account-title-icon" aria-hidden="true"></span>
            <span>사용자 설정</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-file-body workstation-account-body">
          <aside class="workstation-file-sidebar workstation-account-sidebar">
            <h3>계정</h3>
            <p>현재 로그인 중인 LDAP 계정의 비밀번호와 외부 이메일 등록 상태를 관리합니다.</p>
            <p>외부 이메일은 내부 메일 도메인이 아닌 주소만 등록할 수 있고, 인증 번호는 10분 동안만 유효합니다.</p>
            <p>이메일 변경은 현재 LDAP 비밀번호 확인이 필요하며, 이미 다른 계정에 등록된 주소는 사용할 수 없습니다.</p>
          </aside>
          <div class="workstation-file-main workstation-account-main">
            <div class="workstation-account-card">
              <div class="workstation-account-card-section">
                <div class="workstation-account-card-title">외부 이메일</div>
                <p class="workstation-account-card-text" data-role="external-email-summary">외부 이메일 정보를 확인하는 중입니다.</p>
                <p class="workstation-account-card-text workstation-account-card-subtext" data-role="external-email-detail"></p>
                <div class="workstation-account-action-row">
                  <button type="button" class="workstation-file-btn workstation-account-action" data-action="register-email">이메일 등록</button>
                  <button type="button" class="workstation-file-btn workstation-account-action" data-action="change-email">이메일 변경</button>
                </div>
              </div>
              <div class="workstation-account-card-section">
                <div class="workstation-account-card-title">비밀번호</div>
                <p class="workstation-account-card-text">현재 비밀번호를 확인한 뒤 새 비밀번호로 바꿉니다.</p>
                <div class="workstation-account-action-row">
                  <button type="button" class="workstation-file-btn workstation-account-action" data-action="change-password">비밀번호 변경</button>
                </div>
              </div>
              <div class="workstation-account-card-section">
                <div class="workstation-account-card-title">세션</div>
                <p class="workstation-account-card-text">현재 세션을 종료하고 로그인 화면으로 돌아갑니다.</p>
                <div class="workstation-account-action-row">
                  <button type="button" class="workstation-file-btn workstation-account-action" data-action="logout">로그아웃</button>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="workstation-file-statusbar">
          <div class="workstation-file-pane workstation-file-status-left"></div>
          <div class="workstation-file-pane workstation-file-status-right"></div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-account-window");
    const titlebar = panel.querySelector(".workstation-file-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const emailSummary = panel.querySelector('[data-role="external-email-summary"]');
    const emailDetail = panel.querySelector('[data-role="external-email-detail"]');
    const registerEmailButton = panel.querySelector('[data-action="register-email"]');
    const changeEmailButton = panel.querySelector('[data-action="change-email"]');
    const changePasswordButton = panel.querySelector('[data-action="change-password"]');
    const logoutButton = panel.querySelector('[data-action="logout"]');
    const statusLeft = panel.querySelector(".workstation-file-status-left");
    const statusRight = panel.querySelector(".workstation-file-status-right");

    closeButton.addEventListener("click", () => setAccountVisible(false));
    titlebar.addEventListener("pointerdown", beginAccountDrag);
    windowNode.addEventListener("pointerdown", () => {
      activateWindowSurface("account");
    });
    changePasswordButton.addEventListener("click", () => {
      activateWindowSurface("account");
      openPasswordChangeDialog(changePasswordButton);
    });
    registerEmailButton.addEventListener("click", () => {
      activateWindowSurface("account");
      openExternalEmailRequestDialog({
        mode: "register",
        anchorElement: registerEmailButton,
      });
    });
    changeEmailButton.addEventListener("click", () => {
      activateWindowSurface("account");
      openExternalEmailRequestDialog({
        mode: "change",
        anchorElement: changeEmailButton,
      });
    });
    logoutButton.addEventListener("click", () => {
      activateWindowSurface("account");
      accountStatus("로그아웃 중...", publicLogoutUrl);
      showStatus("로그아웃하는 중입니다.");
      submitRedirectPost("/logout");
    });

    registerWindowSurface("account", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncAccountVisibleState(visible);
      },
    });

    accountElements = {
      surfaceId: "account",
      panel,
      window: windowNode,
      emailSummary,
      emailDetail,
      registerEmailButton,
      changeEmailButton,
      changePasswordButton,
      logoutButton,
      statusLeft,
      statusRight,
    };
    renderAccountEmailState();
    accountStatus("사용자 설정", "LDAP 계정");
    return accountElements;
  };

  const selectedSnapshot = () => snapshotState.items.find((item) => item.id === snapshotState.selectedId) || null;

  const snapshotStatus = (left, right) => {
    if (!snapshotElements) {
      return;
    }
    snapshotElements.statusLeft.textContent = left || "";
    snapshotElements.statusRight.textContent = right || "";
  };

  const syncSnapshotVisibleState = (visible) => {
    snapshotState.visible = !!visible;
    setShellButtonSelected("workstation_snapshots_button", snapshotState.visible);
  };

  const setSnapshotVisible = (visible) => {
    syncSnapshotVisibleState(visible);
    if (!snapshotElements) {
      return;
    }
    setWindowSurfaceVisible(snapshotElements.surfaceId, snapshotState.visible);
  };

  const updateSnapshotButtons = () => {
    if (!snapshotElements) {
      return;
    }
    const item = selectedSnapshot();
    snapshotElements.rollback.disabled = !item;
    snapshotElements.remove.disabled = !item;
  };

  const renderSnapshotItems = () => {
    if (!snapshotElements) {
      return;
    }
    const list = snapshotElements.list;
    list.innerHTML = "";

    if (!snapshotState.items.length) {
      const empty = document.createElement("div");
      empty.className = "workstation-file-empty";
      empty.textContent = "저장된 스냅샷이 없습니다.";
      list.appendChild(empty);
      snapshotStatus("스냅샷 없음", "0개 항목");
      updateSnapshotButtons();
      return;
    }

    snapshotState.items.forEach((item) => {
      const row = document.createElement("div");
      row.className = "workstation-file-row workstation-snapshot-row";
      if (item.id === snapshotState.selectedId) {
        row.classList.add("is-selected");
      }
      if (item.description) {
        row.title = item.description;
      }

      const name = document.createElement("div");
      name.className = "workstation-file-name";

      const icon = document.createElement("span");
      icon.className = "workstation-file-icon workstation-snapshot-icon";
      name.appendChild(icon);

      const text = document.createElement("span");
      text.className = "workstation-snapshot-text";

      const label = document.createElement("span");
      label.className = "workstation-file-name-text workstation-snapshot-title";
      label.textContent = item.title || item.created_at_display || item.id;
      text.appendChild(label);

      const meta = document.createElement("span");
      meta.className = "workstation-snapshot-meta";
      meta.textContent = item.id;
      text.appendChild(meta);

      name.appendChild(text);

      const created = document.createElement("div");
      created.className = "workstation-file-mtime workstation-snapshot-created";
      created.textContent = item.created_at_display || "";

      row.appendChild(name);
      row.appendChild(created);

      row.addEventListener("click", () => {
        snapshotState.selectedId = item.id;
        renderSnapshotItems();
        snapshotStatus("스냅샷 선택됨", item.created_at_display || item.id);
      });

      list.appendChild(row);
    });

    snapshotStatus("스냅샷 목록", `${snapshotState.items.length}개 항목`);
    updateSnapshotButtons();
  };

  const loadSnapshots = async () => {
    if (!snapshotElements) {
      return;
    }
    snapshotElements.list.classList.add("is-loading");
    snapshotStatus("불러오는 중...", snapshotElements.statusRight.textContent);
    try {
      const response = await fetch("/api/workspace/snapshots", {
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        cache: "no-store",
      });
      const payload = await response.json().catch(() => ({ ok: false }));
      if (!response.ok || !payload.ok) {
        throw new Error("snapshot list failed");
      }
      snapshotState.items = payload.snapshots || [];
      snapshotState.selectedId = snapshotState.items.some((item) => item.id === snapshotState.selectedId)
        ? snapshotState.selectedId
        : "";
      renderSnapshotItems();
      setSnapshotVisible(true);
    } catch (_error) {
      showStatus("스냅샷을 불러오지 못했습니다.");
      snapshotStatus("스냅샷을 불러오지 못했습니다.", "");
    } finally {
      snapshotElements.list.classList.remove("is-loading");
    }
  };

  const beginSnapshotDrag = (event) => {
    if (!snapshotElements || event.target.closest("button, input, textarea")) {
      return;
    }
    activateWindowSurface(snapshotElements.surfaceId);
    const rect = snapshotElements.window.getBoundingClientRect();
    snapshotDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    snapshotElements.window.style.left = `${rect.left}px`;
    snapshotElements.window.style.top = `${rect.top}px`;
    snapshotElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragSnapshotWindow);
    document.addEventListener("pointerup", endSnapshotDrag);
  };

  const dragSnapshotWindow = (event) => {
    if (!snapshotDragState || !snapshotElements) {
      return;
    }
    const nextLeft = Math.max(12, Math.min(window.innerWidth - 360, event.clientX - snapshotDragState.offsetX));
    const nextTop = Math.max(54, Math.min(window.innerHeight - 220, event.clientY - snapshotDragState.offsetY));
    snapshotElements.window.style.left = `${nextLeft}px`;
    snapshotElements.window.style.top = `${nextTop}px`;
  };

  const endSnapshotDrag = () => {
    snapshotDragState = null;
    document.removeEventListener("pointermove", dragSnapshotWindow);
    document.removeEventListener("pointerup", endSnapshotDrag);
  };

  const syncActionDialogVisibleState = (visible) => {
    actionDialogState.visible = !!visible;
    if (!visible) {
      actionDialogState.busy = false;
      actionDialogState.onSubmit = null;
    }
    if (!actionDialogElements) {
      return;
    }
    if (!visible) {
      actionDialogElements.password.value = "";
      actionDialogElements.password.placeholder = "";
      actionDialogElements.passwordLabel.textContent = "LDAP 비밀번호";
      actionDialogElements.error.textContent = "";
      actionDialogElements.password.disabled = false;
      actionDialogElements.submit.disabled = false;
      actionDialogElements.cancel.disabled = false;
    }
  };

  const setActionDialogVisible = (visible) => {
    syncActionDialogVisibleState(visible);
    if (!actionDialogElements) {
      return;
    }
    setWindowSurfaceVisible(actionDialogElements.surfaceId, visible);
  };

  const beginActionDialogDrag = (event) => {
    if (!actionDialogElements || event.target.closest("button, input, textarea")) {
      return;
    }
    activateWindowSurface(actionDialogElements.surfaceId);
    const rect = actionDialogElements.window.getBoundingClientRect();
    actionDialogDragState = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
    };
    actionDialogElements.window.style.left = `${rect.left}px`;
    actionDialogElements.window.style.top = `${rect.top}px`;
    actionDialogElements.window.style.transform = "none";
    document.addEventListener("pointermove", dragActionDialogWindow);
    document.addEventListener("pointerup", endActionDialogDrag);
  };

  const dragActionDialogWindow = (event) => {
    if (!actionDialogDragState || !actionDialogElements) {
      return;
    }
    const nextLeft = Math.max(24, Math.min(window.innerWidth - 300, event.clientX - actionDialogDragState.offsetX));
    const nextTop = Math.max(72, Math.min(window.innerHeight - 180, event.clientY - actionDialogDragState.offsetY));
    actionDialogElements.window.style.left = `${nextLeft}px`;
    actionDialogElements.window.style.top = `${nextTop}px`;
  };

  const endActionDialogDrag = () => {
    actionDialogDragState = null;
    document.removeEventListener("pointermove", dragActionDialogWindow);
    document.removeEventListener("pointerup", endActionDialogDrag);
  };

  const ensureActionDialog = () => {
    if (actionDialogElements) {
      return actionDialogElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_action_dialog";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-dialog-window" role="dialog" aria-modal="true" aria-label="작업 확인">
        <div class="workstation-file-titlebar workstation-dialog-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon workstation-dialog-title-icon" aria-hidden="true"></span>
            <span class="workstation-dialog-title-text">작업 확인</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-dialog-body">
          <p class="workstation-dialog-body-text"></p>
          <p class="workstation-dialog-detail"></p>
          <label class="workstation-dialog-password-label" for="workstation_action_password">LDAP 비밀번호</label>
          <input id="workstation_action_password" class="workstation-dialog-password" type="password" autocomplete="current-password" spellcheck="false">
          <div class="workstation-dialog-fields" hidden></div>
          <div class="workstation-dialog-progress" hidden>
            <div class="workstation-dialog-progress-text"></div>
            <div class="workstation-dialog-progress-box" aria-hidden="true">
              <div class="workstation-dialog-progress-bar"></div>
            </div>
          </div>
          <div class="workstation-dialog-error" aria-live="polite"></div>
        </div>
        <div class="workstation-dialog-actions">
          <button type="button" class="workstation-file-btn" data-action="cancel">취소</button>
          <button type="button" class="workstation-file-btn" data-action="submit">확인</button>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-dialog-window");
    const titlebar = panel.querySelector(".workstation-dialog-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const title = panel.querySelector(".workstation-dialog-title-text");
    const body = panel.querySelector(".workstation-dialog-body-text");
    const detail = panel.querySelector(".workstation-dialog-detail");
    const progress = panel.querySelector(".workstation-dialog-progress");
    const progressText = panel.querySelector(".workstation-dialog-progress-text");
    const fieldsHost = panel.querySelector(".workstation-dialog-fields");
    const passwordLabel = panel.querySelector(".workstation-dialog-password-label");
    const password = panel.querySelector("#workstation_action_password");
    const error = panel.querySelector(".workstation-dialog-error");
    const cancel = panel.querySelector('[data-action="cancel"]');
    const submit = panel.querySelector('[data-action="submit"]');

    const closeDialog = () => {
      setActionDialogVisible(false);
    };

    closeButton.addEventListener("click", closeDialog);
    cancel.addEventListener("click", closeDialog);
    titlebar.addEventListener("pointerdown", beginActionDialogDrag);
    password.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !submit.disabled) {
        event.preventDefault();
        submit.click();
      }
    });

    submit.addEventListener("click", async () => {
      if (actionDialogState.busy || typeof actionDialogState.onSubmit !== "function") {
        return;
      }
      actionDialogState.busy = true;
      error.textContent = "";
      submit.disabled = true;
      password.disabled = true;
      cancel.disabled = true;
      const fieldInputs = Array.from(fieldsHost.querySelectorAll("[data-action-field]"));
      fieldInputs.forEach((node) => {
        node.disabled = true;
      });
      progress.hidden = false;
      progressText.textContent = actionDialogState.progressText || "작업을 처리하는 중입니다.";
      try {
        const fields = {};
        fieldInputs.forEach((node) => {
          const key = node.getAttribute("data-field-name") || "";
          if (key) {
            fields[key] = node.value;
          }
        });
        await actionDialogState.onSubmit({
          password: password.value,
          fields,
        });
      } catch (submitError) {
        error.textContent = submitError instanceof Error ? submitError.message : "미안합니다.";
      } finally {
        actionDialogState.busy = false;
        submit.disabled = false;
        password.disabled = false;
        cancel.disabled = false;
        fieldInputs.forEach((node) => {
          node.disabled = false;
        });
        progress.hidden = true;
        progressText.textContent = "";
      }
    });

    actionDialogElements = {
      surfaceId: "action-dialog",
      panel,
      window: windowNode,
      title,
      body,
      detail,
      progress,
      progressText,
      fieldsHost,
      passwordLabel,
      password,
      error,
      cancel,
      submit,
      closeDialog,
    };
    registerWindowSurface("action-dialog", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncActionDialogVisibleState(visible);
      },
    });
    return actionDialogElements;
  };

  const positionActionDialog = (anchorElement) => {
    if (!actionDialogElements) {
      return;
    }
    if (!anchorElement || !document.body.contains(anchorElement)) {
      actionDialogElements.window.style.left = "";
      actionDialogElements.window.style.top = "";
      actionDialogElements.window.style.transform = "";
      return;
    }
    const anchorRect = anchorElement.getBoundingClientRect();
    const dialogRect = actionDialogElements.window.getBoundingClientRect();
    const nextLeft = Math.max(
      24,
      Math.min(window.innerWidth - dialogRect.width - 24, anchorRect.left + (anchorRect.width - dialogRect.width) / 2),
    );
    const nextTop = Math.max(
      72,
      Math.min(window.innerHeight - dialogRect.height - 24, anchorRect.top + (anchorRect.height - dialogRect.height) / 2),
    );
    actionDialogElements.window.style.left = `${nextLeft}px`;
    actionDialogElements.window.style.top = `${nextTop}px`;
    actionDialogElements.window.style.transform = "none";
  };

  const openActionDialog = ({
    title,
    body,
    detail,
    submitLabel,
    passwordRequired = false,
    fields = [],
    progressText = "",
    onSubmit,
    anchorElement = null,
  }) => {
    const dialog = ensureActionDialog();
    const parentSurfaceId = resolveWindowSurfaceIdFromElement(anchorElement);
    setWindowSurfaceParent(dialog.surfaceId, parentSurfaceId);
    actionDialogState.title = title || "작업 확인";
    actionDialogState.body = body || "";
    actionDialogState.detail = detail || "";
    actionDialogState.submitLabel = submitLabel || "확인";
    actionDialogState.passwordRequired = passwordRequired;
    actionDialogState.passwordLabel = passwordRequired && passwordRequired.label ? passwordRequired.label : "LDAP 비밀번호";
    actionDialogState.passwordPlaceholder =
      passwordRequired && passwordRequired.placeholder ? passwordRequired.placeholder : "";
    actionDialogState.passwordAutocomplete =
      passwordRequired && passwordRequired.autocomplete ? passwordRequired.autocomplete : "current-password";
    actionDialogState.fields = Array.isArray(fields) ? fields : [];
    actionDialogState.progressText = progressText || "";
    actionDialogState.onSubmit = onSubmit;
    actionDialogState.busy = false;

    dialog.title.textContent = actionDialogState.title;
    dialog.body.textContent = actionDialogState.body;
    dialog.detail.textContent = actionDialogState.detail;
    dialog.fieldsHost.innerHTML = "";
    dialog.fieldsHost.hidden = actionDialogState.fields.length === 0;
    dialog.fieldsHost.style.display = actionDialogState.fields.length ? "grid" : "none";
    actionDialogState.fields.forEach((field) => {
      const wrapper = document.createElement("label");
      wrapper.className = "workstation-dialog-field";
      const label = document.createElement("span");
      label.className = "workstation-dialog-field-label";
      label.textContent = field.label || field.name || "";
      wrapper.appendChild(label);

      let control;
      if (field.type === "textarea") {
        control = document.createElement("textarea");
        control.rows = Math.max(2, Number(field.rows) || 4);
      } else {
        control = document.createElement("input");
        control.type = field.type || "text";
      }
      control.className = "workstation-dialog-input";
      control.setAttribute("data-action-field", "1");
      control.setAttribute("data-field-name", field.name || "");
      control.setAttribute("autocomplete", field.autocomplete || "off");
      control.placeholder = field.placeholder || "";
      control.value = field.value || "";
      control.spellcheck = false;
      wrapper.appendChild(control);
      dialog.fieldsHost.appendChild(wrapper);
    });
    dialog.passwordLabel.textContent = actionDialogState.passwordLabel;
    dialog.passwordLabel.hidden = !passwordRequired;
    dialog.password.hidden = !passwordRequired;
    dialog.passwordLabel.style.display = passwordRequired ? "" : "none";
    dialog.password.style.display = passwordRequired ? "" : "none";
    dialog.password.value = "";
    dialog.password.placeholder = actionDialogState.passwordPlaceholder;
    dialog.password.setAttribute("autocomplete", actionDialogState.passwordAutocomplete);
    dialog.error.textContent = "";
    dialog.submit.textContent = actionDialogState.submitLabel;
    dialog.progress.hidden = true;
    dialog.progressText.textContent = "";
    setActionDialogVisible(true);
    window.requestAnimationFrame(() => {
      positionActionDialog(anchorElement);
    });
    const firstField = dialog.fieldsHost.querySelector("[data-action-field]");
    if (passwordRequired) {
      window.setTimeout(() => dialog.password.focus(), 10);
    } else if (firstField) {
      window.setTimeout(() => firstField.focus(), 10);
    } else {
      window.setTimeout(() => dialog.submit.focus(), 10);
    }
  };

  const requireSnapshotSelection = () => {
    const snapshot = selectedSnapshot();
    if (!snapshot) {
      showStatus("스냅샷을 먼저 선택하십시오.");
      return null;
    }
    return snapshot;
  };

  const ensureSnapshotShell = () => {
    if (snapshotElements) {
      return snapshotElements;
    }

    const panel = document.createElement("section");
    panel.id = "workstation_snapshot_panel";
    panel.hidden = true;
    panel.innerHTML = `
      <div class="workstation-file-window workstation-snapshot-window" role="dialog" aria-modal="false" aria-label="작업공간 스냅샷">
        <div class="workstation-file-titlebar">
          <div class="workstation-file-title">
            <span class="workstation-file-title-icon workstation-snapshot-title-icon" aria-hidden="true"></span>
            <span>작업공간 스냅샷</span>
          </div>
          <button type="button" class="workstation-file-close" aria-label="닫기">×</button>
        </div>
        <div class="workstation-file-toolbar workstation-snapshot-toolbar">
          <button type="button" class="workstation-file-btn workstation-toolbar-btn" data-action="create"><span class="workstation-toolbar-icon workstation-toolbar-icon-create" aria-hidden="true"></span><span class="workstation-toolbar-label">만들기</span></button>
          <button type="button" class="workstation-file-btn workstation-toolbar-btn" data-action="refresh"><span class="workstation-toolbar-icon workstation-toolbar-icon-refresh" aria-hidden="true"></span><span class="workstation-toolbar-label">새로고침</span></button>
          <button type="button" class="workstation-file-btn workstation-toolbar-btn" data-action="rollback"><span class="workstation-toolbar-icon workstation-toolbar-icon-rollback" aria-hidden="true"></span><span class="workstation-toolbar-label">롤백</span></button>
          <button type="button" class="workstation-file-btn workstation-toolbar-btn" data-action="delete"><span class="workstation-toolbar-icon workstation-toolbar-icon-delete" aria-hidden="true"></span><span class="workstation-toolbar-label">삭제</span></button>
          <button type="button" class="workstation-file-btn workstation-toolbar-btn workstation-toolbar-btn-danger" data-action="reset"><span class="workstation-toolbar-icon workstation-toolbar-icon-reset" aria-hidden="true"></span><span class="workstation-toolbar-label">초기화</span></button>
        </div>
        <div class="workstation-file-body">
          <aside class="workstation-file-sidebar workstation-snapshot-sidebar">
            <h3>스냅샷 관리</h3>
            <p><strong>만들기</strong>는 현재 작업공간의 홈, GUI 앱 상태, 브라우저, 메일, Windows 런타임 상태를 지금 시점으로 저장합니다. 제목은 목록에 표시되고, 설명은 입력한 경우에만 마우스 오버 시 보입니다.</p>
            <p><strong>롤백</strong>은 선택한 스냅샷으로 되돌리며, 그 시점 이후에 만든 스냅샷은 함께 정리됩니다.</p>
            <p><strong>삭제</strong>는 선택한 스냅샷과 그보다 최신인 스냅샷을 함께 영구히 제거합니다. 다른 사용자와 서버 전체에는 영향이 없습니다.</p>
            <p><strong>초기화</strong>는 현재 LDAP 비밀번호 확인 후 모든 스냅샷과 사용자 작업공간 상태를 지우고 신규 사용자 첫 접속 기본값으로 다시 시작합니다.</p>
          </aside>
          <div class="workstation-file-main">
            <div class="workstation-file-header workstation-snapshot-header">
              <div>스냅샷</div>
              <div>저장 시각</div>
            </div>
            <div class="workstation-file-list workstation-snapshot-list"></div>
          </div>
        </div>
        <div class="workstation-file-statusbar">
          <div class="workstation-file-pane workstation-file-status-left"></div>
          <div class="workstation-file-pane workstation-file-status-right"></div>
        </div>
      </div>
    `;

    document.body.appendChild(panel);

    const windowNode = panel.querySelector(".workstation-snapshot-window");
    const titlebar = panel.querySelector(".workstation-file-titlebar");
    const closeButton = panel.querySelector(".workstation-file-close");
    const createButton = panel.querySelector('[data-action="create"]');
    const refreshButton = panel.querySelector('[data-action="refresh"]');
    const rollbackButton = panel.querySelector('[data-action="rollback"]');
    const deleteButton = panel.querySelector('[data-action="delete"]');
    const resetButton = panel.querySelector('[data-action="reset"]');
    const list = panel.querySelector(".workstation-snapshot-list");
    const statusLeft = panel.querySelector(".workstation-file-status-left");
    const statusRight = panel.querySelector(".workstation-file-status-right");

    closeButton.addEventListener("click", () => setSnapshotVisible(false));
    createButton.addEventListener("click", () => {
      openActionDialog({
        title: "스냅샷 만들기",
        body: "현재 작업공간 상태를 저장합니다.",
        detail: "제목과 설명은 선택 사항입니다. 제목을 비우면 현재 날짜와 시간이 제목으로 들어가고, 설명을 비우면 목록 hover 설명은 표시되지 않습니다.",
        submitLabel: "만들기",
        passwordRequired: false,
        fields: [
          {
            name: "title",
            label: "스냅샷 제목",
            placeholder: "비워 두면 현재 날짜와 시간으로 저장됩니다.",
          },
          {
            name: "description",
            label: "설명",
            type: "textarea",
            rows: 4,
            placeholder: "선택 사항입니다. 입력하면 목록에서 마우스 오버 시 보입니다.",
          },
        ],
        progressText: "스냅샷을 저장하고 작업공간을 다시 시작하는 중입니다.",
        anchorElement: windowNode,
        onSubmit: async ({ fields }) => {
          const { response, payload } = await postForm("/api/workspace/snapshots/create", {
            title: fields.title || "",
            description: fields.description || "",
          });
          if (!response.ok || !payload.ok) {
            throw new Error(payload.message || "미안합니다.");
          }
          actionDialogElements.closeDialog();
          showStatus(payload.message || "스냅샷을 만들었습니다.");
          setPrepareProgress("스냅샷을 적용하는 중", "작업공간을 다시 연결하는 동안 잠시만 기다려 주세요.");
          reconnectWorkspace(payload.redirect);
        },
      });
    });
    refreshButton.addEventListener("click", () => loadSnapshots());
    rollbackButton.addEventListener("click", () => {
      const snapshot = requireSnapshotSelection();
      if (!snapshot) {
        return;
      }
      openActionDialog({
        title: "스냅샷 롤백",
        body: `"${snapshot.id}" 시점으로 작업공간을 되돌립니다.`,
        detail: "현재 LDAP 비밀번호가 필요하며, 선택한 시점 이후에 만든 스냅샷은 모두 삭제됩니다. 현재 세션은 다시 시작됩니다.",
        submitLabel: "롤백",
        passwordRequired: true,
        progressText: "선택한 스냅샷으로 되돌리고 작업공간을 다시 시작하는 중입니다.",
        anchorElement: windowNode,
        onSubmit: async ({ password }) => {
          const { response, payload } = await postForm("/api/workspace/snapshots/rollback", {
            snapshot_id: snapshot.id,
            password,
          });
          if (!response.ok || !payload.ok) {
            throw new Error(payload.message || "미안합니다.");
          }
          actionDialogElements.closeDialog();
          showStatus(payload.message || "선택한 스냅샷으로 되돌리는 중입니다.");
          setPrepareProgress("스냅샷으로 되돌리는 중", "홈과 앱 상태를 복원하고 작업공간을 다시 연결하고 있습니다.");
          reconnectWorkspace(payload.redirect);
        },
      });
    });
    deleteButton.addEventListener("click", () => {
      const snapshot = requireSnapshotSelection();
      if (!snapshot) {
        return;
      }
      openActionDialog({
        title: "스냅샷 삭제",
        body: `"${snapshot.title || snapshot.id}" 시점과 그보다 최신인 스냅샷을 영구히 삭제합니다.`,
        detail: "현재 LDAP 비밀번호가 필요합니다. 이 작업은 되돌릴 수 없으며, 선택한 스냅샷 이후의 사용자 스냅샷도 함께 제거됩니다.",
        submitLabel: "삭제",
        passwordRequired: true,
        anchorElement: windowNode,
        onSubmit: async ({ password }) => {
          const { response, payload } = await postForm("/api/workspace/snapshots/delete", {
            snapshot_id: snapshot.id,
            password,
          });
          if (!response.ok || !payload.ok) {
            throw new Error(payload.message || "미안합니다.");
          }
          actionDialogElements.closeDialog();
          const newerCount = Number(payload.deleted_newer || 0);
          if (newerCount > 0) {
            showStatus(`스냅샷 ${1 + newerCount}개를 삭제했습니다.`);
          } else {
            showStatus(payload.message || "스냅샷을 삭제했습니다.");
          }
          snapshotState.selectedId = "";
          await loadSnapshots();
        },
      });
    });
    resetButton.addEventListener("click", () => {
      openActionDialog({
        title: "작업공간 초기화",
        body: "현재 사용자의 작업공간을 신규 사용자 첫 접속 상태로 초기화합니다.",
        detail: "현재 LDAP 비밀번호가 필요합니다. 홈 디렉터리, GUI 앱 상태, 브라우저/메일/Windows 런타임 상태와 모든 스냅샷이 삭제되며, 현재 세션은 다시 시작됩니다.",
        submitLabel: "초기화",
        passwordRequired: true,
        progressText: "작업공간을 초기화하고 기본 상태로 다시 만드는 중입니다.",
        anchorElement: windowNode,
        onSubmit: async ({ password }) => {
          const { response, payload } = await postForm("/api/workspace/reset", { password });
          if (!response.ok || !payload.ok) {
            throw new Error(payload.message || "미안합니다.");
          }
          actionDialogElements.closeDialog();
          showStatus(payload.message || "작업공간을 초기화하는 중입니다.");
          setPrepareProgress("작업공간을 초기화하는 중", "기본 상태를 다시 시드하고 작업공간을 다시 연결하고 있습니다.");
          reconnectWorkspace(payload.redirect);
        },
      });
    });
    titlebar.addEventListener("pointerdown", beginSnapshotDrag);
    registerWindowSurface("snapshots", panel, windowNode, {
      onVisibleChange: (visible) => {
        syncSnapshotVisibleState(visible);
      },
    });

    snapshotElements = {
      surfaceId: "snapshots",
      panel,
      window: windowNode,
      list,
      create: createButton,
      refresh: refreshButton,
      rollback: rollbackButton,
      remove: deleteButton,
      reset: resetButton,
      statusLeft,
      statusRight,
    };
    return snapshotElements;
  };

  const createShellButton = ({ id, tooltip, iconClass, onClick }) => {
    const slot = document.createElement("div");
    slot.className = "workstation-bar-slot";

    const button = document.createElement("button");
    button.type = "button";
    button.id = id;
    button.className = "workstation-bar-button";
    button.dataset.tooltip = tooltip;
    button.title = tooltip;
    button.setAttribute("aria-label", tooltip);
    button.setAttribute("aria-pressed", "false");
    button.innerHTML = `<span class="workstation-bar-icon ${iconClass}" aria-hidden="true"></span>`;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      onClick();
    });

    slot.appendChild(button);
    return slot;
  };

  const installBarButtons = () => {
    const bar = document.getElementById("noVNC_control_bar");
    if (!bar || !document.body) {
      return;
    }

    let overlay = document.getElementById("workstation_bar_overlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "workstation_bar_overlay";
      overlay.setAttribute("aria-hidden", "false");
      document.body.appendChild(overlay);
    }

    let shell = document.getElementById("workstation_bar_shell");
    if (!shell) {
      shell = document.createElement("div");
      shell.id = "workstation_bar_shell";
      shell.className = "workstation-bar-shell";
      shell.setAttribute("role", "toolbar");
      shell.setAttribute("aria-label", "작업공간 도구");

      shell.appendChild(
        createShellButton({
          id: "workstation_fullscreen_button",
          tooltip: "전체 화면",
          iconClass: "workstation-bar-icon-fullscreen",
          onClick: () => {
            toggleFullscreen();
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_notifications_button",
          tooltip: "브라우저 알림",
          iconClass: "workstation-bar-icon-notifications",
          onClick: () => {
            setNotificationBridgeEnabled(!notificationState.enabled, { announce: true });
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_terminal_button",
          tooltip: "터미널",
          iconClass: "workstation-bar-icon-terminal",
          onClick: async () => {
            ensureTerminalShell();
            if (terminalState.visible) {
              setTerminalVisible(false);
              return;
            }
            setTerminalVisible(true);
            try {
              await ensureTerminalSession();
            } catch (_error) {
              setTerminalVisible(false);
              showStatus("터미널을 열지 못했습니다.");
              terminalStatus("셸 열기 실패", "");
            }
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_task_manager_button",
          tooltip: "작업 관리자",
          iconClass: "workstation-bar-icon-task-manager",
          onClick: async () => {
            ensureTaskManagerShell();
            if (taskManagerState.visible) {
              setTaskManagerVisible(false);
              return;
            }
            setTaskManagerVisible(true);
            await loadTaskManagerProcesses({ silent: false, preserveScroll: false });
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_files_button",
          tooltip: "파일 전송",
          iconClass: "workstation-bar-icon-files",
          onClick: () => {
            ensureExplorerShell();
            if (explorerState.visible) {
              setExplorerVisible(false);
              return;
            }
            loadExplorer(explorerState.current || "");
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_chat_button",
          tooltip: "채팅",
          iconClass: "workstation-bar-icon-chat",
          onClick: async () => {
            ensureChatShell();
            if (chatState.visible) {
              setChatVisible(false);
              return;
            }
            setChatVisible(true);
            await loadChatUsers({ refreshConversation: false, selectDefault: false });
            scheduleChatPolling();
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_snapshots_button",
          tooltip: "스냅샷",
          iconClass: "workstation-bar-icon-snapshots",
          onClick: () => {
            ensureSnapshotShell();
            if (snapshotState.visible) {
              setSnapshotVisible(false);
              return;
            }
            loadSnapshots();
          },
        }),
      );

      shell.appendChild(
        createShellButton({
          id: "workstation_account_button",
          tooltip: "사용자 설정",
          iconClass: "workstation-bar-icon-account",
          onClick: () => {
            ensureAccountShell();
            if (accountState.visible) {
              setAccountVisible(false);
              return;
            }
            setAccountVisible(true);
          },
        }),
      );
    }

    if (overlay.firstElementChild !== shell) {
      overlay.replaceChildren(shell);
    }
    syncFullscreenButtonState();
    syncNotificationButtonState();
  };

  const boot = () => {
    notificationState.enabled = window.localStorage.getItem("browser_notifications") !== "false";
    applyChrome();
    ensureIme();
    exposeAudioStats();
    autoconnect();
    installBarButtons();
    syncChatUnreadButtonBadge();
    scheduleChatUnreadPolling({ immediate: true });
    installWorkspacePopupFocusHandlers();
    installClipboardImagePaste();
    installClipboardPolling();
    window.addEventListener("message", (event) => {
      if (event && event.data && event.data.action === "enable_audio") {
        resumeAudio();
      }
    });
    window.addEventListener("pointerdown", resumeAudio, { passive: true });
    window.addEventListener("keydown", resumeAudio);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        resetAudioBuffers("visibility-resume");
        resumeAudio();
        pollRichClipboard();
      }
    });
    if (notificationState.enabled) {
      ensureNotificationEventSource();
    }
    resumeAudio();
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
