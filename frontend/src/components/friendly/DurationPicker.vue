<script setup>
/**
 * 时长选择器 (播放/收听时长).
 *
 * 配置里以秒为单位且可能是数组形式 (如 [300, 600]), 这里一律换算成分钟,
 * 用两个数字输入框表达, 回写时再换算回秒.
 */
import { computed } from "vue";
import { parseDuration, formatDuration } from "@/lib/friendly";

const props = defineProps({
  modelValue: { type: [Number, Array], default: null },
  /** 动作词: 播放 / 收听 */
  verb: { type: String, default: "播放" },
});

const emit = defineEmits(["update:modelValue"]);

const dur = computed(() => parseDuration(props.modelValue));

function setBound(which, value) {
  const n = Math.max(1, parseInt(value, 10) || 1);
  const next = { ...dur.value };
  next[which] = n;
  emit("update:modelValue", formatDuration(next));
}

const summary = computed(() => {
  const { minMinutes: lo, maxMinutes: hi } = dur.value;
  if (lo === hi) return `每次${props.verb}约 ${lo} 分钟`;
  return `每次${props.verb} ${lo} ~ ${hi} 分钟（随机）`;
});
</script>

<template>
  <div>
    <div class="num-unit">
      <input
        class="input"
        type="number"
        min="1"
        :value="dur.minMinutes"
        @input="setBound('minMinutes', $event.target.value)"
      />
      <span class="num-unit-label">到</span>
      <input
        class="input"
        type="number"
        min="1"
        :value="dur.maxMinutes"
        @input="setBound('maxMinutes', $event.target.value)"
      />
      <span class="num-unit-label">分钟</span>
    </div>
    <div class="hint" style="margin-top: 9px">{{ summary }}</div>
  </div>
</template>
