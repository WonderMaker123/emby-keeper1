<script setup>
/**
 * 签到站点页.
 *
 * 用户只需做三件事: 选范围、点站点、加自定义 Bot.
 * 配置里 site.checkiner 的表达式细节 (-all / +cc / templ_a<@x>) 全部由
 * lib/friendly 负责转换, 界面上不出现任何语法.
 */
import { computed, onMounted, ref } from "vue";
import { useConfigStore } from "@/stores/config";
import { useSitesStore } from "@/stores/sites";
import { useToastStore } from "@/stores/toast";
import { parseSiteTokens, composeSiteTokens, templateToken, tokenBot } from "@/lib/friendly";
import { api } from "@/api";
import UiIcon from "@/components/ui/UiIcon.vue";
import UiModal from "@/components/ui/UiModal.vue";

const config = useConfigStore();
const sites = useSitesStore();
const toast = useToastStore();

const keyword = ref("");
const activeCategory = ref("");
const onlyPicked = ref(false);

const botDialogOpen = ref(false);
const botForm = ref({});
const botParams = ref([]);
const botError = ref("");
const botBusy = ref(false);
const editingToken = ref("");
// 高级参数默认折叠: 默认值已覆盖绝大多数站点, 不应一上来就给用户 13 个输入框
const showAdvancedBot = ref(false);

const runningCheckin = ref(false);
const runningSite = ref("");

async function runAllCheckin() {
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
      toast.ok(data.message || "已在后台开始执行站点签到，请查看运行日志");
    } else {
      toast.bad((data && (data.error || data.message)) || "触发签到失败");
    }
  } catch (e) {
    toast.bad(e.message);
  } finally {
    runningCheckin.value = false;
  }
}

async function runSingleSite(site) {
  runningSite.value = site;
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
    const data = await api.runCheckinNow(site);
    if (data && data.ok) {
      toast.ok(data.message || `已在后台开始签到，请查看运行日志`);
    } else {
      toast.bad((data && (data.error || data.message)) || "触发签到失败");
    }
  } catch (e) {
    toast.bad(e.message);
  } finally {
    runningSite.value = "";
  }
}

onMounted(async () => {
  await Promise.all([config.load(), sites.load()]);
});

/* ---------------- 站点范围模型 ---------------- */

const model = computed(() => parseSiteTokens(config.draft?.site?.checkiner));

const MODES = [
  { key: "recommend", label: "默认推荐", desc: "使用项目推荐的站点，最省心" },
  { key: "all", label: "全部站点", desc: "签到所有已知站点，数量较多" },
  { key: "manual", label: "手动选择", desc: "自己挑选要签到的站点" },
];

function update(mutator) {
  const next = JSON.parse(JSON.stringify(model.value));
  mutator(next);
  config.draft.site = { ...(config.draft.site || {}), checkiner: composeSiteTokens(next) };
}

function setMode(mode) {
  update((m) => {
    m.mode = mode;
    // 切到手动且尚未选过任何站点时, 以推荐站为起点, 避免出现「空范围」
    if (mode === "manual" && !m.picked.length && !m.excludeAll) {
      m.picked = sites.list.filter((s) => s.recommended).map((s) => s.key);
    }
  });
}

function toggleExcludeSgk() {
  update((m) => {
    m.excludeSgk = !m.excludeSgk;
  });
}

const pickedSet = computed(() => new Set(model.value.picked));

function toggleSite(site) {
  update((m) => {
    const set = new Set(m.picked);
    if (set.has(site.key)) set.delete(site.key);
    else set.add(site.key);
    m.picked = Array.from(set);
    m.excludeAll = false;
  });
}

function selectRecommended() {
  update((m) => {
    m.picked = sites.list.filter((s) => s.recommended).map((s) => s.key);
    m.excludeAll = false;
  });
}

function clearAll() {
  update((m) => {
    m.picked = [];
  });
}

/* ---------------- 站点清单筛选 ---------------- */

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase();
  let list = sites.list;
  if (activeCategory.value) list = list.filter((s) => s.category === activeCategory.value);
  if (onlyPicked.value) list = list.filter((s) => pickedSet.value.has(s.key));
  if (!kw) return list;
  return list.filter(
    (s) =>
      (s.name || "").toLowerCase().includes(kw) ||
      (s.key || "").toLowerCase().includes(kw) ||
      (s.bot_username || "").toLowerCase().includes(kw)
  );
});

const pickedCount = computed(() => model.value.picked.length);

const rangeSummary = computed(() => {
  const m = model.value;
  if (m.mode === "all") return `全部站点${m.excludeSgk ? "（排除社工库）" : ""}`;
  if (m.mode === "recommend") return `默认推荐站点${m.excludeSgk ? "（排除社工库）" : ""}`;
  if (!m.picked.length) return "没有选择任何站点，将不会执行签到";
  return `已选择 ${m.picked.length} 个站点`;
});

/* ---------------- 自定义站点 ---------------- */

const templates = computed(() => model.value.templates);

function botName(token) {
  return config.draft?.checkiner?.[token]?.name || `@${tokenBot(token)}`;
}

async function openBot(token = "") {
  botError.value = "";
  editingToken.value = token;
  // 编辑已有站点时默认展开高级参数, 否则用户看不到之前改过什么
  showAdvancedBot.value = Boolean(token);

  if (!botParams.value.length) {
    try {
      const data = await api.getTemplateFields();
      botParams.value = data.fields || [];
    } catch (e) {
      botError.value = e.message;
    }
  }

  if (token) {
    const params = config.draft?.checkiner?.[token] || {};
    const { name, ...rest } = params;
    botForm.value = { bot_username: tokenBot(token), name: name || "", ...rest };
  } else {
    botForm.value = { bot_username: "", name: "", bot_checkin_cmd: "/start", bot_use_captcha: true };
  }
  botDialogOpen.value = true;
}

function setBotField(key, value) {
  const next = { ...botForm.value };
  if (value === null || value === undefined || value === "") delete next[key];
  else next[key] = value;
  botForm.value = next;
}

async function submitBot() {
  botError.value = "";
  const bot = String(botForm.value.bot_username || "").trim().replace(/^@/, "");
  if (!bot) {
    botError.value = "请填写机器人用户名";
    return;
  }

  botBusy.value = true;
  try {
    const check = await api.validateBot(bot);
    if (check && !check.ok) {
      botError.value = check.error || "机器人用户名不合法";
      return;
    }
  } catch (e) {
    botError.value = e.message;
    return;
  } finally {
    botBusy.value = false;
  }

  const token = templateToken(bot);
  const params = { ...botForm.value };
  delete params.bot_username;

  if (!config.draft.checkiner) config.draft.checkiner = {};
  if (editingToken.value && editingToken.value !== token) {
    delete config.draft.checkiner[editingToken.value];
  }
  config.draft.checkiner[token] = params;

  update((m) => {
    m.templates = m.templates.filter((t) => t !== editingToken.value);
    if (!m.templates.includes(token)) m.templates.push(token);
  });

  botDialogOpen.value = false;
  toast.info("已加入站点列表，记得点击「保存配置」");
}

function removeBot(token) {
  if (!window.confirm(`确定移除自定义站点「${botName(token)}」吗？`)) return;
  if (config.draft.checkiner) delete config.draft.checkiner[token];
  update((m) => {
    m.templates = m.templates.filter((t) => t !== token);
  });
  toast.info("已移除，记得保存配置");
}
</script>

<template>
  <section>
    <div class="head">
      <div>
        <h1>签到站点</h1>
        <p>决定参与签到的站点。共收录 {{ sites.list.length }} 个站点，也可添加自己的 Bot。</p>
      </div>
      <div class="head-actions">
        <button
          class="btn btn-primary"
          :disabled="runningCheckin"
          @click="runAllCheckin"
          title="立即执行所有已选站点的签到"
        >
          <UiIcon name="play" :size="15" />
          {{ runningCheckin ? "签到中…" : "立即签到一次" }}
        </button>
        <button
          class="btn"
          @click="openBot()"
        >
          <UiIcon name="plus" :size="15" />
          添加自定义站点
        </button>
      </div>
    </div>

    <div v-if="sites.loading && !sites.loaded" class="alert alert-info">
      <UiIcon name="info" :size="16" />
      <div class="alert-body">正在读取站点清单…</div>
    </div>

    <template v-if="config.ready">
      <!-- 范围 -->
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">签到范围</h2>
            <div class="card-desc">{{ rangeSummary }}</div>
          </div>
          <span class="badge badge-brand">{{ pickedCount || (model.mode === "manual" ? 0 : "自动") }}</span>
        </div>

        <div class="card-body">
          <div class="seg">
            <button
              v-for="m in MODES"
              :key="m.key"
              type="button"
              class="seg-item"
              :class="{ on: model.mode === m.key }"
              @click="setMode(m.key)"
            >
              {{ m.label }}
            </button>
          </div>

          <div class="hint" style="margin-top: 9px">
            {{ MODES.find((x) => x.key === model.mode)?.desc }}
          </div>

          <div v-if="model.mode === 'manual'" style="margin-top: 14px">
            <div class="small muted" style="margin-bottom: 6px">
              当前已勾选的内置站点（{{ pickedCount }} 个）：
            </div>
            <div v-if="!model.picked.length" class="small" style="color: var(--bad)">
              尚未勾选任何内置站点，请在下方列表中勾选您需要签到的站点。
            </div>
            <div v-else class="row-flex" style="gap: 6px">
              <span v-for="key in model.picked" :key="key" class="tag">
                {{ sites.displayName(key) }}
                <button type="button" class="tag-x" title="取消勾选" @click="toggleSite({ key })">×</button>
              </span>
            </div>
          </div>

          <div v-if="model.mode !== 'manual'" class="divider"></div>

          <label v-if="model.mode !== 'manual'" class="sw">
            <input type="checkbox" :checked="model.excludeSgk" @change="toggleExcludeSgk" />
            <span class="sw-track"></span>
            <span class="sw-text">排除社工库类站点（这些站点通常不需要签到）</span>
          </label>
        </div>
      </div>

      <!-- 手动选择 -->
      <div v-if="model.mode === 'manual'" class="card">
        <div class="logbar">
          <div class="search">
            <span class="search-ico"><UiIcon name="search" :size="15" /></span>
            <input v-model="keyword" class="input" placeholder="搜索站点名称" />
          </div>
          <select v-model="activeCategory" class="select" style="width: auto; min-width: 130px">
            <option value="">全部分类</option>
            <option v-for="c in sites.categories" :key="c" :value="c">{{ c }}</option>
          </select>
          <label class="chk">
            <input v-model="onlyPicked" type="checkbox" />
            只看已选
          </label>
          <div class="spacer"></div>
          <button class="btn btn-sm" @click="selectRecommended">选推荐</button>
          <button class="btn btn-sm" @click="clearAll">清空</button>
        </div>

        <div v-if="!filtered.length" class="empty">
          <div class="empty-t">没有找到站点</div>
          <div class="empty-d">换个关键词，或切换分类试试。</div>
        </div>

        <div v-else class="site-grid">
          <div
            v-for="site in filtered"
            :key="site.key"
            class="site-cell"
            :class="{ on: pickedSet.has(site.key) }"
            @click="toggleSite(site)"
          >
            <div class="site-box">
              <UiIcon v-if="pickedSet.has(site.key)" name="check" :size="12" />
            </div>
            <div style="flex: 1; min-width: 0">
              <div class="site-name">{{ site.name }}</div>
              <div class="site-key">{{ site.key }}</div>
            </div>
            <span v-if="site.has_captcha" class="badge badge-warn" title="签到需要识别验证码">验证码</span>
          </div>
        </div>
      </div>

      <!-- 自定义站点 -->
      <div class="card">
        <div class="card-head">
          <div>
            <h2 class="card-title">
              自定义站点
              <span class="pill">{{ templates.length }}</span>
            </h2>
            <div class="card-desc">
              内置清单里没有你的服时，填入它的 Telegram 机器人用户名即可
            </div>
          </div>
          <button class="btn btn-sm" @click="openBot()">
            <UiIcon name="plus" :size="14" />
            添加
          </button>
        </div>

        <div v-if="!templates.length" class="empty">
          <div class="empty-ico"><UiIcon name="robot" :size="24" /></div>
          <div class="empty-t">还没有自定义站点</div>
          <div class="empty-d">
            只有一种情况需要加：你的站点机器人<b>不在上面列表里</b>。
            在 Telegram 能对它发送 <code>/start</code> 并看到带「签到」按钮的面板，就可以加。
          </div>
          <button class="btn btn-primary btn-sm" @click="openBot()">添加一个</button>
        </div>

        <div v-else>
          <div v-for="token in templates" :key="token" class="row">
            <div class="row-main">
              <div class="row-t">{{ botName(token) }}</div>
              <div class="row-s mono">@{{ tokenBot(token) }}</div>
            </div>
            <div class="row-actions">
              <button
                class="btn btn-sm"
                :disabled="runningSite === token || runningCheckin"
                @click="runSingleSite(token)"
                title="只立即签到这一个自定义站点"
              >
                <UiIcon name="play" :size="13" />
                {{ runningSite === token ? "执行中…" : "立即签到" }}
              </button>
              <button class="btn btn-sm btn-ghost" @click="openBot(token)">
                <UiIcon name="pencil" :size="14" />
                编辑
              </button>
              <button class="btn btn-sm btn-danger" @click="removeBot(token)">
                <UiIcon name="trash" :size="14" />
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- 自定义站点弹窗 -->
    <UiModal
      v-model="botDialogOpen"
      :title="editingToken ? '编辑自定义站点' : '添加自定义站点'"
      desc="填写机器人用户名即可，其余参数保持默认通常就能用"
      :busy="botBusy"
    >
      <div v-if="botError" class="alert alert-bad">
        <UiIcon name="alert" :size="16" />
        <div class="alert-body">{{ botError }}</div>
      </div>

      <!-- 第一步: 只问机器人用户名 -->
      <div class="field">
        <label class="label">
          机器人用户名
          <span class="req">必填</span>
        </label>
        <div class="hint">
          在 Telegram 里打开这个机器人，看它名字下方的 <code>@xxx</code>，
          把 xxx 填到这里（不带 @ 也可以）。
        </div>
        <div class="input-join">
          <input
            class="input"
            :value="botForm.bot_username || ''"
            placeholder="例如 peach_emby_bot"
            @input="setBotField('bot_username', $event.target.value)"
          />
        </div>
      </div>

      <div class="field" style="margin-top: 16px">
        <label class="label">显示名称</label>
        <div class="hint">在列表和日志里显示的名字，可留空（自动用机器人名）</div>
        <input
          class="input"
          :value="botForm.name || ''"
          placeholder="例如 我的小站"
          @input="setBotField('name', $event.target.value)"
        />
      </div>

      <!-- 提醒: 默认值已覆盖绝大多数情况 -->
      <div class="alert alert-ok" style="margin-top: 18px; margin-bottom: 0">
        <UiIcon name="check" :size="16" />
        <div class="alert-body">
          <b>不需要再填其他参数。</b>
          程序默认会发送 <code>/start</code> 并自动点击「签到」按钮、自动识别验证码，
          已适配绝大多数站点。
          <button
            type="button"
            class="btn btn-sm btn-ghost"
            style="margin-top: 8px"
            @click="showAdvancedBot = !showAdvancedBot"
          >
            <UiIcon name="arrow" :size="13" />
            {{ showAdvancedBot ? "收起高级参数" : "签到不成功？展开高级参数" }}
          </button>
        </div>
      </div>

      <!-- 第二步 (可选): 高级参数 -->
      <template v-if="showAdvancedBot">
        <div class="divider"></div>
        <div class="small muted" style="margin-bottom: 14px">
          不确定含义就保持默认。常见需要改的只有「签到命令」与「签到按钮文本」。
        </div>

        <div class="grid-2">
          <div v-for="p in botParams.filter((x) => x.key !== 'name')" :key="p.key" class="field">
            <label class="label">{{ p.label }}</label>
            <div v-if="p.description" class="hint">{{ p.description }}</div>

            <label v-if="p.schema?.type === 'boolean'" class="sw">
              <input
                type="checkbox"
                :checked="!!botForm[p.key]"
                @change="setBotField(p.key, $event.target.checked)"
              />
              <span class="sw-track"></span>
              <span class="sw-text">{{ botForm[p.key] ? "已开启" : "已关闭" }}</span>
            </label>
            <input
              v-else
              class="input"
              :type="p.schema?.type === 'integer' ? 'number' : 'text'"
              :value="botForm[p.key] ?? ''"
              @input="setBotField(p.key, $event.target.value)"
            />
          </div>
        </div>
      </template>

      <template #footer>
        <button class="btn" :disabled="botBusy" @click="botDialogOpen = false">取消</button>
        <button class="btn btn-primary" :disabled="botBusy" @click="submitBot">
          {{ botBusy ? "校验中…" : "确定" }}
        </button>
      </template>
    </UiModal>
  </section>
</template>
