import type { Theme } from "vitepress";

import DefaultTheme from "vitepress/theme";

import GlossaryTerm from "./components/GlossaryTerm.vue";
import StudioExample from "./components/StudioExample.vue";
import StudioExampleCard from "./components/StudioExampleCard.vue";
import StudioFigure from "./components/StudioFigure.vue";
import StudioLensTrace from "./components/StudioLensTrace.vue";
import StudioPipeline from "./components/StudioPipeline.vue";
import StudioPreparedStates from "./components/StudioPreparedStates.vue";
import StudioResultMap from "./components/StudioResultMap.vue";
import StudioViewMasonry from "./components/StudioViewMasonry.vue";
import StudioViewStack from "./components/StudioViewStack.vue";
import StudioLayout from "./StudioLayout.vue";
import "./custom.css";
import "./figure.css";

export default {
  extends: DefaultTheme,
  Layout: StudioLayout,
  enhanceApp({ app }) {
    app.component("GlossaryTerm", GlossaryTerm);
    app.component("StudioLensTrace", StudioLensTrace);
    app.component("StudioPipeline", StudioPipeline);
    app.component("StudioPreparedStates", StudioPreparedStates);
    app.component("StudioResultMap", StudioResultMap);
    app.component("StudioExample", StudioExample);
    app.component("StudioExampleCard", StudioExampleCard);
    app.component("StudioFigure", StudioFigure);
    app.component("StudioViewMasonry", StudioViewMasonry);
    app.component("StudioViewStack", StudioViewStack);
  },
} satisfies Theme;
