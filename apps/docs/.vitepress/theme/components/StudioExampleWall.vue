<script setup lang="ts">
import { withBase } from "vitepress";
import { onBeforeUnmount, onMounted, ref, watch } from "vue";

import {
  documentationExampleFamilies as families,
  documentationExamplePages,
  documentationExampleWall as wall,
} from "../../../examples.ts";

// The four middle columns hold the families in catalog order, and the
// columns beyond them continue the cycle. Narrower screens drop the outer
// pairs. Each column repeats its pages three times and scrolls one copy per
// cycle, so it loops without a seam.
const columnCount = 8;
const copies = 3;
const first = Math.floor((columnCount - families.length) / 2);

const columns = Array.from({ length: columnCount }, (_, index) => {
  const family = families[(index - first + columnCount) % families.length] ?? families[0];
  return {
    pages: documentationExamplePages(family).map((page) => ({
      ...page,
      href: withBase(`/examples/${family.slug}?view=${page.key}`),
      src: withBase(`/thumbnails/${page.path}.webp`),
    })),
    // 0 for the middle pair, 1 for the pair around it, and so on.
    ring: Math.floor(Math.abs(index - (columnCount - 1) / 2)),
    // Neighbors scroll in opposite directions, a third of a cycle apart.
    phase: (index % 3) / 3,
    reverse: index % 2 === 1,
  };
});

const geometry = {
  "--wall-aspect": wall.aspect,
  "--wall-copies": copies,
  "--wall-pages": Math.max(...columns.map(({ pages }) => pages.length)),
  "--wall-gap": wall.gap,
  "--wall-perspective": wall.perspective,
  "--wall-rotate-x": `${wall.rotateX}deg`,
  "--wall-rotate-z": `${wall.rotateZ}deg`,
};

// The pause button, or a mouse over the wall, eases the scroll to a stop by
// tweening the playback rate of the columns' CSS animations.
const root = ref<HTMLElement>();
const paused = ref(false);
const hovered = ref(false);
const easeMs = 280;
let rate = 1;
let target = 1;
let frame = 0;

const tween =
  (previous?: number) =>
  (now: number): void => {
    rate = target + (rate - target) * Math.exp((now - (previous ?? now)) / -easeMs);
    if (Math.abs(rate - target) < 0.002) {
      rate = target;
    }
    for (const animation of root.value?.getAnimations({ subtree: true }) ?? []) {
      if (animation instanceof CSSAnimation) {
        animation.playbackRate = rate;
      }
    }
    frame = rate === target ? 0 : requestAnimationFrame(tween(now));
  };

watch([paused, hovered], () => {
  target = paused.value || hovered.value ? 0 : 1;
  frame ||= requestAnimationFrame(tween());
});

const hover = (event: PointerEvent, next: boolean): void => {
  if (event.pointerType === "mouse") {
    hovered.value = next;
  }
};

// Columns stop scrolling while the wall is off screen.
const visible = ref(true);
let observer: IntersectionObserver | undefined;
onMounted(() => {
  observer = new IntersectionObserver((entries) => {
    visible.value = entries.at(-1)?.isIntersecting ?? true;
  });
  if (root.value) {
    observer.observe(root.value);
  }
});
onBeforeUnmount(() => {
  observer?.disconnect();
  cancelAnimationFrame(frame);
});
</script>

<template>
  <div ref="root" class="studio-example-wall" :style="geometry">
    <!-- The examples gallery lists every page as well, so the cards stay out
         of the accessibility tree and the tab order. -->
    <div
      class="studio-example-wall__frame"
      :data-idle="!visible || undefined"
      aria-hidden="true"
      @pointerenter="hover($event, true)"
      @pointerleave="hover($event, false)"
    >
      <div class="studio-example-wall__plane">
        <div
          v-for="(column, index) in columns"
          :key="index"
          class="studio-example-wall__column"
          :data-ring="column.ring"
        >
          <div
            class="studio-example-wall__track"
            :style="{ '--wall-phase': column.phase }"
            :data-reverse="column.reverse || undefined"
          >
            <template v-for="copy in copies" :key="copy">
              <a
                v-for="page in column.pages"
                :key="page.path"
                class="studio-example-wall__card"
                :data-notebook="page.notebook || undefined"
                :href="page.href"
                tabindex="-1"
                draggable="false"
              >
                <span class="studio-example-wall__header">
                  <span>{{ page.label }}</span>
                  <span>{{ page.detail }}</span>
                </span>
                <img :src="page.src" alt="" width="1600" height="1000" decoding="async" />
              </a>
            </template>
          </div>
        </div>
      </div>
    </div>
    <button
      type="button"
      class="studio-example-wall__pause"
      :aria-pressed="paused"
      aria-label="Pause the example wall"
      @click="paused = !paused"
    >
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path v-if="paused" d="M5 3.5v9l7-4.5z" />
        <path v-else d="M5 3.5v9M11 3.5v9" />
      </svg>
    </button>
  </div>
</template>

<style scoped>
/* Lengths follow the card width, as in the README wall. */
.studio-example-wall {
  --card: clamp(168px, 21vw, 320px);
  --gap: calc(var(--card) * var(--wall-gap));
  --header: 26px;
  --wall-cycle: 120s;
  --period: calc(
    (var(--card) * var(--wall-aspect) + var(--header) + var(--gap)) * var(--wall-pages)
  );

  position: relative;
  margin-top: -8px;
  container-type: inline-size;
}

.studio-example-wall__frame {
  position: relative;
  height: clamp(320px, 46vw, 620px);
  overflow: hidden;
  perspective: calc(var(--card) * var(--wall-perspective));
  perspective-origin: 50% 30%;
  user-select: none;
  /* The wall bleeds past the frame, so every edge fades out. */
  mask-image:
    linear-gradient(to bottom, transparent, #000 10%, #000 76%, transparent),
    linear-gradient(to right, transparent, #000 10%, #000 90%, transparent);
  mask-composite: intersect;
}

.studio-example-wall__plane {
  position: absolute;
  top: 50%;
  left: 50%;
  display: flex;
  gap: var(--gap);
  height: calc(var(--period) * 2);
  transform: translate(-50%, -50%) rotateX(var(--wall-rotate-x)) rotateZ(var(--wall-rotate-z));
}

.studio-example-wall__column {
  width: var(--card);
  flex: none;
}

/* The outer rings join as the page widens. */
@container (max-width: 1279px) {
  .studio-example-wall__column[data-ring="3"] {
    display: none;
  }
}

@container (max-width: 767px) {
  .studio-example-wall__column[data-ring="2"] {
    display: none;
  }
}

.studio-example-wall__track {
  display: flex;
  flex-direction: column;
  animation: studio-example-wall-scroll var(--wall-cycle) linear infinite;
  animation-delay: calc(var(--wall-phase) * -1 * var(--wall-cycle));
  will-change: transform;
}

.studio-example-wall__track[data-reverse] {
  animation-direction: reverse;
}

.studio-example-wall__frame[data-idle] .studio-example-wall__track {
  animation-play-state: paused;
}

@keyframes studio-example-wall-scroll {
  to {
    transform: translateY(calc(-100% / var(--wall-copies)));
  }
}

.studio-example-wall__pause {
  position: absolute;
  right: 16px;
  bottom: 8px;
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  border-radius: 6px;
  color: var(--vp-c-text-3);
  transition:
    color 0.2s ease,
    background-color 0.2s ease;
}

.studio-example-wall__pause:hover {
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
}

.studio-example-wall__pause:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.studio-example-wall__pause svg {
  width: 14px;
  height: 14px;
  fill: currentColor;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.75;
}

@media (prefers-reduced-motion: reduce) {
  .studio-example-wall__track {
    animation: none;
  }

  .studio-example-wall__pause {
    display: none;
  }
}

/* Each card owns the gap below it, so a copy is exactly one cycle long. */
.studio-example-wall__card {
  display: flex;
  flex-direction: column;
  margin-bottom: var(--gap);
  overflow: hidden;
  border: 1px solid var(--studio-card-border);
  border-radius: calc(var(--card) * 12 / 640 + 4px);
  background: var(--studio-card-bg);
  color: inherit;
  text-decoration: none;
  transition:
    transform 0.45s cubic-bezier(0.2, 0.7, 0.2, 1),
    border-color 0.3s ease;
  -webkit-user-drag: none;
}

.studio-example-wall__card:hover {
  border-color: var(--studio-link);
  transform: scale(1.03);
}

.studio-example-wall__header {
  display: flex;
  flex: none;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
  height: var(--header);
  padding: 0 10px;
  border-bottom: 1px solid var(--studio-chrome-rule);
  background: var(--studio-chrome);
  color: var(--studio-chrome-label);
  font-size: 11px;
  font-weight: 550;
  line-height: 1;
  white-space: nowrap;
}

.studio-example-wall__header span:last-child {
  min-width: 0;
  overflow: hidden;
  color: var(--studio-chrome-muted);
  font-weight: 450;
  text-overflow: ellipsis;
}

.studio-example-wall__card[data-notebook] .studio-example-wall__header {
  background: var(--studio-notebook-chrome);
  color: var(--studio-notebook-label);
}

.studio-example-wall__card[data-notebook] .studio-example-wall__header span:last-child {
  font-family: var(--vp-font-family-mono);
  font-size: 10.5px;
}

.studio-example-wall__card img {
  display: block;
  width: 100%;
  height: auto;
  aspect-ratio: 1 / var(--wall-aspect);
  object-fit: cover;
  object-position: top center;
  pointer-events: none;
}

.dark .studio-example-wall__card img {
  filter: brightness(0.88);
}
</style>
