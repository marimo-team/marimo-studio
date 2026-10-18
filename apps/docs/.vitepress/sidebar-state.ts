// Shared by the head script in config.mts and the theme. Keep this module free
// of browser and theme imports, because the config loads it in Node.

/** localStorage key that remembers a hidden sidebar. */
export const sidebarStorageKey = "studio-sidebar";

/** Class on `<html>` while the reader has hidden the sidebar. */
export const sidebarCollapsedClass = "studio-sidebar-collapsed";
