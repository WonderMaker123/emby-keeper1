<script setup>
/**
 * 密码/密钥输入框.
 *
 * 默认掩码显示, 右侧提供「显示/隐藏」切换. 保存配置时后端会按字段名识别
 * 敏感项并做掩码还原, 因此这里显示掩码串不会把密码写坏.
 */
import { computed, ref } from "vue";
import UiIcon from "@/components/ui/UiIcon.vue";

const props = defineProps({
  modelValue: { type: String, default: "" },
  placeholder: { type: String, default: "" },
  /** 输入框为空时的提示语, 例如「留空表示不修改」 */
  emptyHint: { type: String, default: "" },
});

const emit = defineEmits(["update:modelValue"]);

const revealed = ref(false);

const text = computed(() => props.modelValue ?? "");

/** 值形如 ****** 时说明是后端返回的掩码, 提示用户原样保留即可 */
const isMasked = computed(() => /^\*{4,}$/.test(text.value));

function onInput(e) {
  emit("update:modelValue", e.target.value);
}
</script>

<template>
  <div>
    <div class="input-join">
      <input
        class="input"
        :type="revealed ? 'text' : 'password'"
        :value="text"
        :placeholder="placeholder"
        autocomplete="new-password"
        spellcheck="false"
        @input="onInput"
      />
      <button
        type="button"
        class="join-btn"
        :title="revealed ? '隐藏' : '显示'"
        @click="revealed = !revealed"
      >
        <UiIcon :name="revealed ? 'eye-off' : 'eye'" :size="15" />
      </button>
    </div>
    <div v-if="isMasked" class="hint" style="margin-top: 5px">
      当前显示的是已保存的密码，保持不变即可；重新输入则覆盖
    </div>
    <div v-else-if="emptyHint" class="hint" style="margin-top: 5px">{{ emptyHint }}</div>
  </div>
</template>
