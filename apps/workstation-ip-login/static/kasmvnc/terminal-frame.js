(function () {
  const config = window.WORKSTATION_TERMINAL_CONFIG || {};
  const websocketPath = typeof config.websocketPath === "string" && config.websocketPath ? config.websocketPath : "/api/workspace-terminal-ws";
  const host = document.getElementById("workstation_terminal_host");
  const empty = document.getElementById("workstation_terminal_empty");
  const menu = document.getElementById("workstation_terminal_menu");
  const menuCopy = menu ? menu.querySelector('[data-action="copy"]') : null;
  const menuPaste = menu ? menu.querySelector('[data-action="paste"]') : null;
  const outputDecoder = new TextDecoder();
  const fitDelayMs = 40;

  let term = null;
  let fitAddon = null;
  let socket = null;
  let socketReady = false;
  let fitTimer = null;
  let resizeObserver = null;

  const waitForNextPaint = () =>
    new Promise((resolve) => {
      window.requestAnimationFrame(() => {
        window.requestAnimationFrame(resolve);
      });
    });

  const waitForHostLayout = async (minimumWidth = 80, minimumHeight = 80, maxFrames = 120) => {
    if (!(host instanceof Element)) {
      return false;
    }
    for (let frame = 0; frame < maxFrames; frame += 1) {
      const rect = host.getBoundingClientRect();
      if (rect.width >= minimumWidth && rect.height >= minimumHeight) {
        return true;
      }
      await waitForNextPaint();
    }
    return false;
  };

  const postToParent = (type, payload = {}) => {
    if (!window.parent || window.parent === window) {
      return;
    }
    window.parent.postMessage(
      {
        source: "workstation-terminal-frame",
        type,
        ...payload,
      },
      window.location.origin,
    );
  };

  const websocketUrl = (path) => {
    const url = new URL(path, window.location.href);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString();
  };

  const setOverlayText = (message) => {
    if (!empty) {
      return;
    }
    empty.textContent = message || "";
    empty.hidden = !message;
  };

  const setStatus = (left, right) => {
    postToParent("status", { left: left || "", right: right || "" });
  };

  const hideMenu = () => {
    if (menu) {
      menu.hidden = true;
    }
  };

  const syncViewportToBottom = () => {
    if (!term) {
      return;
    }
    try {
      term.scrollToBottom();
    } catch (_error) {
      return;
    }
    const viewport = host ? host.querySelector(".xterm-viewport") : null;
    if (viewport) {
      viewport.scrollTop = viewport.scrollHeight;
    }
  };

  const fitNow = () => {
    if (!term || !fitAddon || !host) {
      return;
    }
    const rect = host.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) {
      return;
    }
    try {
      fitAddon.fit();
    } catch (_error) {
      return;
    }
    const cols = term.cols || 0;
    const rows = term.rows || 0;
    if (!cols || !rows) {
      return;
    }
    setStatus(socketReady ? "셸 연결됨" : "셸 연결 중...", `${cols} × ${rows}`);
    if (socketReady && socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: "resize", cols, rows }));
    }
    syncViewportToBottom();
  };

  const scheduleFit = (immediate = false) => {
    window.clearTimeout(fitTimer);
    fitTimer = window.setTimeout(() => {
      fitTimer = null;
      fitNow();
    }, immediate ? 0 : fitDelayMs);
  };

  const focusTerminal = () => {
    if (!term) {
      return;
    }
    postToParent("activate");
    term.focus();
    syncViewportToBottom();
  };

  const sendInput = (text) => {
    if (!text || !socket || socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    socket.send(JSON.stringify({ type: "input", data: String(text) }));
    syncViewportToBottom();
    return true;
  };

  const copySelection = async () => {
    const text = term ? term.getSelection() : "";
    if (!text) {
      postToParent("toast", { message: "복사할 터미널 텍스트가 없습니다." });
      return false;
    }
    try {
      await navigator.clipboard.writeText(text);
      setStatus("선택 텍스트 복사됨", `${text.length}자`);
      postToParent("toast", { message: "터미널 텍스트를 복사했습니다." });
      return true;
    } catch (_error) {
      postToParent("toast", { message: "클립보드 복사에 실패했습니다." });
      return false;
    }
  };

  const pasteIntoTerminal = async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (!text) {
        return false;
      }
      if (!sendInput(text)) {
        postToParent("toast", { message: "터미널이 아직 연결되지 않았습니다." });
        return false;
      }
      setStatus("클립보드 붙여넣기", `${text.length}자`);
      return true;
    } catch (_error) {
      postToParent("toast", { message: "클립보드 읽기에 실패했습니다." });
      return false;
    }
  };

  const updateMenuState = () => {
    if (menuCopy && term) {
      menuCopy.disabled = !term.hasSelection();
    }
  };

  const openMenu = (clientX, clientY) => {
    if (!menu) {
      return;
    }
    updateMenuState();
    const width = 126;
    const height = 60;
    menu.style.left = `${Math.max(4, Math.min(window.innerWidth - width - 4, clientX))}px`;
    menu.style.top = `${Math.max(4, Math.min(window.innerHeight - height - 4, clientY))}px`;
    menu.hidden = false;
  };

  const connectSocket = () => {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
      return;
    }
    socket = new WebSocket(websocketUrl(websocketPath));
    socket.binaryType = "arraybuffer";
    socketReady = false;
    setOverlayText("셸을 연결하는 중입니다.");
    setStatus("셸 연결 중...", "");

    socket.addEventListener("open", () => {
      socketReady = true;
      setOverlayText("");
      scheduleFit(true);
      focusTerminal();
    });

    socket.addEventListener("message", (event) => {
      if (!term) {
        return;
      }
      if (typeof event.data === "string") {
        term.write(event.data);
      } else if (event.data instanceof ArrayBuffer) {
        term.write(outputDecoder.decode(new Uint8Array(event.data), { stream: true }));
      } else if (event.data instanceof Blob) {
        event.data.arrayBuffer().then((buffer) => {
          if (!term) {
            return;
          }
          term.write(outputDecoder.decode(new Uint8Array(buffer), { stream: true }));
        }).catch(() => {});
      }
      setOverlayText("");
      syncViewportToBottom();
    });

    socket.addEventListener("close", () => {
      socketReady = false;
      setOverlayText("터미널 연결이 종료되었습니다. 버튼을 다시 눌러도 기존 셸은 복구되지 않습니다.");
      setStatus("셸 연결 종료", "");
    });

    socket.addEventListener("error", () => {
      socketReady = false;
      setStatus("셸 연결 오류", "");
    });
  };

  const handleParentMessage = (event) => {
    if (event.origin !== window.location.origin) {
      return;
    }
    const data = event.data;
    if (!data || data.source !== "workstation-parent") {
      return;
    }
    if (data.type === "shown") {
      if ((!socket || socket.readyState === WebSocket.CLOSED || socket.readyState === WebSocket.CLOSING) && term) {
        connectSocket();
      }
      scheduleFit(true);
      focusTerminal();
      return;
    }
    if (data.type === "focus") {
      focusTerminal();
      return;
    }
    if (data.type === "resize") {
      scheduleFit(true);
    }
  };

  const installMenuHandlers = () => {
    if (!menu || !menuCopy || !menuPaste) {
      return;
    }
    menuCopy.addEventListener("click", async () => {
      hideMenu();
      await copySelection();
      focusTerminal();
    });
    menuPaste.addEventListener("click", async () => {
      hideMenu();
      await pasteIntoTerminal();
      focusTerminal();
    });
    document.addEventListener("pointerdown", (event) => {
      if (event?.target instanceof Node && menu.contains(event.target)) {
        return;
      }
      hideMenu();
    }, true);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        hideMenu();
      }
    }, true);
    window.addEventListener("resize", hideMenu);
  };

  const failBootstrap = (message, error = null) => {
    if (error) {
      try {
        console.error(error);
      } catch (_ignore) {
        // Ignore console failures in restricted environments.
      }
    }
    setOverlayText(message);
    setStatus("셸 열기 실패", "");
    postToParent("error", { message });
  };

  const bootstrap = async () => {
    if (!host || typeof window.Terminal !== "function" || !window.FitAddon || typeof window.FitAddon.FitAddon !== "function") {
      failBootstrap("터미널 자산을 불러오지 못했습니다.");
      return;
    }
    try {
      setOverlayText("터미널 화면을 준비하는 중입니다.");
      await waitForNextPaint();
      const layoutReady = await waitForHostLayout();
      if (!layoutReady) {
        failBootstrap("터미널 화면 크기를 아직 계산하지 못했습니다.");
        return;
      }

      term = new window.Terminal({
        allowTransparency: false,
        convertEol: true,
        cursorBlink: false,
        cursorStyle: "block",
        fontFamily: '"Liberation Mono", "Nimbus Mono L", monospace',
        fontSize: 14,
        scrollback: 5000,
        theme: {
          background: "#000000",
          foreground: "#c0c0c0",
          cursor: "#ffffff",
          cursorAccent: "#000000",
          selectionBackground: "rgba(0, 0, 128, 0.5)",
          black: "#000000",
          red: "#800000",
          green: "#008000",
          yellow: "#808000",
          blue: "#000080",
          magenta: "#800080",
          cyan: "#008080",
          white: "#c0c0c0",
          brightBlack: "#808080",
          brightRed: "#ff0000",
          brightGreen: "#00ff00",
          brightYellow: "#ffff00",
          brightBlue: "#0000ff",
          brightMagenta: "#ff00ff",
          brightCyan: "#00ffff",
          brightWhite: "#ffffff",
        },
      });
      fitAddon = new window.FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      term.open(host);
      term.onData((data) => {
        sendInput(data);
      });
      term.onSelectionChange(() => {
        updateMenuState();
      });
      term.attachCustomKeyEventHandler((event) => {
        if (event.type !== "keydown") {
          return true;
        }
        if (event.shiftKey && !event.ctrlKey && !event.altKey && event.key === "Insert") {
          event.preventDefault();
          pasteIntoTerminal();
          return false;
        }
        if (event.ctrlKey && !event.shiftKey && !event.altKey && event.key === "Insert") {
          event.preventDefault();
          copySelection();
          return false;
        }
        if (event.ctrlKey && event.shiftKey && !event.altKey && (event.key === "C" || event.key === "c")) {
          event.preventDefault();
          copySelection();
          return false;
        }
        if (event.ctrlKey && event.shiftKey && !event.altKey && (event.key === "V" || event.key === "v")) {
          event.preventDefault();
          pasteIntoTerminal();
          return false;
        }
        return true;
      });

      host.addEventListener("pointerdown", () => {
        postToParent("activate");
      });
      host.addEventListener("contextmenu", (event) => {
        event.preventDefault();
        postToParent("activate");
        openMenu(event.clientX, event.clientY);
        focusTerminal();
      });
      host.addEventListener("paste", (event) => {
        const text = event.clipboardData?.getData("text/plain") || "";
        if (!text) {
          return;
        }
        event.preventDefault();
        sendInput(text);
      });

      document.addEventListener("pointerdown", () => {
        postToParent("activate");
      }, true);
      document.addEventListener("keydown", () => {
        postToParent("activate");
      }, true);
      window.addEventListener("focus", () => {
        postToParent("activate");
      });
      window.addEventListener("message", handleParentMessage);
      window.addEventListener("resize", () => scheduleFit(true));

      if (typeof ResizeObserver === "function") {
        resizeObserver = new ResizeObserver(() => {
          scheduleFit(false);
        });
        resizeObserver.observe(document.documentElement);
        resizeObserver.observe(host);
      }

      installMenuHandlers();
      connectSocket();
      window.requestAnimationFrame(() => {
        scheduleFit(true);
        postToParent("ready");
      });
    } catch (error) {
      failBootstrap("터미널을 초기화하지 못했습니다.", error);
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bootstrap, { once: true });
  } else {
    bootstrap();
  }
})();
