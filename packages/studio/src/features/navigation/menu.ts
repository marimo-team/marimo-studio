export const closeParentMenu = (target: HTMLElement): void => {
  target.closest("details")?.removeAttribute("open");
};
