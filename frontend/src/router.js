import { createRouter, createWebHashHistory } from "vue-router";

// hash 路由: 无需服务端为每个子路径配置 fallback, 兼容任意部署前缀.
const routes = [
  { path: "/", redirect: "/overview" },
  { path: "/overview", name: "overview", component: () => import("./views/Overview.vue") },
  { path: "/accounts", name: "accounts", component: () => import("./views/Accounts.vue") },
  { path: "/sites", name: "sites", component: () => import("./views/Sites.vue") },
  { path: "/notify", name: "notify", component: () => import("./views/Notify.vue") },
  { path: "/settings", name: "settings", component: () => import("./views/Settings.vue") },
  { path: "/logs", name: "logs", component: () => import("./views/Logs.vue") },
  // 兼容旧书签
  { path: "/dashboard", redirect: "/overview" },
  { path: "/config", redirect: "/accounts" },
];

export default createRouter({
  history: createWebHashHistory(),
  routes,
});
