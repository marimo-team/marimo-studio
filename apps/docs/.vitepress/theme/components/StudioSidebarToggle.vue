<script setup lang="ts">
defineProps<{ collapsed: boolean }>();
defineEmits<{ toggle: [] }>();
</script>

<template>
  <button
    type="button"
    class="studio-sidebar-toggle"
    :aria-pressed="collapsed"
    :aria-label="collapsed ? 'Show sidebar' : 'Hide sidebar'"
    :title="collapsed ? 'Show sidebar' : 'Hide sidebar'"
    @click="$emit('toggle')"
  >
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9 4v16" />
      <path v-if="collapsed" d="m13 10 2 2-2 2" />
      <path v-else d="m15 10-2 2 2 2" />
    </svg>
  </button>
</template>

<style scoped>
.studio-sidebar-toggle {
  display: none;
  width: 36px;
  height: 36px;
  flex: none;
  align-items: center;
  justify-content: center;
  margin-right: 8px;
  border-radius: 6px;
  color: var(--vp-c-text-2);
  transition:
    color 0.2s ease,
    background-color 0.2s ease;
}

.studio-sidebar-toggle:hover {
  background: var(--vp-c-bg-soft);
  color: var(--vp-c-text-1);
}

.studio-sidebar-toggle:focus-visible {
  outline: 2px solid var(--vp-c-brand-1);
  outline-offset: 2px;
}

.studio-sidebar-toggle svg {
  width: 20px;
  height: 20px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.6;
}

/* Below this width the default theme keeps the sidebar behind its menu. */
@media (min-width: 960px) {
  .studio-sidebar-toggle {
    display: inline-flex;
  }
}
</style>
