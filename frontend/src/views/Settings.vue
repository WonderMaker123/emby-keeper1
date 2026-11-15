<script setup>
/**
 * 系统设置页.
 *
 * 分成四块, 每块只讲一件事:
 *   1. 签到什么时候跑
 *   2. 保活什么时候跑
 *   3. 验证码怎么识别
 *   4. 走不走代理
 * 时间、间隔一律用友好控件, 不出现任何表达式语法.
 */
import { computed, onMounted } from "vue";
import { useConfigStore } from "@/stores/config";
import UiIcon from "@/components/ui/UiIcon.vue";
import UiSecret from "@/components/ui/UiSecret.vue";
import TimeRange from "@/components/friendly/TimeRange.vue";
import IntervalPicker from "@/components/friendly/IntervalPicker.vue";

const config = useConfigStore();

onMounted(async () => {
  await config.load();
});

/** 取某模块对象 (确保存在), 返回可写的引用 */
function useSection(name) {
  if (!config.draft) config.draft = {};
  if (!config.draft[name] || typeof config.draft[name] !== "object") {
    config.draft[name] = {};
  }
  return config.draft[name];
}

const checkiner = computed(() => useSection("checkiner"));
const emby = computed(() => useSection("emby"));
const subsonic = computed(() => useSection("subsonic"));
const ocr = computed(() => useSection("ocr"));

/** 写入某模块的字段; 空值删除, 让业务回落到默认值 */
function setField(name, key, value) {
  const target = { ...useSection(name) };
  if (value === null || value === undefined || value === "") delete target[key];
  else target[key] = value;
  config.draft[name] = target;
}

/** 数字型字段: 空值删除, 便于回落到默认值 */
function setNumber(name, key, value) {
  const sec = { ...useSection(name) };
  const n = value === "" ? null : Number(value);
  if (n === null || Number.isNaN(n)) delete sec[key];
  else sec[key] = n;
  config.draft[name] = sec;
}

/* ---------------- 代理 ---------------- */

const proxyOn = computed(() => config.draft?.proxy != null);

function toggleProxy(on) {
  config.draft.proxy = on
    ? { hostname: "", port: 1080, scheme: "socks5" }
    : null;
}

function setProxy(key, value) {
  const next = { ...(config.draft.proxy || {}) };
  if (value === null || value === undefined || value === "") delete next[key];
  else next[key] = key === "port" ? Number(value) : value;
  config.draft.proxy = next;
}

const proxyValid = computed(
  () => !!config.draft?.proxy?.hostname && !!config.draft?.proxy?.port
);

/* ---------------- 验证码 ---------------- */

const aiEnabled = computed(() => (ocr.value.provider || "ai") === "ai");

function setProvider(p) {
  setField("ocr", "provider", p);
}

</script>

<template>
  <section>
    <div class="head">
      <div>
        <h1>系统设置</h1>
        <p>签到与保活的执行时间、验证码识别方式，以及网络代理。</p>
      </div>
    </div>

    <div v-if="config.loading && !config.ready" class="alert alert-info">
      <UiIcon name="info" :size="16" />
      <div class="alert-body">正在加载配置…</div>
    </div>

    <template v-if="config.ready">
      <!-- 签到 -->
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">
              <UiIcon name="globe" :size="16" />
              站点签到
            </h2>
            <div class="card-desc">Telegram 机器人签到的执行时间与重试策略</div>
          </div>
        </div>
        <div class="card-body">
          <div class="grid-2">
            <div class="field">
              <label class="label">签到时间段</label>
              <TimeRange
                :model-value="checkiner.time_range"
                verb="签到"
                @update:model-value="(v) => setField('checkiner', 'time_range', v)"
              />
            </div>
            <div class="field">
              <label class="label">签到间隔</label>
              <IntervalPicker
                :model-value="checkiner.interval_days ?? '1'"
                verb="签到"
                @update:model-value="(v) => setField('checkiner', 'interval_days', v)"
              />
            </div>
          </div>

          <div class="divider"></div>

          <div class="grid-2">
            <div class="field">
              <label class="label">启动随机延迟</label>
              <div class="hint">各站点错开启动，避免同一秒集中请求</div>
              <div class="num-unit">
                <input
                  class="input"
                  type="number"
                  min="0"
                  :value="checkiner.random_start ?? ''"
                  @input="setNumber('checkiner', 'random_start', $event.target.value)"
                />
                <span class="num-unit-label">分钟</span>
              </div>
            </div>
            <div class="field">
              <label class="label">单站超时</label>
              <div class="hint">单个站点签到最长等待时间</div>
              <div class="num-unit">
                <input
                  class="input"
                  type="number"
                  min="1"
                  :value="checkiner.timeout ?? ''"
                  @input="setNumber('checkiner', 'timeout', $event.target.value)"
                />
                <span class="num-unit-label">秒</span>
              </div>
            </div>
            <div class="field">
              <label class="label">失败重试次数</label>
              <div class="num-unit">
                <input
                  class="input"
                  type="number"
                  min="0"
                  :value="checkiner.retries ?? ''"
                  @input="setNumber('checkiner', 'retries', $event.target.value)"
                />
                <span class="num-unit-label">次</span>
              </div>
            </div>
            <div class="field">
              <label class="label">同时签到站点数</label>
              <div class="hint">调大可加快完成，但更容易触发风控</div>
              <div class="num-unit">
                <input
                  class="input"
                  type="number"
                  min="1"
                  :value="checkiner.concurrency ?? ''"
                  @input="setNumber('checkiner', 'concurrency', $event.target.value)"
                />
                <span class="num-unit-label">个</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 保活 -->
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">
              <UiIcon name="server" :size="16" />
              媒体服保活
            </h2>
            <div class="card-desc">Emby 与 Subsonic 的播放/收听时间安排</div>
          </div>
        </div>
        <div class="card-body">
          <div class="grid-2">
            <div class="field">
              <label class="label">Emby 保活时间段</label>
              <TimeRange
                :model-value="emby.time_range"
                verb="保活"
                @update:model-value="(v) => setField('emby', 'time_range', v)"
              />
            </div>
            <div class="field">
              <label class="label">Emby 保活间隔</label>
              <IntervalPicker
                :model-value="emby.interval_days ?? '1'"
                verb="保活"
                @update:model-value="(v) => setField('emby', 'interval_days', v)"
              />
            </div>
          </div>

          <div class="divider"></div>

          <div class="grid-2">
            <div class="field">
              <label class="label">Subsonic 保活时间段</label>
              <TimeRange
                :model-value="subsonic.time_range"
                verb="保活"
                @update:model-value="(v) => setField('subsonic', 'time_range', v)"
              />
            </div>
            <div class="field">
              <label class="label">Subsonic 保活间隔</label>
              <IntervalPicker
                :model-value="subsonic.interval_days ?? '1'"
                verb="保活"
                @update:model-value="(v) => setField('subsonic', 'interval_days', v)"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- 验证码 -->
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">
              <UiIcon name="shield" :size="16" />
              验证码识别
            </h2>
            <div class="card-desc">部分站点签到时会弹图片验证码，需要自动识别</div>
          </div>
        </div>
        <div class="card-body">
          <div class="field">
            <label class="label">识别方式</label>
            <div class="seg" style="margin-top: 4px">
              <button
                type="button"
                class="seg-item"
                :class="{ on: aiEnabled }"
                @click="setProvider('ai')"
              >
                AI 识别（准确率高，推荐）
              </button>
              <button
                type="button"
                class="seg-item"
                :class="{ on: !aiEnabled }"
                @click="setProvider('local')"
              >
                本地识别（免费，准确率较低）
              </button>
            </div>
          </div>

          <template v-if="aiEnabled">
            <div class="divider"></div>
            <div class="alert alert-info" style="margin-bottom: 16px">
              <UiIcon name="info" :size="16" />
              <div class="alert-body">
                AI 识别需要填写模型服务的 API Key。若 AI 调用失败，程序会自动退回本地识别，
                不会因此跳过签到。
              </div>
            </div>
            <div class="grid-2">
              <div class="field">
                <label class="label">
                  API Key
                  <span class="req">必填</span>
                </label>
                <UiSecret
                  :model-value="ocr.ai_api_key || ''"
                  placeholder="sk-..."
                  @update:model-value="(v) => setField('ocr', 'ai_api_key', v)"
                />
              </div>
              <div class="field">
                <label class="label">模型名称</label>
                <div class="hint">留空使用内置默认模型</div>
                <input
                  class="input"
                  :value="ocr.ai_model || ''"
                  placeholder="sensenova-6.8-flash-lite"
                  @input="setField('ocr', 'ai_model', $event.target.value)"
                />
              </div>
              <div class="field">
                <label class="label">接口地址</label>
                <div class="hint">留空使用内置默认地址</div>
                <input
                  class="input"
                  :value="ocr.ai_base_url || ''"
                  placeholder="https://token.sensenova.cn/v1"
                  @input="setField('ocr', 'ai_base_url', $event.target.value)"
                />
              </div>
              <div class="field">
                <label class="label">请求超时</label>
                <div class="num-unit">
                  <input
                    class="input"
                    type="number"
                    min="1"
                    :value="ocr.ai_timeout ?? ''"
                    @input="setNumber('ocr', 'ai_timeout', $event.target.value)"
                  />
                  <span class="num-unit-label">秒</span>
                </div>
              </div>
            </div>
          </template>

          <div v-else class="alert alert-warn" style="margin-top: 16px; margin-bottom: 0">
            <UiIcon name="alert" :size="16" />
            <div class="alert-body">
              本地识别依靠离线模型，字体稍有变化的验证码就容易认错。若签到老是失败，
              建议改用 AI 识别。
            </div>
          </div>
        </div>
      </div>

      <!-- 代理 -->
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">
              <UiIcon name="link" :size="16" />
              网络代理
            </h2>
            <div class="card-desc">服务器访问境外站点困难时才需要配置</div>
          </div>
          <label class="sw">
            <input type="checkbox" :checked="proxyOn" @change="toggleProxy($event.target.checked)" />
            <span class="sw-track"></span>
            <span class="sw-text">{{ proxyOn ? "已启用" : "未启用" }}</span>
          </label>
        </div>

        <div v-if="proxyOn" class="card-body">
          <div class="grid-2">
            <div class="field">
              <label class="label">
                代理地址
                <span class="req">必填</span>
              </label>
              <input
                class="input"
                :value="config.draft.proxy?.hostname || ''"
                placeholder="127.0.0.1"
                @input="setProxy('hostname', $event.target.value)"
              />
            </div>
            <div class="field">
              <label class="label">
                端口
                <span class="req">必填</span>
              </label>
              <input
                class="input"
                type="number"
                :value="config.draft.proxy?.port ?? ''"
                placeholder="1080"
                @input="setProxy('port', $event.target.value)"
              />
            </div>
            <div class="field">
              <label class="label">协议</label>
              <select
                class="select"
                :value="config.draft.proxy?.scheme || 'socks5'"
                @change="setProxy('scheme', $event.target.value)"
              >
                <option value="socks5">socks5</option>
                <option value="http">http</option>
              </select>
            </div>
            <div class="field">
              <label class="label">用户名</label>
              <div class="hint">代理无需认证时留空</div>
              <input
                class="input"
                :value="config.draft.proxy?.username || ''"
                @input="setProxy('username', $event.target.value)"
              />
            </div>
            <div class="field">
              <label class="label">密码</label>
              <UiSecret
                :model-value="config.draft.proxy?.password || ''"
                @update:model-value="(v) => setProxy('password', v)"
              />
            </div>
          </div>

          <div v-if="!proxyValid" class="alert alert-warn" style="margin: 16px 0 0">
            <UiIcon name="alert" :size="16" />
            <div class="alert-body">代理地址和端口需要填写完整，否则连接会失败。</div>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>
