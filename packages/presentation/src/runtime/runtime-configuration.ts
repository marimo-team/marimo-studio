import { PAGE_THEME_EVENT, themeFromColorScheme } from "../document/theme";

export type InitialMode = "edit" | "read";
export type ViewMode = "present" | "read";

const preferredColorScheme = (): MediaQueryList | undefined =>
  globalThis.matchMedia?.("(prefers-color-scheme: dark)");

const pageTheme = (): "light" | "dark" | undefined =>
  themeFromColorScheme(
    globalThis.getComputedStyle(document.documentElement).colorScheme,
    preferredColorScheme()?.matches ?? false,
  );

export const pageThemeSource = {
  current: pageTheme,
  subscribe(listener: () => void): () => void {
    const preferred = preferredColorScheme();
    globalThis.addEventListener(PAGE_THEME_EVENT, listener);
    preferred?.addEventListener("change", listener);
    return () => {
      globalThis.removeEventListener(PAGE_THEME_EVENT, listener);
      preferred?.removeEventListener("change", listener);
    };
  },
};
