<script setup>
/**
 * 应用外壳: 左侧导航 + 顶栏 + 内容区 + 全局保存条 + 吐司.
 *
 * 保存条放在外壳而非各页面: 配置是全局共享的草稿, 无论身处哪个页面,
 * 有未保存改动时都应在同一位置看到提示, 行为保持一致.
 */
import { computed, onMounted } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import UiIcon from "@/components/ui/UiIcon.vue";
import Toasts from "@/components/Toasts.vue";
import { useConfigStore } from "@/stores/config";
import { useToastStore } from "@/stores/toast";

const route = useRoute();
const config = useConfigStore();
const toast = useToastStore();

const NAV = [
  {
    cap: "开始使用",
    items: [
      { to: "/overview", name: "overview", label: "总览", icon: "home" },
      { to: "/accounts", name: "accounts", label: "账号", icon: "user" },
      { to: "/sites", name: "sites", label: "签到站点", icon: "globe" },
    ],
  },
  {
    cap: "偏好",
    items: [
      { to: "/notify", name: "notify", label: "结果通知", icon: "bell" },
      { to: "/settings", name: "settings", label: "系统设置", icon: "gear" },
    ],
  },
  {
    cap: "诊断",
    items: [{ to: "/logs", name: "logs", label: "运行日志", icon: "list" }],
  },
];

const TITLES = {
  overview: "总览",
  accounts: "账号",
  sites: "签到站点",
  notify: "结果通知",
  settings: "系统设置",
  logs: "运行日志",
};

const title = computed(() => TITLES[route.name] || "控制台");

onMounted(async () => {
  await config.load();
});

async function save() {
  const res = await config.save();
  if (res.ok) toast.ok(res.message);
  else toast.bad(res.message);
}
</script>

<template>
  <div class="shell">
    <aside class="nav">
      <div class="nav-brand">
        <div class="nav-mark">E</div>
        <div>
          <div class="nav-brand-name">Embykeeper</div>
          <div class="nav-brand-tag">签到保活控制台</div>
        </div>
      </div>

      <nav class="nav-body">
        <template v-for="group in NAV" :key="group.cap">
          <div class="nav-cap">{{ group.cap }}</div>
          <RouterLink
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :class="{ on: route.name === item.name }"
          >
            <UiIcon :name="item.icon" class="nav-ico" />
            {{ item.label }}
          </RouterLink>
        </template>
      </nav>

      <div class="nav-foot">
        <div class="nav-status">
          <div class="small muted">配置保存后自动生效</div>
          <div class="small muted" style="margin-top: 2px">无需重启容器</div>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="top">
        <div class="top-title">{{ title }}</div>
        <div class="top-actions">
          <button
            v-if="config.dirty"
            class="btn btn-sm"
            :disabled="config.saving"
            @click="config.discard()"
          >
            放弃更改
          </button>
          <button
            class="btn btn-primary btn-sm"
            :disabled="config.saving || !config.dirty"
            @click="save"
          >
            <UiIcon name="check" :size="14" />
            {{ config.saving ? "保存中…" : "保存配置" }}
          </button>
        </div>
      </header>

      <main class="page">
        <div class="page-inner">
          <RouterView />
        </div>
      </main>
    </div>

    <div v-if="config.dirty" class="savebar">
      <span class="savebar-msg">有尚未保存的修改，保存后立即生效</span>
      <button class="btn" :disabled="config.saving" @click="config.discard()">放弃更改</button>
      <button class="btn btn-primary" :disabled="config.saving" @click="save">
        {{ config.saving ? "保存中…" : "保存配置" }}
      </button>
    </div>

    <Toasts />
  </div>
</template>
