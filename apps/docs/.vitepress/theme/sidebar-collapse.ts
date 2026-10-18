import { useLayout } from "vitepress/theme";
import {
  inject,
  onMounted,
  provide,
  ref,
  type ComputedRef,
  type InjectionKey,
  type Ref,
} from "vue";

import { sidebarCollapsedClass, sidebarStorageKey } from "../sidebar-state.ts";

const collapsedKey: InjectionKey<Readonly<Ref<boolean>>> = Symbol("studio-sidebar-collapsed");

interface SidebarCollapse {
  collapsed: Readonly<Ref<boolean>>;
  /** The page shows sidebar items, so the toggle has something to hide. */
  available: ComputedRef<boolean>;
  toggle: () => void;
}

/**
 * Lets a reader hide the desktop sidebar, the way the default theme toggles
 * dark mode: a class on `<html>` that a head script restores before the first
 * paint. CSS in custom.css reads the class. Call it once, from the layout,
 * which provides the state to `useSidebarCollapsed()`.
 */
export const useSidebarCollapse = (): SidebarCollapse => {
  const { hasSidebar } = useLayout();
  const collapsed = ref(false);
  provide(collapsedKey, collapsed);

  onMounted(() => {
    collapsed.value = document.documentElement.classList.contains(sidebarCollapsedClass);
  });

  const toggle = (): void => {
    collapsed.value = !collapsed.value;
    document.documentElement.classList.toggle(sidebarCollapsedClass, collapsed.value);
    try {
      localStorage.setItem(sidebarStorageKey, collapsed.value ? "collapsed" : "open");
    } catch {
      // Storage can be unavailable, such as in private browsing. The choice
      // still holds until the next full page load.
    }
  };

  return { collapsed, available: hasSidebar, toggle };
};

/** Whether the reader has hidden the sidebar. `false` outside the layout. */
export const useSidebarCollapsed = (): Readonly<Ref<boolean>> =>
  inject(collapsedKey, () => ref(false), true);
