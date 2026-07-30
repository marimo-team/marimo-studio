export type PageTheme = "light" | "dark";

export const themeFromColorScheme = (
  colorScheme: string,
  prefersDark = false,
): PageTheme | undefined => {
  const themes = colorScheme
    .toLowerCase()
    .split(/\s+/)
    .filter((value): value is PageTheme =>
      value === "light" || value === "dark"
    );
  if (themes.includes("light") && themes.includes("dark")) {
    return prefersDark ? "dark" : "light";
  }
  return themes[0];
};

export const PAGE_THEME_EVENT = "marimo-studio:page-theme";

export const notifyPageTheme = (): void => {
  globalThis.dispatchEvent(new Event(PAGE_THEME_EVENT));
};
