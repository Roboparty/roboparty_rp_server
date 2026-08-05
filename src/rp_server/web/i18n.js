/* ═══════════════════════════════════════════════════════════
   RoboParty i18n  v1.0
   data-i18n="key" in HTML → replaced on load & lang change.
   t('key') for JS strings.
   ═══════════════════════════════════════════════════════════ */
window.RP = window.RP || {};

(function () {
  const KEY = "rp_lang";
  const DICT = {
    /* ── Global / Nav ─────────────────────────────────── */
    "nav.home":              { zh: "首页",           en: "Home" },
    "nav.control":           { zh: "手柄",           en: "Gamepad" },
    "nav.chat":              { zh: "聊天",           en: "Chat" },
    "nav.connected":         { zh: "已连接",         en: "Connected" },
    "nav.disconnected":      { zh: "已断开",         en: "Disconnected" },
    "nav.connecting":        { zh: "连接中",         en: "Connecting" },
    "nav.battery":           { zh: "电池",           en: "Battery" },
    "nav.power":             { zh: "电量",           en: "Power" },

    /* ── Index page ──────────────────────────────────── */
    "index.title":           { zh: "机器人控制台",   en: "Robot Console" },
    "index.sub":             { zh: "三块独立页面：看状态、用手柄控制、和大模型对话。点下面进入。", en: "Three independent pages: monitor status, control with gamepad, chat with the LLM." },
    "index.stat.battery":    { zh: "电池",           en: "Battery" },
    "index.stat.imu":        { zh: "IMU 温度",       en: "IMU Temp" },
    "index.stat.mode":       { zh: "模式",           en: "Mode" },
    "index.stat.version":    { zh: "版本",           en: "Version" },
    "index.mode.mock":       { zh: "模拟",           en: "Mock" },
    "index.mode.real":       { zh: "真机",           en: "Real" },
    "index.card.control":    { zh: "手柄控制",       en: "Gamepad Control" },
    "index.card.control.desc": { zh: "Xbox 造型虚拟手柄，按键与摇杆直接发 AT 指令。", en: "Xbox-style virtual gamepad — buttons and sticks send AT commands." },
    "index.card.chat":       { zh: "大模型聊天",     en: "LLM Chat" },
    "index.card.chat.desc":  { zh: "独立对话页，走 AI Gateway，支持连续会话。", en: "Dedicated chat page via AI Gateway with persistent sessions." },
    "index.card.status":     { zh: "实时推流",       en: "Live Stream" },
    "index.card.status.desc":{ zh: "首页已连接 WebSocket，电量与 IMU 自动更新。", en: "WebSocket-connected — battery & IMU update in real time." },

    /* ── Control page ────────────────────────────────── */
    "control.title":         { zh: "虚拟手柄",       en: "Virtual Gamepad" },
    "control.sub":           { zh: "按真实手柄布局操作。按下发 AT+BTN，拖动摇杆发 AT+JOY。", en: "Operate as a real gamepad. Press sends AT+BTN, drag sticks send AT+JOY." },
    "control.hint":          { zh: "拖动左右摇杆 · 点击按键", en: "Drag sticks · Click buttons" },
    "control.log":           { zh: "通信日志",       en: "Comm Log" },
    "control.custom":        { zh: "自定义 AT…",     en: "Custom AT…" },
    "control.send":          { zh: "发送",           en: "Send" },
    "control.not_connected": { zh: "未连接",          en: "Not connected" },

    /* ── Chat page ───────────────────────────────────── */
    "chat.title":            { zh: "机器人助手",     en: "Robot Assistant" },
    "chat.gateway":          { zh: "DeepSeek · V4 Flash", en: "DeepSeek · V4 Flash" },
    "chat.gateway.mock":     { zh: "模拟回复（未接 DeepSeek）", en: "Mock reply (no DeepSeek)" },
    "chat.gateway.live":     { zh: "连续对话中 · DeepSeek", en: "Live session · DeepSeek" },
    "chat.new_session":      { zh: "新会话",         en: "New Session" },
    "chat.new_started":      { zh: "新会话已开始",   en: "New session started" },
    "chat.placeholder":      { zh: "输入消息，回车发送…", en: "Type a message, Enter to send…" },
    "chat.send":             { zh: "发送",           en: "Send" },
    "chat.greeting":         { zh: "你好，我是 RoboParty 助手。可以问电量、状态，或随便聊。", en: "Hi, I'm the RoboParty assistant. Ask me about battery, status, or anything." },
    "chat.error":            { zh: "出错了：",       en: "Error: " },

    /* ── Demo page ───────────────────────────────────── */
    "demo.brand":            { zh: "控制台",         en: "Console" },
    "demo.hero":             { zh: "机器人后端演示", en: "Robot Backend Demo" },
    "demo.hero.sub":         { zh: "不用看代码。点按钮就能试：传感器、手柄、对话、登录、AI 工具。板上打开同样是这个界面。", en: "No code needed. Click to try: sensors, gamepad, chat, login, AI tools. Same UI on the robot board." },
    "demo.eyebrow.realtime": { zh: "实时",           en: "Live" },
    "demo.section.telemetry":{ zh: "机器人状态",     en: "Robot Status" },
    "demo.section.telemetry.hint": { zh: "电池与姿态自动刷新（WebSocket 推送）", en: "Battery & attitude auto-refresh (WebSocket push)" },
    "demo.stat.battery":     { zh: "电池",           en: "Battery" },
    "demo.stat.imu":         { zh: "IMU 温度",       en: "IMU Temp" },
    "demo.stat.gz":          { zh: "角速度 Z",       en: "Angular Vel Z" },
    "demo.stat.hw":          { zh: "硬件",           en: "Hardware" },
    "demo.hw.ready":         { zh: "就绪",           en: "Ready" },
    "demo.hw.not_ready":     { zh: "未就绪",         en: "Not Ready" },
    "demo.hw.error":         { zh: "异常",           en: "Error" },
    "demo.eyebrow.control":  { zh: "控制",           en: "Control" },
    "demo.section.gamepad":  { zh: "虚拟手柄",       en: "Virtual Gamepad" },
    "demo.section.gamepad.hint": { zh: "按键 / 摇杆 → 发给后端（以后控电机）", en: "Buttons / sticks → send to backend (motor control future)" },
    "demo.joy.hint":         { zh: "拖动摇杆",       en: "Drag stick" },
    "demo.eyebrow.command":  { zh: "指令",           en: "Commands" },
    "demo.section.shortcuts":{ zh: "快捷查询",       en: "Quick Query" },
    "demo.section.shortcuts.hint": { zh: "一键问连接、系统、策略、电机错误", en: "One-tap: connection, system, policy, motor errors" },
    "demo.at.conn":          { zh: "连接状态",       en: "Connection" },
    "demo.at.sysinfo":       { zh: "系统资源",       en: "System" },
    "demo.at.policy":        { zh: "推理状态",       en: "Policy" },
    "demo.at.error":         { zh: "电机错误",       en: "Motor Errors" },
    "demo.at.custom":        { zh: "高级：自定义 AT 命令", en: "Advanced: custom AT command" },
    "demo.eyebrow.log":      { zh: "日志",           en: "Log" },
    "demo.section.log":      { zh: "通信记录",       en: "Comm Log" },
    "demo.section.log.hint": { zh: "发出去的命令、收回来的响应", en: "Sent commands & received responses" },
    "demo.eyebrow.chat":     { zh: "对话",           en: "Chat" },
    "demo.section.chat":     { zh: "和大模型聊天",   en: "Chat with LLM" },
    "demo.section.chat.hint":{ zh: "DeepSeek V4 Flash / V4 Pro", en: "DeepSeek V4 Flash / V4 Pro" },
    "demo.chat.placeholder": { zh: "问点什么…",      en: "Ask something…" },
    "demo.session.none":     { zh: "会话未开始",     en: "Session not started" },
    "demo.session.mock":     { zh: "模拟回复（未接大模型）", en: "Mock reply (no LLM)" },
    "demo.session.live":     { zh: "已连接 AI Gateway · 连续对话中", en: "Connected to AI Gateway · live session" },
    "demo.eyebrow.auth":     { zh: "登录",           en: "Login" },
    "demo.section.auth":     { zh: "扫码登录演示",   en: "QR Login Demo" },
    "demo.section.auth.hint":{ zh: "三步：生成 → 模拟扫码 → 拿 Token", en: "3 steps: Generate → Simulate scan → Get Token" },
    "demo.auth.qr":          { zh: "① 生成登录码",   en: "① Generate QR" },
    "demo.auth.scan":        { zh: "② 模拟手机扫码", en: "② Simulate scan" },
    "demo.auth.poll":        { zh: "③ 领取 Token",   en: "③ Claim Token" },
    "demo.auth.none":        { zh: "还没开始",       en: "Not started" },
    "demo.auth.generated":   { zh: "已生成登录码",   en: "QR generated" },
    "demo.auth.result":      { zh: "扫码结果：",     en: "Scan result: " },
    "demo.auth.user":        { zh: "用户：",         en: "User: " },
    "demo.auth.claim":       { zh: "领取：",         en: "Claim: " },
    "demo.eyebrow.mcp":      { zh: "AI 工具",        en: "AI Tools" },
    "demo.section.mcp":      { zh: "板卡 MCP",       en: "Board MCP" },
    "demo.section.mcp.hint": { zh: "让 AI 能查状态（只读工具）", en: "Let AI query board status (read-only tools)" },
    "demo.mcp.placeholder":  { zh: "点上面的工具看结果…", en: "Click a tool above to see results…" },
    "demo.foot":             { zh: "RoboParty RP Server · 演示界面（非正式 App）", en: "RoboParty RP Server · Demo UI (not production)" },
    "demo.mcp.conn":         { zh: "查连接",         en: "Connection" },
    "demo.mcp.sysinfo":      { zh: "查系统",         en: "System" },
    "demo.mcp.errors":       { zh: "查错误",         en: "Errors" },
    "demo.mcp.policy":       { zh: "查策略",         en: "Policy" },
    "demo.mcp.status":       { zh: "完整状态",       en: "Full Status" },

    /* ── Toolbar (theme / lang toggles) ──────────────── */
    "toolbar.theme":         { zh: "切换主题",       en: "Toggle Theme" },
    "toolbar.lang":          { zh: "EN",             en: "中文" },

    /* ── Status pills ────────────────────────────────── */
    "pill.version":          { zh: "版本",           en: "v" },
    "pill.mode.mock":        { zh: "模拟数据",       en: "Mock Data" },
    "pill.mode.real":        { zh: "真实硬件",       en: "Real HW" },
    "pill.not_connected":    { zh: "未连接",          en: "Disconnected" },

    /* ── Tokens ──────────────────────────────────────── */
    "token":                 { zh: "Token：",        en: "Token: " },

    /* ── Full-screen scroll page ─────────────────────── */
    "full.hero.desc":        { zh: "机器人后端控制台——传感器、手柄、对话、AI 工具，一页全包。", en: "Robot backend console — sensors, gamepad, chat, AI tools. One page, everything." },
    "full.scroll":           { zh: "↓ 向下滚动",      en: "↓ Scroll down" },
    "full.stat.battery":     { zh: "电池",           en: "Battery" },
    "full.stat.version":     { zh: "版本",           en: "Version" },
    "full.stat.mode":        { zh: "模式",           en: "Mode" },
    "full.stat.ws":          { zh: "连接",           en: "Connection" },
    "full.stat.imu":         { zh: "IMU 温度",       en: "IMU Temp" },
    "full.stat.gz":          { zh: "角速度 Z",       en: "Angular Vel Z" },
    "full.stat.hw":          { zh: "硬件",           en: "Hardware" },
    "full.mode.mock":        { zh: "模拟",           en: "Mock" },
    "full.mode.real":        { zh: "真机",           en: "Real" },
    "full.hw.ready":         { zh: "就绪",           en: "Ready" },
    "full.hw.not":           { zh: "未就绪",         en: "Not ready" },
    "full.sec.telemetry":    { zh: "实时数据",       en: "Live Data" },
    "full.telemetry.title":  { zh: "实时遥测",       en: "Real-time Telemetry" },
    "full.telemetry.desc":   { zh: "电池、IMU、角速度——通过 WebSocket 自动刷新。", en: "Battery, IMU, and angular velocity — auto-refreshed via WebSocket." },
    "full.sec.control":      { zh: "控制",           en: "Control" },
    "full.gamepad.title":    { zh: "虚拟手柄 & 快捷指令", en: "Virtual Gamepad & Commands" },
    "full.gamepad.desc":     { zh: "按下按钮、拖动摇杆发送 AT 指令。下方是常用快捷查询。", en: "Press buttons and drag the stick to send AT commands. Quick-query shortcuts below." },
    "full.gamepad.hint":     { zh: "拖动摇杆",       en: "Drag stick" },
    "full.cmd.title":        { zh: "快捷指令",       en: "Quick Commands" },
    "full.cmd.conn":         { zh: "连接状态",       en: "Connection" },
    "full.cmd.sys":          { zh: "系统资源",       en: "System" },
    "full.cmd.policy":       { zh: "推理状态",       en: "Policy" },
    "full.cmd.err":          { zh: "电机错误",       en: "Errors" },
    "full.cmd.custom":       { zh: "自定义 AT…",     en: "Custom AT…" },
    "full.send":             { zh: "发送",           en: "Send" },
    "full.sec.chat":         { zh: "AI",             en: "AI" },
    "full.chat.title":       { zh: "大模型对话",     en: "Chat with LLM" },
    "full.chat.desc":        { zh: "通过 AI Gateway 连接。连续会话。随时问机器人状态。", en: "Connected via AI Gateway. Persistent session. Ask about robot status or anything." },
    "full.chat.placeholder": { zh: "问点什么…",      en: "Ask something…" },
    "full.chat.clear":       { zh: "新会话",         en: "New" },
    "full.chat.idle":        { zh: "就绪",           en: "Ready" },
    "full.chat.mock":        { zh: "模拟回复（未接 Gateway）", en: "Mock reply (no Gateway)" },
    "full.chat.live":        { zh: "连续对话中 · Gateway", en: "Live session · Gateway" },
    "full.chat.cleared":     { zh: "新会话已开始",   en: "Session cleared" },
    "full.sec.tools":        { zh: "工具",           en: "Tools" },
    "full.tools.title":      { zh: "登录 & MCP 工具", en: "Auth & MCP Tools" },
    "full.tools.desc":       { zh: "二维码登录演示和板卡 MCP 工具，查询机器人硬件状态。", en: "QR login demo and board MCP tools for querying robot hardware." },
    "full.auth.title":       { zh: "扫码登录演示",   en: "QR Login Demo" },
    "full.auth.qr":          { zh: "① 生成登录码",   en: "① Generate QR" },
    "full.auth.scan":        { zh: "② 模拟手机扫码", en: "② Simulate scan" },
    "full.auth.poll":        { zh: "③ 领取 Token",   en: "③ Claim Token" },
    "full.auth.idle":        { zh: "还没开始",       en: "Not started" },
    "full.auth.gen":         { zh: "已生成登录码",   en: "QR generated" },
    "full.auth.result":      { zh: "扫码结果：",     en: "Scan result: " },
    "full.auth.user":        { zh: "用户：",         en: "User: " },
    "full.auth.claim":       { zh: "领取：",         en: "Claim: " },
    "full.mcp.title":        { zh: "板卡 MCP",       en: "Board MCP" },
    "full.mcp.placeholder":  { zh: "点上面的工具看结果…", en: "Click a tool to see result…" },
    "full.mcp.conn":         { zh: "查连接",         en: "Connection" },
    "full.mcp.sys":          { zh: "查系统",         en: "System" },
    "full.mcp.err":          { zh: "查错误",         en: "Errors" },
    "full.mcp.policy":       { zh: "查策略",         en: "Policy" },
    "full.mcp.status":       { zh: "完整状态",       en: "Full Status" },
    "full.footer":           { zh: "RoboParty RP Server · v1.1.0 · 演示控制台", en: "RoboParty RP Server · v1.1.0 · Demo Console" },

    /* ── Dashboard (full.html v2) ─────────────────────── */
    "db.ws":                 { zh: "未连接",         en: "Disconnected" },
    "db.mode":               { zh: "模式",           en: "Mode" },
    "db.gamepad":            { zh: "虚拟手柄",       en: "Gamepad" },
    "db.cmds":               { zh: "快捷指令",       en: "Quick Cmds" },
    "db.cmd.conn":           { zh: "连接",           en: "Conn" },
    "db.cmd.sys":            { zh: "系统",           en: "Sys" },
    "db.cmd.policy":         { zh: "策略",           en: "Policy" },
    "db.cmd.err":            { zh: "错误",           en: "Errors" },
    "db.auth":               { zh: "扫码登录",       en: "QR Login" },
    "db.auth.qr":            { zh: "生成码",         en: "QR" },
    "db.auth.scan":          { zh: "模拟扫码",       en: "Scan" },
    "db.auth.poll":          { zh: "领Token",        en: "Token" },
    "db.telemetry":          { zh: "实时遥测",       en: "Telemetry" },
    "db.stat.bat":           { zh: "电池",           en: "Battery" },
    "db.stat.imu":           { zh: "IMU温度",        en: "IMU Temp" },
    "db.stat.gz":            { zh: "角速度Z",        en: "Ang Vel Z" },
    "db.stat.hw":            { zh: "硬件",           en: "Hardware" },
    "db.chat":               { zh: "大模型对话",     en: "LLM Chat" },
    "db.chat.ready":         { zh: "就绪",           en: "Ready" },
    "db.chat.ph":            { zh: "输入消息…",      en: "Message…" },
    "db.chat.clear":         { zh: "新会话",         en: "New" },
    "db.send":               { zh: "发送",           en: "Send" },
    "db.log":                { zh: "通信日志",       en: "Comm Log" },
    "db.at.ph":              { zh: "AT指令…",        en: "AT cmd…" },
    "db.mcp":                { zh: "板卡MCP",        en: "Board MCP" },
    "db.mcp.ph":             { zh: "点工具看结果…",  en: "Click a tool…" },
  };

  /** Simple t() look-up. Falls back to key if missing. */
  function t(key, lang) {
    if (!lang) lang = currentLang();
    const entry = DICT[key];
    if (!entry) {
      console.warn("RP.i18n: missing key", key);
      return key;
    }
    return entry[lang] || entry.en || key;
  }

  /** Get current language. */
  function currentLang() {
    return localStorage.getItem(KEY) || "zh";
  }

  /** Set language & re-render the page. */
  function setLang(lang) {
    if (lang !== "zh" && lang !== "en") return;
    localStorage.setItem(KEY, lang);
    render();
    document.dispatchEvent(new CustomEvent("rp:langchange", { detail: lang }));
  }

  /** Toggle zh ↔ en. */
  function toggleLang() {
    setLang(currentLang() === "zh" ? "en" : "zh");
  }

  /** Walk DOM and replace text in [data-i18n] elements. */
  function render() {
    const lang = currentLang();
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
    document.querySelectorAll("[data-i18n]").forEach(function (el) {
      const key = el.getAttribute("data-i18n");
      // only replace pure text nodes, keep child elements
      if (el.childNodes.length === 1 && el.childNodes[0].nodeType === Node.TEXT_NODE) {
        el.childNodes[0].textContent = t(key, lang);
      } else {
        // mixed content — try to set textContent, but be safe
        el.textContent = t(key, lang);
      }
    });
    // also handle [data-i18n-placeholder]
    document.querySelectorAll("[data-i18n-placeholder]").forEach(function (el) {
      const key = el.getAttribute("data-i18n-placeholder");
      el.placeholder = t(key, lang);
    });
    // handle [data-i18n-title]
    document.querySelectorAll("[data-i18n-title]").forEach(function (el) {
      const key = el.getAttribute("data-i18n-title");
      el.title = t(key, lang);
    });
  }

  // ── init on DOM ready ──
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", render);
  } else {
    render();
  }

  // ── expose ──
  RP.i18n = { t, setLang, toggleLang, currentLang, render, DICT };
})();
