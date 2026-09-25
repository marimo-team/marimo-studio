<script setup lang="ts">
import { Icon } from "@iconify/vue/offline";
import { withBase } from "vitepress";
import { computed, ref, useId } from "vue";

import { documentationExampleFamilies } from "../../../examples.ts";
import { externalLinkIcon } from "./studio-icons.ts";

/** One framed document: a notebook export or a view entrypoint. */
interface Layer {
  label: string;
  /** Site-relative paths receive the deployment base. Absolute URLs load as given. */
  src: string;
}

const props = defineProps<{
  /** Resolve the notebook and views from the documentation example catalog. */
  family?: string;
  notebook?: Layer;
  views?: readonly Layer[];
}>();

const catalog = props.family
  ? documentationExampleFamilies.find(({ slug }) => slug === props.family)
  : undefined;
if (props.family && !catalog) {
  throw new Error(`Unknown documentation example family: ${props.family}`);
}
const notebook: Layer | undefined =
  props.notebook ??
  (catalog && {
    label: catalog.notebook.replace(/^.*\//, ""),
    src: `/examples/${catalog.slug}/notebook/index.html`,
  });
const views: readonly Layer[] =
  props.views ??
  catalog?.views.map(({ key, label }) => ({
    label,
    src: `/examples/${catalog.slug}/${key}/index.html`,
  })) ??
  [];
if (!notebook || views.length === 0) {
  throw new Error("StudioViewStack needs a family, or a notebook and at least one view.");
}

const href = (src: string): string => (src.startsWith("/") ? withBase(src) : src);
const id = useId();
const tabId = (index: number): string => `${id}-tab-${index}`;
const panelId = `${id}-panel`;

// Tab 0 is the notebook. Tabs 1..n are the views, in declaration order.
const tabs = [notebook, ...views];
const selectedIndex = ref(1);
const lastView = ref(1);
const notebookLoaded = ref(false);
const viewLoaded = ref(false);
const viewFrame = ref<HTMLIFrameElement>();
// Only a tab choice reloads the frame. Navigation inside the frame updates
// the labels without resetting the view's own URL state.
const viewSrc = ref(href(views[0].src));

const front = computed(() => (selectedIndex.value === 0 ? "notebook" : "view"));
const view = computed(() => views[lastView.value - 1] ?? views[0]);

const select = (index: number): void => {
  selectedIndex.value = index;
  if (index > 0 && index !== lastView.value) {
    lastView.value = index;
    viewLoaded.value = false;
    viewSrc.value = href(tabs[index].src);
  }
};

const selectFromKeyboard = (event: KeyboardEvent, index: number): void => {
  const count = tabs.length;
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
  document.getElementById(tabId(next))?.focus();
};

// Views link to their siblings. Follow a same-origin navigation inside the
// frame so the rail keeps naming the document on screen.
const markViewLoaded = (): void => {
  viewLoaded.value = true;
  let current: string | undefined;
  let pathname: string | undefined;
  try {
    ({ href: current, pathname } = viewFrame.value?.contentWindow?.location ?? {});
  } catch {
    // Cross-origin views keep the label of the tab that loaded them.
    return;
  }
  if (!current || !pathname) {
    return;
  }
  // Views add their own query and fragment state, so compare document paths.
  const index = views.findIndex(({ src }) => new URL(href(src), current).pathname === pathname);
  if (index >= 0 && index + 1 !== lastView.value) {
    lastView.value = index + 1;
    if (selectedIndex.value > 0) {
      selectedIndex.value = index + 1;
    }
  }
};
</script>

<template>
  <figure class="studio-view-stack" :aria-label="`${notebook.label} and its views`">
    <nav role="tablist" aria-label="Choose the document in front">
      <template v-for="(tab, index) in tabs" :key="tab.src">
        <span v-if="index === 1" class="studio-view-stack__rule" aria-hidden="true" />
        <button
          :id="tabId(index)"
          type="button"
          role="tab"
          :aria-controls="panelId"
          :aria-selected="index === selectedIndex"
          :tabindex="index === selectedIndex ? 0 : -1"
          @click="select(index)"
          @keydown="selectFromKeyboard($event, index)"
        >
          {{ index === 0 ? "Notebook" : tab.label }}
        </button>
      </template>
    </nav>

    <div
      :id="panelId"
      class="studio-view-stack__stage"
      role="tabpanel"
      :aria-labelledby="tabId(selectedIndex)"
      :data-front="front"
    >
      <section class="studio-view-stack__layer is-notebook" :aria-label="notebook.label">
        <header>
          <span class="studio-view-stack__file">{{ notebook.label }}</span>
          <a
            :href="href(notebook.src)"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="`Open ${notebook.label} in a new tab`"
            title="Open in a new tab"
          >
            <Icon :icon="externalLinkIcon" :aria-hidden="true" />
          </a>
        </header>
        <div class="studio-view-stack__body" :inert="front !== 'notebook'">
          <div v-if="!notebookLoaded" class="studio-view-stack__loading">Loading…</div>
          <iframe
            :src="href(notebook.src)"
            :title="notebook.label"
            loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            @load="notebookLoaded = true"
          />
        </div>
        <button
          v-if="front !== 'notebook'"
          class="studio-view-stack__raise"
          type="button"
          tabindex="-1"
          :aria-label="`Bring ${notebook.label} to the front`"
          @click="select(0)"
        />
      </section>

      <section class="studio-view-stack__layer is-view" :aria-label="view.label">
        <header>
          <span>{{ view.label }}</span>
          <a
            :href="href(view.src)"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="`Open ${view.label} in a new tab`"
            title="Open in a new tab"
          >
            <Icon :icon="externalLinkIcon" :aria-hidden="true" />
          </a>
        </header>
        <div class="studio-view-stack__body" :inert="front !== 'view'">
          <div v-if="!viewLoaded" class="studio-view-stack__loading">Loading…</div>
          <iframe
            ref="viewFrame"
            :src="viewSrc"
            :title="view.label"
            allow="clipboard-write; fullscreen"
            allowfullscreen
            loading="lazy"
            referrerpolicy="strict-origin-when-cross-origin"
            @load="markViewLoaded"
          />
        </div>
        <button
          v-if="front !== 'view'"
          class="studio-view-stack__raise"
          type="button"
          tabindex="-1"
          :aria-label="`Bring ${view.label} to the front`"
          @click="select(lastView)"
        />
      </section>
    </div>
  </figure>
</template>

<style scoped>
.studio-view-stack {
  --stack-ease: cubic-bezier(0.2, 0.7, 0.2, 1);
  --stack-shadow-back: 0 1px 2px rgb(20 30 25 / 5%), 0 8px 24px -12px rgb(20 30 25 / 18%);
  --stack-shadow-front: 0 1px 2px rgb(20 30 25 / 6%), 0 24px 48px -16px rgb(20 30 25 / 26%);
  margin: 2.5rem 0 3rem;
  container-type: inline-size;
}

:global(.dark) .studio-view-stack {
  --stack-shadow-back: 0 1px 2px rgb(0 0 0 / 30%), 0 8px 24px -12px rgb(0 0 0 / 50%);
  --stack-shadow-front: 0 1px 2px rgb(0 0 0 / 35%), 0 24px 48px -16px rgb(0 0 0 / 65%);
}

nav {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  padding-bottom: 0.75rem;
  overflow-x: auto;
  scrollbar-width: none;
}

nav::-webkit-scrollbar {
  display: none;
}

nav button {
  flex: 0 0 auto;
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
  text-decoration: underline 1px transparent;
  text-underline-offset: 7px;
  touch-action: manipulation;
}

nav button:hover,
nav button[aria-selected="true"] {
  color: var(--vp-c-text-1);
}

nav button[aria-selected="true"] {
  text-decoration-color: currentColor;
}

.studio-view-stack__rule {
  flex: 0 0 auto;
  width: 1px;
  height: 14px;
  margin-inline: -0.25rem;
  background: var(--vp-c-divider);
}

.studio-view-stack__stage {
  position: relative;
  height: clamp(30rem, 56cqi, 46rem);
}

.studio-view-stack__layer {
  position: absolute;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--vp-c-divider);
  border-radius: 6px;
  background: var(--vp-c-bg);
  box-shadow: var(--stack-shadow-back);
  transition:
    transform 0.5s var(--stack-ease),
    box-shadow 0.5s var(--stack-ease),
    filter 0.5s var(--stack-ease);
}

/* The notebook sits up and to the left, the view down and to the right, so
   each layer stays visible while the other is in front. */
.studio-view-stack__layer.is-notebook {
  top: 0;
  left: 0;
  width: 58%;
  height: 86%;
  transform-origin: 100% 50%;
}

.studio-view-stack__layer.is-view {
  right: 0;
  bottom: 0;
  width: 72%;
  height: 90%;
  transform-origin: 0% 50%;
}

.studio-view-stack__stage[data-front="view"] .is-notebook,
.studio-view-stack__stage[data-front="notebook"] .is-view {
  z-index: 0;
  filter: saturate(0.85) brightness(0.985);
}

.studio-view-stack__stage[data-front="view"] .is-notebook {
  transform: translate(-0.5%, 0.5%) rotate(-1.75deg) scale(0.97);
}

.studio-view-stack__stage[data-front="notebook"] .is-view {
  transform: translate(0.5%, -0.5%) rotate(1.75deg) scale(0.97);
}

/* A back layer straightens slightly under the pointer to show it can come forward. */
.studio-view-stack__stage[data-front="view"] .is-notebook:hover {
  transform: translate(-0.5%, 0.25%) rotate(-1.25deg) scale(0.975);
}

.studio-view-stack__stage[data-front="notebook"] .is-view:hover {
  transform: translate(0.5%, -0.25%) rotate(1.25deg) scale(0.975);
}

.studio-view-stack__stage[data-front="view"] .is-view,
.studio-view-stack__stage[data-front="notebook"] .is-notebook {
  z-index: 1;
  box-shadow: var(--stack-shadow-front);
}

.studio-view-stack__layer header {
  position: relative;
  z-index: 3;
  display: flex;
  flex: 0 0 auto;
  gap: 1rem;
  align-items: center;
  justify-content: space-between;
  height: 2.25rem;
  padding: 0 0.5rem 0 0.875rem;
  border-bottom: 1px solid var(--vp-c-divider);
  color: var(--vp-c-text-2);
  font-size: 12px;
  font-weight: 500;
  line-height: 18px;
}

.studio-view-stack__file {
  font-family: var(--vp-font-family-mono);
  font-size: 12px;
}

.studio-view-stack__layer header a {
  display: inline-grid;
  place-items: center;
  width: 1.75rem;
  height: 1.75rem;
  color: var(--vp-c-text-2);
}

.studio-view-stack__layer header a:hover {
  color: var(--vp-c-text-1);
}

.studio-view-stack__layer header svg {
  width: 13px;
  height: 13px;
}

.studio-view-stack__body {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
}

.studio-view-stack__body iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}

.studio-view-stack__loading {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-content: center;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-2);
  font-size: 13px;
}

/* Covers the back layer so a click brings it forward instead of reaching
   the inert frame underneath. */
.studio-view-stack__raise {
  position: absolute;
  inset: 0;
  z-index: 2;
  border: 0;
  background: transparent;
  cursor: pointer;
}

nav button:focus-visible,
.studio-view-stack a:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 3px;
  border-radius: 2px;
}

/* Narrow containers show one layer at a time in the same frame. */
@container (max-width: 36rem) {
  .studio-view-stack__stage {
    height: min(70svh, 36rem);
  }

  /* A single layer lies flat in the page. */
  .studio-view-stack__layer.is-notebook,
  .studio-view-stack__layer.is-view,
  .studio-view-stack__stage[data-front] .studio-view-stack__layer {
    inset: 0;
    width: auto;
    height: auto;
    box-shadow: none;
    filter: none;
    transform: none;
    transition: none;
  }

  .studio-view-stack__stage[data-front="view"] .is-notebook,
  .studio-view-stack__stage[data-front="notebook"] .is-view {
    visibility: hidden;
  }
}

@media (prefers-reduced-motion: reduce) {
  .studio-view-stack__layer {
    transition: none;
  }
}
</style>
