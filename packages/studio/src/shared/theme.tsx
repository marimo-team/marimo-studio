import {
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useState,
  useSyncExternalStore,
} from "react";

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

const subscribeSystemTheme = (listener: () => void): (() => void) => {
  const media = globalThis.matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
};

interface NativeThemeState {
  connect: ThemeFrameConnector;
  frame: HTMLIFrameElement;
  theme: StudioTheme | undefined;
}

export const useResolvedStudioTheme = (
  frame: HTMLIFrameElement | null,
  connectThemeFrame?: ThemeFrameConnector,
): StudioTheme => {
  const system = useSyncExternalStore<StudioTheme>(
    subscribeSystemTheme,
    systemTheme,
    () => "light",
  );
  const [native, setNative] = useState<NativeThemeState>();

  useEffect(() => {
    if (!frame || !connectThemeFrame) {
      return;
    }
    let active = true;
    const disconnect = connectThemeFrame(frame, (theme) => {
      if (active) {
        setNative({ connect: connectThemeFrame, frame, theme });
      }
    });
    return () => {
      active = false;
      disconnect();
    };
  }, [connectThemeFrame, frame]);

  const nativeTheme =
    native && native.connect === connectThemeFrame && native.frame === frame
      ? native.theme
      : undefined;
  return nativeTheme ?? system;
};

export const StudioThemeProvider = ({
  children,
  theme,
}: {
  children: ReactNode;
  theme: StudioTheme;
}) => <StudioThemeContext.Provider value={theme}>{children}</StudioThemeContext.Provider>;

export const useStudioTheme = (): StudioTheme => useContext(StudioThemeContext);
