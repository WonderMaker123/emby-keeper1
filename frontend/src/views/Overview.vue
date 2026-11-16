<script setup>
/**
 * 总览页.
 *
 * 首屏回答三个问题:
 *   1. 已经配好了什么 (账号 / 站点 / 通知)
 *   2. 还差什么 (缺账号、通知未开 → 给出直达入口)
 *   3. 能立刻做什么 (立即运行一次、看日志)
 */
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "@/api";
import { useConfigStore } from "@/stores/config";
import { useSitesStore } from "@/stores/sites";
import { useToastStore } from "@/stores/toast";
import UiIcon from "@/components/ui/UiIcon.vue";

const config = useConfigStore();
const sites = useSitesStore();
const toast = useToastStore();

const summary = ref(null);
const recent = ref([]);
const logError = ref("");
const running = ref(false);
const runningCheckin = ref(false);

let timer = null;

onMounted(async () => {
  await Promise.all([config.load(), sites.load()]);
  await refresh();
  timer = setInterval(loadLogs, 15000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});

async function refresh() {
  try {
    summary.value = await api.getSummary();
  } catch (e) {
    logError.value = e.message;
  }
  await loadLogs();
}

async function loadLogs() {
  try {
    const data = await api.getLogs({ limit: 7 });
    if (data && data.error) {
      logError.value = data.error;
      recent.value = [];
      return;
    }
    logError.value = "";
    recent.value = (data.logs || []).slice(-7).reverse();
  } catch (e) {
    logError.value = e.message;
  }
}

async function runCheckinNow() {
  runningCheckin.value = true;
  try {
    if (config.dirty) {
      toast.info("检测到未保存改动，正在自动保存配置…");
      const saveRes = await config.save();
      if (!saveRes.ok) {
        toast.bad("自动保存配置失败: " + saveRes.message);
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    const data = await api.runCheckinNow();
    if (data && data.ok) {
      toast.ok(data.message || "已在后台开始执行站点签到，请查看日志");
      setTimeout(loadLogs, 2500);
    } else {
      toast.bad((data && (data.error || data.message)) || "触发签到失败");
    }
  } catch (e) {
    toast.bad(e.message);
  } finally {
    runningCheckin.value = false;
  }
}

async function runNow() {
  running.value = true;
  try {
    if (config.dirty) {
      toast.info("检测到未保存改动，正在自动保存配置…");
      const saveRes = await config.save();
      if (!saveRes.ok) {
        toast.bad("自动保存配置失败: " + saveRes.message);
        return;
      }
      await new Promise((r) => setTimeout(r, 1500));
    }
    const data = await api.runNow();
    if (data && data.ok) {
      toast.ok(data.message || "已在后台开始执行，请查看日志");
      setTimeout(loadLogs, 2500);
    } else {
      toast.bad((data && (data.error || data.message)) || "触发失败");
    }
  } catch (e) {
    toast.bad(e.message);
  } finally {
    running.value = false;
  }
}

/* 账号数量直接从草稿里读, 保证与「账号」页即时一致 */
const counts = computed(() => {
  const acc = (s) => config.draft?.[s]?.account?.length || 0;
  const tg = config.draft?.telegram?.account || [];
  return {
    emby: acc("emby"),
    subsonic: acc("subsonic"),
    telegram: tg.length,
    telegramActive: tg.filter((a) => a.enabled !== false && a.checkiner !== false).length,
  };
});

/* 待办: 按「不配就用不了」的严重程度排序 */
const todos = computed(() => {
  const list = [];
  if (!counts.value.telegram) {
    list.push({ text: "还没有 Telegram 账号，站点签到无法运行", to: "/accounts?type=telegram" });
  } else if (!counts.value.telegramActive) {
    list.push({ text: "Telegram 账号已停用或关闭了签到", to: "/accounts?type=telegram" });
  }
  if (!counts.value.emby && !counts.value.subsonic) {
    list.push({ text: "还没有 Emby / Subsonic 账号，保活不会执行", to: "/accounts?type=emby" });
  }
  if (summary.value && !summary.value.ocr?.ai_configured) {
    list.push({
      text: "验证码识别未填 API Key，遇到验证码的站点可能签到失败",
      to: "/settings",
    });
  }
  if (summary.value && !summary.value.notifier_enabled) {
    list.push({ text: "通知未开启，签到结果不会推送到手机", to: "/notify" });
  }
  return list;
});

const siteText = computed(() => {
  if (!config.draft) return "-";
  const tokens = config.draft.site?.checkiner;
  if (!Array.isArray(tokens) || !tokens.length) return "默认推荐站点";
  const positive = tokens.filter((t) => !String(t).startsWith("-"));
  const excluded = tokens.filter((t) => String(t).startsWith("-"));
  if (!positive.length) return "未选择站点";
  return `${positive.length} 个站点`;
});

function levelClass(level) {
  const l = (level || "").toUpperCase();
  if (l === "ERROR" || l === "CRITICAL") return "lv-err";
  if (l === "WARNING") return "lv-warn";
  if (l === "SUCCESS") return "lv-ok";
  if (l === "DEBUG") return "lv-debug";
  return "lv-info";
}

function shortTime(t) {
  if (!t) return "";
  const m = String(t).match(/T(\d{2}:\d{2}:\d{2})/);
  return m ? m[1] : t;
}

const notifyMethod = computed(() => config.draft?.notifier?.method || "telegram");
const notifyEnabled = computed(() => !!config.draft?.notifier?.enabled);
const notifyReady = computed(() =>
  notifyMethod.value === "telegram"
    ? !!config.draft?.notifier?.bot_token && !!config.draft?.notifier?.chat_id
    : !!config.draft?.notifier?.apprise_uri
);
</script>

<template>
  <section>
    <div class="head">
      <div>
        <h1>总览</h1>
        <p>所有设置保存后立即生效，无需重启容器。</p>
      </div>
      <div class="head-actions">
        <button class="btn" :disabled="config.loading" @click="refresh">
          <UiIcon name="refresh" :size="15" />
          刷新
        </button>
        <button
          class="btn btn-primary"
          :disabled="runningCheckin || running"
          @click="runCheckinNow"
          title="只执行 Telegram 站点签到，不执行耗时的 Emby 播放保活"
        >
          <UiIcon name="play" :size="15" />
          {{ runningCheckin ? "签到中…" : "立即签到一次" }}
        </button>
        <button
          class="btn"
          :disabled="running || runningCheckin"
          @click="runNow"
          title="执行所有任务，包括站点签到与 Emby/Subsonic 保活"
        >
          全部运行(含保活)
        </button>
      </div>
    </div>

    <div v-if="config.error" class="alert alert-bad">
      <UiIcon name="alert" :size="16" />
      <div class="alert-body">{{ config.error }}</div>
    </div>

    <div v-if="todos.length" class="alert alert-warn">
      <UiIcon name="alert" :size="16" />
      <div class="alert-body">
        <div style="font-weight: 650; margin-bottom: 3px">
          还有 {{ todos.length }} 项没配置好
        </div>
        <div v-for="t in todos" :key="t.text" style="margin-top: 2px">
          · {{ t.text }} <RouterLink :to="t.to">去设置 →</RouterLink>
        </div>
      </div>
    </div>

    <div v-if="config.loading && !config.ready" class="alert alert-info">
      <UiIcon name="info" :size="16" />
      <div class="alert-body">正在加载配置…</div>
    </div>

    <template v-if="config.ready">
      <div class="stats">
        <RouterLink to="/accounts?type=emby" class="stat">
          <div class="stat-top">
            Emby 账号
            <UiIcon name="server" :size="15" />
          </div>
          <div class="stat-num">{{ counts.emby }}</div>
          <div class="stat-foot">{{ counts.emby ? "定时模拟播放保活" : "点击添加账号" }}</div>
        </RouterLink>

        <RouterLink to="/accounts?type=subsonic" class="stat">
          <div class="stat-top">
            Subsonic 账号
            <UiIcon name="server" :size="15" />
          </div>
          <div class="stat-num">{{ counts.subsonic }}</div>
          <div class="stat-foot">{{ counts.subsonic ? "定时模拟听歌保活" : "未配置" }}</div>
        </RouterLink>

        <RouterLink to="/accounts?type=telegram" class="stat">
          <div class="stat-top">
            Telegram 账号
            <UiIcon name="robot" :size="15" />
          </div>
          <div class="stat-num">{{ counts.telegram }}</div>
          <div class="stat-foot">
            {{ counts.telegram ? `其中 ${counts.telegramActive} 个启用签到` : "签到需要至少一个" }}
          </div>
        </RouterLink>

        <RouterLink to="/sites" class="stat">
          <div class="stat-top">
            签到站点
            <UiIcon name="globe" :size="15" />
          </div>
          <div class="stat-num txt">{{ siteText }}</div>
          <div class="stat-foot">点击调整范围</div>
        </RouterLink>
      </div>

      <div class="stack">
        <div class="card">
          <div class="card-head">
            <div>
              <h2 class="card-title">运行设置</h2>
              <div class="card-desc">签到与保活什么时候执行</div>
            </div>
            <RouterLink to="/settings" class="btn btn-sm">修改</RouterLink>
          </div>
          <div class="card-body">
            <div class="grid-2">
              <div>
                <div class="small muted">签到时间</div>
                <div style="font-weight: 570; margin-top: 2px">
                  {{ config.draft.checkiner?.time_range || "未设置" }}
                </div>
              </div>
              <div>
                <div class="small muted">验证码识别</div>
                <div class="row-flex" style="margin-top: 2px">
                  <span
                    class="badge"
                    :class="
                      config.draft.ocr?.ai_api_key ? 'badge-ok' : 'badge-warn'
                    "
                  >
                    {{ config.draft.ocr?.ai_api_key ? "AI 优先" : "未配置 AI" }}
                  </span>
                  <span v-if="config.draft.ocr?.ai_model" class="small muted">
                    {{ config.draft.ocr.ai_model }}
                  </span>
                </div>
              </div>
              <div>
                <div class="small muted">结果通知</div>
                <div class="row-flex" style="margin-top: 2px">
                  <span class="badge" :class="notifyEnabled && notifyReady ? 'badge-ok' : ''">
                    {{
                      notifyEnabled
                        ? notifyReady
                          ? "已开启"
                          : "已开启但未填完"
                        : "未开启"
                    }}
                  </span>
                  <RouterLink v-if="!notifyReady" to="/notify" class="small">去设置</RouterLink>
                </div>
              </div>
              <div>
                <div class="small muted">配置文件位置</div>
                <div class="mono small" style="margin-top: 2px; overflow-wrap: anywhere">
                  {{ summary?.config_path || "-" }}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-head">
            <div>
              <h2 class="card-title">最近动态</h2>
              <div class="card-desc">业务进程最近输出的几行</div>
            </div>
            <RouterLink to="/logs" class="btn btn-sm">全部日志</RouterLink>
          </div>
          <div class="card-body" style="padding: 12px 20px">
            <div v-if="logError" class="small muted">{{ logError }}</div>
            <div v-else-if="!recent.length" class="small muted">
              暂无日志。业务进程开始执行任务后会显示在这里。
            </div>
            <div
              v-for="(item, i) in recent"
              :key="i"
              style="
                display: flex;
                gap: 9px;
                padding: 6px 0;
                font-size: 12.5px;
                border-bottom: 1px solid #f5f6f9;
                align-items: flex-start;
              "
            >
              <span class="muted mono" style="flex: 0 0 auto">{{ shortTime(item.time) }}</span>
              <span
                v-if="['ERROR', 'WARNING', 'SUCCESS'].includes((item.level || '').toUpperCase())"
                class="badge"
                :class="
                  (item.level || '').toUpperCase() === 'ERROR'
                    ? 'badge-bad'
                    : (item.level || '').toUpperCase() === 'WARNING'
                      ? 'badge-warn'
                      : 'badge-ok'
                "
              >
                {{ item.level }}
              </span>
              <span style="flex: 1; min-width: 0; overflow-wrap: anywhere; color: var(--ink-2)">
                {{ item.message }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>
