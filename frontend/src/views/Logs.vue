<script setup>
/**
 * 运行日志页.
 *
 * 日志存放在业务进程的内存环形缓冲中, 通过控制桥接服务读取.
 * 采用增量轮询: 每次带上最后一条的时间戳, 只取新记录.
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { api } from "@/api";
import UiIcon from "@/components/ui/UiIcon.vue";

const logs = ref([]);
const loading = ref(false);
const unreachable = ref(false);
const autoRefresh = ref(true);
const follow = ref(true);
const keyword = ref("");
const level = ref("");
const box = ref(null);
const lastTime = ref("");
const health = ref(null);

let timer = null;
let queryTimer = null;
let healthTimer = null;

const LEVELS = [
  { value: "", label: "全部级别" },
  { value: "ERROR,CRITICAL", label: "仅错误" },
  { value: "WARNING,ERROR,CRITICAL", label: "警告及以上" },
  { value: "SUCCESS", label: "成功" },
];

async function reload() {
  loading.value = true;
  lastTime.value = "";
  try {
    const data = await api.getLogs({
      level: level.value || undefined,
      keyword: keyword.value || undefined,
      limit: 400,
    });
    if (data && data.error) {
      unreachable.value = !!data.unreachable;
      logs.value = [];
      return;
    }
    unreachable.value = false;
    logs.value = data.logs || [];
    if (logs.value.length) lastTime.value = logs.value[logs.value.length - 1].time;
    await toBottom();
  } finally {
    loading.value = false;
  }
}

async function poll() {
  if (!autoRefresh.value) return;
  try {
    const data = await api.getLogs({
      since: lastTime.value || undefined,
      level: level.value || undefined,
      keyword: keyword.value || undefined,
      limit: 400,
    });
    if (data && data.error) {
      unreachable.value = !!data.unreachable;
      return;
    }
    unreachable.value = false;
    const fresh = data.logs || [];
    if (!fresh.length) return;

    // 同一毫秒的记录可能重复, 用末尾若干条做去重锚点
    const seen = new Set(logs.value.slice(-60).map((x) => `${x.time}|${x.message}`));
    const add = fresh.filter((x) => !seen.has(`${x.time}|${x.message}`));
    if (add.length) {
      logs.value = [...logs.value, ...add].slice(-2000);
      lastTime.value = add[add.length - 1].time;
      if (follow.value) await toBottom();
    }
  } catch {
    unreachable.value = true;
  }
}

async function toBottom() {
  await nextTick();
  const el = box.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function onScroll() {
  const el = box.value;
  if (!el) return;
  // 距底部 40px 内视为「跟随」, 用户向上翻看时不打断
  follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
}

async function checkHealth() {
  try {
    const data = await api.bridgeHealth();
    health.value = data.status === "ok";
  } catch {
    health.value = false;
  }
}

function levelClass(lv) {
  const l = (lv || "").toUpperCase();
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

watch([keyword, level], () => {
  clearTimeout(queryTimer);
  queryTimer = setTimeout(reload, 350);
});

onMounted(async () => {
  await Promise.all([reload(), checkHealth()]);
  timer = setInterval(poll, 3000);
  healthTimer = setInterval(checkHealth, 30000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (healthTimer) clearInterval(healthTimer);
  if (queryTimer) clearTimeout(queryTimer);
});
</script>

<template>
  <section>
    <div class="head">
      <div>
        <h1>运行日志</h1>
        <p>实时查看业务进程的输出，用于排查签到失败原因。</p>
      </div>
      <div class="head-actions">
        <span
          class="badge"
          :class="health === null ? '' : health ? 'badge-ok' : 'badge-bad'"
        >
          <span class="dot" :class="{ 'dot-live': health !== true }"></span>
          {{ health === null ? "检测中" : health ? "业务运行中" : "业务未运行" }}
        </span>
        <button class="btn" :disabled="loading" @click="reload">
          <UiIcon name="refresh" :size="15" />
          刷新
        </button>
      </div>
    </div>

    <div v-if="unreachable" class="alert alert-warn">
      <UiIcon name="alert" :size="16" />
      <div class="alert-body">无法连接业务进程，暂时读不到日志。请确认容器正在运行。</div>
    </div>

    <div class="card">
      <div class="logbar">
        <div class="search">
          <span class="search-ico"><UiIcon name="search" :size="15" /></span>
          <input v-model="keyword" class="input" placeholder="搜索日志内容" />
        </div>
        <select v-model="level" class="select" style="width: auto; min-width: 132px">
          <option v-for="lv in LEVELS" :key="lv.value" :value="lv.value">{{ lv.label }}</option>
        </select>
        <label class="chk">
          <input v-model="autoRefresh" type="checkbox" />
          自动刷新
        </label>
        <label class="chk">
          <input v-model="follow" type="checkbox" />
          跟随最新
        </label>
        <div class="spacer"></div>
        <span class="small muted">{{ logs.length }} 条</span>
        <button class="btn btn-sm" @click="(logs = []), (lastTime = '')">清空</button>
      </div>

      <div ref="box" class="term" @scroll="onScroll">
        <div v-if="!logs.length && !loading" class="term-empty">
          暂无日志。业务进程开始执行任务后会显示在这里。
        </div>
        <div v-for="(item, i) in logs" :key="i" class="term-line" :class="levelClass(item.level)">
          <span class="term-time">{{ shortTime(item.time) }}</span>
          <span class="term-lv">{{ item.level }}</span>
          <span v-if="item.scheme" class="term-scope">[{{ item.scheme }}]</span>
          <span class="term-msg">{{ item.message }}</span>
        </div>
      </div>
    </div>
  </section>
</template>
