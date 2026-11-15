/**
 * API 客户端: 统一处理部署前缀、错误信息与 JSON 解析.
 * 前缀由 Flask 注入到 window.__EK_BASE_PREFIX__, 兼容 --prefix 子路径部署.
 */
const BASE = (() => {
  const injected = window.__EK_BASE_PREFIX__;
  if (typeof injected === "string") return injected.replace(/\/$/, "");
  return "";
})();

export function apiUrl(path) {
  return `${BASE}/api${path}`;
}

async function request(path, options = {}) {
  const resp = await fetch(apiUrl(path), {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });

  const text = await resp.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = { raw: text };
  }

  if (!resp.ok) {
    const message = (data && (data.error || data.message)) || `请求失败 (HTTP ${resp.status})`;
    const err = new Error(message);
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  return data;
}

export const api = {
  /* 配置读写 */
  getConfig: () => request("/config"),
  saveConfig: (config) => request("/config", { method: "POST", body: JSON.stringify({ config }) }),

  /* 概览 */
  getSummary: () => request("/summary"),

  /* 站点 */
  getSites: (refresh = false) => request(`/sites${refresh ? "?refresh=1" : ""}`),
  resolveSites: (tokens) =>
    request("/sites/resolve", { method: "POST", body: JSON.stringify({ tokens }) }),
  getTemplateFields: () => request("/sites/template-fields"),
  validateBot: (botUsername) =>
    request("/sites/validate-bot", {
      method: "POST",
      body: JSON.stringify({ bot_username: botUsername }),
    }),

  /* 运行与日志 */
  runNow: (site) => request("/run", { method: "POST", body: JSON.stringify(site ? { site } : {}) }),
  getLogs: ({ since, level, keyword, limit = 300 } = {}) => {
    const q = new URLSearchParams();
    if (since) q.set("since", since);
    if (level) q.set("level", level);
    if (keyword) q.set("keyword", keyword);
    q.set("limit", limit);
    return request(`/logs?${q.toString()}`);
  },
  bridgeHealth: () => request("/bridge/health"),

  /* 通知 */
  testNotifier: () => request("/notifier/test", { method: "POST" }),
};
