import type { Theme } from "vitepress";

import DefaultTheme from "vitepress/theme";

import StudioExample from "./components/StudioExample.vue";
import StudioExampleCard from "./components/StudioExampleCard.vue";
import StudioViewStack from "./components/StudioViewStack.vue";
import "./custom.css";

export default {
  extends: DefaultTheme,
  enhanceApp({ app }) {
    app.component("StudioExample", StudioExample);
    app.component("StudioExampleCard", StudioExampleCard);
    app.component("StudioViewStack", StudioViewStack);
  },
} satisfies Theme;
