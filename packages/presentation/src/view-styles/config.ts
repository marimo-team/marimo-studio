import type { Postprocessor } from "@unocss/core";

import presetWind4, { type Theme } from "@unocss/preset-wind4";
import { clone, generate, parse, type SelectorList } from "css-tree";

// A selector inside @scope starts below the scope root. Include :scope so
// utilities on #app-shell follow the same rules as utilities on its children.
const parseSelectorList = (selector: string): SelectorList => {
  const parsed = parse(selector, { context: "selectorList" });
  if (parsed.type !== "SelectorList") {
    throw new Error(`Unable to parse selector list ${selector}`);
  }
  return parsed;
};

const scopeSubjectSelector = parseSelectorList(":where(:scope, *)");
const scopeSubject = scopeSubjectSelector.children.first;
const SCOPE_SUBJECT = scopeSubject?.type === "Selector" ? scopeSubject.children.first : null;
if (!SCOPE_SUBJECT) {
  throw new Error("Unable to create the view scope subject");
}

const targetScopedElement: Postprocessor = (utility) => {
  if (utility.selector.startsWith("@")) {
    return;
  }
  let selectors: SelectorList;
  try {
    selectors = parseSelectorList(utility.selector);
  } catch (error) {
    throw new Error(`Unable to scope view utility selector ${utility.selector}`, {
      cause: error,
    });
  }
  selectors.children.forEach((selector) => {
    if (selector.type === "Selector") {
      selector.children.prependData(clone(SCOPE_SUBJECT));
    }
  });
  utility.selector = generate(selectors);
};

const completeBorderWidth: Postprocessor = (utility) => {
  const properties = new Set(utility.entries.map(([property]) => property));
  for (const [property] of utility.entries) {
    if (!property.startsWith("border-") || !property.endsWith("-width")) {
      continue;
    }
    const style = property.replace(/-width$/, "-style");
    if (!properties.has(style)) {
      utility.entries.push([style, "solid"]);
      properties.add(style);
    }
  }
};

const theme = {
  colors: {
    accent: {
      DEFAULT: "var(--accent)",
      foreground: "var(--accent-foreground)",
    },
    background: "var(--background)",
    border: "var(--border)",
    card: {
      DEFAULT: "var(--card)",
      foreground: "var(--card-foreground)",
    },
    destructive: {
      DEFAULT: "var(--destructive)",
      foreground: "var(--destructive-foreground)",
    },
    foreground: "var(--foreground)",
    input: "var(--input)",
    link: "var(--link)",
    muted: {
      DEFAULT: "var(--muted)",
      foreground: "var(--muted-foreground)",
    },
    popover: {
      DEFAULT: "var(--popover)",
      foreground: "var(--popover-foreground)",
    },
    primary: {
      DEFAULT: "var(--primary)",
      foreground: "var(--primary-foreground)",
    },
    ring: "var(--ring)",
    secondary: {
      DEFAULT: "var(--secondary)",
      foreground: "var(--secondary-foreground)",
    },
  },
  font: {
    heading: "var(--heading-font)",
    mono: "var(--monospace-font)",
    sans: "var(--text-font)",
  },
  radius: {
    DEFAULT: "var(--radius)",
    lg: "var(--radius)",
    md: "calc(var(--radius) - 2px)",
    sm: "calc(var(--radius) - 4px)",
  },
} satisfies Theme;

const shortcuts = {
  "studio-button":
    "inline-flex items-center justify-center gap-2 rounded-md border border-solid border-input bg-background px-3 py-2 font-sans text-sm font-medium text-foreground shadow-xs transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:pointer-events-none disabled:opacity-50",
  "studio-card": "rounded-lg border border-solid border-border bg-card text-card-foreground",
  "studio-eyebrow": "text-xs font-semibold uppercase tracking-widest text-muted-foreground",
  "studio-view": "mx-auto w-full max-w-7xl px-4 py-10 sm:px-6 lg:px-8",
} as const;

export const createViewStyleDefaults = () => ({
  postprocess: [targetScopedElement, completeBorderWidth],
  presets: [
    presetWind4({
      dark: "media",
      preflights: { reset: false, theme: "on-demand" },
    }),
  ],
  shortcuts,
  theme,
});
