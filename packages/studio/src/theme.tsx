import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

export type StudioTheme = "light" | "dark";

export interface StudioBrand {
  marks: Readonly<Record<StudioTheme, string>>;
}

export type ThemeFrameConnector = (
  frame: HTMLIFrameElement,
  listener: (theme: StudioTheme | undefined) => void,
) => () => void;

const StudioThemeContext = createContext<StudioTheme>("light");

const systemTheme = (): StudioTheme =>
  globalThis.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";

export const useResolvedStudioTheme = (
  frame: HTMLIFrameElement | null,
  connectThemeFrame?: ThemeFrameConnector,
): StudioTheme => {
  const [system, setSystem] = useState(systemTheme);
  const [native, setNative] = useState<StudioTheme | undefined>();

  useEffect(() => {
    const media = globalThis.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystem(media.matches ? "dark" : "light");
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    if (!frame || !connectThemeFrame) {
      return;
    }
    return connectThemeFrame(frame, setNative);
  }, [connectThemeFrame, frame]);

  return native ?? system;
};

export const StudioThemeProvider = ({
  children,
  theme,
}: {
  children: ReactNode;
  theme: StudioTheme;
}) => <StudioThemeContext.Provider value={theme}>{children}</StudioThemeContext.Provider>;

export const useStudioTheme = (): StudioTheme => useContext(StudioThemeContext);
