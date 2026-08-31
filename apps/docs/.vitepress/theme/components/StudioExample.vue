<script setup lang="ts">
import { Icon, type IconifyIcon } from "@iconify/vue/offline";
import { withBase } from "vitepress";
import { computed, ref } from "vue";

import {
  documentationExampleFamilies,
  documentationExampleSource,
  documentationTechnologies,
  type DocumentationExampleKind,
} from "../../../examples.ts";
import {
  appIcon,
  externalLinkIcon,
  githubIcon,
  notebookIcon,
  reportIcon,
  slidesIcon,
} from "./studio-icons.ts";

const props = defineProps<{
  family: string;
}>();

const example = documentationExampleFamilies.find(({ slug }) => slug === props.family);
if (!example) {
  throw new Error(`Unknown documentation example family: ${props.family}`);
}

const notebookTab = {
  key: "notebook",
  kind: "notebook",
  label: "Notebook",
  technologies: [documentationTechnologies.marimo],
} as const;

const viewKindIcons = {
  app: appIcon,
  report: reportIcon,
  slides: slidesIcon,
} satisfies Record<DocumentationExampleKind, IconifyIcon>;

const selectedKey = ref(example.views[0].key);
const loaded = ref(false);
const frameKey = ref(0);
const frame = ref<HTMLIFrameElement>();

const selected = computed(() =>
  selectedKey.value === notebookTab.key
    ? notebookTab
    : (example.views.find(({ key }) => key === selectedKey.value) ?? example.views[0]),
);
const viewHref = (key: string): string => withBase(`/examples/${example.slug}/${key}/index.html`);
const href = computed(() => viewHref(selected.value.key));
const notebookName = computed(() => example.notebook.split("/").at(-1));
const notebookSourceHref = computed(
  () =>
    `${documentationExampleSource.repository}/blob/${documentationExampleSource.revision}/${example.notebook}`,
);
const viewSourceHref = (key: string): string =>
  `${documentationExampleSource.repository}/tree/${documentationExampleSource.revision}/${documentationExampleSource.viewProjectsRoot}/${example.slug}/${key}`;

const select = (key: string): void => {
  if (selectedKey.value === key) {
    return;
  }
  selectedKey.value = key;
  loaded.value = false;
  frameKey.value += 1;
};

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
  const active = [notebookTab, ...example.views].find(({ key }) =>
    pathname.endsWith(`/${example.slug}/${key}/index.html`),
  );
  if (active) {
    selectedKey.value = active.key;
  }
};
</script>

<template>
  <figure class="studio-example">
    <header class="studio-example__header">
      <div class="studio-example__heading">
        <h3>{{ example.title }}</h3>
      </div>
      <a
        :href="href"
        target="_blank"
        rel="noopener noreferrer"
        :aria-label="`Open ${selected.label.toLowerCase()} full page`"
        title="Open full page"
      >
        <span class="studio-example__open-label">Open full page</span>
        <Icon :icon="externalLinkIcon" class="studio-example__icon" :aria-hidden="true" />
      </a>
      <p class="studio-example__summary">{{ example.summary }}</p>
    </header>

    <div class="studio-example__switcher">
      <span class="studio-example__current" aria-label="Technologies used">
        <template v-for="(technology, index) in selected.technologies" :key="technology.name">
          <span v-if="index > 0" class="studio-example__technology-separator" aria-hidden="true">
            ·
          </span>
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
      <nav aria-label="Switch between the shared notebook and its views">
        <button
          type="button"
          class="studio-example__source-tab"
          :aria-pressed="selected.key === notebookTab.key"
          @click="select(notebookTab.key)"
        >
          <Icon :icon="notebookIcon" class="studio-example__icon" :aria-hidden="true" />
          <span>{{ notebookTab.label }}</span>
        </button>
        <span class="studio-example__tab-flow" aria-hidden="true">→</span>
        <button
          v-for="view in example.views"
          :key="view.key"
          type="button"
          :aria-pressed="view.key === selected.key"
          @click="select(view.key)"
        >
          <Icon :icon="viewKindIcons[view.kind]" class="studio-example__icon" :aria-hidden="true" />
          <span>{{ view.label }}</span>
        </button>
      </nav>
    </div>

    <div class="studio-example__viewport" :data-kind="selected.kind" :aria-busy="!loaded">
      <div v-if="!loaded" class="studio-example__loading" role="status">
        Starting {{ selected.label.toLowerCase() }}…
      </div>
      <iframe
        :key="frameKey"
        ref="frame"
        :src="href"
        :title="`${example.title}: ${selected.label}`"
        allow="clipboard-write; fullscreen"
        allowfullscreen
        loading="eager"
        referrerpolicy="strict-origin-when-cross-origin"
        @load="markLoaded"
      />
    </div>

    <figcaption>
      <span class="studio-example__source-links">
        <span class="studio-example__source-prefix">
          <Icon :icon="githubIcon" class="studio-example__icon" :aria-hidden="true" />
          <span class="studio-example__source-label">Source</span>
        </span>
        <span class="studio-example__source-divider" aria-hidden="true" />
        <a :href="notebookSourceHref" target="_blank" rel="noopener noreferrer">
          {{ notebookName }}
        </a>
        <span
          class="studio-example__source-divider studio-example__view-divider"
          aria-hidden="true"
        />
        <span class="studio-example__view-sources">
          <template v-for="(view, index) in example.views" :key="view.key">
            <span v-if="index > 0" class="studio-example__source-separator" aria-hidden="true">
              ·
            </span>
            <a :href="viewSourceHref(view.key)" target="_blank" rel="noopener noreferrer">
              {{ view.label }}
            </a>
          </template>
        </span>
      </span>
    </figcaption>
  </figure>
</template>

<style scoped>
.studio-example {
  --studio-example-accent: var(--vp-c-brand-1);
  display: grid;
  height: calc(100vh - var(--vp-nav-height));
  height: calc(100dvh - var(--vp-nav-height));
  grid-template-rows: auto auto minmax(0, 1fr) auto;
  margin: 2rem 0 3rem;
  scroll-margin-top: var(--vp-nav-height);
  overflow: hidden;
  border: 1px solid var(--vp-c-divider);
  border-top: 3px solid var(--studio-example-accent);
  border-radius: 10px;
  background: var(--vp-c-bg-elv);
  box-shadow: none;
}

.studio-example__header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  column-gap: 2rem;
  row-gap: 0.45rem;
  align-items: start;
  padding: 1.1rem 1.25rem 1rem;
}

.studio-example__heading {
  min-width: 0;
}

.studio-example__current,
figcaption {
  font-family: var(--vp-font-family-mono);
}

.studio-example h3 {
  margin: 0;
  border: 0;
  font-size: 1.3rem;
  letter-spacing: -0.02em;
}

.studio-example__summary {
  grid-column: 1 / -1;
  max-width: 44rem;
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 0.9rem;
  line-height: 1.55;
}

.studio-example__header > a {
  display: inline-flex;
  gap: 0.35rem;
  align-items: center;
  margin-top: 0.25rem;
  color: var(--vp-c-text-1);
  font-size: 0.78rem;
  font-weight: 650;
  text-decoration: none;
}

.studio-example__header > a:hover {
  color: var(--studio-example-accent);
}

.studio-example__icon {
  width: 0.875rem;
  height: 0.875rem;
  flex: 0 0 auto;
}

.studio-example__switcher {
  display: flex;
  gap: 1rem;
  align-items: center;
  justify-content: space-between;
  min-height: 2.75rem;
  padding: 0 1.25rem;
  border-top: 1px solid var(--vp-c-divider);
  border-bottom: 1px solid var(--vp-c-divider);
  background: var(--vp-c-bg-soft);
}

.studio-example__current {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  gap: 0.35rem;
  align-items: center;
  color: var(--vp-c-text-2);
  font-size: 0.68rem;
}

.studio-example__current a {
  color: inherit;
  text-decoration: none;
}

.studio-example__current a:hover {
  color: var(--studio-example-accent);
}

.studio-example__technology-separator {
  color: var(--vp-c-text-3);
}

.studio-example__switcher nav {
  display: flex;
  gap: 1.15rem;
  justify-content: flex-end;
}

.studio-example__tab-flow {
  align-self: center;
  color: var(--vp-c-text-3);
  font-family: var(--vp-font-family-mono);
  font-size: 0.72rem;
}

.studio-example__switcher button {
  display: inline-flex;
  gap: 0.35rem;
  align-items: center;
  border: 0;
  border-bottom: 2px solid transparent;
  border-radius: 0;
  padding: 0.72rem 0.05rem 0.62rem;
  background: transparent;
  color: var(--vp-c-text-2);
  cursor: pointer;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 650;
}

.studio-example__switcher button:hover {
  border-bottom-color: var(--vp-c-divider);
  color: var(--vp-c-text-1);
}

.studio-example__switcher button[aria-pressed="true"] {
  border-bottom-color: var(--studio-example-accent);
  color: var(--vp-c-text-1);
}

.studio-example__switcher button:focus-visible,
.studio-example__header > a:focus-visible {
  outline: 3px solid color-mix(in srgb, var(--studio-example-accent) 45%, transparent);
  outline-offset: 3px;
}

.studio-example__viewport {
  position: relative;
  min-height: 0;
  background: #111513;
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
  justify-items: center;
  padding: 2rem;
  background: var(--vp-c-bg-soft);
  color: var(--studio-example-accent);
  font-family: var(--vp-font-family-mono);
  font-size: 0.68rem;
  letter-spacing: 0.06em;
  text-align: center;
  text-transform: uppercase;
}

figcaption {
  display: flex;
  gap: 1rem;
  justify-content: flex-start;
  padding: 0.65rem 1.5rem;
  border-top: 1px solid var(--vp-c-divider);
  color: var(--vp-c-text-3);
  font-size: 0.64rem;
}

.studio-example__source-links {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem;
}

.studio-example__source-prefix,
.studio-example__view-sources {
  display: inline-flex;
  align-items: center;
}

.studio-example__source-prefix {
  gap: 0.3rem;
}

.studio-example__view-sources {
  flex-wrap: wrap;
  gap: 0.45rem;
}

.studio-example__source-divider {
  width: 1px;
  height: 0.85rem;
  flex: 0 0 auto;
  background: var(--vp-c-divider);
}

.studio-example__source-separator {
  color: var(--vp-c-text-3);
}

.studio-example__source-links a {
  display: inline-flex;
  gap: 0.2rem;
  align-items: baseline;
  color: var(--vp-c-text-2);
  text-decoration: none;
}

.studio-example__source-links a:hover {
  color: var(--studio-example-accent);
}

@media (max-width: 720px) {
  .studio-example__header {
    column-gap: 0.75rem;
    row-gap: 0.55rem;
  }

  .studio-example__header > a {
    width: 2rem;
    height: 2rem;
    justify-content: center;
    margin-top: 0;
  }

  .studio-example__open-label {
    display: none;
  }

  .studio-example__source-label {
    display: none;
  }

  .studio-example__switcher {
    display: flex;
    padding: 0 1rem;
  }

  .studio-example__current {
    display: none;
  }

  .studio-example__switcher nav {
    width: 100%;
    gap: 0.25rem;
    justify-content: space-between;
    overflow-x: auto;
  }

  .studio-example__switcher button {
    flex: 0 0 auto;
  }

  figcaption {
    display: grid;
    padding-inline: 1rem;
  }

  .studio-example__source-links {
    justify-content: flex-start;
  }

  .studio-example__view-divider {
    display: none;
  }

  .studio-example__view-sources {
    width: 100%;
    padding-top: 0.45rem;
    border-top: 1px solid var(--vp-c-divider);
  }
}

@media (prefers-reduced-motion: reduce) {
  .studio-example *,
  .studio-example *::before,
  .studio-example *::after {
    scroll-behavior: auto !important;
  }
}
</style>
