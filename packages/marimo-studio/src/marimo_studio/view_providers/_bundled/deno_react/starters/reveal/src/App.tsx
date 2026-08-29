/// <reference path="./marimo-studio.d.ts" />

import { Deck, Fragment, Slide } from "@revealjs/react";
import "reveal.js/reveal.css";

const NOTEBOOK_LABEL = __NOTEBOOK_NAME_JSON__;
const VIEW_HEADING = __VIEW_HEADING_JSON__;

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
      <h1>{VIEW_HEADING}</h1>
      <p className="deck-lede">
        Shape the presentation around the audience, the evidence, and the
        decision it supports.
      </p>
    </Slide>

    <Slide>
      <p className="deck-kicker">Notebook evidence</p>
      <h2>Place results in the argument</h2>
      <div className="result-frame">
        <p>Select a notebook output, then mount it inside this slide.</p>
        <code>{'<marimo-output value="summary" />'}</code>
      </div>
    </Slide>

    <Slide>
      <p className="deck-kicker">Sequence</p>
      <h2>Build one claim at a time</h2>
      <ol className="claim-list">
        <Fragment as="li">State the question.</Fragment>
        <Fragment as="li">Show the evidence.</Fragment>
        <Fragment as="li">Name the consequence.</Fragment>
      </ol>
    </Slide>
  </Deck>
);
