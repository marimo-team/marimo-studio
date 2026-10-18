<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref } from "vue";

import { data as glossary } from "../glossary.data";

// `glossaryLinks` in .vitepress/glossary.ts wraps every Markdown link to a
// glossary term in this component and points the link's aria-describedby at
// `tip`, so the card is the link's accessible description.
const props = defineProps<{ term: string; tip: string }>();

const entry = computed(() => glossary[props.term]);
const root = ref<HTMLElement>();
const card = ref<HTMLElement>();
const open = ref(false);
const position = ref<{ left: number; top: number }>();
let timer: ReturnType<typeof setTimeout> | undefined;

const margin = 12;
const gap = 6;

// The card is fixed to the viewport so tables and other scrolling containers
// cannot clip it. It sits above the link's first line, or below the link when
// the navigation bar would cover it.
const place = (): void => {
  const link = root.value?.querySelector("a")?.getClientRects()[0];
  const size = card.value?.getBoundingClientRect();
  if (!link || !size) {
    return;
  }
  const nav =
    Number.parseFloat(
      getComputedStyle(document.documentElement).getPropertyValue("--vp-nav-height"),
    ) || 64;
  const above = link.top - gap - size.height;
  const left = Math.min(link.left, window.innerWidth - margin - size.width);
  position.value = {
    left: Math.max(margin, left),
    top: above < nav + margin ? link.bottom + gap : above,
  };
};

const show = async (): Promise<void> => {
  clearTimeout(timer);
  if (open.value || !entry.value) {
    return;
  }
  position.value = undefined;
  open.value = true;
  // Capture catches scrolling inside tables and other containers too.
  window.addEventListener("scroll", place, { passive: true, capture: true });
  window.addEventListener("resize", place, { passive: true });
  window.addEventListener("keydown", dismiss);
  await nextTick();
  place();
};

const hide = (): void => {
  clearTimeout(timer);
  open.value = false;
  window.removeEventListener("scroll", place, { capture: true });
  window.removeEventListener("resize", place);
  window.removeEventListener("keydown", dismiss);
};

function dismiss(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    hide();
  }
}

// Short delays let the pointer cross the gap between the link and the card,
// and keep the card closed while the pointer only passes over a link.
const schedule = (next: () => void, delay: number): void => {
  clearTimeout(timer);
  timer = setTimeout(next, delay);
};

onBeforeUnmount(hide);
</script>

<template>
  <span
    ref="root"
    class="glossary-term"
    @mouseenter="schedule(show, 200)"
    @mouseleave="schedule(hide, 150)"
    @focusin="show"
    @focusout="hide"
  >
    <slot />
    <span
      v-if="entry"
      v-show="open"
      :id="tip"
      ref="card"
      role="tooltip"
      class="glossary-card"
      :style="
        position
          ? { left: `${position.left}px`, top: `${position.top}px` }
          : { visibility: 'hidden' }
      "
    >
      <span class="glossary-card-title" v-html="entry.title" />
      <span class="glossary-card-definition" v-html="entry.definition" />
    </span>
  </span>
</template>

<style scoped>
.glossary-term :slotted(a) {
  text-decoration-style: dotted;
  text-underline-offset: 3px;
}

.glossary-card {
  position: fixed;
  z-index: 40;
  display: block;
  width: max-content;
  max-width: min(22rem, calc(100vw - 24px));
  padding: 10px 12px;
  border: 1px solid var(--studio-card-border);
  border-radius: var(--studio-radius-inner);
  background: var(--studio-card-bg);
  box-shadow: var(--studio-card-shadow);
  color: var(--vp-c-text-2);
  font-size: 13px;
  font-weight: 400;
  line-height: 1.55;
  text-align: start;
  white-space: normal;
}

.glossary-card-title {
  display: block;
  margin-bottom: 2px;
  color: var(--vp-c-text-1);
  font-weight: 600;
}

.glossary-card-definition {
  display: block;
}

.glossary-card :deep(code) {
  font-size: 12px;
}
</style>
