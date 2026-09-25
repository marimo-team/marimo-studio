<script setup lang="ts">
import { Icon } from "@iconify/vue/offline";
import { withBase } from "vitepress";
import { computed, onMounted, ref } from "vue";

import {
  documentationExampleFamilies,
  documentationExampleSource,
  documentationTechnologies,
} from "../../../examples.ts";
import { externalLinkIcon } from "./studio-icons.ts";

const props = defineProps<{
  family: string;
}>();

const example = documentationExampleFamilies.find(({ slug }) => slug === props.family);
if (!example) {
  throw new Error(`Unknown documentation example family: ${props.family}`);
}

const notebookTab = {
  key: "notebook",
  label: "Notebook",
  technologies: [documentationTechnologies.marimo],
} as const;

const selectedKey = ref(example.views[0].key);
const loaded = ref(false);
const frame = ref<HTMLIFrameElement>();
// Only a tab choice changes the frame source. Navigation inside the frame
// updates the tab without reloading the document or resetting its URL state.
const frameSrc = ref<string>();
const tabs = [notebookTab, ...example.views];

const selected = computed(() =>
  selectedKey.value === notebookTab.key
    ? notebookTab
    : (example.views.find(({ key }) => key === selectedKey.value) ?? example.views[0]),
);
const documentHref = (key: string): string =>
  withBase(`/examples/${example.slug}/${key}/index.html`);
const href = computed(() => documentHref(selected.value.key));
// Studio stores view projects under a directory named after the notebook file.
const viewProjects = example.notebook.replace(/^.*\//, "").replace(/\.py$/, "");
const sourceHref = computed(() => {
  const { repository, revision, viewProjectsRoot } = documentationExampleSource;
  return selected.value.key === notebookTab.key
    ? `${repository}/blob/${revision}/${example.notebook}`
    : `${repository}/tree/${revision}/${viewProjectsRoot}/${viewProjects}/${selected.value.key}`;
});
const tabId = (key: string): string => `studio-example-${example.slug}-${key}-tab`;
const panelId = `studio-example-${example.slug}-panel`;

const select = (key: string): void => {
  if (selectedKey.value === key) {
    return;
  }
  selectedKey.value = key;
  loaded.value = false;
  frameSrc.value = documentHref(key);
};

const selectFromKeyboard = (event: KeyboardEvent, key: string): void => {
  const currentIndex = tabs.findIndex((tab) => tab.key === key);
  let nextIndex: number | undefined;
  if (event.key === "ArrowLeft") {
    nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
  } else if (event.key === "ArrowRight") {
    nextIndex = (currentIndex + 1) % tabs.length;
  } else if (event.key === "Home") {
    nextIndex = 0;
  } else if (event.key === "End") {
    nextIndex = tabs.length - 1;
  }
  if (nextIndex === undefined) {
    return;
  }
  event.preventDefault();
  const next = tabs[nextIndex];
  select(next.key);
  requestAnimationFrame(() => document.getElementById(tabId(next.key))?.focus());
};

// Gallery cards link to the view they were showing through `?view=KEY`. The
// frame loads after mount so a requested view is the first document fetched.
onMounted(() => {
  const requested = new URLSearchParams(window.location.search).get("view");
  if (requested && example.views.some(({ key }) => key === requested)) {
    selectedKey.value = requested;
  }
  frameSrc.value = documentHref(selectedKey.value);
});

const markLoaded = (): void => {
  loaded.value = true;
  let pathname: string | undefined;
  try {
    pathname = frame.value?.contentWindow?.location.pathname;
  } catch {
    return;
  }
  if (!pathname) {
    return;
  }
  const active = tabs.find(({ key }) => pathname.endsWith(`/${example.slug}/${key}/index.html`));
  if (active) {
    selectedKey.value = active.key;
  }
};
</script>

<template>
  <figure class="studio-example" :aria-label="example.title">
    <div class="studio-example__rail">
      <nav aria-label="Switch between the shared notebook and its views" role="tablist">
        <template v-for="(tab, index) in tabs" :key="tab.key">
          <span v-if="index === 1" class="studio-example__rule" aria-hidden="true" />
          <button
            :id="tabId(tab.key)"
            type="button"
            role="tab"
            :aria-controls="panelId"
            :aria-selected="tab.key === selected.key"
            :tabindex="tab.key === selected.key ? 0 : -1"
            @click="select(tab.key)"
            @keydown="selectFromKeyboard($event, tab.key)"
          >
            {{ tab.label }}
          </button>
        </template>
      </nav>
      <a
        class="studio-example__open"
        :href="href"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="`Open ${selected.label} in a new tab`"
        title="Open in a new tab"
      >
        <Icon :icon="externalLinkIcon" :aria-hidden="true" />
      </a>
    </div>

    <div
      :id="panelId"
      class="studio-example__viewport"
      :aria-busy="!loaded"
      :aria-labelledby="tabId(selected.key)"
      role="tabpanel"
    >
      <div v-if="!loaded" class="studio-example__loading" role="status">Loading…</div>
      <iframe
        v-if="frameSrc"
        ref="frame"
        :src="frameSrc"
        :title="`${example.title}: ${selected.label}`"
        allow="clipboard-write; fullscreen"
        allowfullscreen
        loading="eager"
        referrerpolicy="strict-origin-when-cross-origin"
        @load="markLoaded"
      />
    </div>

    <figcaption>
      <span class="studio-example__technologies" role="group" aria-label="Technologies used">
        <template v-for="(technology, index) in selected.technologies" :key="technology.name">
          <span v-if="index > 0" aria-hidden="true"> · </span>
          <a
            :href="technology.projectUrl"
            target="_blank"
            rel="noopener noreferrer"
            :title="technology.description"
          >
            {{ technology.name }}
          </a>
        </template>
      </span>
      <a
        :href="sourceHref"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="`${selected.label} source on GitHub`"
      >
        Source
      </a>
    </figcaption>
  </figure>
</template>

<style scoped>
.studio-example {
  display: grid;
  height: calc(100vh - var(--vp-nav-height) - 2rem);
  height: calc(100dvh - var(--vp-nav-height) - 2rem);
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto minmax(0, 1fr) auto;
  margin: 2.5rem 0 3rem;
  scroll-margin-top: calc(var(--vp-nav-height) + 1rem);
}

.studio-example__rail {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  justify-content: space-between;
  padding-bottom: 0.75rem;
}

.studio-example__rail nav {
  display: flex;
  gap: 1.5rem;
  align-items: center;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: none;
}

.studio-example__rail nav::-webkit-scrollbar {
  display: none;
}

.studio-example__rail button {
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

.studio-example__rail button:hover {
  color: var(--vp-c-text-1);
}

.studio-example__rail button[aria-selected="true"] {
  color: var(--vp-c-text-1);
  text-decoration-color: currentColor;
}

.studio-example__rule {
  flex: 0 0 auto;
  width: 1px;
  height: 14px;
  margin-inline: -0.25rem;
  background: var(--vp-c-divider);
}

.studio-example__open {
  display: inline-grid;
  flex: 0 0 auto;
  place-items: center;
  width: 2rem;
  height: 2rem;
  margin-right: -0.5rem;
  color: var(--vp-c-text-2);
  touch-action: manipulation;
}

.studio-example__open:hover {
  color: var(--vp-c-text-1);
}

.studio-example__open svg {
  width: 14px;
  height: 14px;
}

.studio-example__rail button:focus-visible,
.studio-example a:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 3px;
  border-radius: 2px;
}

.studio-example__viewport {
  position: relative;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--vp-c-divider);
  border-radius: 4px;
  background: var(--vp-c-bg);
}

.studio-example__viewport iframe {
  display: block;
  width: 100%;
  height: 100%;
  border: 0;
  background: #fff;
}

.studio-example__loading {
  position: absolute;
  inset: 0;
  z-index: 1;
  display: grid;
  place-content: center;
  background: var(--vp-c-bg);
  color: var(--vp-c-text-2);
  font-size: 13px;
}

figcaption {
  display: flex;
  gap: 1.5rem;
  align-items: baseline;
  justify-content: space-between;
  padding-top: 0.75rem;
  color: var(--vp-c-text-2);
  font-size: 12px;
  line-height: 18px;
}

.studio-example__technologies {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

figcaption a {
  color: inherit;
  text-decoration: none;
}

figcaption a:hover {
  color: var(--vp-c-text-1);
}

@media (max-width: 720px) {
  .studio-example {
    height: calc(100svh - var(--vp-nav-height) - 1.5rem);
    height: calc(100dvh - var(--vp-nav-height) - 1.5rem);
    margin-block: 2rem 2.5rem;
  }

  .studio-example__rail {
    gap: 0.5rem;
  }

  /* Labels can outgrow a phone width. The faded edge shows that the tabs scroll. */
  .studio-example__rail nav {
    gap: 1rem;
    padding-right: 1.5rem;
    mask-image: linear-gradient(to right, #000 calc(100% - 1.5rem), transparent);
  }

  .studio-example__rail button {
    min-height: 2.75rem;
  }

  .studio-example__open {
    width: 2.75rem;
    height: 2.75rem;
    margin-right: -0.75rem;
  }
}
</style>
