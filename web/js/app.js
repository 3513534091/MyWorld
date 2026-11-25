/* MyWorld 前端：状态展示 + WebSocket 通道 + 事件日志。
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
    log: $("log"),
    uptime: $("uptime"),
    btnPing: $("btnPing"),
    btnTick: $("btnTick"),
    btnClear: $("btnClear"),
  };

  const MAX_LOG_ROWS = 400;

  const state = {
    ws: null,
    connected: false,
    reconnectDelay: 1000,
    reconnectMax: 15000,
    heartbeat: null,
    pingAt: 0,
    serverUptime: 0,
    syncedAt: 0,
    config: null,
    status: null,
  };

  // ---------------- 日志 ----------------

  function log(level, text) {
    const row = document.createElement("div");
    row.className = "log-row log-" + level;

    const time = document.createElement("span");
    time.className = "log-time";
    time.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });

    const tag = document.createElement("span");
    tag.className = "log-tag";
    tag.textContent = level.toUpperCase();

    const body = document.createElement("span");
    body.className = "log-text";
    body.textContent = text;

    row.append(time, tag, body);
    el.log.append(row);
    while (el.log.childElementCount > MAX_LOG_ROWS) {
      el.log.removeChild(el.log.firstElementChild);
    }
    el.log.scrollTop = el.log.scrollHeight;
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
    log("warn", "未连接，消息未发送：" + payload.type);
    return false;
  }

  // ---------------- WebSocket ----------------

  function connect() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws`;
    log("info", "正在连接 " + url);

    const ws = new WebSocket(url);
    state.ws = ws;

    ws.onopen = () => {
      state.connected = true;
      state.reconnectDelay = 1000;
      setConnection("on", "已连接");
      log("ok", "WebSocket 已建立");
      startHeartbeat();
    };

    ws.onmessage = (event) => {
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        log("warn", "收到非 JSON 消息：" + String(event.data).slice(0, 120));
        return;
      }
      handle(msg);
    };

    ws.onerror = () => log("warn", "WebSocket 异常（细节见浏览器控制台）");

    ws.onclose = (event) => {
      const wasConnected = state.connected;
      state.connected = false;
      stopHeartbeat();
      setConnection("off", "重连中");
      log("warn", `连接断开 code=${event.code}${event.reason ? " reason=" + event.reason : ""}`);
      if (wasConnected) {
        log("info", `将在 ${(state.reconnectDelay / 1000).toFixed(1)}s 后重连`);
      }
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
        log("ok", `握手成功：版本 ${msg.version}，pid ${msg.pid}，端口 ${msg.port}`);
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
        log("info", "收到服务端广播 tick");
        refreshStatus();
        break;

      case "broadcast":
        log("info", "收到广播：" + JSON.stringify(msg.payload));
        break;

      case "ack":
        log("ok", `广播已送达 ${msg.delivered} 个连接`);
        break;

      case "stats":
        fillMeta(msg);
        log("info", "状态已刷新");
        break;

      case "error":
        log("error", "服务端错误：" + msg.message);
        break;

      default:
        log("info", `未知事件 ${msg.kind}：${JSON.stringify(msg)}`);
    }
  }

  // ---------------- REST ----------------

  async function fetchJSON(path, options = {}) {
    const res = await fetch(path, { cache: "no-store", ...options });
    if (!res.ok) throw new Error(`${path} → HTTP ${res.status}`);
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
      log("error", "读取状态失败：" + err.message);
    }
  }

  async function loadConfig() {
    try {
      state.config = await fetchJSON("/api/config");
      const sources = Object.entries(state.config.sources || {})
        .map(([key, value]) => `${key}=${value}`)
        .join("  ");
      log("info", "配置来源：" + sources);
      // 状态可能先到，配置后到：补一次渲染，保证「端口来源」有值
      if (state.status) fillMeta(state.status);
    } catch (err) {
      log("error", "读取配置失败：" + err.message);
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
    if (send({ type: "ping", t: Date.now() })) log("info", "已发送 ping");
  });

  el.btnTick.addEventListener("click", async () => {
    try {
      const result = await fetchJSON("/api/demo/tick", { method: "POST" });
      log("ok", `已触发服务端广播，送达 ${result.delivered} 个连接`);
    } catch (err) {
      log("error", "广播失败：" + err.message);
    }
  });

  el.btnClear.addEventListener("click", () => {
    el.log.replaceChildren();
    log("info", "日志已清空");
  });

  // ---------------- 启动 ----------------

  log("info", "MyWorld 前端启动：" + location.href);
  refreshStatus();
  loadConfig();
  connect();
  setInterval(tickUptime, 1000);
  setInterval(refreshStatus, 15000);
})();
