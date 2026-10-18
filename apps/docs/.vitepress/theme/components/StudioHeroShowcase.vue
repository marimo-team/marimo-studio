<script setup lang="ts">
import { withBase } from "vitepress";

// tools/example-showcase renders this image from the exported example views,
// at 2400 px wide with a 2x variant, in both themes.
const name = "marimo-studio-fan-quadratic-programs";
const themes = ["light", "dark"] as const;
const source = (theme: (typeof themes)[number], scale = ""): string =>
  withBase(`/showcase/${name}-${theme}${scale}.webp`);
</script>

<template>
  <figure class="studio-hero-showcase">
    <picture v-for="theme in themes" :key="theme" :class="`is-${theme}`">
      <img
        :src="source(theme)"
        :srcset="`${source(theme)} 1x, ${source(theme, '@2x')} 2x`"
        width="2400"
        height="1100"
        alt="The quadratic_program.py notebook above the views built from it: a React and Reveal.js lecture deck, a Svelte lab, a Typst report, and a plain HTML explainer."
        decoding="async"
        fetchpriority="high"
      />
    </picture>
    <figcaption>
      <code>quadratic_program.py</code> and the views built from its results: a lecture deck, an
      interactive lab, a typeset report, and a reading explainer.
    </figcaption>
  </figure>
</template>

<style scoped>
/* Match the hero's container, so the image lines up with the text above. */
.studio-hero-showcase {
  max-width: calc(72rem + 48px);
  margin: 1.5rem auto 1rem;
  padding: 0 24px;
}

@media (min-width: 640px) {
  .studio-hero-showcase {
    max-width: calc(72rem + 96px);
    padding: 0 48px;
  }
}

@media (min-width: 960px) {
  .studio-hero-showcase {
    max-width: calc(72rem + 128px);
    margin-top: 1rem;
    padding: 0 64px;
  }
}

.studio-hero-showcase img {
  display: block;
  width: 100%;
  height: auto;
}

.studio-hero-showcase figcaption {
  margin-top: 0.25rem;
  color: var(--vp-c-text-2);
  font-size: 13px;
  line-height: 1.55;
  text-align: center;
}

.dark .is-light,
html:not(.dark) .is-dark {
  display: none;
}
</style>
