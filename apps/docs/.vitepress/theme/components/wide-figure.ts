import { nextTick, onBeforeUnmount, onMounted, ref, watch, type Ref } from "vue";

import { useSidebarCollapsed } from "../sidebar-collapse.ts";

const gutter = 24;

const visibleRect = (selector: string): DOMRect | undefined => {
  const rect = document.querySelector(selector)?.getBoundingClientRect();
  return rect && rect.width > 0 ? rect : undefined;
};

/**
 * Lets a figure grow past the reading column into the free space beside it,
 * up to `maxWidth`. The figure stops short of the sidebar and the outline, so
 * it widens when the sidebar collapses or the window grows, and prose keeps
 * its reading width.
 */
export const useWideFigure = (
  figure: Ref<HTMLElement | undefined>,
  maxWidth = 1120,
): Ref<Record<string, string>> => {
  const style = ref<Record<string, string>>({});
  let frame = 0;

  const measure = (): void => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => {
      const column = figure.value?.parentElement?.getBoundingClientRect();
      if (!column) {
        return;
      }
      const left = visibleRect(".VPSidebar")?.right ?? 0;
      const right = visibleRect(".VPDoc .aside")?.left ?? document.documentElement.clientWidth;
      const roomLeft = Math.max(0, column.left - left - gutter);
      const roomRight = Math.max(0, right - column.right - gutter);
      // Grow evenly while both sides have room, then use what one side has left.
      let rest = Math.max(0, maxWidth - column.width);
      let growLeft = Math.min(roomLeft, rest / 2);
      let growRight = Math.min(roomRight, rest / 2);
      rest -= growLeft + growRight;
      const moreLeft = Math.min(roomLeft - growLeft, rest);
      growLeft += moreLeft;
      growRight += Math.min(roomRight - growRight, rest - moreLeft);
      style.value =
        growLeft + growRight < 8
          ? {}
          : {
              marginLeft: `${-Math.floor(growLeft)}px`,
              marginRight: `${-Math.floor(growRight)}px`,
            };
    });
  };

  let resize: ResizeObserver | undefined;
  // Showing or hiding the sidebar moves the column without resizing it.
  watch(useSidebarCollapsed(), () => nextTick(measure));
  onMounted(() => {
    measure();
    window.addEventListener("resize", measure, { passive: true });
    resize = new ResizeObserver(measure);
    if (figure.value?.parentElement) {
      resize.observe(figure.value.parentElement);
    }
  });
  onBeforeUnmount(() => {
    cancelAnimationFrame(frame);
    window.removeEventListener("resize", measure);
    resize?.disconnect();
  });

  return style;
};
