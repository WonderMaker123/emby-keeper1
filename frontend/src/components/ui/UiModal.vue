<script setup>
/**
 * 通用弹窗.
 *
 * Teleport 到 body: 避免被父级容器的 overflow 裁剪; 打开时锁定页面滚动.
 * 支持 Esc 与点击遮罩关闭, 但 busy 状态下禁止关闭, 防止提交中途被误触中断.
 */
import { onBeforeUnmount, watch } from "vue";

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: "" },
  desc: { type: String, default: "" },
  wide: { type: Boolean, default: false },
  busy: { type: Boolean, default: false },
});

const emit = defineEmits(["update:modelValue"]);

function close() {
  if (props.busy) return;
  emit("update:modelValue", false);
}

function onKey(e) {
  if (e.key === "Escape") close();
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      document.addEventListener("keydown", onKey);
      document.body.style.overflow = "hidden";
    } else {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    }
  }
);

onBeforeUnmount(() => {
  document.removeEventListener("keydown", onKey);
  document.body.style.overflow = "";
});
</script>

<template>
  <Teleport to="body">
    <div v-if="modelValue" class="mask" @click.self="close">
      <div class="dlg" :class="{ wide }" role="dialog" aria-modal="true">
        <header class="dlg-head">
          <div>
            <h3 class="dlg-t">{{ title }}</h3>
            <p v-if="desc" class="dlg-d">{{ desc }}</p>
          </div>
          <button type="button" class="dlg-x" aria-label="关闭" @click="close">×</button>
        </header>

        <div class="dlg-body">
          <slot />
        </div>

        <footer v-if="$slots.footer" class="dlg-foot">
          <slot name="footer" />
        </footer>
      </div>
    </div>
  </Teleport>
</template>
