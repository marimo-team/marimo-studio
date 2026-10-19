import type { Starter } from "@marimo-studio/protocol/provider-catalog";

import { FileCodeIcon, FileTextIcon, FolderIcon } from "lucide-react";
import { useState } from "react";

const PROSE_DOCUMENT = /\.(?:md|qmd|tex|typ|txt)$/i;
const POSTER_DOCUMENTS = 6;

const useLoadedImage = (url: string | undefined) => {
  const [failed, setFailed] = useState<string>();
  return {
    url: url !== undefined && url !== failed ? url : undefined,
    onError: () => setFailed(url),
  };
};

/** Lay out the documents a starter creates when it ships no preview image. */
const StarterPoster = ({ starter, folder }: { starter: Starter; folder: string }) => {
  const shown = starter.documents.slice(0, POSTER_DOCUMENTS);
  const hidden = starter.documents.length - shown.length;
  return (
    <div className="studio-starter-poster">
      <div className="studio-starter-poster-window">
        <div className="studio-starter-poster-path">
          <FolderIcon aria-hidden="true" />
          <span>{folder}</span>
        </div>
        <ul>
          {shown.map((document) => {
            const Icon = PROSE_DOCUMENT.test(document) ? FileTextIcon : FileCodeIcon;
            return (
              <li key={document}>
                <Icon aria-hidden="true" />
                <span>{document}</span>
              </li>
            );
          })}
          {hidden > 0 ? <li className="studio-starter-poster-more">{hidden} more</li> : null}
        </ul>
      </div>
    </div>
  );
};

export const StarterPreview = ({
  starter,
  url,
  folder,
}: {
  starter: Starter;
  url: string | undefined;
  folder: string;
}) => {
  const image = useLoadedImage(url);
  return (
    <figure className="studio-starter-preview" data-available={starter.availability.available}>
      {image.url ? (
        <img
          key={image.url}
          src={image.url}
          alt={`Preview of a view created from ${starter.title}`}
          decoding="async"
          onError={image.onError}
        />
      ) : (
        <StarterPoster starter={starter} folder={folder} />
      )}
    </figure>
  );
};

/**
 * Show a starter's technology mark, painted as a mask so it follows the
 * theme. A starter without a mark shows its preview, then its initial.
 */
export const StarterMark = ({ starter, url }: { starter: Starter; url: string | undefined }) => {
  const image = useLoadedImage(starter.icon ? undefined : url);
  if (starter.icon) {
    const mask = `url("data:image/svg+xml,${encodeURIComponent(starter.icon)}")`;
    return (
      <span className="studio-starter-mark" data-kind="icon" aria-hidden="true">
        <span style={{ maskImage: mask, WebkitMaskImage: mask }} />
      </span>
    );
  }
  return (
    <span
      className="studio-starter-mark"
      data-kind={image.url ? "preview" : "initial"}
      aria-hidden="true"
    >
      {image.url ? (
        <img src={image.url} alt="" decoding="async" loading="lazy" onError={image.onError} />
      ) : (
        <span>{starter.title.charAt(0)}</span>
      )}
    </span>
  );
};
