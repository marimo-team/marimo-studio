<script setup lang="ts">
import { withBase } from "vitepress";

import { documentationExampleFamilies, documentationPosterViewports } from "../../../examples.ts";

// Interleave the families and rotate their order each round, so neighboring
// tiles come from different notebooks.
const families = documentationExampleFamilies;
const depth = Math.max(...families.map(({ views }) => views.length));
const interleaved = Array.from({ length: depth }, (_, index) =>
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

// CSS columns fill top to bottom and break where the heights balance. Deal
// each tile to the shortest of three columns, then list the columns in turn,
// so every column ends at the same height. A tile and its caption are
// measured in poster widths.
const columnCount = 3;
const captionHeight = 0.2;
const columns: { height: number; tiles: typeof interleaved }[] = Array.from(
  { length: columnCount },
  () => ({ height: 0, tiles: [] }),
);
// Among equally short columns, prefer the one with fewer posters from the
// same notebook.
const shared = (column: (typeof columns)[number], family: string): number =>
  column.tiles.filter((tile) => tile.family === family).length;
for (const tile of interleaved) {
  const shortest = columns.reduce((best, column) => {
    const difference = column.height - best.height;
    if (Math.abs(difference) < 1e-9) {
      return shared(column, tile.family) < shared(best, tile.family) ? column : best;
    }
    return difference < 0 ? column : best;
  });
  shortest.tiles.push(tile);
  shortest.height += tile.height / tile.width + captionHeight;
}
// Keep two posters from one notebook from stacking directly. Swap a repeated
// tile with one below the first row that fits between different neighbors.
const repeats = (tiles: typeof interleaved, index: number): boolean =>
  [index - 1, index + 1].some((other) => tiles[other]?.family === tiles[index]?.family);
for (const { tiles } of columns) {
  for (let index = 1; index < tiles.length; index += 1) {
    if (!repeats(tiles, index)) {
      continue;
    }
    for (let other = 1; other < tiles.length; other += 1) {
      [tiles[index], tiles[other]] = [tiles[other], tiles[index]];
      if (!repeats(tiles, index) && !repeats(tiles, other)) {
        break;
      }
      [tiles[index], tiles[other]] = [tiles[other], tiles[index]];
    }
  }
}
const tiles = columns.flatMap((column) => column.tiles);
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

/* Two narrow columns keep all fifteen posters within a few screens on a phone. */
@media (max-width: 640px) {
  .studio-view-masonry {
    columns: 2;
    column-gap: 0.875rem;
  }

  .vp-doc .studio-view-masonry li {
    margin-bottom: 1.25rem;
  }

  .studio-view-masonry__caption {
    flex-direction: column;
    gap: 0;
    padding-top: 0.5rem;
    font-size: 13px;
    line-height: 18px;
  }

  .studio-view-masonry__caption span {
    font-size: 12px;
  }

  .studio-view-masonry small {
    display: none;
  }
}
</style>
