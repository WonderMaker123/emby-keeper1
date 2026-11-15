<script setup>
/**
 * 时间段选择器.
 *
 * 把配置文件里的 `"<11:00AM,11:00PM>"` 换成两个原生时间选择框,
 * 并给出「每天在 11:00 到 23:00 之间随机执行」这类人话描述.
 * 用户完全不需要知道表达式语法.
 */
import { computed } from "vue";
import UiIcon from "@/components/ui/UiIcon.vue";
import { parseTimeRange, formatTimeRange } from "@/lib/friendly";

const props = defineProps({
  modelValue: { type: String, default: "" },
  /** 动作词, 用于生成描述, 例如「签到」「保活」 */
  verb: { type: String, default: "执行" },
});

const emit = defineEmits(["update:modelValue"]);

const range = computed(() => parseTimeRange(props.modelValue));

function update(which, val) {
  const next = { ...range.value };
  next[which] = val || "00:00";
  emit("update:modelValue", formatTimeRange(next.start, next.end) || "");
}

/** 常见区间, 免去手动选择 */
const PRESETS = [
  { label: "上午", start: "08:00", end: "12:00" },
  { label: "下午", start: "13:00", end: "18:00" },
  { label: "晚间", start: "19:00", end: "23:30" },
  { label: "白天全天", start: "08:00", end: "23:00" },
];

function applyPreset(p) {
  emit("update:modelValue", formatTimeRange(p.start, p.end));
}

const isActive = (p) => range.value.start === p.start && range.value.end === p.end;

/** 人话描述, 让用户确认设置意图 */
const summary = computed(() => {
  const { start, end } = range.value;
  if (start === end) return `每天 ${start} 左右${props.verb}一次`;
  return `每天在 ${start} ~ ${end} 之间随机${props.verb}一次`;
});
</script>

<template>
  <div>
    <div class="time-pair">
      <div class="time-chip">
        <UiIcon name="clock" :size="15" style="color: var(--ink-3)" />
        <input
          type="time"
          :value="range.start"
          aria-label="开始时间"
          @input="update('start', $event.target.value)"
        />
      </div>
      <span class="muted">至</span>
      <div class="time-chip">
        <UiIcon name="clock" :size="15" style="color: var(--ink-3)" />
        <input
          type="time"
          :value="range.end"
          aria-label="结束时间"
          @input="update('end', $event.target.value)"
        />
      </div>
    </div>

    <div class="presets">
      <button
        v-for="p in PRESETS"
        :key="p.label"
        type="button"
        class="preset"
        :style="
          isActive(p)
            ? 'border-color: var(--brand); color: var(--brand); background: var(--brand-soft)'
            : ''
        "
        @click="applyPreset(p)"
      >
        {{ p.label }}
      </button>
    </div>

    <div class="hint" style="margin-top: 9px">
      {{ summary }}
      <span class="muted">（在此区间内随机挑选时刻，避免所有任务同一时间触发）</span>
    </div>
  </div>
</template>
