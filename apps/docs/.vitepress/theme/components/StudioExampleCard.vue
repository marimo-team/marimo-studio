<script setup lang="ts">
import { withBase } from "vitepress";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";

import { documentationExampleFamilies } from "../../../examples.ts";

const props = defineProps<{
  family: string;
}>();

const order = documentationExampleFamilies.findIndex(({ slug }) => slug === props.family);
const example = documentationExampleFamilies[order];
if (!example) {
  throw new Error(`Unknown documentation example family: ${props.family}`);
}

const cycleSeconds = 4.5;
const selectedIndex = ref(0);
const autoplay = ref(true);
const firstCycle = ref(true);
const visible = ref(false);
const hovered = ref(false);
const reducedMotion = ref(true);
const card = ref<HTMLElement>();
let observer: IntersectionObserver | undefined;
let motionQuery: MediaQueryList | undefined;

const selected = computed(() => example.views[selectedIndex.value] ?? example.views[0]);
const cycling = computed(() => autoplay.value && !reducedMotion.value);
const playing = computed(() => cycling.value && visible.value && !hovered.value);
const pageHref = withBase(`/examples/${example.slug}`);
const viewHref = computed(() => `${pageHref}?view=${selected.value.key}`);
const thumbnail = (key: string): string => withBase(`/thumbnails/card/${example.slug}/${key}.webp`);
const tabId = (key: string): string => `studio-example-card-${example.slug}-${key}-tab`;
const panelId = `studio-example-card-${example.slug}-panel`;
// Start each card part-way through its first cycle so the gallery does not
// switch every card at the same moment.
const progressStyle = computed(() => ({
  animationDelay: firstCycle.value
    ? `${(-order * cycleSeconds) / documentationExampleFamilies.length}s`
    : "0s",
  animationDuration: `${cycleSeconds}s`,
  animationPlayState: playing.value ? "running" : "paused",
}));

const advance = (): void => {
  firstCycle.value = false;
  selectedIndex.value = (selectedIndex.value + 1) % example.views.length;
};

const select = (index: number): void => {
  autoplay.value = false;
  selectedIndex.value = index;
};

const selectFromKeyboard = (event: KeyboardEvent, index: number): void => {
  const count = example.views.length;
  const next = {
    ArrowLeft: (index - 1 + count) % count,
    ArrowRight: (index + 1) % count,
    End: count - 1,
    Home: 0,
  }[event.key];
  if (next === undefined) {
    return;
  }
  event.preventDefault();
  select(next);
  document.getElementById(tabId(example.views[next].key))?.focus();
};

const updateMotion = (): void => {
  reducedMotion.value = motionQuery?.matches ?? true;
};

onMounted(() => {
  motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
  updateMotion();
  motionQuery.addEventListener("change", updateMotion);
  observer = new IntersectionObserver(
    ([entry]) => {
      visible.value = entry?.isIntersecting ?? false;
    },
    { threshold: 0.5 },
  );
  if (card.value) {
    observer.observe(card.value);
  }
});

onBeforeUnmount(() => {
  motionQuery?.removeEventListener("change", updateMotion);
  observer?.disconnect();
});
</script>

<template>
  <article
    ref="card"
    class="studio-example-card"
    @pointerenter="hovered = true"
    @pointerleave="hovered = false"
    @focusin="hovered = true"
    @focusout="hovered = false"
  >
    <header>
      <h2>
        <a :href="pageHref">{{ example.title }}</a>
      </h2>
      <nav :aria-label="`${example.title} views`" role="tablist">
        <button
          v-for="(view, index) in example.views"
          :id="tabId(view.key)"
          :key="view.key"
          type="button"
          role="tab"
          :aria-controls="panelId"
          :aria-selected="index === selectedIndex"
          :tabindex="index === selectedIndex ? 0 : -1"
          @click="select(index)"
          @keydown="selectFromKeyboard($event, index)"
        >
          {{ view.label }}
          <span
            v-if="index === selectedIndex"
            :class="['studio-example-card__progress', { 'is-cycling': cycling }]"
            :style="cycling ? progressStyle : undefined"
            aria-hidden="true"
            @animationend="advance"
          />
        </button>
      </nav>
    </header>

    <a
      :id="panelId"
      class="studio-example-card__frame"
      :href="viewHref"
      role="tabpanel"
      :aria-labelledby="tabId(selected.key)"
    >
      <img
        v-for="(view, index) in example.views"
        :key="view.key"
        :src="thumbnail(view.key)"
        :alt="index === selectedIndex ? `${example.title}: ${view.label}` : ''"
        :aria-hidden="index !== selectedIndex"
        :class="{ 'is-selected': index === selectedIndex }"
        decoding="async"
        loading="lazy"
        width="1440"
        height="900"
      />
    </a>

    <footer>
      <p><slot /></p>
      <small aria-label="Technologies used">
        {{ selected.technologies.map(({ name }) => name).join(" · ") }}
      </small>
    </footer>
  </article>
</template>

<style scoped>
.studio-example-card {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

header {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 1.5rem;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: 0.75rem;
}

.vp-doc h2 {
  margin: 0;
  padding: 0;
  border: 0;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
  line-height: 24px;
}

h2 a {
  color: var(--vp-c-text-1);
  text-decoration: none;
}

h2 a:hover {
  color: var(--vp-c-brand-1);
}

nav {
  display: flex;
  gap: 1.25rem;
  align-items: baseline;
}

button {
  position: relative;
  padding: 0.25rem 0;
  border: 0;
  background: transparent;
  color: var(--vp-c-text-2);
  cursor: pointer;
  font: inherit;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
  white-space: nowrap;
  touch-action: manipulation;
}

/* Extends the touch target without moving the underline away from the label. */
button::after {
  position: absolute;
  inset: -0.75rem -0.5rem;
  content: "";
}

button:hover,
button[aria-selected="true"] {
  color: var(--vp-c-text-1);
}

button[aria-selected="true"]::before,
.studio-example-card__progress {
  position: absolute;
  right: 0;
  bottom: -2px;
  left: 0;
  height: 1px;
}

button[aria-selected="true"]::before {
  background: var(--vp-c-divider);
  content: "";
}

.studio-example-card__progress {
  background: currentColor;
  transform-origin: left;
}

.studio-example-card__progress.is-cycling {
  animation-name: studio-example-card-progress;
  animation-timing-function: linear;
  animation-fill-mode: both;
}

@keyframes studio-example-card-progress {
  from {
    transform: scaleX(0);
  }

  to {
    transform: scaleX(1);
  }
}

.studio-example-card__frame {
  position: relative;
  display: block;
  overflow: hidden;
  aspect-ratio: 16 / 10;
  border: 1px solid var(--vp-c-divider);
  border-radius: 4px;
  background: var(--vp-c-bg-soft);
  transition: border-color 0.2s ease;
}

.studio-example-card__frame:hover {
  border-color: var(--vp-c-border);
}

.studio-example-card__frame img {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  margin: 0;
  object-fit: cover;
  object-position: top center;
  opacity: 0;
  /* The outgoing image stays opaque beneath the incoming one until the fade ends. */
  transition: opacity 0s 0.5s;
}

.studio-example-card__frame img.is-selected {
  z-index: 1;
  opacity: 1;
  transition: opacity 0.5s ease;
}

footer {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding-top: 0.75rem;
}

.vp-doc footer p {
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 14px;
  line-height: 22px;
}

small {
  color: var(--vp-c-text-3);
  font-size: 12px;
  line-height: 18px;
}

button:focus-visible,
a:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 3px;
  border-radius: 2px;
}

@media (prefers-reduced-motion: reduce) {
  .studio-example-card__frame img,
  .studio-example-card__frame img.is-selected {
    transition: none;
  }
}
</style>
