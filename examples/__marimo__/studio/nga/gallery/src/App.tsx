/// <reference path="./marimo-studio.d.ts" />

// @deno-types="npm:@types/react@19.2.10"
import React, { useMemo, useState } from "react";

import { type Artwork, ArtworkCard } from "./components/ArtworkCard.tsx";
import { useMarimoValue } from "./lib/use-marimo-value.ts";

const CHARTS = [
  { label: "Artwork types", name: "classification_bar_chart" },
  { label: "Rights distribution", name: "classification_waffle_chart" },
  { label: "Collection timeline", name: "collection_timeline_chart" },
] as const;

const METRICS = [
  { label: "Artworks", selector: "studio_summary.artworks" },
  { label: "Artists", selector: "studio_summary.artists" },
  { label: "Public domain", selector: "studio_summary.public_domain" },
] as const;

export const App = () => {
  const { error, hostRef, value: artworks } = useMarimoValue<Artwork[]>(
    "studio_artworks",
  );
  const [query, setQuery] = useState("");
  const [type, setType] = useState("All types");
  const [publicOnly, setPublicOnly] = useState(false);
  const [chartIndex, setChartIndex] = useState(0);

  const types = useMemo(
    () => [
      "All types",
      ...new Set(
        (artworks ?? []).map((artwork) => artwork.type).filter((
          item,
        ): item is string => item !== null),
      ),
    ],
    [artworks],
  );

  const filteredArtworks = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    return (artworks ?? []).filter((artwork) => {
      if (publicOnly && !artwork.public) {
        return false;
      }
      if (type !== "All types" && artwork.type !== type) {
        return false;
      }
      if (normalizedQuery.length === 0) {
        return true;
      }
      return [artwork.title, artwork.name]
        .filter((item): item is string => item !== null)
        .some((item) => item.toLocaleLowerCase().includes(normalizedQuery));
    });
  }, [artworks, publicOnly, query, type]);

  const activeChart = CHARTS[chartIndex];
  const resultLabel = error
    ? "Artwork data unavailable"
    : artworks === undefined
    ? "Loading artwork data"
    : `${filteredArtworks.length} ${filteredArtworks.length === 1 ? "work" : "works"} shown`;

  return (
    <div className="gallery-shell">
      <span ref={hostRef} hidden mo-value="studio_artworks" />

      <nav className="view-nav" aria-label="NGA views">
        <a href="../overview/">Overview</a>
        <a href="../gallery/" aria-current="page">Gallery</a>
        <a href="../story/">Story</a>
      </nav>

      <header className="gallery-header">
        <div>
          <p className="eyebrow">React view · Collection browser</p>
          <h1>Seventy-two ways into the collection</h1>
        </div>
        <p>
          Filter a compact image set in the browser, then change the analytical
          projection without leaving the page.
        </p>
      </header>

      <section className="metric-row" aria-label="Collection measures">
        {METRICS.map((metric) => (
          <article key={metric.selector}>
            <span>{metric.label}</span>
            <strong mo-value={metric.selector} />
          </article>
        ))}
      </section>

      <section className="gallery-workspace">
        <aside className="filter-panel" aria-label="Artwork filters">
          <div>
            <p className="eyebrow">Filter the tray</p>
            <label htmlFor="artwork-search">Title or artist</label>
            <input
              id="artwork-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
              placeholder="Search artworks"
            />
          </div>

          <div>
            <label htmlFor="artwork-type">Artwork type</label>
            <select
              id="artwork-type"
              value={type}
              onChange={(event) => setType(event.currentTarget.value)}
            >
              {types.map((option) => <option key={option}>{option}</option>)}
            </select>
          </div>

          <label className="check-row">
            <input
              type="checkbox"
              checked={publicOnly}
              onChange={(event) => setPublicOnly(event.currentTarget.checked)}
            />
            Public-domain images
          </label>

          <p className="result-count" aria-live="polite">
            {resultLabel}
          </p>
        </aside>

        <div
          className="artwork-grid"
          aria-busy={artworks === undefined && !error}
        >
          {filteredArtworks.map((artwork) => (
            <ArtworkCard key={artwork.objectid} artwork={artwork} />
          ))}
        </div>
      </section>

      <section className="chart-workspace" aria-labelledby="chart-heading">
        <div className="chart-controls">
          <div>
            <p className="eyebrow">Reactive context</p>
            <h2 id="chart-heading">{activeChart.label}</h2>
          </div>
          <div
            className="chart-tabs"
            role="group"
            aria-label="Choose a chart"
          >
            {CHARTS.map((chart, index) => (
              <button
                key={chart.name}
                type="button"
                aria-pressed={index === chartIndex}
                onClick={() => setChartIndex(index)}
              >
                {chart.label}
              </button>
            ))}
          </div>
        </div>
        <marimo-cell name={activeChart.name} data-marimo-allow="*" />
      </section>
    </div>
  );
};
