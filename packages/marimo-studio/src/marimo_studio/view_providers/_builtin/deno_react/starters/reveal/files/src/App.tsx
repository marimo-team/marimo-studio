/// <reference path="./marimo-studio.d.ts" />

import { Deck, Slide } from "@revealjs/react";
import { useEffect, useRef } from "react";
import type { RevealApi } from "reveal.js";
import "reveal.js/reveal.css";

const VIEW_TITLE = STARTER_VIEW_TITLE_JSON;
const NOTEBOOK_TITLE = STARTER_NOTEBOOK_TITLE_JSON;

const keyboardCondition = (event: KeyboardEvent) =>
  !event.composedPath().some(
    (target) =>
      target instanceof Element && target.matches("marimo-cell, marimo-output"),
  );

/** Center slides again once projected notebook content has its final size. */
const useSettledLayout = () => {
  const deck = useRef<RevealApi | null>(null);
  useEffect(() => {
    const layout = () => deck.current?.layout();
    document.addEventListener("marimo-studio:idle", layout);
    return () => document.removeEventListener("marimo-studio:idle", layout);
  }, []);
  return deck;
};

export const App = () => {
  const deck = useSettledLayout();
  return (
    <Deck
      className="studio-deck"
      deckRef={deck}
      config={{
        controls: true,
        keyboardCondition,
        progress: true,
        scrollActivationWidth: 0,
        transition: "slide",
      }}
    >
      <Slide>
        <p className="deck-kicker">{VIEW_TITLE}</p>
        <h1>{NOTEBOOK_TITLE}</h1>
      </Slide>
      STARTER_NOTEBOOK_SLIDE_HOSTS_TSX
    </Deck>
  );
};
