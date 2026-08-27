<script lang="ts">
  import type { Artwork } from "../model.ts";

  let { artwork }: { artwork: Artwork } = $props();
</script>

<a
  class="artwork"
  href={`https://www.nga.gov/collection/art-object-page.${encodeURIComponent(artwork.objectid)}.html`}
  target="_blank"
  rel="noreferrer"
>
  <img
    src={artwork.thumburl}
    alt={artwork.title ?? "Untitled artwork"}
    loading="lazy"
    decoding="async"
  />
  <span>{artwork.year ?? "Date unknown"}</span>
  <strong>{artwork.title ?? "Untitled"}</strong>
  <small>{artwork.name ?? "Artist not recorded"}</small>
</a>

<style>
  .artwork {
    color: inherit;
    display: grid;
    grid-template-rows: auto auto auto 1fr;
    min-width: 0;
    text-decoration: none;
  }

  img {
    aspect-ratio: 4 / 5;
    display: block;
    filter: saturate(0.72) contrast(1.03);
    margin-bottom: 0.8rem;
    object-fit: cover;
    width: 100%;
  }

  span {
    color: var(--primary);
    font-size: 0.64rem;
    font-weight: 800;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  strong {
    display: -webkit-box;
    font-family: var(--heading-font);
    font-size: 1rem;
    font-weight: 600;
    line-height: 1.3;
    margin-top: 0.35rem;
    overflow: hidden;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
  }

  small {
    color: var(--muted-foreground);
    font-size: 0.7rem;
    line-height: 1.35;
    margin-top: 0.45rem;
  }

  .artwork:focus-visible {
    outline: 2px solid var(--ring);
    outline-offset: 3px;
  }
</style>
