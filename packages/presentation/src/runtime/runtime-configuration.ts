import { PAGE_THEME_EVENT, themeFromColorScheme } from "../document/theme";

export type InitialMode = "edit" | "read";
export type ViewMode = "present" | "read";

const preferredColorScheme = globalThis.matchMedia("(prefers-color-scheme: dark)");

const pageTheme = (): "light" | "dark" | undefined =>
  themeFromColorScheme(
    globalThis.getComputedStyle(document.documentElement).colorScheme,
    preferredColorScheme.matches,
  );

export const pageThemeSource = {
  current: pageTheme,
  subscribe(listener: () => void): () => void {
    globalThis.addEventListener(PAGE_THEME_EVENT, listener);
    preferredColorScheme.addEventListener("change", listener);
    return () => {
      globalThis.removeEventListener(PAGE_THEME_EVENT, listener);
      preferredColorScheme.removeEventListener("change", listener);
    };
  },
};
