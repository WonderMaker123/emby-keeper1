<script setup>
/**
 * 间隔天数选择器.
 *
 * 配置里是 "1" 或 "<7,12>" 这类串, 这里换成三段式选择:
 *   每天 / 每隔 N 天 / 每隔 X~Y 天随机
 */
import { computed } from "vue";
import { parseInterval, formatInterval } from "@/lib/friendly";

const props = defineProps({
  modelValue: { type: [String, Number], default: "1" },
  verb: { type: String, default: "执行" },
});

const emit = defineEmits(["update:modelValue"]);

const iv = computed(() => parseInterval(props.modelValue));

/** 三段式: 每天(N=1) / 固定 N 天 / 区间随机 */
const mode = computed(() => {
  if (iv.value.mode === "range") return "range";
  return iv.value.days === 1 ? "daily" : "fixed";
});

function switchMode(target) {
  if (target === "daily") return emit("update:modelValue", "1");
  if (target === "fixed") {
    const days = iv.value.mode === "range" ? iv.value.min : Math.max(2, iv.value.days);
    return emit("update:modelValue", formatInterval({ mode: "every", days }));
  }
  const min = iv.value.mode === "range" ? iv.value.min : 7;
  const max = iv.value.mode === "range" ? iv.value.max : 12;
  return emit("update:modelValue", formatInterval({ mode: "range", min, max }));
}

function setDays(value) {
  const n = Math.max(1, parseInt(value, 10) || 1);
  emit("update:modelValue", formatInterval({ mode: "every", days: n }));
}

function setBound(which, value) {
  const n = Math.max(1, parseInt(value, 10) || 1);
  const next = { mode: "range", min: iv.value.min, max: iv.value.max };
  next[which] = n;
  emit("update:modelValue", formatInterval(next));
}

const summary = computed(() => {
  if (mode.value === "daily") return `每天${props.verb}一次`;
  if (mode.value === "fixed") return `每 ${iv.value.days} 天${props.verb}一次`;
  return `每隔 ${iv.value.min} ~ ${iv.value.max} 天${props.verb}一次（随机）`;
});
</script>

<template>
  <div>
    <div class="seg">
      <button type="button" class="seg-item" :class="{ on: mode === 'daily' }" @click="switchMode('daily')">
        每天
      </button>
      <button type="button" class="seg-item" :class="{ on: mode === 'fixed' }" @click="switchMode('fixed')">
        每隔几天
      </button>
      <button type="button" class="seg-item" :class="{ on: mode === 'range' }" @click="switchMode('range')">
        间隔随机
      </button>
    </div>

    <div v-if="mode === 'fixed'" class="num-unit" style="margin-top: 12px">
      <span class="num-unit-label">每隔</span>
      <input
        class="input"
        type="number"
        min="2"
        :value="iv.days"
        @input="setDays($event.target.value)"
      />
      <span class="num-unit-label">天</span>
    </div>

    <div v-else-if="mode === 'range'" class="num-unit" style="margin-top: 12px">
      <span class="num-unit-label">每隔</span>
      <input class="input" type="number" min="1" :value="iv.min" @input="setBound('min', $event.target.value)" />
      <span class="num-unit-label">到</span>
      <input class="input" type="number" min="1" :value="iv.max" @input="setBound('max', $event.target.value)" />
      <span class="num-unit-label">天</span>
    </div>

    <div class="hint" style="margin-top: 9px">{{ summary }}</div>
  </div>
</template>
