import type { DocumentationExampleFamily, DocumentationExampleView } from "../examples.ts";

export interface SelectedExampleFamily {
  family: DocumentationExampleFamily;
  notebook: boolean;
  views: readonly DocumentationExampleView[];
}

export interface ExampleBuildSelection {
  complete: boolean;
  families: readonly SelectedExampleFamily[];
  notebooks: number;
  views: number;
}

type SelectorKind = "family" | "notebook" | "view";

interface Selector {
  kind: SelectorKind;
  value: string;
}

const selectorFlags = new Set(["--family", "--notebook", "--view"]);

const parseSelectors = (arguments_: readonly string[]): readonly Selector[] => {
  const selectors: Selector[] = [];
  for (let index = 0; index < arguments_.length; index += 1) {
    const argument = arguments_[index] ?? "";
    if (argument === "--") {
      continue;
    }
    const separator = argument.indexOf("=");
    const flag = separator < 0 ? argument : argument.slice(0, separator);
    if (!selectorFlags.has(flag)) {
      throw new Error(`Unknown examples build option: ${argument}`);
    }
    const inline = separator < 0 ? undefined : argument.slice(separator + 1);
    const value = inline ?? arguments_[index + 1];
    if (!value || value.startsWith("--")) {
      throw new Error(`${flag} requires a value.`);
    }
    if (inline === undefined) {
      index += 1;
    }
    let kind: SelectorKind;
    if (flag === "--family") {
      kind = "family";
    } else if (flag === "--notebook") {
      kind = "notebook";
    } else {
      kind = "view";
    }
    selectors.push({ kind, value });
  }
  return selectors;
};

const selectedViews = (
  family: DocumentationExampleFamily,
  names: ReadonlySet<string>,
): readonly DocumentationExampleView[] => family.views.filter((view) => names.has(view.key));

export const selectDocumentationExamples = (
  families: readonly DocumentationExampleFamily[],
  arguments_: readonly string[],
): ExampleBuildSelection => {
  const selectors = parseSelectors(arguments_);
  if (selectors.length === 0) {
    return {
      complete: true,
      families: families.map((family) => ({
        family,
        notebook: true,
        views: family.views,
      })),
      notebooks: families.length,
      views: families.reduce((count, family) => count + family.views.length, 0),
    };
  }

  const bySlug = new Map(families.map((family) => [family.slug, family]));
  const notebooks = new Set<string>();
  const views = new Map<string, Set<string>>();
  for (const selector of selectors) {
    const [slug, view, ...extra] = selector.value.split("/");
    const family = slug ? bySlug.get(slug) : undefined;
    if (family === undefined) {
      throw new Error(`Unknown documentation example family: ${slug || selector.value}`);
    }
    if (selector.kind === "view") {
      if (!view || extra.length > 0) {
        throw new Error(`--view requires FAMILY/VIEW, received ${selector.value}.`);
      }
      if (!family.views.some((candidate) => candidate.key === view)) {
        throw new Error(`Unknown documentation example view: ${selector.value}`);
      }
      const selected = views.get(family.slug) ?? new Set<string>();
      selected.add(view);
      views.set(family.slug, selected);
      continue;
    }
    if (view !== undefined) {
      throw new Error(`--${selector.kind} requires a family slug.`);
    }
    if (selector.kind === "notebook") {
      notebooks.add(family.slug);
      continue;
    }
    notebooks.add(family.slug);
    views.set(family.slug, new Set(family.views.map((candidate) => candidate.key)));
  }

  const selected = families.flatMap((family) => {
    const notebook = notebooks.has(family.slug);
    const familyViews = selectedViews(family, views.get(family.slug) ?? new Set());
    return notebook || familyViews.length > 0 ? [{ family, notebook, views: familyViews }] : [];
  });
  const notebookCount = selected.filter((item) => item.notebook).length;
  const viewCount = selected.reduce((count, item) => count + item.views.length, 0);
  const totalViews = families.reduce((count, family) => count + family.views.length, 0);
  return {
    complete: notebookCount === families.length && viewCount === totalViews,
    families: selected,
    notebooks: notebookCount,
    views: viewCount,
  };
};
