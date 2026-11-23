/**
 * WorkBuddy 自动签到 + 派猫猫旅行 —— 金山文档 / WPS AirScript 云端版（真·不开机）
 * ================================================================================
 * 部署：金山文档 → 新建「智能表格」→ 效率 → 高级开发 → AirScript 脚本编辑器
 *       → 新建脚本 → 粘贴本文件全部内容 → 保存
 *       → 编辑器「服务」里勾选「网络 API」（不加这个 HTTP 对象不存在！）
 *       → 效率 → 高级开发 → 定时任务 → 每天 09:00（可再加 21:00 兜底）→ 关联本脚本
 *
 * 表格约定（脚本自动创建名为「WorkBuddy签到」的工作表和表头）：
 *   B1 = refresh_token（必填；脚本每次运行自动换新并回写，永久有效，不用再手动取）
 *   B3 = 接口地址（留空即默认 https://copilot.tencent.com）
 *   A5/B5 = 签到结论   A6/B6 = 猫猫结论   A7/B7 = 整体   A8/B8 = 上次运行时间
 *   A9/B9 = 微信推送 SendKey（可选，Server酱；留空则不推送）  A10/B10 = 微信推送结果
 *
 * 幂等：今日已签不重复领；猫猫先领已到家的礼物，在旅行中不重派，名额用完不重派。
 * 安全：B1 等于账号钥匙，文档权限务必设为「仅自己可见」，绝不分享。
 *
 * 接口来源：WorkBuddy 桌面端 v5.9.3 程序包提取 + 本机实测 HTTP 200（非猜测）。
 * 兼容：AirScript 2.0（ET JSAPI）与 1.0（databook）双兼容，运行时自动探测。
 * 注意：AirScript 不支持 async/await，全部用同步 HTTP.fetch；域名不能带端口/IP；超时上限 60s。
 */

var ENDPOINT_DEFAULT = "https://copilot.tencent.com";
var SHEET_NAME = "WorkBuddy签到";
var XL_WORKSHEET = -4167;
var MAX_RETRY = 3;
var NO_NETWORK = -1;

// ---------------------------------------------------------------- 基础工具
function log(msg) { try { console.log(msg); } catch (e) {} }

function dig() {
  var obj = arguments[0];
  for (var i = 1; i < arguments.length; i++) {
    var k = arguments[i];
    if (obj && typeof obj === "object" && obj[k] !== undefined && obj[k] !== null) obj = obj[k];
    else return null;
  }
  return obj;
}
function masked(text) {
  if (text && typeof text === "object" && !Array.isArray(text)) {
    var out = {};
    for (var k in text) if (Object.prototype.hasOwnProperty.call(text, k)) out[k] = masked(text[k]);
    return out;
  }
  if (Array.isArray(text)) { var a = []; for (var i = 0; i < text.length; i++) a.push(masked(text[i])); return a; }
  if (typeof text === "string" && text.length > 24) return text.slice(0, 6) + "***" + text.slice(-4);
  return text;
}
function parseJson(raw) { try { return JSON.parse(raw); } catch (e) { return { raw: String(raw).slice(0, 300) }; } }
function asInt(v, d) { var n = parseInt(v, 10); return isNaN(n) ? (d || 0) : n; }

/** 统一请求：带重试（3xx/5xx/网络异常退避），返回 [code, body]。 */
function request(method, url, headers, payload) {
  var attempt = 0;
  while (true) {
    attempt++;
    try {
      var opts = { method: method, timeout: 20000, headers: headers };
      if (method === "POST" && payload !== null && payload !== undefined) opts.body = JSON.stringify(payload);
      var resp = HTTP.fetch(url, opts);
      var code = resp.status, body;
      try { body = resp.json(); } catch (e1) {
        try { body = parseJson(resp.text()); } catch (e2) { body = { raw: "unparseable" }; }
      }
      if (attempt < MAX_RETRY && ((code >= 300 && code < 400) || code >= 500)) {
        log("  · HTTP " + code + "，重试 " + attempt + "/" + MAX_RETRY);
        Time.sleep(1500 * attempt);
        continue;
      }
      return [code, body];
    } catch (e) {
      if (attempt >= MAX_RETRY) return [NO_NETWORK, { error: String(e) }];
      log("  · 请求异常，重试 " + attempt + "/" + MAX_RETRY + "：" + String(e));
      Time.sleep(1500 * attempt);
    }
  }
}
function get(url, headers) { return request("GET", url, headers, null); }
function post(url, headers, payload) { return request("POST", url, headers, payload === undefined ? null : payload); }
function apiOk(code, body) {
  if (code < 200 || code >= 300) return false;
  if (body && typeof body === "object" && body.code !== undefined && body.code !== 0 && body.code !== "0") return false;
  return true;
}
function unwrap(body) {
  if (body && typeof body === "object" && body.data && typeof body.data === "object") return body.data;
  return body && typeof body === "object" ? body : {};
}

// ---------------------------------------------------------------- token：refreshToken 自动续期
/** 用 B1 的 refreshToken 换新 accessToken + 新 refreshToken。
 *  返回 {ok, accessToken, newRefreshToken, err}；每次成功都回写新 refreshToken → 永久有效。 */
function refreshToken(rt, endpoint) {
  var headers = {
    "Content-Type": "application/json",
    "X-Refresh-Token": rt,
    "X-Auth-Refresh-Source": "plugin",
    "X-Domain": "copilot.tencent.com",
    "User-Agent": "Mozilla/5.0 WorkBuddy/5.9.3"
  };
  var r = post(endpoint + "/v2/plugin/auth/token/refresh", headers, {});
  var code = r[0], body = r[1];
  log("  [refresh] HTTP " + code + " " + JSON.stringify(masked(body)));
  if (code === NO_NETWORK) return { ok: false, err: "网络不可达，无法刷新令牌" };
  if (code === 401 || code === 403) return { ok: false, err: "refreshToken 已失效（HTTP " + code + "），请重新导出并粘贴到 B1" };
  var data = unwrap(body);
  var at = dig(data, "accessToken") || dig(body, "accessToken");
  if (!at) return { ok: false, err: "刷新未返回 accessToken：code=" + dig(body, "code") + " msg=" + dig(body, "msg") };
  var nrt = dig(data, "refreshToken") || dig(body, "refreshToken") || rt;
  return { ok: true, accessToken: at, newRefreshToken: nrt };
}

function bizHeaders(accessToken, uid) {
  return {
    "Accept": "application/json",
    "Authorization": "Bearer " + accessToken,
    "Content-Type": "application/json",
    "X-User-Id": uid,
    "X-Domain": "www.workbuddy.cn",
    "X-Product-Code": "workbuddy",
    "User-Agent": "Mozilla/5.0 WorkBuddy/5.9.3",
    "Referer": "https://www.workbuddy.cn/"
  };
}

// ---------------------------------------------------------------- 签到
function fmtAlready(status, via) {
  if (!via) via = "今日已签过";
  var parts = [];
  if (dig(status, "today_credit") !== null) parts.push("今日 +" + dig(status, "today_credit"));
  if (dig(status, "streak_days") !== null) parts.push("连续 " + dig(status, "streak_days") + " 天");
  if (dig(status, "total_credits") !== null) parts.push("累计 " + dig(status, "total_credits") + " 积分");
  return parts.length ? via + "（" + parts.join("，") + "）" : via;
}
function alreadySigned(body) {
  if (body && typeof body === "object") {
    if (body.code === 10001 || String(body.msg || "").indexOf("已签") >= 0) return true;
  }
  return false;
}
function runCheckin(headers, endpoint) {
  var r = post(endpoint + "/v2/billing/meter/checkin-activity-status", headers, {});
  var scode = r[0], sbody = r[1];
  log("  [签到-状态] HTTP " + scode + " " + JSON.stringify(masked(sbody)));
  if (scode === NO_NETWORK) return [false, { result: "NETWORK", report: "网络不可达，签到未完成" }];
  if (scode === 401 || scode === 403) return [false, { result: "AUTH", report: "认证被拒（HTTP " + scode + "）" }];
  if (scode < 200 || scode >= 300) {
    // 状态接口异常时尝试直接领（幂等由服务端保证）
    var rc = post(endpoint + "/v2/billing/meter/daily-checkin", headers, {});
    if (apiOk(rc[0], rc[1]) || alreadySigned(rc[1])) return [true, { result: "CLAIMED", report: "签到完成（状态查询异常但领取成功）" }];
    return [false, { result: "ERROR", report: "状态接口异常（HTTP " + scode + "）" }];
  }
  var status = unwrap(sbody);
  if (dig(status, "active") === false) return [true, { result: "INACTIVE", report: "签到活动未开启" }];
  if (dig(status, "today_checked_in") === true || dig(status, "today_checked_in") === 1) {
    return [true, { result: "ALREADY", report: fmtAlready(status) }];
  }
  var r2 = post(endpoint + "/v2/billing/meter/daily-checkin", headers, {});
  var ccode = r2[0], cbody = r2[1];
  log("  [签到-领取] HTTP " + ccode + " " + JSON.stringify(masked(cbody)));
  if (ccode === NO_NETWORK) return [false, { result: "NETWORK", report: "领取请求未送达" }];
  if (ccode === 401 || ccode === 403) return [false, { result: "AUTH", report: "认证被拒（HTTP " + ccode + "）" }];
  if (alreadySigned(cbody)) {
    var rf = post(endpoint + "/v2/billing/meter/checkin-activity-status", headers, {});
    return [true, { result: "ALREADY", report: fmtAlready(unwrap(rf[1]), "服务端判定今日已签") }];
  }
  var credit = dig(unwrap(cbody), "credit");
  if (credit !== null && credit !== undefined) {
    var rf2 = post(endpoint + "/v2/billing/meter/checkin-activity-status", headers, {});
    var s = unwrap(rf2[1]), tail = "";
    var streak = dig(s, "streak_days"), cum = dig(s, "total_credits");
    if (streak !== null) tail = "（连续 " + streak + " 天" + (cum !== null ? "，累计 " + cum + " 积分" : "") + "）";
    return [true, { result: "CLAIMED", report: "成功领取 " + credit + " 积分" + tail }];
  }
  if (apiOk(ccode, cbody)) return [true, { result: "CLAIMED", report: "签到成功" }];
  return [false, { result: "ERROR", report: "领取失败：" + (dig(cbody, "msg") || dig(cbody, "code") || "未知") + "（HTTP " + ccode + "）" }];
}

// ---------------------------------------------------------------- 猫猫
function fmtEta(arriveAt, serverNow) {
  if (arriveAt === null || serverNow === null) return "";
  var left = asInt(arriveAt, NaN) - asInt(serverNow, NaN);
  if (isNaN(left)) return "";
  if (left <= 0) return "，已到家待领";
  if (left < 3600) return "，约 " + Math.max(1, Math.floor(left / 60)) + " 分钟后到家";
  return "，约 " + (left / 3600).toFixed(1) + " 小时后到家";
}
function runBuddy(headers, endpoint, locationId) {
  var base = endpoint + "/v2/activity/growth/buddy";
  var notes = [];
  try {
    var r = get(base + "/travel/status", headers);
    var code = r[0], body = r[1];
    log("  [猫猫-状态] HTTP " + code + " " + JSON.stringify(masked(body)));
    if (code === NO_NETWORK) return { result: "NETWORK", report: "网络不可达，猫猫未处理" };
    if (code === 401 || code === 403) return { result: "AUTH", report: "猫猫认证被拒（HTTP " + code + "）" };
    if (code < 200 || code >= 300) return { result: "ERROR", report: "旅行状态接口异常（HTTP " + code + "）" };
    var tb = unwrap(body);
    var state = dig(tb, "state"), limit = !!dig(tb, "daily_limit_reached");
    // 1) 已到家 → 先领礼物
    if (state === "arrived") {
      var rc = post(base + "/travel/claim", headers, { record_id: dig(tb, "record_id") });
      var got = dig(unwrap(rc[1]), "reward_credit");
      log("  [猫猫-领礼物] HTTP " + rc[0] + " " + JSON.stringify(masked(rc[1])));
      if (apiOk(rc[0], rc[1]) && got !== null && got !== undefined) { notes.push("领旅行礼物 +" + got + " 积分"); state = "idle"; }
      else return { result: "ERROR", report: "领旅行礼物失败：" + (dig(rc[1], "msg") || "未知"), notes: notes };
    } else if (state === "traveling") {
      notes.push("旅行中（" + (dig(tb, "location", "name") || "?") + fmtEta(dig(tb, "arrive_at"), dig(tb, "server_now")) + "）");
      return { result: "IN_TRIP", report: notes.join("；") };
    }
    // 2) idle 且未达上限 → 派新一趟
    if (state === "idle") {
      if (limit) return { result: "LIMIT_REACHED", report: "今日旅行名额已用完，不重派" };
      var rd = post(base + "/travel/depart", headers, { location_id: locationId || 1 });
      log("  [猫猫-派出] HTTP " + rd[0] + " " + JSON.stringify(masked(rd[1])));
      if (rd[0] >= 200 && rd[0] < 300) {
        var d = unwrap(rd[1]);
        return { result: "DEPARTED", report: "已派猫猫去" + (dig(d, "location", "name") || "目的地") };
      }
      var msg = String(dig(unwrap(rd[1]), "msg") || dig(rd[1], "msg") || "");
      if (msg.toLowerCase().indexOf("limit") >= 0 || rd[0] === 429) return { result: "LIMIT_REACHED", report: "今日旅行名额已用完" };
      return { result: "ERROR", report: "派出失败：" + (msg || "未知") + "（HTTP " + rd[0] + "）" };
    }
    return { result: "UNKNOWN_STATE", report: "未识别的旅行状态：" + state };
  } catch (e) {
    return { result: "ERROR", report: "猫猫模块异常：" + String(e) };
  }
}

// ---------------------------------------------------------------- 表格读写（1.0 / 2.0 兼容层）
function sheetsColl() { return Application.Sheets ? Application.Sheets : (Application.Worksheets || null); }
function getSheet(name) {
  var c = sheetsColl(); if (!c) return null;
  try { return c.Item(name); } catch (e) {}
  try { return c(name); } catch (e) {}
  return null;
}
function activeSheetName() { try { return Application.ActiveSheet && Application.ActiveSheet.Name; } catch (e) { return null; } }
function addSheet(name) {
  var c = sheetsColl(); if (!c) return null;
  var after = activeSheetName();
  try { return c.Add(null, after, 1, XL_WORKSHEET, name); } catch (e) {}
  var s = null;
  try { s = c.Add(null, after, 1, XL_WORKSHEET); } catch (e) {}
  if (s) { try { s.Name = name; } catch (e) {} return s; }
  return null;
}
function ensureSheet() {
  var s = getSheet(SHEET_NAME);
  if (!s) { s = addSheet(SHEET_NAME); s = getSheet(SHEET_NAME) || s; }
  if (s) { try { s.Activate(); } catch (e) {} }
}
function rangeAt(addr) {
  try { return Application.Range(addr); } catch (e) {}
  try { return Application.ActiveSheet.Range(addr); } catch (e) {}
  return null;
}
function cleanVal(v) {
  if (v === null || v === undefined) return "";
  if (typeof v === "function") return "";
  if (Array.isArray(v)) { var f = v[0]; v = (f && typeof f === "object" && Array.isArray(f)) ? f[0] : f; if (v === null || typeof v === "object") return ""; }
  if (typeof v === "object") return "";
  return String(v).replace(/^\s+|\s+$/g, "");
}
function readCell(addr) {
  var r = rangeAt(addr); if (!r) return "";
  var v;
  try { v = r.Value2; var a = cleanVal(v); if (a !== "") return a; } catch (e) {}
  try { v = r.Value(); var b = cleanVal(v); if (b !== "") return b; } catch (e) {}
  try { return cleanVal(r.Text); } catch (e) {}
  return "";
}
function writeCell(addr, value) {
  var r = rangeAt(addr); if (!r) return false;
  try { r.Value2 = value; return true; } catch (e) {}
  try { r.Value(null, value); return true; } catch (e) {}
  try { r.Value = value; return true; } catch (e) {}
  return false;
}
function ensureLabels() {
  var labels = { A1: "refresh_token（B1 粘贴，自动续期）", A3: "接口地址", A5: "签到结论", A6: "猫猫结论", A7: "整体", A8: "上次运行时间", A9: "微信推送SendKey（可选）", A10: "微信推送结果" };
  for (var a in labels) if (Object.prototype.hasOwnProperty.call(labels, a) && readCell(a) === "") writeCell(a, labels[a]);
  if (readCell("B3") === "") writeCell("B3", ENDPOINT_DEFAULT);
}
function nowBeijing() {
  try {
    var d = new Date(Date.now() + 8 * 3600 * 1000);
    function p(n) { return (n < 10 ? "0" : "") + n; }
    return d.getUTCFullYear() + "-" + p(d.getUTCMonth() + 1) + "-" + p(d.getUTCDate()) + " " + p(d.getUTCHours()) + ":" + p(d.getUTCMinutes()) + ":" + p(d.getUTCSeconds());
  } catch (e) { return ""; }
}

// ---------------------------------------------------------------- 微信推送（Server酱，可选；失败绝不影响签到主流程）
/** 用 B9 的 SendKey 把今天的结论推一条到微信。免费 5 条/天，够用。
 *  SCT 开头 → sctapi.ftqq.com；sctp 开头 → {uid}.push.ft07.com。成功返回 code=0。 */
function pushWechat(sendKey, title, desp) {
  if (!sendKey) return { sent: false, msg: "未填 SendKey，跳过" };
  var url, m = /^sctp(\d+)t/.exec(sendKey);
  if (m) url = "https://" + m[1] + ".push.ft07.com/send/" + sendKey + ".send";
  else url = "https://sctapi.ftqq.com/" + sendKey + ".send";
  var payload = { title: String(title).replace(/[\r\n]+/g, " ").slice(0, 100), desp: String(desp).slice(0, 30000) };
  try {
    var r = post(url, { "Content-Type": "application/json;charset=utf-8" }, payload);
    var code = r[0], body = r[1];
    log("  [微信推送] HTTP " + code + " " + JSON.stringify(masked(body)));
    if (code >= 200 && code < 300 && body && (body.code === 0 || body.code === "0")) return { sent: true, msg: "已推送微信" };
    if (code === NO_NETWORK) return { sent: false, msg: "推送网络不可达" };
    return { sent: false, msg: "推送未成功（HTTP " + code + "，" + (dig(body, "message") || dig(body, "msg") || dig(body, "errno") || "未知") + "）" };
  } catch (e) { return { sent: false, msg: "推送异常：" + String(e) }; }
}

// ---------------------------------------------------------------- 表格美化（全部容错，失败绝不影响签到）
function rgb(r, g, b) { return r + g * 256 + b * 65536; }
function paint(addr, o) {
  var r = rangeAt(addr); if (!r) return;
  try { if (o.fill !== undefined) r.Interior.Color = o.fill; } catch (e) {}
  try { if (o.bold !== undefined) r.Font.Bold = o.bold; } catch (e) {}
  try { if (o.size) r.Font.Size = o.size; } catch (e) {}
  try { if (o.color !== undefined) r.Font.Color = o.color; } catch (e) {}
  try { if (o.wrap !== undefined) r.WrapText = o.wrap; } catch (e) {}
  try { if (o.halign !== undefined) r.HorizontalAlignment = o.halign; } catch (e) {}
}
function beautify() {
  var C = {
    labelBg: rgb(235, 241, 250), labelFg: rgb(31, 78, 121),
    okBg: rgb(214, 243, 219), badBg: rgb(255, 220, 220),
    catBg: rgb(255, 241, 214), muted: rgb(140, 140, 140), ink: rgb(32, 32, 32)
  };
  var xlLeft = -4131;
  // A 列标签：浅蓝底 + 深蓝加粗字
  try { var ar = rangeAt("A1:A10"); if (ar) { ar.Font.Bold = true; ar.Font.Color = C.labelFg; ar.Interior.Color = C.labelBg; } } catch (e) {}
  // B 列数据：左对齐自动换行
  try { var br = rangeAt("B1:B10"); if (br) { br.WrapText = true; br.HorizontalAlignment = xlLeft; br.Font.Color = C.ink; } } catch (e) {}
  // 密钥/接口等长文本：小字灰，密钥不换行
  paint("B1", { size: 9, color: C.muted, wrap: false });
  paint("B3", { size: 10, color: C.muted });
  paint("B9", { size: 9, color: C.muted });
  paint("B10", { size: 10, color: C.muted });
  // 结论区：按成功/失败上色
  var ok = readCell("B5").indexOf("✅") >= 0;
  paint("B5", { bold: true, fill: ok ? C.okBg : C.badBg, wrap: true });
  paint("B6", { bold: true, fill: C.catBg, wrap: true });
  paint("B7", { bold: true, fill: ok ? C.okBg : C.badBg });
  paint("B8", { size: 10, color: C.muted });
  // 列宽 + 行高（多路径尝试，兼容 1.0/2.0）
  try { var sh = Application.ActiveSheet; sh.Columns.Item(1).ColumnWidth = 22; sh.Columns.Item(2).ColumnWidth = 68; }
  catch (e) { try { rangeAt("A:A").ColumnWidth = 22; rangeAt("B:B").ColumnWidth = 68; } catch (e2) {} }
  try { var rs = Application.ActiveSheet.Rows; for (var i = 1; i <= 10; i++) { try { rs.Item(i).RowHeight = 24; } catch (e3) {} } } catch (e4) {}
}

/** 从 JWT 的 payload 解析用户 ID（sub），避免在脚本里写死任何账号。
 *  AirScript 环境若无 atob，用内置 base64 解码兜底。 */
function uidFromToken(token) {
  try {
    var seg = token.split(".")[1];
    seg = seg.replace(/-/g, "+").replace(/_/g, "/");
    while (seg.length % 4) seg += "=";
    var json;
    if (typeof atob === "function") {
      json = decodeURIComponent(escape(atob(seg)));
    } else {
      var chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
      var out = "", i = 0;
      while (i < seg.length) {
        var c1 = chars.indexOf(seg.charAt(i++)), c2 = chars.indexOf(seg.charAt(i++)),
            c3 = chars.indexOf(seg.charAt(i++)), c4 = chars.indexOf(seg.charAt(i++));
        out += String.fromCharCode((c1 << 2) | (c2 >> 4));
        if (c3 >= 0) out += String.fromCharCode(((c2 & 15) << 4) | (c3 >> 2));
        if (c4 >= 0) out += String.fromCharCode(((c3 & 3) << 6) | c4);
      }
      json = decodeURIComponent(escape(out));
    }
    var p = JSON.parse(json);
    return p.sub || p.userId || p.uid || "";
  } catch (e) { return ""; }
}

var UID = ""; // 运行时由 accessToken 自动填充，见 main()

// ---------------------------------------------------------------- 主流程
function main() {
  ensureSheet(); ensureLabels();
  var rt = readCell("B1").replace(/\s/g, "");
  var endpoint = readCell("B3") || ENDPOINT_DEFAULT;

  if (!rt) {
    writeCell("B5", "❌ B1 未填 refresh_token"); writeCell("B8", nowBeijing());
    log("请在 B1 粘贴 refresh_token"); return;
  }

  // 1) 刷新令牌并回写（永久续期的核心）
  log("=== 1/3 刷新令牌 ===");
  var tk = refreshToken(rt, endpoint);
  if (!tk.ok) {
    writeCell("B5", "❌ 令牌刷新失败：" + tk.err); writeCell("B7", "失败"); writeCell("B8", nowBeijing());
    log("令牌刷新失败：" + tk.err); return;
  }
  if (tk.newRefreshToken && tk.newRefreshToken !== rt) {
    if (writeCell("B1", tk.newRefreshToken)) log("  · 新 refreshToken 已回写 B1（下次自动用新的）");
    else log("  · 警告：新 refreshToken 回写失败，但旧 token 仍可用一段时间");
  }

  UID = uidFromToken(tk.accessToken);
  if (!UID) { log("警告：无法从 token 解析用户 ID，将尝试空值（多数情况仍可用）"); }
  var headers = bizHeaders(tk.accessToken, UID);

  // 2) 签到
  log("=== 2/3 签到 ===");
  var cok, checkin;
  try { var c = runCheckin(headers, endpoint); cok = c[0]; checkin = c[1]; }
  catch (e) { cok = false; checkin = { report: "签到模块异常：" + String(e) }; }
  log("  " + checkin.report);

  // 3) 猫猫
  log("=== 3/3 猫猫 ===");
  var buddy;
  try { buddy = runBuddy(headers, endpoint, 1); }
  catch (e) { buddy = { report: "猫猫模块异常：" + String(e) }; }
  log("  " + buddy.report);

  writeCell("B5", (cok ? "✅ " : "❌ ") + checkin.report);
  writeCell("B6", "🐱 " + (buddy.report || "无结论"));
  writeCell("B7", cok ? "成功" : "失败（签到未达成）");
  var stamp = nowBeijing();
  writeCell("B8", stamp);
  log("=== 完成：" + (cok ? "成功" : "失败") + " ===");

  // 4) 微信推送（可选）：B9 填了 SendKey 才推，且推送失败不影响上面已写好的签到记录
  var sk = readCell("B9").replace(/\s/g, "");
  if (sk) {
    var title = "WorkBuddy 签到 " + (cok ? "✅" : "❌") + " " + stamp.slice(0, 10);
    var desp = "**整体**：" + (cok ? "成功" : "失败") + "\n\n**签到**：" + checkin.report +
               "\n\n**猫猫**：" + (buddy.report || "无结论") + "\n\n时间：" + stamp;
    var pr = pushWechat(sk, title, desp);
    writeCell("B10", pr.msg + "（" + stamp + "）");
    log("  " + pr.msg);
  } else {
    writeCell("B10", "未填 SendKey，未推送");
  }

  // 5) 表格美化（纯外观，全部容错；放最后，前面结果已全部写好）
  try { beautify(); log("  · 表格美化已应用"); } catch (e) { log("  · 美化跳过（不影响签到）：" + String(e)); }
}

main();
