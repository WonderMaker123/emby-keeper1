<script setup>
/**
 * 全局吐司容器.
 *
 * 固定的右下角位置: 切换页面或滚动时都不会错过反馈, 点击可提前关闭.
 */
import { useToastStore } from "@/stores/toast";
import UiIcon from "@/components/ui/UiIcon.vue";

const toast = useToastStore();

const ICONS = { ok: "check", bad: "alert", info: "info" };
</script>

<template>
  <div class="toasts">
    <div
      v-for="item in toast.items"
      :key="item.id"
      class="toast"
      :class="`toast-${item.kind}`"
      role="status"
      @click="toast.dismiss(item.id)"
    >
      <UiIcon class="toast-ico" :name="ICONS[item.kind] || 'info'" :size="16" />
      <div class="toast-body">{{ item.message }}</div>
    </div>
  </div>
</template>
