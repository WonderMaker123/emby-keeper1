<script setup>
/**
 * 账号管理页.
 *
 * 针对「不知道怎么加账号」的反馈, 这里做了几件事:
 *   1. 三类账号分段切换, 一次只处理一类;
 *   2. 账号以列表呈现, 一眼看清有几个、地址是什么、是否启用;
 *   3. 新增/编辑用弹窗, 且**只显示真正需要填的字段** (地址/用户名/密码),
 *      其余参数收进「高级」, 不会一上来就给用户二十个输入框;
 *   4. 时长、间隔、时间段都用友好控件, 不暴露 [300,600]、"<7,12>" 之类的写法.
 */
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useConfigStore } from "@/stores/config";
import { useToastStore } from "@/stores/toast";
import { api } from "@/api";
import UiIcon from "@/components/ui/UiIcon.vue";
import UiModal from "@/components/ui/UiModal.vue";
import UiSecret from "@/components/ui/UiSecret.vue";
import DurationPicker from "@/components/friendly/DurationPicker.vue";
import IntervalPicker from "@/components/friendly/IntervalPicker.vue";
import TimeRange from "@/components/friendly/TimeRange.vue";

const route = useRoute();
const router = useRouter();
const config = useConfigStore();
const toast = useToastStore();

/* ---------------- 字段定义 (手工定制) ---------------- */

/**
 * 每类账号的字段分两组:
 *   base     —— 添加账号时必须/常改的, 直接展示
 *   advanced —— 可选的进阶项, 默认折叠
 * 未列出的字段不会出现在表单里, 但也不会从配置中丢失 (提交时整体回写).
 */
const SCHEMAS = {
  emby: {
    label: "Emby",
    desc: "定时模拟播放影片, 保持账号活跃",
    addWord: "账号",
    title: (a) => a.name || a.username || a.url || "未命名账号",
    sub: (a) => [a.url, a.username].filter(Boolean).join("　·　"),
    base: [
      { key: "url", label: "服务器地址", type: "text", required: true, ph: "https://example.com:443" },
      { key: "username", label: "用户名", type: "text", required: true },
      { key: "password", label: "密码", type: "secret", required: true },
      { key: "name", label: "备注名称", type: "text", hint: "便于区分多个账号，可留空" },
      { key: "time", label: "每次播放时长", type: "duration", verb: "播放" },
      { key: "use_proxy", label: "通过代理连接", type: "switch", hint: "在「系统设置」里配置了代理时才有意义" },
      { key: "enabled", label: "启用此账号", type: "switch" },
    ],
    advanced: [
      { key: "allow_stream", label: "允许流式播放", type: "switch", hint: "无法获取影片长度时仍然播放" },
      { key: "continuous", label: "连续播放", type: "switch" },
      { key: "client", label: "客户端名称", type: "text" },
      { key: "client_version", label: "客户端版本", type: "text" },
      { key: "useragent", label: "User-Agent", type: "text" },
      { key: "interval_days", label: "单独保活间隔", type: "interval", verb: "保活", hint: "填写后该账号按自己的周期保活" },
      { key: "time_range", label: "单独保活时间", type: "timeRange", verb: "保活" },
    ],
  },
  subsonic: {
    label: "Subsonic",
    desc: "定时模拟听歌, 保持音乐服账号活跃",
    addWord: "账号",
    title: (a) => a.name || a.username || a.url || "未命名账号",
    sub: (a) => [a.url, a.username].filter(Boolean).join("　·　"),
    base: [
      { key: "url", label: "服务器地址", type: "text", required: true, ph: "https://music.example.com" },
      { key: "username", label: "用户名", type: "text", required: true },
      { key: "password", label: "密码", type: "secret", required: true },
      { key: "name", label: "备注名称", type: "text", hint: "便于区分多个账号，可留空" },
      { key: "time", label: "每次收听时长", type: "duration", verb: "收听" },
      { key: "use_proxy", label: "通过代理连接", type: "switch" },
      { key: "enabled", label: "启用此账号", type: "switch" },
    ],
    advanced: [
      { key: "client", label: "客户端名称", type: "text" },
      { key: "client_version", label: "客户端版本", type: "text" },
      { key: "useragent", label: "User-Agent", type: "text" },
      { key: "interval_days", label: "单独保活间隔", type: "interval", verb: "保活" },
      { key: "time_range", label: "单独保活时间", type: "timeRange", verb: "保活" },
    ],
  },
  telegram: {
    label: "Telegram",
    desc: "用于登录 Telegram 并执行站点签到",
    addWord: "账号",
    title: (a) => a.name || a.phone || "未命名账号",
    sub: (a) => (a.phone ? `手机号 ${a.phone}` : ""),
    base: [
      {
        key: "phone",
        label: "手机号",
        type: "text",
        required: true,
        ph: "+8613800138000",
        hint: "带国家区号，例如中国大陆为 +86 开头",
      },
      { key: "name", label: "备注名称", type: "text", hint: "方便区分多个账号，可留空" },
      { key: "checkiner", label: "启用签到", type: "switch", hint: "关闭后此账号不参与站点签到" },
      { key: "enabled", label: "启用此账号", type: "switch" },
    ],
    advanced: [
      { key: "api_id", label: "API ID", type: "number", hint: "一般无需填写，程序内置了默认值" },
      { key: "api_hash", label: "API Hash", type: "secret", hint: "与 API ID 配套，一般无需填写" },
    ],
  },
};

const TYPE_ORDER = ["emby", "subsonic", "telegram"];

const activeType = ref("emby");
const dialogOpen = ref(false);
const editingIndex = ref(-1);
const form = ref({});
const showAdvanced = ref(false);
const formError = ref("");

/* ---------------- Telegram 登录 ---------------- */

// 登录是异步的: 业务侧拿到验证码需求后会挂起, 这里轮询状态并弹窗让用户填写
const loginDialog = ref(false);
const loginPhone = ref("");
const loginSessionId = ref("");
const loginState = ref("idle");
const loginHint = ref("");
const loginInput = ref("");
const loginBusy = ref(false);
const loginError = ref("");
const loggingInPhone = ref("");
let loginTimer = null;

onMounted(async () => {
  await config.load();
  const t = route.query.type;
  if (t && SCHEMAS[t]) activeType.value = t;
});

watch(activeType, (v) => router.replace({ query: { ...route.query, type: v } }));

/* ---------------- 列表 ---------------- */

const schema = computed(() => SCHEMAS[activeType.value]);
const accounts = computed(() => config.draft?.[activeType.value]?.account || []);

function isOn(account) {
  return account.enabled !== false;
}

function toggleEnabled(index) {
  const list = config.ensureAccounts(activeType.value);
  const item = { ...list[index] };
  item.enabled = item.enabled === false;
  list.splice(index, 1, item);
}

/* ---------------- 表单 ---------------- */

function openAdd() {
  const draft = { enabled: true, use_proxy: true };
  if (activeType.value === "telegram") draft.checkiner = true;
  form.value = draft;
  editingIndex.value = -1;
  showAdvanced.value = false;
  formError.value = "";
  dialogOpen.value = true;
}

function openEdit(index) {
  // 深拷贝, 取消编辑时不污染原数据
  form.value = JSON.parse(JSON.stringify(accounts.value[index] || {}));
  editingIndex.value = index;
  showAdvanced.value = false;
  formError.value = "";
  dialogOpen.value = true;
}

function setField(key, value) {
  const next = { ...form.value };
  if (value === null || value === undefined || value === "") delete next[key];
  else next[key] = value;
  form.value = next;
}

const missing = computed(() =>
  schema.value.base
    .filter((f) => f.required)
    .filter((f) => {
      const v = form.value[f.key];
      return v === undefined || v === null || v === "";
    })
    .map((f) => f.label)
);

function submit() {
  if (missing.value.length) {
    formError.value = `请填写：${missing.value.join("、")}`;
    return;
  }
  formError.value = "";
  const list = config.ensureAccounts(activeType.value);
  const payload = JSON.parse(JSON.stringify(form.value));
  if (editingIndex.value >= 0) list.splice(editingIndex.value, 1, payload);
  else list.push(payload);

  dialogOpen.value = false;
  const word = editingIndex.value >= 0 ? "已更新" : "已添加";
  toast.info(`${word}${schema.value.label}账号，记得点击右上角「保存配置」`);
}

function removeAccount(index) {
  const item = accounts.value[index];
  const label = schema.value.title(item);
  if (!window.confirm(`确定删除账号「${label}」吗？\n删除后需保存配置才会生效。`)) return;
  const list = config.ensureAccounts(activeType.value);
  list.splice(index, 1);
  toast.info("已删除，记得保存配置");
}

/* ---------------- Telegram 登录实现 ---------------- */

/** 发起登录并开始轮询状态 */
async function startLogin(item) {
  const phone = String(item.phone || "").trim();
  if (!phone) {
    toast.bad("该账号没有填写手机号，请先编辑账号补充手机号");
    return;
  }
  if (config.dirty) {
    toast.bad("请先保存配置，再发起 Telegram 登录");
    return;
  }

  loginError.value = "";
  loginHint.value = "";
  loginInput.value = "";
  loginState.value = "starting";
  loginPhone.value = phone;
  loggingInPhone.value = phone;
  loginDialog.value = true;

  try {
    const res = await api.loginStart(phone);
    if (res && res.ok === false) {
      loginError.value = res.error || "发起登录失败";
      loginState.value = "failed";
      loggingInPhone.value = "";
      return;
    }
  } catch (e) {
    loginError.value = e.message;
    loginState.value = "failed";
    loggingInPhone.value = "";
    return;
  }

  stopLoginPolling();
  loginTimer = setInterval(pollLogin, 1500);
}

/** 轮询登录状态 */
async function pollLogin() {
  try {
    const data = await api.loginStatus();
    if (!data || !data.active) {
      // 会话已结束: 根据最后一次已知状态判定结果
      if (["need_code", "need_password", "starting"].includes(loginState.value)) {
        loginState.value = "failed";
        loginError.value = loginError.value || "登录会话已结束，请重新发起";
        loggingInPhone.value = "";
        stopLoginPolling();
      }
      return;
    }

    loginSessionId.value = data.session_id || "";
    loginState.value = data.state;
    if (data.message) loginHint.value = data.message;

    if (data.state === "need_code") {
      loginHint.value = `请输入发送到 ${data.phone || loginPhone.value} 的验证码`;
    } else if (data.state === "need_password") {
      loginHint.value = "该账号开启了两步验证，请输入两步验证密码";
    } else if (data.state === "done") {
      loginState.value = "done";
      loggingInPhone.value = "";
      stopLoginPolling();
      toast.ok("Telegram 登录成功");
      setTimeout(() => {
        loginDialog.value = false;
      }, 1200);
    } else if (data.state === "failed") {
      loginError.value = data.error || "登录失败";
      loggingInPhone.value = "";
      stopLoginPolling();
    }
  } catch (e) {
    // 网络抖动不终止轮询, 避免误判为失败
    if (e.status === 401) {
      loginError.value = "控制台登录已过期，请刷新页面";
      stopLoginPolling();
    }
  }
}

function stopLoginPolling() {
  if (loginTimer) {
    clearInterval(loginTimer);
    loginTimer = null;
  }
}

/** 提交验证码或密码 */
async function submitLogin() {
  const value = loginInput.value.trim();
  if (!value) {
    loginError.value = "请输入内容";
    return;
  }
  loginBusy.value = true;
  loginError.value = "";
  try {
    const kind = loginState.value === "need_password" ? "password" : "code";
    const res = await api.loginSubmit(loginSessionId.value, kind, value);
    if (res && res.ok) {
      loginInput.value = "";
      loginState.value = "starting";
      loginHint.value = "正在验证…";
    } else {
      loginError.value = (res && res.error) || "提交失败";
    }
  } catch (e) {
    loginError.value = e.message;
  } finally {
    loginBusy.value = false;
  }
}

function closeLogin() {
  if (["need_code", "need_password", "starting"].includes(loginState.value)) {
    if (!window.confirm("登录尚未完成，关闭后需重新发起。确定关闭吗？")) return;
  }
  stopLoginPolling();
  loginDialog.value = false;
  loginState.value = "idle";
  loggingInPhone.value = "";
}

onUnmounted(() => stopLoginPolling());
</script>

<template>
  <section>
    <div class="head">
      <div>
        <h1>账号</h1>
        <p>管理用于保活的媒体服账号，以及用于签到的 Telegram 账号。</p>
      </div>
      <div class="head-actions">
        <button class="btn" :disabled="config.loading" @click="config.load(true)">
          <UiIcon name="refresh" :size="15" />
          重新加载
        </button>
        <button class="btn btn-primary" @click="openAdd">
          <UiIcon name="plus" :size="15" />
          添加{{ schema.label }}账号
        </button>
      </div>
    </div>

    <div v-if="config.loading && !config.ready" class="alert alert-info">
      <UiIcon name="info" :size="16" />
      <div class="alert-body">正在加载配置…</div>
    </div>

    <template v-if="config.ready">
      <div class="seg" style="margin-bottom: 16px">
        <button
          v-for="t in TYPE_ORDER"
          :key="t"
          type="button"
          class="seg-item"
          :class="{ on: activeType === t }"
          @click="activeType = t"
        >
          {{ SCHEMAS[t].label }}
          <span class="pill">{{ config.draft?.[t]?.account?.length || 0 }}</span>
        </button>
      </div>

      <div class="alert alert-info">
        <UiIcon name="info" :size="16" />
        <div class="alert-body">
          {{ schema.desc }}
          <div v-if="activeType === 'telegram'" style="margin-top: 6px">
            <b>添加后需要点「登录」完成验证</b>：程序会向该账号的 Telegram 发送验证码，
            在弹窗里填入即可。登录一次后会话会保存，之后无需重复登录。
          </div>
        </div>
      </div>

      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">
              已添加的{{ schema.label }}账号
              <span class="pill">{{ accounts.length }}</span>
            </h2>
            <div class="card-desc">左侧开关可临时停用账号</div>
          </div>
          <button class="btn btn-sm" @click="openAdd">
            <UiIcon name="plus" :size="14" />
            添加
          </button>
        </div>

        <div v-if="!accounts.length" class="empty">
          <div class="empty-ico"><UiIcon name="user" :size="24" /></div>
          <div class="empty-t">还没有 {{ schema.label }} 账号</div>
          <div class="empty-d">{{ schema.desc }}</div>
          <button class="btn btn-primary" @click="openAdd">
            <UiIcon name="plus" :size="15" />
            添加第一个账号
          </button>
        </div>

        <div v-else>
          <div v-for="(item, index) in accounts" :key="index" class="row">
            <label class="sw" :title="isOn(item) ? '已启用' : '已停用'">
              <input type="checkbox" :checked="isOn(item)" @change="toggleEnabled(index)" />
              <span class="sw-track"></span>
            </label>

            <div class="row-main">
              <div class="row-t">
                {{ schema.title(item) }}
                <span v-if="!isOn(item)" class="badge" style="margin-left: 7px">已停用</span>
              </div>
              <div v-if="schema.sub(item)" class="row-s">{{ schema.sub(item) }}</div>
            </div>

            <div class="row-actions">
              <button
                v-if="activeType === 'telegram'"
                class="btn btn-sm"
                :disabled="loggingInPhone === item.phone"
                @click="startLogin(item)"
              >
                <UiIcon name="key" :size="14" />
                {{ loggingInPhone === item.phone ? "登录中…" : "登录" }}
              </button>
              <button class="btn btn-sm btn-ghost" @click="openEdit(index)">
                <UiIcon name="pencil" :size="14" />
                编辑
              </button>
              <button class="btn btn-sm btn-danger" @click="removeAccount(index)">
                <UiIcon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 添加 / 编辑账号 -->
    <UiModal
      v-model="dialogOpen"
      :title="`${editingIndex >= 0 ? '编辑' : '添加'}${schema.label}账号`"
      :desc="editingIndex >= 0 ? '修改后需保存配置' : '只需填写下面标红的必填项即可'"
    >
      <div v-if="formError" class="alert alert-bad">
        <UiIcon name="alert" :size="16" />
        <div class="alert-body">{{ formError }}</div>
      </div>

      <div class="grid-2">
        <div v-for="f in schema.base" :key="f.key" class="field">
          <label class="label">
            {{ f.label }}
            <span v-if="f.required" class="req">必填</span>
          </label>
          <div v-if="f.hint" class="hint">{{ f.hint }}</div>

          <UiSecret
            v-if="f.type === 'secret'"
            :model-value="form[f.key] || ''"
            :placeholder="f.ph || '请输入'"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <DurationPicker
            v-else-if="f.type === 'duration'"
            :model-value="form[f.key]"
            :verb="f.verb"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <IntervalPicker
            v-else-if="f.type === 'interval'"
            :model-value="form[f.key]"
            :verb="f.verb"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <TimeRange
            v-else-if="f.type === 'timeRange'"
            :model-value="form[f.key]"
            :verb="f.verb"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <label v-else-if="f.type === 'switch'" class="sw">
            <input
              type="checkbox"
              :checked="f.key === 'enabled' ? form[f.key] !== false : !!form[f.key]"
              @change="setField(f.key, $event.target.checked)"
            />
            <span class="sw-track"></span>
            <span class="sw-text">{{ form[f.key] !== false && !!form[f.key] ? "已开启" : "已关闭" }}</span>
          </label>
          <input
            v-else
            class="input"
            :type="f.type === 'number' ? 'number' : 'text'"
            :value="form[f.key] ?? ''"
            :placeholder="f.ph || ''"
            @input="setField(f.key, $event.target.value)"
          />
        </div>
      </div>

      <div v-if="schema.advanced.length" class="divider"></div>

      <button
        v-if="schema.advanced.length"
        type="button"
        class="btn btn-sm btn-ghost"
        @click="showAdvanced = !showAdvanced"
      >
        <UiIcon name="arrow" :size="14" />
        {{ showAdvanced ? "收起高级选项" : `高级选项（${schema.advanced.length}）` }}
      </button>

      <div v-if="showAdvanced" class="grid-2" style="margin-top: 16px">
        <div v-for="f in schema.advanced" :key="f.key" class="field">
          <label class="label">{{ f.label }}</label>
          <div v-if="f.hint" class="hint">{{ f.hint }}</div>

          <UiSecret
            v-if="f.type === 'secret'"
            :model-value="form[f.key] || ''"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <IntervalPicker
            v-else-if="f.type === 'interval'"
            :model-value="form[f.key]"
            :verb="f.verb"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <TimeRange
            v-else-if="f.type === 'timeRange'"
            :model-value="form[f.key]"
            :verb="f.verb"
            @update:model-value="(v) => setField(f.key, v)"
          />
          <label v-else-if="f.type === 'switch'" class="sw">
            <input
              type="checkbox"
              :checked="!!form[f.key]"
              @change="setField(f.key, $event.target.checked)"
            />
            <span class="sw-track"></span>
            <span class="sw-text">{{ form[f.key] ? "已开启" : "已关闭" }}</span>
          </label>
          <input
            v-else
            class="input"
            :type="f.type === 'number' ? 'number' : 'text'"
            :value="form[f.key] ?? ''"
            @input="setField(f.key, $event.target.value)"
          />
        </div>
      </div>

      <template #footer>
        <button class="btn" @click="dialogOpen = false">取消</button>
        <button class="btn btn-primary" @click="submit">
          {{ editingIndex >= 0 ? "保存修改" : "添加账号" }}
        </button>
      </template>
    </UiModal>

    <!-- Telegram 登录: 验证码 / 两步验证密码 -->
    <UiModal
      v-model="loginDialog"
      title="Telegram 登录"
      :desc="loginPhone"
      :busy="loginBusy"
    >
      <div v-if="loginState === 'starting'" class="alert alert-info">
        <UiIcon name="info" :size="16" />
        <div class="alert-body">
          正在连接 Telegram 并发送验证码，请稍候…
          <div class="small muted" style="margin-top: 4px">
            验证码会发送到该账号的 Telegram 客户端，不是短信。
          </div>
        </div>
      </div>

      <div v-else-if="loginState === 'need_code' || loginState === 'need_password'">
        <div class="alert alert-warn" style="margin-bottom: 14px">
          <UiIcon name="key" :size="16" />
          <div class="alert-body">{{ loginHint }}</div>
        </div>

        <div class="field">
          <label class="label">
            {{ loginState === "need_password" ? "两步验证密码" : "验证码" }}
          </label>
          <input
            class="input"
            :type="loginState === 'need_password' ? 'password' : 'text'"
            v-model="loginInput"
            :placeholder="loginState === 'need_password' ? '请输入两步验证密码' : '请输入收到的验证码'"
            autocomplete="one-time-code"
            autofocus
            @keyup.enter="submitLogin"
          />
          <div v-if="loginState === 'need_code'" class="hint">
            打开手机 Telegram 查看官方账号发来的验证码，数字之间不用加空格。
          </div>
        </div>

        <div v-if="loginError" class="alert alert-bad" style="margin-top: 14px; margin-bottom: 0">
          <UiIcon name="alert" :size="16" />
          <div class="alert-body">{{ loginError }}</div>
        </div>
      </div>

      <div v-else-if="loginState === 'done'" class="alert alert-ok">
        <UiIcon name="check" :size="16" />
        <div class="alert-body">登录成功，会话已保存。刷新页面即可看到账号状态。</div>
      </div>

      <div v-else-if="loginState === 'failed'">
        <div class="alert alert-bad">
          <UiIcon name="alert" :size="16" />
          <div class="alert-body">{{ loginError || "登录失败" }}</div>
        </div>
        <div class="small muted">
          常见原因：验证码过期、手机号未注册、网络无法访问 Telegram、或该账号需要先在手机上登录一次。
          可查看「运行日志」了解详情。
        </div>
      </div>

      <template #footer>
        <button class="btn" @click="closeLogin">
          {{ loginState === "done" ? "完成" : "关闭" }}
        </button>
        <button
          v-if="loginState === 'need_code' || loginState === 'need_password'"
          class="btn btn-primary"
          :disabled="loginBusy"
          @click="submitLogin"
        >
          {{ loginBusy ? "提交中…" : "提交" }}
        </button>
      </template>
    </UiModal>
  </section>
</template>
