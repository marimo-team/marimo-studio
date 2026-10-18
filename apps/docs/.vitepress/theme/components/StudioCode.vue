<script setup lang="ts">
import { computed } from "vue";

import { type CodeLanguage, codeLines } from "./studio-code.ts";

const props = withDefaults(
  defineProps<{
    code: string;
    language: CodeLanguage;
    /** Zero-based lines that the surrounding figure points at. */
    active?: readonly number[];
    /** Show a gutter with line numbers, as marimo's cell editor does. */
    lineNumbers?: boolean;
  }>(),
  { active: () => [], lineNumbers: false },
);

const lines = computed(() => codeLines(props.code, props.language));
</script>

<template>
  <!-- Lines are blocks, so the markup between spans must add no whitespace
       inside the <pre>. -->
  <pre
    class="studio-code"
    :data-language="language"
    :data-numbered="lineNumbers || undefined"
    tabindex="0"
  ><code><span v-for="(line, index) in lines" :key="index" class="studio-code__line" :data-active="active.includes(index) || undefined"><span v-if="lineNumbers" class="studio-code__gutter" aria-hidden="true">{{ index + 1 }}</span><span class="studio-code__text"><span v-for="(token, position) in line" :key="position" :class="`studio-code__${token.kind}`">{{ token.text }}</span></span></span></code></pre>
</template>

<style scoped>
.studio-code {
  margin: 0;
  padding: 8px 0;
  overflow-x: auto;
  background: transparent;
  color: var(--studio-code-plain);
  font-family: var(--vp-font-family-mono);
  font-size: 12px;
  line-height: 1.6;
  tab-size: 4;
}

.studio-code code {
  display: block;
  min-width: max-content;
  padding: 0;
  background: transparent;
  color: inherit;
  font-size: inherit;
}

.studio-code__line {
  display: block;
  min-height: 1.6em;
  padding-inline: 12px 16px;
  transition:
    background-color 0.2s ease,
    box-shadow 0.2s ease;
}

/* Numbered lines draw marimo's gutter: the numbers, then a rule that runs
   unbroken from line to line. */
.studio-code[data-numbered] .studio-code__line {
  display: grid;
  grid-template-columns: 28px max-content;
  padding-inline: 0 16px;
}

.studio-code__gutter {
  padding-right: 8px;
  border-right: 1px solid var(--studio-chrome-rule);
  color: var(--vp-c-text-3);
  text-align: right;
  user-select: none;
}

.studio-code[data-numbered] .studio-code__text {
  padding-left: 12px;
}

.studio-code__line[data-active] {
  background: var(--studio-link-soft);
  box-shadow: inset 2px 0 var(--studio-link);
}

.studio-code__keyword {
  color: var(--studio-code-keyword);
}

.studio-code__string {
  color: var(--studio-code-string);
}

.studio-code__number {
  color: var(--studio-code-number);
}

.studio-code__function,
.studio-code__decorator {
  color: var(--studio-code-function);
}

.studio-code__comment {
  color: var(--studio-code-comment);
}

.studio-code__tag {
  color: var(--studio-code-tag);
}

.studio-code__attribute {
  color: var(--studio-code-attribute);
}
</style>
