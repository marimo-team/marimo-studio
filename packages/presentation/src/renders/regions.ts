import type { RenderRegion } from "@marimo-studio/protocol/render";

import type { RenderRecord } from "./view.ts";

/** The named slot of a render host's shadow root that shows region layers. */
export const REGION_SLOT = "marimo-regions";
// Read sources sit in a slot the shadow root never renders.
const SOURCE_SLOT = "marimo-region-sources";
const REGION_ATTRIBUTE = "data-marimo-studio-region";
const LAYER_ATTRIBUTE = "data-marimo-studio-regions";
const MEDIA_SELECTOR = "img, video, [data-marimo-render-file]";
const VIDEO_EVENTS = ["timeupdate", "seeked", "play", "pause", "loadedmetadata", "emptied"];
// Lens bounds the notebook sources of one target.
const MAX_SOURCES = 64;
let sourceIds = 0;

/** An element on screen that shows one bundle file, such as a PDF page or a video. */
export interface RenderSurface {
  readonly element: HTMLElement;
  readonly file: string;
  readonly page: number | null;
  /** The file a video shows as its poster before it plays. */
  readonly poster?: string;
}

/**
 * The notebook cell that produced one read, the value the read narrows to,
 * and the name the notebook shows for the cell.
 */
export interface ReadProducer {
  readonly cellId: string;
  readonly selector: string | null;
  readonly label?: string;
}

/** Return the producer of one read the render names, or nothing when it has none. */
export type ProducerOf = (read: string) => ReadProducer | undefined;

interface Layer {
  readonly surface: RenderSurface;
  readonly element: HTMLElement;
  readonly regions: readonly { readonly region: RenderRegion; readonly element: HTMLElement }[];
  readonly release: () => void;
}

const area = ({ rect }: RenderRegion) => rect.width * rect.height;

const seconds = (value: number) => `${Number(value.toFixed(2))} s`;

const where = (region: RenderRegion): string => {
  const file = region.file.split("/").at(-1) ?? region.file;
  if (region.page !== null) {
    return `${file}, page ${region.page}`;
  }
  if (region.start !== null || region.end !== null) {
    const end = region.end === null ? "end" : seconds(region.end);
    return `${file}, ${seconds(region.start ?? 0)} to ${end}`;
  }
  return file;
};

const sourceElement = (producer: ReadProducer, slot?: string): HTMLElement => {
  const element = document.createElement("span");
  element.hidden = true;
  element.dataset.marimoLensCellId = producer.cellId;
  if (producer.selector !== null) {
    element.dataset.marimoLensSelector = producer.selector;
  }
  if (slot) {
    element.slot = slot;
  }
  return element;
};

const pixels = (value: string) => Number.parseFloat(value) || 0;

/**
 * Return the viewport box of the picture an element shows: its content box,
 * narrowed by `object-fit` to the image or video frame inside it.
 */
const pictureBox = (element: HTMLElement): DOMRect => {
  const rect = element.getBoundingClientRect();
  const style = getComputedStyle(element);
  const left = rect.left + pixels(style.borderLeftWidth) + pixels(style.paddingLeft);
  const top = rect.top + pixels(style.borderTopWidth) + pixels(style.paddingTop);
  const width =
    rect.width -
    pixels(style.borderLeftWidth) -
    pixels(style.borderRightWidth) -
    pixels(style.paddingLeft) -
    pixels(style.paddingRight);
  const height =
    rect.height -
    pixels(style.borderTopWidth) -
    pixels(style.borderBottomWidth) -
    pixels(style.paddingTop) -
    pixels(style.paddingBottom);
  let natural: [number, number] | undefined;
  if (element instanceof HTMLVideoElement && element.videoWidth > 0) {
    natural = [element.videoWidth, element.videoHeight];
  } else if (element instanceof HTMLImageElement && element.naturalWidth > 0) {
    natural = [element.naturalWidth, element.naturalHeight];
  }
  if (!natural || style.objectFit === "fill" || width <= 0 || height <= 0) {
    return new DOMRect(left, top, width, height);
  }
  const [naturalWidth, naturalHeight] = natural;
  const fit = style.objectFit === "cover" ? Math.max : Math.min;
  let scale = fit(width / naturalWidth, height / naturalHeight);
  if (style.objectFit === "none") {
    scale = 1;
  } else if (style.objectFit === "scale-down") {
    scale = Math.min(scale, 1);
  }
  const shown = [naturalWidth * scale, naturalHeight * scale] as const;
  return new DOMRect(
    left + (width - shown[0]) / 2,
    top + (height - shown[1]) / 2,
    shown[0],
    shown[1],
  );
};

const absolute = (url: string) => new URL(url, document.baseURI).href;

/**
 * Return the elements of a page's own markup that show bundle files: images
 * and videos whose source is a bundle file, and elements that name a file in
 * `data-marimo-render-file`, such as a canvas the page draws a PDF page on.
 */
export const markupSurfaces = (
  host: HTMLElement,
  record: RenderRecord,
): readonly RenderSurface[] => {
  const files = new Map(record.files.map((file) => [absolute(file.url), file.path]));
  const pdfs = new Set(
    record.files.filter((file) => file.mediaType === "application/pdf").map((file) => file.path),
  );
  const file = (url: string) => (url ? files.get(absolute(url)) : undefined);
  const surfaces: RenderSurface[] = [];
  for (const element of host.querySelectorAll<HTMLElement>(MEDIA_SELECTOR)) {
    if (element.closest(`[${LAYER_ATTRIBUTE}]`)) {
      continue;
    }
    const named = element.dataset.marimoRenderFile;
    if (named !== undefined) {
      const page = Number(element.dataset.marimoRenderPage);
      // An element shows one page of a PDF, so it names the page.
      if (Number.isInteger(page) && page > 0) {
        surfaces.push({ element, file: named, page });
      } else if (!pdfs.has(named)) {
        surfaces.push({ element, file: named, page: null });
      }
    } else if (element instanceof HTMLVideoElement) {
      const shown = file(element.currentSrc || element.src);
      if (shown) {
        surfaces.push({ element, file: shown, page: null, poster: file(element.poster) });
      }
    } else if (element instanceof HTMLImageElement) {
      const shown = file(element.currentSrc || element.src);
      if (shown) {
        surfaces.push({ element, file: shown, page: null });
      }
    }
  }
  return surfaces;
};

/**
 * Publish the regions of a render's bundle as Lens selection targets.
 *
 * Lens selects targets in the page's light DOM, so each surface gets a layer
 * element in the host's light DOM, which the regions slot shows above the
 * presentation. A layer covers the picture of its surface, and each region is
 * a box in it that carries its reads as notebook sources. The host itself
 * carries every read of the render, so selecting it traces the whole file.
 * Regions ignore the pointer until Lens arms a selection, so readers keep
 * scrolling, selecting text, and using video controls.
 */
export class RenderRegions {
  private layers: Layer[] = [];
  private sources: HTMLElement[] = [];
  private readonly created = new WeakSet<Node>();
  private readonly elements = new WeakMap<HTMLElement, number>();
  private nextElement = 0;
  private shown?: string;
  private published = new Map<string, string>();
  private resize?: ResizeObserver;
  private frame = 0;

  constructor(
    private readonly host: HTMLElement,
    private readonly anchor: HTMLElement,
  ) {}

  /**
   * Show the regions of `record` over `surfaces`. `reads` lists every target
   * the render reads, and `producerOf` names the producer of each read.
   */
  show(
    record: RenderRecord,
    surfaces: readonly RenderSurface[],
    reads: readonly string[],
    producerOf: ProducerOf,
  ): void {
    // A runtime configuration or markup change that leaves the bundle, its
    // surfaces, and its producers as they were keeps the targets, so a
    // selection or hover in progress stays attached.
    const shown = this.signature(record, surfaces, reads, producerOf);
    if (shown === this.shown && this.layers.every(({ element }) => element.isConnected)) {
      this.place();
      return;
    }
    this.clear();
    this.shown = shown;
    this.describeHost(record, reads, producerOf);
    if ("ResizeObserver" in globalThis) {
      this.resize = new ResizeObserver(() => this.schedule());
      this.resize.observe(this.host);
      surfaces.forEach((surface) => this.resize?.observe(surface.element));
    }
    for (const surface of surfaces) {
      const files = new Set([surface.file, ...(surface.poster ? [surface.poster] : [])]);
      const regions = record.regions
        .filter(
          (region) =>
            files.has(region.file) && (surface.page === null || region.page === surface.page),
        )
        .toSorted((left, right) => area(right) - area(left));
      if (regions.length === 0) {
        continue;
      }
      const element = document.createElement("div");
      this.created.add(element);
      element.setAttribute(LAYER_ATTRIBUTE, "");
      element.slot = REGION_SLOT;
      element.setAttribute("aria-hidden", "true");
      Object.assign(element.style, { position: "absolute", pointerEvents: "none" });
      const shown = regions.map((region) => {
        const box = this.regionElement(region, producerOf);
        element.append(box);
        return { region, element: box };
      });
      this.host.append(element);
      const layer: Layer = {
        surface,
        element,
        regions: shown,
        release: this.follow(surface),
      };
      this.layers.push(layer);
    }
    this.place();
  }

  /** Return whether a DOM change only concerns this host's layers and sources. */
  owns(record: MutationRecord): boolean {
    const nodes = [...record.addedNodes, ...record.removedNodes];
    if (record.type === "childList" && record.target === this.host) {
      return nodes.length > 0 && nodes.every((node) => this.created.has(node));
    }
    for (
      let node: Node | null = record.target;
      node && node !== this.host;
      node = node.parentNode
    ) {
      if (this.created.has(node)) {
        return true;
      }
    }
    return false;
  }

  /** Measure every layer against its surface again. */
  place(): void {
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    const origin = this.anchor.getBoundingClientRect();
    for (const layer of this.layers) {
      const picture = pictureBox(layer.surface.element);
      Object.assign(layer.element.style, {
        left: `${picture.left - origin.left}px`,
        top: `${picture.top - origin.top}px`,
        width: `${picture.width}px`,
        height: `${picture.height}px`,
      });
      this.showTime(layer);
    }
  }

  private signature(
    record: RenderRecord,
    surfaces: readonly RenderSurface[],
    reads: readonly string[],
    producerOf: ProducerOf,
  ): string {
    const identity = (element: HTMLElement) => {
      let id = this.elements.get(element);
      if (id === undefined) {
        id = this.nextElement += 1;
        this.elements.set(element, id);
      }
      return id;
    };
    const named = new Set([...reads, ...record.regions.flatMap((region) => region.reads)]);
    return JSON.stringify([
      record.bundle,
      surfaces.map((surface) => [
        identity(surface.element),
        surface.file,
        surface.page,
        surface.poster,
      ]),
      [...named].map((read) => [read, producerOf(read) ?? null]),
    ]);
  }

  clear(): void {
    this.shown = undefined;
    cancelAnimationFrame(this.frame);
    this.frame = 0;
    this.resize?.disconnect();
    this.resize = undefined;
    for (const layer of this.layers) {
      layer.release();
      layer.element.remove();
    }
    this.layers = [];
    this.sources.forEach((element) => element.remove());
    this.sources = [];
    for (const [attribute, value] of this.published) {
      if (this.host.getAttribute(attribute) === value) {
        this.host.removeAttribute(attribute);
      }
    }
    this.published.clear();
  }

  private schedule(): void {
    if (this.frame === 0) {
      this.frame = requestAnimationFrame(() => this.place());
    }
  }

  /**
   * Trace the whole file to every read of the render. The host names its
   * sources by ID, which Lens takes as its complete input set, so the sources
   * of the regions inside it never add up past what one target may carry.
   */
  private describeHost(
    record: RenderRecord,
    reads: readonly string[],
    producerOf: ProducerOf,
  ): void {
    const seen = new Set<string>();
    for (const read of reads) {
      const found = producerOf(read);
      const key = found && JSON.stringify([found.cellId, found.selector]);
      if (found && key && !seen.has(key) && this.sources.length < MAX_SOURCES) {
        seen.add(key);
        const element = sourceElement(found, SOURCE_SLOT);
        element.id = `marimo-render-source-${(sourceIds += 1)}`;
        this.created.add(element);
        this.host.append(element);
        this.sources.push(element);
      }
    }
    const main = record.main.split("/").at(-1) ?? record.main;
    for (const [attribute, value] of [
      ["data-marimo-lens-label", record.render],
      ["data-marimo-lens-detail", `Rendered ${main}`],
      ["data-marimo-lens-render-source", JSON.stringify({ path: record.render })],
      ["data-marimo-lens-context", ""],
      ...(this.sources.length > 0
        ? ([["data-marimo-lens-inputs", this.sources.map(({ id }) => id).join(" ")]] as const)
        : []),
    ] as const) {
      if (!this.host.hasAttribute(attribute)) {
        this.host.setAttribute(attribute, value);
        this.published.set(attribute, value);
      }
    }
  }

  private regionElement(region: RenderRegion, producerOf: ProducerOf): HTMLElement {
    const element = document.createElement("div");
    element.setAttribute(REGION_ATTRIBUTE, "");
    element.setAttribute("data-marimo-lens-target", "");
    const { x, y, width, height } = region.rect;
    Object.assign(element.style, {
      position: "absolute",
      left: `${x * 100}%`,
      top: `${y * 100}%`,
      width: `${width * 100}%`,
      height: `${height * 100}%`,
      pointerEvents: "none",
    });
    const found = region.reads.flatMap((read) => producerOf(read) ?? []);
    const producers = [...new Set(found.flatMap((item) => item.label ?? []))];
    element.dataset.marimoLensLabel = region.label ?? region.reads[0] ?? "Part of the render";
    element.dataset.marimoLensDetail = [
      producers.length > 0 ? `From ${producers.join(", ")}` : undefined,
      where(region),
    ]
      .filter(Boolean)
      .join(" · ");
    if (region.source) {
      element.dataset.marimoLensRenderSource = JSON.stringify(region.source);
    }
    // Lens records the file part a target shows, its page or its time span, as
    // structured evidence beside the readable detail. JSON leaves out the
    // undefined fields of a part without a page or time.
    element.dataset.marimoLensMedia = JSON.stringify({
      path: region.file,
      page: region.page ?? undefined,
      start: region.start ?? undefined,
      end: region.end ?? undefined,
    });
    element.append(...found.map((item) => sourceElement(item)));
    return element;
  }

  /** Keep a surface's layer on its picture, and a video's regions on its frame. */
  private follow(surface: RenderSurface): () => void {
    const element = surface.element;
    if (!(element instanceof HTMLVideoElement)) {
      return () => {};
    }
    let callback = 0;
    const update = () => {
      const layer = this.layers.find((item) => item.surface === surface);
      if (layer) {
        this.showTime(layer);
      }
    };
    // Frame callbacks keep regions on moving shapes while the video plays.
    // One chain runs at a time, and it ends at the first frame after a pause.
    const frames = () => {
      callback = 0;
      update();
      if (!element.paused && "requestVideoFrameCallback" in element) {
        callback = element.requestVideoFrameCallback(frames);
      }
    };
    const playing = () => {
      if (callback === 0) {
        frames();
      }
    };
    const changed = () => {
      update();
      this.schedule();
    };
    VIDEO_EVENTS.forEach((type) => element.addEventListener(type, changed));
    element.addEventListener("play", playing);
    return () => {
      VIDEO_EVENTS.forEach((type) => element.removeEventListener(type, changed));
      element.removeEventListener("play", playing);
      if (callback && "cancelVideoFrameCallback" in element) {
        element.cancelVideoFrameCallback(callback);
      }
    };
  }

  /** Show the regions of the file and moment a surface shows. */
  private showTime(layer: Layer): void {
    const { surface } = layer;
    const video = surface.element instanceof HTMLVideoElement ? surface.element : undefined;
    // Before a video plays, it shows its poster.
    const posterShown =
      video !== undefined &&
      surface.poster !== undefined &&
      video.played.length === 0 &&
      video.currentTime === 0;
    const file = posterShown ? surface.poster : surface.file;
    // A finished video shows its last frame at its duration.
    const time = Math.min(video?.currentTime ?? 0, (video?.duration || Infinity) - 1e-3);
    for (const { region, element } of layer.regions) {
      const shown =
        region.file === file &&
        (file !== surface.file ||
          video === undefined ||
          ((region.start ?? 0) <= time && (region.end === null || time < region.end)));
      element.style.display = shown ? "" : "none";
    }
  }
}
