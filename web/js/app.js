/* MyWorld 前端：状态展示 + WebSocket 通道。
 * 页面不放日志面板 —— 运行日志统一由控制台输出；
 * 这里只在浏览器 DevTools 里留 console.debug，便于排查。
 * 无构建步骤，浏览器直接加载。 */

(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const el = {
    version: $("version"),
    port: $("port"),
    latency: $("latency"),
    pill: $("connPill"),
    pillText: $("pillText"),
    meta: $("meta"),
    uptime: $("uptime"),
    btnPing: $("btnPing"),
    btnTick: $("btnTick"),
    btnTheme: $("btnTheme"),
    layout: $("layout"),
    sidebar: $("sidebar"),
    btnSidebar: $("btnSidebar"),
    worldName: $("worldName"),
    worldForm: $("worldForm"),
    btnCreateWorld: $("btnCreateWorld"),
    btnSubmitWorld: $("btnSubmitWorld"),
    btnCancelWorld: $("btnCancelWorld"),
    worldError: $("worldError"),
    worldList: $("worldList"),
    worldEmpty: $("worldEmpty"),
    loadTarget: $("loadTarget"),
    btnLoadWorld: $("btnLoadWorld"),
    loadError: $("loadError"),
    canvasHint: $("canvasHint"),
    canvasWorld: $("canvasWorld"),
    canvasWorldName: $("canvasWorldName"),
    canvasWorldPath: $("canvasWorldPath"),
    btnCloseWorld: $("btnCloseWorld"),
  };

  const state = {
    ws: null,
    connected: false,
    reconnectDelay: 1000,
    reconnectMax: 15000,
    heartbeat: null,
    pingAt: 0,
    failures: 0,
    serverUptime: 0,
    syncedAt: 0,
    config: null,
    status: null,
  };

  // DevTools 里的调试输出，不影响页面
  const debug = (...args) => console.debug("[myworld]", ...args);

  // 页面结构与脚本版本万一不匹配（比如缓存错位），宁可少绑一个事件也别整个脚本崩掉
  const on = (node, event, handler) => {
    if (node) node.addEventListener(event, handler);
  };

  // ---------------- 明暗主题 ----------------

  const THEME_KEY = "myworld.theme";

  function currentTheme() {
    return document.documentElement.dataset.theme === "light" ? "light" : "dark";
  }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    // 图标由 CSS 按 data-theme 切换（暗色显示太阳、浅色显示月亮），这里只更新提示
    const tip = theme === "light" ? "切换到深色" : "切换到浅色";
    el.btnTheme.title = tip;
    el.btnTheme.setAttribute("aria-label", tip);
    // 默认缩略图分深浅两版，切主题时重新取
    refreshThumbnailThemes();
  }

  function initTheme() {
    // index.html 里的内联脚本已经定好初始主题（localStorage → 系统偏好），
    // 这里只负责同步按钮外观与手动切换。
    applyTheme(currentTheme());

    on(el.btnTheme, "click", () => {
      const next = currentTheme() === "light" ? "dark" : "light";
      applyTheme(next);
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        /* 隐私模式下写不进去，忽略 */
      }
    });

    // 用户没手动选过时，跟随系统主题变化
    const media = window.matchMedia("(prefers-color-scheme: light)");
    if (typeof media.addEventListener === "function") {
      media.addEventListener("change", (event) => {
        let stored = null;
        try {
          stored = localStorage.getItem(THEME_KEY);
        } catch {
          stored = null;
        }
        if (!stored) applyTheme(event.matches ? "light" : "dark");
      });
    }
  }

  // ---------------- 左侧功能区 ----------------

  function activatePane(name) {
    document.querySelectorAll(".rail-item").forEach((item) => {
      const active = item.dataset.pane === name;
      item.classList.toggle("is-active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll(".pane").forEach((pane) => {
      pane.hidden = pane.dataset.pane !== name;
    });
    // 世界列表可能被别处改过（比如删了目录），切过去时 reload 一次
    if (name === "world") loadWorlds();
  }

  function initRail() {
    document.querySelectorAll(".rail-item").forEach((item) => {
      if (item.disabled) return;
      on(item, "click", () => activatePane(item.dataset.pane));
    });
  }

  // ---------------- 世界 ----------------

  let selectedWorld = null;
  let selectedItem = null;

  function showWorldError(message) {
    el.worldError.textContent = message;
    el.worldError.hidden = false;
  }

  function clearWorldError() {
    el.worldError.textContent = "";
    el.worldError.hidden = true;
  }

  async function loadWorlds() {
    try {
      const data = await fetchJSON("/api/worlds");
      clearWorldError();
      renderWorlds(Array.isArray(data.items) ? data.items : []);
    } catch (err) {
      showWorldError("读取世界列表失败：" + err.message);
    }
  }

  function renderWorlds(items) {
    el.worldList.replaceChildren();
    el.worldEmpty.hidden = items.length > 0;

    // 选中的世界可能已经不在了
    if (selectedWorld && !items.some((item) => item.name === selectedWorld)) {
      clearSelection();
    }

    for (const item of items) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "world-card";
      card.dataset.name = item.name;
      card.title = `${item.name} · ${formatStartTime(item.created_at)}`;
      if (item.name === selectedWorld) card.classList.add("is-selected");

      const thumb = document.createElement("div");
      thumb.className = "world-thumb";
      const img = document.createElement("img");
      // 没有真实缩略图时，后端按 ?theme= 返回对应的默认图（深/浅两版）
      const thumbBase = `/api/worlds/${encodeURIComponent(item.name)}/thumbnail`;
      img.dataset.thumbBase = thumbBase;
      img.src = `${thumbBase}?theme=${currentTheme()}`;
      img.alt = item.name;
      // 不用 loading="lazy"：动态插入的元素在部分浏览器里不会触发懒加载，
      // 表现就是缩略图一直空着。本地小图直接加载更快也更可靠。
      img.decoding = "async";
      thumb.append(img);

      const name = document.createElement("span");
      name.className = "world-name";
      name.textContent = item.name;

      // 选中标记：浅色圆圈 + 对号，盖在暗色蒙版之上（蒙版由 CSS 负责）
      const check = document.createElement("span");
      check.className = "world-check";
      check.setAttribute("aria-hidden", "true");
      check.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M5.6 12.6l4 4 8.8-9" fill="none" stroke="currentColor"
              stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>`;
      thumb.append(check);

      card.append(thumb, name);
      card.addEventListener("click", () => selectWorld(item, card));
      el.worldList.append(card);
    }
  }

  function selectWorld(item, node) {
    selectedItem = item;
    selectedWorld = item.name;
    el.worldList.querySelectorAll(".world-card").forEach((el2) => {
      el2.classList.toggle("is-selected", el2 === node);
    });
    if (el.loadTarget) {
      el.loadTarget.textContent = item.name;
      el.loadTarget.classList.remove("is-empty");
    }
    if (el.btnLoadWorld) el.btnLoadWorld.disabled = false;
    clearLoadError();
    debug("选择世界", item);
  }

  /* 选中项没了（比如目录被删）就回到未选中状态 */
  function clearSelection() {
    selectedItem = null;
    selectedWorld = null;
    el.worldList.querySelectorAll(".world-card").forEach((card) => {
      card.classList.remove("is-selected");
    });
    if (el.loadTarget) {
      el.loadTarget.textContent = "未选择世界";
      el.loadTarget.classList.add("is-empty");
    }
    if (el.btnLoadWorld) el.btnLoadWorld.disabled = true;
  }

  /* 主题切换后，让默认缩略图跟着换版本 */
  function refreshThumbnailThemes() {
    const theme = currentTheme();
    document.querySelectorAll(".world-card img").forEach((img) => {
      const base = img.dataset.thumbBase;
      if (base) img.src = `${base}?theme=${theme}`;
    });
  }

  // ---------------- 底部加载栏 ----------------

  function showLoadError(message) {
    if (!el.loadError) return;
    el.loadError.textContent = message;
    el.loadError.hidden = false;
  }

  function clearLoadError() {
    if (!el.loadError) return;
    el.loadError.textContent = "";
    el.loadError.hidden = true;
  }

  async function loadSelectedWorld() {
    if (!selectedItem) {
      showLoadError("先选中一个世界");
      return;
    }
    clearLoadError();
    if (el.canvasHint) el.canvasHint.hidden = true;
    if (el.canvasWorld) el.canvasWorld.hidden = false;
    if (el.canvasWorldName) el.canvasWorldName.textContent = selectedItem.name;
    if (el.canvasWorldPath) el.canvasWorldPath.textContent = selectedItem.path;
    debug("加载世界", selectedItem);
  }

  function closeLoadedWorld() {
    if (el.canvasWorld) el.canvasWorld.hidden = true;
    if (el.canvasHint) el.canvasHint.hidden = false;
  }

  function openWorldForm() {
    if (!el.worldForm || !el.btnCreateWorld) return;
    el.btnCreateWorld.hidden = true;
    el.worldForm.hidden = false;
    clearWorldError();
    el.worldName.value = "";
    // 等这一帧渲染完再聚焦，避免元素还没上屏时 focus 无效
    requestAnimationFrame(() => el.worldName?.focus());
  }

  function closeWorldForm() {
    if (!el.worldForm || !el.btnCreateWorld) return;
    el.worldForm.hidden = true;
    el.btnCreateWorld.hidden = false;
    el.worldName.value = "";
    clearWorldError();
  }

  async function createWorld() {
    if (!el.worldName) return;
    const name = el.worldName.value.trim();
    if (!name) {
      showWorldError("先给世界取个名字");
      el.worldName.focus();
      return;
    }

    el.btnSubmitWorld.disabled = true;
    try {
      const created = await fetchJSON("/api/worlds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      closeWorldForm();
      selectedWorld = created.name;
      await loadWorlds();
      const node = el.worldList.querySelector(`.world-card[data-name="${CSS.escape(created.name)}"]`);
      if (node) selectWorld(created, node);
    } catch (err) {
      showWorldError(err.message);
    } finally {
      el.btnSubmitWorld.disabled = false;
    }
  }

  // ---------------- 左侧栏展开/收起 ----------------

  const SIDEBAR_KEY = "myworld.sidebar";

  function applySidebar(collapsed) {
    if (!el.layout || !el.sidebar || !el.btnSidebar) return;
    el.layout.classList.toggle("is-collapsed", collapsed);
    el.btnSidebar.setAttribute("aria-expanded", String(!collapsed));
    el.btnSidebar.title = collapsed ? "展开左侧栏 (Ctrl+B)" : "收起左侧栏 (Ctrl+B)";
    el.sidebar.setAttribute("aria-hidden", String(collapsed));
    // 收起后把面板移出 Tab 顺序
    if ("inert" in HTMLElement.prototype) el.sidebar.inert = collapsed;
  }

  function initSidebar() {
    if (!el.layout || !el.sidebar || !el.btnSidebar) return;

    let stored = null;
    try {
      stored = localStorage.getItem(SIDEBAR_KEY);
    } catch {
      stored = null;
    }
    applySidebar(stored === "collapsed");

    on(el.btnSidebar, "click", () => {
      const collapsed = !el.layout.classList.contains("is-collapsed");
      applySidebar(collapsed);
      try {
        localStorage.setItem(SIDEBAR_KEY, collapsed ? "collapsed" : "open");
      } catch {
        /* 隐私模式写不进去，忽略 */
      }
    });

    document.addEventListener("keydown", (event) => {
      if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "b") {
        event.preventDefault();
        el.btnSidebar.click();
      }
    });
  }

  // ---------------- 连接状态 ----------------

  function setConnection(status, label) {
    el.pill.dataset.state = status;
    el.pillText.textContent = label;
  }

  function send(payload) {
    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify(payload));
      return true;
    }
    debug("未连接，消息未发送", payload);
    return false;
  }

  // ---------------- WebSocket ----------------

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws`;
    debug("连接中", url);

    const ws = new WebSocket(url);
    state.ws = ws;

    ws.onopen = () => {
      state.connected = true;
      state.failures = 0;
      state.reconnectDelay = 1000;
      el.pill.title = "WebSocket 已连接";
      setConnection("on", "已连接");
      startHeartbeat();
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        debug("收到非 JSON 消息", event.data);
        return;
      }
      handle(msg);
    };

    ws.onerror = () => debug("WebSocket 异常");

    ws.onclose = (event) => {
      state.connected = false;
      stopHeartbeat();
      state.failures += 1;
      // 连续失败就别再说“重连中”了：后端多半没起来
      if (state.failures >= 3) {
        setConnection("off", "连不上后端");
        el.pill.title = "没连上本地服务：MyWorld.exe 可能已退出（关闭控制台窗口会停掉它）";
      } else {
        setConnection("off", "重连中");
      }
      debug("断开", event.code, "第", state.failures, "次失败，", state.reconnectDelay, "ms 后重连");
      scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    const delay = state.reconnectDelay;
    state.reconnectDelay = Math.min(state.reconnectDelay * 1.7, state.reconnectMax);
    setTimeout(() => {
      if (!state.connected) connect();
    }, delay);
  }

  function startHeartbeat() {
    stopHeartbeat();
    ping();
    state.heartbeat = setInterval(ping, 10000);
  }

  function stopHeartbeat() {
    if (state.heartbeat) clearInterval(state.heartbeat);
    state.heartbeat = null;
  }

  function ping() {
    state.pingAt = performance.now();
    send({ type: "ping", t: Date.now() });
  }

  // ---------------- 服务端消息 ----------------

  function handle(msg) {
    switch (msg.kind) {
      case "hello":
        state.serverUptime = Number(msg.uptime_seconds || 0);
        state.syncedAt = performance.now();
        el.version.textContent = "v" + (msg.version || "?");
        el.port.textContent = msg.port ?? "—";
        debug("握手成功", msg);
        break;

      case "pong": {
        const rtt = Math.max(0, Math.round(performance.now() - state.pingAt));
        el.latency.textContent = rtt + " ms";
        if (typeof msg.uptime_seconds === "number") {
          state.serverUptime = msg.uptime_seconds;
          state.syncedAt = performance.now();
        }
        break;
      }

      case "tick":
        debug("收到服务端推送", msg);
        refreshStatus();
        break;

      case "broadcast":
        debug("收到广播", msg.payload);
        break;

      case "ack":
        debug("广播已送达", msg.delivered);
        break;

      case "stats":
        fillMeta(msg);
        break;

      case "error":
        debug("服务端错误", msg.message);
        break;

      default:
        debug("未知事件", msg);
    }
  }

  // ---------------- REST ----------------

  async function fetchJSON(path, options = {}) {
    const res = await fetch(path, { cache: "no-store", ...options });
    if (!res.ok) {
      // 后端的 HTTPException 会把可读原因放在 detail 里，直接透给用户
      let detail = `${path} → HTTP ${res.status}`;
      try {
        const body = await res.json();
        if (body && body.detail) {
          detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        }
      } catch {
        /* 响应不是 JSON，保持默认信息 */
      }
      throw new Error(detail);
    }
    return res.json();
  }

  async function refreshStatus() {
    try {
      state.status = await fetchJSON("/api/status");
      fillMeta(state.status);
      el.port.textContent = state.status.port;
      el.version.textContent = "v" + state.status.version;
      if (typeof state.status.uptime_seconds === "number") {
        state.serverUptime = state.status.uptime_seconds;
        state.syncedAt = performance.now();
      }
    } catch (err) {
      debug("读取状态失败", err.message);
    }
  }

  async function loadConfig() {
    try {
      state.config = await fetchJSON("/api/config");
      // 状态可能先到、配置后到：补一次渲染，保证「端口来源」有值
      if (state.status) fillMeta(state.status);
    } catch (err) {
      debug("读取配置失败", err.message);
    }
  }

  // ---------------- 渲染 ----------------

  function pair(label, value) {
    const dt = document.createElement("dt");
    dt.textContent = label;
    const dd = document.createElement("dd");
    dd.textContent = value;
    return [dt, dd];
  }

  function formatStartTime(iso) {
    if (!iso) return "—";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return iso;
    return date.toLocaleString("zh-CN", { hour12: false });
  }

  function fillMeta(s) {
    el.meta.replaceChildren(
      ...pair("监听地址", `${s.host}:${s.port}`),
      ...pair("端口来源", state.config?.sources?.port ?? "—"),
      ...pair("启动时间", formatStartTime(s.started_at)),
      ...pair("Python", s.python ?? "—"),
      ...pair("PID", String(s.pid ?? "—")),
      ...pair("请求数", String(s.requests ?? "—")),
      ...pair("广播事件", String(s.events_published ?? "—")),
      ...pair("平台", s.platform ?? "—"),
    );
  }

  function formatDuration(totalSeconds) {
    const total = Math.max(0, Math.floor(totalSeconds));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
  }

  function tickUptime() {
    if (!state.syncedAt) return;
    const seconds = state.serverUptime + (performance.now() - state.syncedAt) / 1000;
    el.uptime.textContent = "运行 " + formatDuration(seconds);
  }

  // ---------------- 交互 ----------------

  el.btnPing.addEventListener("click", () => {
    if (send({ type: "ping", t: Date.now() })) debug("已发送 ping");
  });

  el.btnTick.addEventListener("click", async () => {
    try {
      const result = await fetchJSON("/api/demo/tick", { method: "POST" });
      debug("已触发服务端推送", result);
    } catch (err) {
      debug("推送失败", err.message);
    }
  });

  // ---------------- 启动 ----------------

  initTheme();
  initRail();
  initSidebar();
  on(el.btnCreateWorld, "click", openWorldForm);
  on(el.btnCancelWorld, "click", closeWorldForm);
  on(el.btnLoadWorld, "click", loadSelectedWorld);
  on(el.btnCloseWorld, "click", closeLoadedWorld);
  on(el.worldForm, "submit", (event) => {
    event.preventDefault();
    createWorld();
  });
  on(el.worldName, "keydown", (event) => {
    if (event.key === "Escape") closeWorldForm();
  });
  refreshStatus();
  loadConfig();
  loadWorlds();
  connect();
  setInterval(tickUptime, 1000);
  setInterval(refreshStatus, 15000);
})();
