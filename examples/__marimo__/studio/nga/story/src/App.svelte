<script lang="ts">
  import ArtworkCard from "./components/ArtworkCard.svelte";
  import { observeMarimoValue } from "./lib/marimo-value.ts";
  import type { Artwork } from "./model.ts";

  const metrics = [
    { label: "Drawings, 1935–1942", selector: "studio_summary.index_drawings" },
    { label: "Artists represented", selector: "studio_summary.index_artists" },
    { label: "Public-domain artworks", selector: "studio_summary.public_domain" },
  ];

  const chapters = [
    {
      number: "01",
      label: "The signal",
      title: "A spike appears in the public-domain timeline.",
      name: "notable_period_chart",
    },
    {
      number: "02",
      label: "The scale",
      title: "Thousands of drawings connect more than a thousand artists.",
      name: "index_drawing_count",
    },
    {
      number: "03",
      label: "The archive",
      title: "The works resolve into a shared visual record.",
      name: "index_gallery",
    },
  ];

  let artworks = $state<Artwork[]>([]);
  let artworkError = $state(false);
  let visibleCount = $state(8);
  let visibleArtworks = $derived(artworks.slice(0, visibleCount));
</script>

<span
  hidden
  mo-value="studio_index_artworks"
  use:observeMarimoValue={{
    selector: "studio_index_artworks",
    onValue: (value) => {
      artworks = value as Artwork[];
      artworkError = false;
    },
    onError: () => {
      artworkError = true;
    },
  }}
></span>

<div class="story-shell">
  <nav class="view-nav" aria-label="NGA views">
    <a href="../overview/">Overview</a>
    <a href="../gallery/">Gallery</a>
    <a href="../story/" aria-current="page">Story</a>
  </nav>

  <header class="story-header">
    <p class="eyebrow">Svelte view · Collection story</p>
    <h1>The archive hidden inside a spike</h1>
    <p class="standfirst">
      NGA collection data points to a Depression-era federal art program that
      documented American material culture in watercolor.
    </p>
  </header>

  <section class="metric-row" aria-label="Index of American Design measures">
    {#each metrics as metric}
      <article>
        <span>{metric.label}</span>
        <strong mo-value={metric.selector}></strong>
      </article>
    {/each}
  </section>

  {#each chapters as chapter}
    <section class="chapter" aria-labelledby={`chapter-${chapter.number}`}>
      <div class="chapter-copy">
        <span class="chapter-number">{chapter.number}</span>
        <p class="eyebrow">{chapter.label}</p>
        <h2 id={`chapter-${chapter.number}`}>{chapter.title}</h2>
      </div>
      <div class="chapter-result">
        <marimo-cell name={chapter.name} data-marimo-allow="*"></marimo-cell>
      </div>
    </section>
  {/each}

  <section class="artwork-section" aria-labelledby="artwork-heading">
    <div class="artwork-heading">
      <div>
        <p class="eyebrow">Selected records</p>
        <h2 id="artwork-heading">Objects from the Index period</h2>
      </div>
      <label>
        Works shown
        <select bind:value={visibleCount}>
          <option value={4}>4</option>
          <option value={8}>8</option>
          <option value={12}>12</option>
        </select>
      </label>
    </div>

    {#if artworkError}
      <p class="artwork-status">Artwork records are unavailable.</p>
    {:else if visibleArtworks.length === 0}
      <p class="artwork-status">Loading artwork records…</p>
    {:else}
      <div class="artwork-grid">
        {#each visibleArtworks as artwork (artwork.objectid)}
          <ArtworkCard {artwork} />
        {/each}
      </div>
    {/if}
  </section>

  <section class="finding" aria-label="Notebook conclusion">
    <marimo-cell name="index_finding"></marimo-cell>
  </section>

  <footer>
    <p>One analytical notebook · Three authored views</p>
    <a href="../overview/">Return to the collection overview →</a>
  </footer>
</div>
