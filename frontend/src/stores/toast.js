/**
 * 轻量吐司提示.
 *
 * 用它替代「页面顶部插一条提示」: 提示出现在固定位置, 不会因为切换页面或
 * 滚动而错过, 操作反馈更明确.
 */
import { defineStore } from "pinia";

let seq = 0;

export const useToastStore = defineStore("toast", {
  state: () => ({
    items: [],
  }),
  actions: {
    push(message, kind = "info", timeout = 3600) {
      const id = ++seq;
      this.items.push({ id, message: String(message ?? ""), kind });
      if (timeout > 0) {
        setTimeout(() => this.dismiss(id), timeout);
      }
      return id;
    },
    ok(message) {
      return this.push(message, "ok");
    },
    bad(message) {
      // 错误停留更久, 便于阅读排查提示
      return this.push(message, "bad", 7000);
    },
    info(message) {
      return this.push(message, "info");
    },
    dismiss(id) {
      this.items = this.items.filter((x) => x.id !== id);
    },
  },
});
