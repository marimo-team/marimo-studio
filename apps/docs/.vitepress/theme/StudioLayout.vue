<script setup lang="ts">
import DefaultTheme from "vitepress/theme";

import StudioExampleWall from "./components/StudioExampleWall.vue";
import StudioSidebarToggle from "./components/StudioSidebarToggle.vue";
import { useSidebarCollapse } from "./sidebar-collapse.ts";

const { Layout } = DefaultTheme;
const { collapsed, available, toggle } = useSidebarCollapse();
</script>

<template>
  <Layout>
    <template #home-hero-after>
      <StudioExampleWall />
    </template>
    <template #nav-bar-content-before>
      <StudioSidebarToggle v-if="available" :collapsed="collapsed" @toggle="toggle" />
    </template>
  </Layout>
</template>
