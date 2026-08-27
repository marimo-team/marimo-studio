// @deno-types="npm:@types/react@19.2.10"
import React from "react";

export type Artwork = {
  objectid: number;
  title: string | null;
  year: number | null;
  name: string | null;
  type: string | null;
  thumburl: string;
  public: boolean;
};

type ArtworkCardProps = {
  artwork: Artwork;
};

export const ArtworkCard = ({ artwork }: ArtworkCardProps) => (
  <a
    className="artwork-card"
    href={`https://www.nga.gov/collection/art-object-page.${
      encodeURIComponent(artwork.objectid)
    }.html`}
    target="_blank"
    rel="noreferrer"
  >
    <div className="artwork-image-frame">
      <img
        src={artwork.thumburl}
        alt={artwork.title ?? "Untitled artwork"}
        loading="lazy"
        decoding="async"
      />
      <span className="rights-mark" data-public={artwork.public}>
        {artwork.public ? "CC0" : "Rights managed"}
      </span>
    </div>
    <div className="artwork-copy">
      <h2>{artwork.title ?? "Untitled"}</h2>
      <p>{artwork.name ?? "Artist not recorded"}</p>
      <p className="artwork-meta">
        {artwork.year ?? "Date unknown"} · {artwork.type ?? "Unclassified"}
      </p>
    </div>
  </a>
);
