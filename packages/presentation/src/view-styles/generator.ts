import { createGenerator } from "@unocss/core";
import { generate, parse, walk } from "css-tree";

import { createViewStyleDefaults } from "./config.ts";

const THEME_ROOT = /:root,\s*:host\s*\{/g;
const KEYFRAME_PREFIX = "marimo-studio-view-";
let generationQueue = Promise.resolve();

const namespaceKeyframes = (css: string): string => {
  const stylesheet = parse(css);
  const names = new Map<string, string>();
  walk(stylesheet, {
    visit: "Atrule",
    enter(node) {
      if (node.name !== "keyframes" || node.prelude?.type !== "AtrulePrelude") {
        return;
      }
      const name = node.prelude.children.first;
      if (name?.type !== "Identifier") {
        return;
      }
      const namespaced = `${KEYFRAME_PREFIX}${name.name}`;
      names.set(name.name, namespaced);
      name.name = namespaced;
    },
  });
  if (names.size === 0) {
    return generate(stylesheet);
  }
  walk(stylesheet, {
    visit: "Declaration",
    enter(node) {
      if (node.property === "animation-name") {
        walk(node.value, (value) => {
          if (value.type === "Identifier") {
            value.name = names.get(value.name) ?? value.name;
          }
        });
        return;
      }
      if (node.property !== "animation" || node.value.type !== "Value") {
        return;
      }
      let groupStart = true;
      node.value.children.forEach((value) => {
        if (value.type === "Operator" && value.value === ",") {
          groupStart = true;
          return;
        }
        if (!groupStart) {
          return;
        }
        groupStart = false;
        if (value.type === "Identifier") {
          value.name = names.get(value.name) ?? value.name;
        }
      });
    },
  });
  return generate(stylesheet);
};

const generateExclusive = <Value>(work: () => Promise<Value>): Promise<Value> => {
  const result = generationQueue.then(work, work);
  generationQueue = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
};

export const generateViewCss = (tokens: ReadonlySet<string>): Promise<string> => {
  const snapshot = new Set(tokens);
  return generateExclusive(async () => {
    const generator = await createGenerator(createViewStyleDefaults());
    const result = await generator.generate(snapshot, { minify: true });
    return namespaceKeyframes(result.css.replace(THEME_ROOT, "#app-shell{"));
  });
};
