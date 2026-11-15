/**
 * 配置状态仓库.
 *
 * 所有页面共享同一份「配置草稿」: 任何页面上的修改都落到 draft 上,
 * 由底部保存条统一提交. 这样跨页面编辑不会互相覆盖, 也不会有
 * 「在 A 页面改了, 切到 B 页面又变回去」的困惑.
 */
import { defineStore } from "pinia";
import { api } from "@/api";

function clone(value) {
  return JSON.parse(JSON.stringify(value ?? null));
}

export const useConfigStore = defineStore("config", {
  state: () => ({
    draft: null,
    /** 服务端快照, 用于判断是否有未保存改动, 以及「放弃更改」 */
    frozen: null,
    loading: false,
    saving: false,
    error: "",
    loaded: false,
  }),

  getters: {
    ready: (state) => !!state.draft,
    dirty: (state) =>
      !!state.draft && JSON.stringify(state.draft) !== JSON.stringify(state.frozen),
    /** 账号列表 (指定模块) */
    accounts: (state) => (section) => state.draft?.[section]?.account || [],
  },

  actions: {
    async load(force = false) {
      if (this.loaded && !force) return;
      this.loading = true;
      this.error = "";
      try {
        const data = await api.getConfig();
        if (data && data.error) throw new Error(data.error);
        this.draft = normalize(data);
        this.frozen = clone(this.draft);
        this.loaded = true;
      } catch (e) {
        this.error = e.message || String(e);
      } finally {
        this.loading = false;
      }
    },

    async save() {
      this.saving = true;
      this.error = "";
      try {
        const result = await api.saveConfig(clone(this.draft));
        if (result && result.error) throw new Error(result.error);
        // 重新拉取: 服务端会补齐默认值, 以服务端结果为准可避免本地与磁盘不一致
        const fresh = await api.getConfig();
        this.draft = normalize(fresh);
        this.frozen = clone(this.draft);
        return { ok: true, message: result?.message || "已保存" };
      } catch (e) {
        this.error = e.message || String(e);
        return { ok: false, message: this.error };
      } finally {
        this.saving = false;
      }
    },

    discard() {
      this.draft = clone(this.frozen);
      this.error = "";
    },

    /** 确保某个模块及其 account 数组存在, 返回该数组 (可直接 push) */
    ensureAccounts(section) {
      if (!this.draft) this.draft = {};
      if (!this.draft[section] || typeof this.draft[section] !== "object") {
        this.draft[section] = {};
      }
      if (!Array.isArray(this.draft[section].account)) {
        this.draft[section].account = [];
      }
      return this.draft[section].account;
    },

    /** 确保模块对象存在, 返回它 (用于写全局设置) */
    section(name) {
      if (!this.draft) this.draft = {};
      if (!this.draft[name] || typeof this.draft[name] !== "object") {
        this.draft[name] = {};
      }
      return this.draft[name];
    },
  },
});

/** 补齐配置文件可能缺失的结构, 避免各页面到处判空 */
function normalize(data) {
  const conf = { ...(data || {}) };
  for (const key of ["emby", "subsonic", "telegram", "checkiner", "ocr", "notifier", "site"]) {
    if (!conf[key] || typeof conf[key] !== "object") conf[key] = {};
  }
  for (const key of ["emby", "subsonic", "telegram"]) {
    if (!Array.isArray(conf[key].account)) conf[key].account = [];
  }
  if (conf.proxy !== null && typeof conf.proxy !== "object") conf.proxy = null;
  return conf;
}
