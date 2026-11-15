<script setup>
/**
 * 结果通知页.
 *
 * 推荐用 Telegram 机器人直推: 只需两步 —— 从 @BotFather 拿 Token,
 * 填入自己的 Chat ID. 页面内提供分步说明与「发送测试通知」,
 * 填完当场就能验证是否配置正确.
 */
import { computed, onMounted, ref } from "vue";
import { useConfigStore } from "@/stores/config";
import { useToastStore } from "@/stores/toast";
import { api } from "@/api";
import UiIcon from "@/components/ui/UiIcon.vue";
import UiSecret from "@/components/ui/UiSecret.vue";

const config = useConfigStore();
const toast = useToastStore();

const testing = ref(false);
const testResult = ref(null);

onMounted(async () => {
  await config.load();
});

const notifier = computed(() => {
  if (!config.draft.notifier || typeof config.draft.notifier !== "object") {
    config.draft.notifier = {};
  }
  return config.draft.notifier;
});

const method = computed(() => notifier.value.method || "telegram");

function setField(key, value) {
  const next = { ...notifier.value };
  if (value === null || value === undefined || value === "") delete next[key];
  else next[key] = value;
  config.draft.notifier = next;
}

function setEnabled(on) {
  setField("enabled", on);
}

function setMethod(m) {
  setField("method", m);
}

const statusText = computed(() => {
  if (!notifier.value.enabled) return "通知已关闭";
  if (method.value === "telegram") {
    if (!notifier.value.bot_token) return "还缺 Bot Token";
    if (!notifier.value.chat_id) return "还缺 Chat ID";
    return "配置完整";
  }
  return notifier.value.apprise_uri ? "配置完整" : "还缺 Apprise 地址";
});

const ready = computed(() => statusText.value === "配置完整");

async function test() {
  testing.value = true;
  testResult.value = null;
  try {
    const data = await api.testNotifier();
    testResult.value = data;
    if (data && data.ok) toast.ok(data.message || "测试通知已发送");
    else toast.bad((data && data.error) || "发送失败");
  } catch (e) {
    testResult.value = { ok: false, error: e.message };
    toast.bad(e.message);
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <section>
    <div class="head">
      <div>
        <h1>结果通知</h1>
        <p>签到完成后把结果推送到手机，避免自己惦记着去查。</p>
      </div>
    </div>

    <div v-if="config.loading && !config.ready" class="alert alert-info">
      <UiIcon name="info" :size="16" />
      <div class="alert-body">正在加载配置…</div>
    </div>

    <template v-if="config.ready">
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">通知开关</h2>
            <div class="card-desc">{{ statusText }}</div>
          </div>
          <label class="sw">
            <input
              type="checkbox"
              :checked="!!notifier.enabled"
              @change="setEnabled($event.target.checked)"
            />
            <span class="sw-track"></span>
            <span class="sw-text">{{ notifier.enabled ? "已开启" : "已关闭" }}</span>
          </label>
        </div>

        <div class="card-body">
          <div class="field">
            <label class="label">推送方式</label>
            <div class="seg" style="margin-top: 4px">
              <button
                type="button"
                class="seg-item"
                :class="{ on: method === 'telegram' }"
                @click="setMethod('telegram')"
              >
                Telegram 机器人（推荐）
              </button>
              <button
                type="button"
                class="seg-item"
                :class="{ on: method === 'apprise' }"
                @click="setMethod('apprise')"
              >
                Apprise 服务
              </button>
            </div>
          </div>

          <!-- Telegram -->
          <template v-if="method === 'telegram'">
            <div class="divider"></div>
            <div class="grid-2">
              <div class="field">
                <label class="label">
                  Bot Token
                  <span class="req">必填</span>
                </label>
                <UiSecret
                  :model-value="notifier.bot_token || ''"
                  placeholder="123456789:ABCdef..."
                  empty-hint="从 @BotFather 创建机器人后获得"
                  @update:model-value="(v) => setField('bot_token', v)"
                />
              </div>
              <div class="field">
                <label class="label">
                  Chat ID
                  <span class="req">必填</span>
                </label>
                <input
                  class="input"
                  :value="notifier.chat_id || ''"
                  placeholder="例如 123456789"
                  @input="setField('chat_id', $event.target.value)"
                />
                <div class="hint">你的用户 ID；群组填负数，频道可填 @频道名</div>
              </div>
            </div>

            <div class="divider"></div>

            <div class="small" style="font-weight: 620; margin-bottom: 8px">
              怎么拿到这两个值？
            </div>
            <ol class="small muted" style="margin: 0; padding-left: 20px; line-height: 2">
              <li>
                在 Telegram 搜索 <code>@BotFather</code>，发送 <code>/newbot</code>，
                按提示创建机器人
              </li>
              <li>创建完成后 BotFather 会回复一串 Token（形如 <code>123456789:ABCdef...</code>），填入上面</li>
              <li>在 Telegram 里打开刚创建的机器人，<b>先点一次「开始」并发一条任意消息</b></li>
              <li>
                再搜索 <code>@userinfobot</code> 并给它发消息，它会回复你的 ID，填入 Chat ID
              </li>
              <li>最后点击下面「发送测试通知」，能收到消息就说明配置正确</li>
            </ol>

            <div class="row-flex" style="margin-top: 16px">
              <button class="btn" :disabled="testing || !ready" @click="test">
                <UiIcon name="bell" :size="15" />
                {{ testing ? "发送中…" : "发送测试通知" }}
              </button>
              <span v-if="!ready" class="small muted">先填完 Token 与 Chat ID，保存后再测试</span>
              <span v-else class="small muted">使用已保存的配置发送</span>
            </div>
          </template>

          <!-- Apprise -->
          <template v-else>
            <div class="divider"></div>
            <div class="field">
              <label class="label">
                Apprise 地址
                <span class="req">必填</span>
              </label>
              <div class="hint">形如 <code>tgram://bot_token/chat_id</code> 或自建服务地址</div>
              <input
                class="input"
                :value="notifier.apprise_uri || ''"
                placeholder="tgram://123456:ABC/123456789"
                @input="setField('apprise_uri', $event.target.value)"
              />
            </div>
            <div class="alert alert-info" style="margin-top: 16px; margin-bottom: 0">
              <UiIcon name="info" :size="16" />
              <div class="alert-body">
                Apprise 方式支持更多推送渠道，但需要自己拼接地址。若只是想推到 Telegram，
                建议改用上面的「Telegram 机器人」方式，更简单。
              </div>
            </div>
          </template>
        </div>
      </div>

      <div v-if="testResult && !testResult.ok" class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">测试结果</h2>
            <div class="card-desc">下面是 Telegram 返回的具体原因</div>
          </div>
        </div>
        <div class="card-body">
          <pre class="mono small" style="margin: 0; white-space: pre-wrap">{{ testResult.error }}</pre>
        </div>
      </div>
    </template>
  </section>
</template>
