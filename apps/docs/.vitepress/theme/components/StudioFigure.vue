<script setup lang="ts">
import { withBase } from "vitepress";

// `name` selects a figure that scripts/example-figure/render.ts writes to
// public/figures/ as NAME-LAYOUT-THEME.webp.
const props = defineProps<{ name: string; alt: string }>();

const themes = ["light", "dark"] as const;
const source = (layout: "narrow" | "wide", theme: (typeof themes)[number]): string =>
  withBase(`/figures/${props.name}-${layout}-${theme}.webp`);
</script>

<template>
  <figure class="studio-figure">
    <picture v-for="theme in themes" :key="theme" :class="`studio-figure-${theme}`">
      <source media="(max-width: 640px)" :srcset="source('narrow', theme)" />
      <img :src="source('wide', theme)" :alt="alt" decoding="async" loading="lazy" />
    </picture>
  </figure>
</template>

<style scoped>
.studio-figure {
  margin-block: 1.5rem;
}

/* The figure draws its own cards on a transparent background, so it drops
   the frame that docs pages give images. */
.studio-figure img {
  display: block;
  width: 100%;
  height: auto;
  border: 0;
  border-radius: 0;
}
</style>

<style>
/* A figure spans the content column. Zero specificity lets page rules, such as
   the overview breakout, set its inline margins. */
:where(.studio-figure) {
  margin-inline: 0;
}

/* VitePress marks its dark theme with a class on <html>, so the picture for
   the other theme leaves the layout. Scoped :global() would compile these
   selectors to the bare <html> condition. */
.dark .studio-figure-light,
html:not(.dark) .studio-figure-dark {
  display: none;
}
</style>
