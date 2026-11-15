/**
 * 站点清单仓库.
 *
 * 站点元数据 (中文名/分类/是否需要验证码) 由后端扫描签到器模块生成,
 * 各页面共用一份, 只在首次加载时请求.
 */
import { defineStore } from "pinia";
import { api } from "@/api";

export const useSitesStore = defineStore("sites", {
  state: () => ({
    list: [],
    categories: [],
    recommendedCount: 0,
    loading: false,
    loaded: false,
    error: "",
  }),

  getters: {
    byKey: (state) => {
      const map = {};
      for (const site of state.list) map[site.key] = site;
      return map;
    },
  },

  actions: {
    async load(force = false) {
      if (this.loaded && !force) return;
      if (this.loading) return;
      this.loading = true;
      this.error = "";
      try {
        const data = await api.getSites(force);
        if (data && data.error) throw new Error(data.error);
        this.list = data.sites || [];
        this.categories = data.categories || [];
        this.recommendedCount = data.recommended_count || 0;
        this.loaded = true;
      } catch (e) {
        this.error = e.message || String(e);
      } finally {
        this.loading = false;
      }
    },

    /** 配置里的模块名 → 可读中文名 */
    displayName(key) {
      const site = this.byKey[key];
      return site ? site.name : key;
    },
  },
});
