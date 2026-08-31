/// <reference path="./marimo-studio.d.ts" />

import { Deck, Slide } from "@revealjs/react";
import "reveal.js/reveal.css";

const NOTEBOOK_LABEL = __NOTEBOOK_NAME_JSON__;
const NOTEBOOK_TITLE = __NOTEBOOK_TITLE_JSON__;

export const App = () => (
  <Deck
    className="studio-deck"
    config={{
      controls: true,
      progress: true,
      scrollActivationWidth: 0,
      transition: "slide",
    }}
  >
    <Slide>
      <p className="deck-kicker">{NOTEBOOK_LABEL}</p>
      <h1>{NOTEBOOK_TITLE}</h1>
    </Slide>
    __NOTEBOOK_SLIDE_HOSTS_TSX__
  </Deck>
);
