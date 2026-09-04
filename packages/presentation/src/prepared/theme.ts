import { PAGE_THEME_EVENT, themeFromColorScheme } from "../document/theme.ts";

const preferredColorScheme = (): MediaQueryList | undefined =>
  globalThis.matchMedia?.("(prefers-color-scheme: dark)");

const pageTheme = (): "light" | "dark" | undefined =>
  themeFromColorScheme(
    globalThis.getComputedStyle(document.documentElement).colorScheme,
    preferredColorScheme()?.matches ?? false,
  );

export const presentationThemeSource = {
  current: pageTheme,
  subscribe(listener: () => void): () => void {
    const media = preferredColorScheme();
    globalThis.addEventListener(PAGE_THEME_EVENT, listener);
    media?.addEventListener("change", listener);
    return () => {
      globalThis.removeEventListener(PAGE_THEME_EVENT, listener);
      media?.removeEventListener("change", listener);
    };
  },
};
