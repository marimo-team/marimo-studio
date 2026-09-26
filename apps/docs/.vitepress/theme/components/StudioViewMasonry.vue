<script setup lang="ts">
import { withBase } from "vitepress";

import { documentationExampleFamilies, documentationPosterViewports } from "../../../examples.ts";

// Columns fill top to bottom. Interleave the families and rotate their order
// each round so tiles side by side and above each other come from different
// notebooks.
const families = documentationExampleFamilies;
const depth = Math.max(...families.map(({ views }) => views.length));
const tiles = Array.from({ length: depth }, (_, index) =>
  families.flatMap((_, offset) => {
    const family = families[(index + offset) % families.length];
    const view = family.views[index];
    if (!view) {
      return [];
    }
    const { height, width } = documentationPosterViewports[view.poster];
    return [
      {
        family: family.title,
        height,
        href: withBase(`/examples/${family.slug}?view=${view.key}`),
        key: `${family.slug}/${view.key}`,
        label: view.label,
        src: withBase(`/posters/${family.slug}/${view.key}.webp`),
        technologies: view.technologies.map(({ name }) => name).join(" · "),
        width,
      },
    ];
  }),
).flat();
</script>

<template>
  <ul class="studio-view-masonry" aria-label="Example views">
    <li v-for="tile in tiles" :key="tile.key">
      <a :href="tile.href">
        <span class="studio-view-masonry__frame">
          <img
            :src="tile.src"
            alt=""
            :width="tile.width"
            :height="tile.height"
            decoding="async"
            loading="lazy"
          />
        </span>
        <span class="studio-view-masonry__caption">
          <strong>{{ tile.label }}</strong>
          <span>{{ tile.family }}</span>
        </span>
        <small>{{ tile.technologies }}</small>
      </a>
    </li>
  </ul>
</template>

<style scoped>
.studio-view-masonry {
  columns: 3 18rem;
  column-gap: 1.75rem;
  margin: 2rem 0 1.5rem;
  padding: 0;
  list-style: none;
}

.vp-doc .studio-view-masonry li {
  margin: 0 0 2.25rem;
  break-inside: avoid;
}

.vp-doc .studio-view-masonry a {
  display: block;
  color: inherit;
  text-decoration: none;
}

.studio-view-masonry__frame {
  display: block;
  overflow: hidden;
  border: 1px solid var(--vp-c-divider);
  border-radius: 6px;
  background: var(--vp-c-bg-soft);
  transition: border-color 0.2s ease;
}

a:hover .studio-view-masonry__frame {
  border-color: var(--vp-c-border);
}

.studio-view-masonry img {
  display: block;
  width: 100%;
  height: auto;
  margin: 0;
}

.studio-view-masonry__caption {
  display: flex;
  gap: 1rem;
  align-items: baseline;
  justify-content: space-between;
  padding-top: 0.75rem;
  font-size: 14px;
  line-height: 20px;
}

.studio-view-masonry__caption strong {
  color: var(--vp-c-text-1);
  font-weight: 600;
}

a:hover .studio-view-masonry__caption strong {
  color: var(--vp-c-brand-1);
}

.studio-view-masonry__caption span,
.studio-view-masonry small {
  color: var(--vp-c-text-2);
}

.studio-view-masonry small {
  display: block;
  padding-top: 0.125rem;
  font-size: 12px;
  line-height: 18px;
}

.studio-view-masonry a:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 4px;
  border-radius: 6px;
}
</style>
