/// <reference path="./marimo-studio.d.ts" />

import { Deck, Slide } from "@revealjs/react";
import { useEffect, useRef } from "react";
import type { RevealApi } from "reveal.js";
import "reveal.js/reveal.css";

import { useMarimoValue } from "./lib/use-marimo-value.ts";
import {
  type Bowl,
  ProblemFigure,
  type Region,
  type Solution,
} from "./problem.tsx";

const keyboardCondition = (event: KeyboardEvent) =>
  !event.composedPath().some(
    (target) =>
      target instanceof Element && target.matches("marimo-cell, marimo-output"),
  );

const Figure = (
  { region, bowl, solution, steps }: {
    region?: Region;
    bowl?: Bowl;
    solution?: Solution;
    steps?: boolean;
  },
) => (
  <figure
    className="figure"
    data-marimo-lens-inputs="region-data bowl-data solution-data"
    data-marimo-lens-label="Feasible region and level curves"
    data-marimo-lens-render-source={JSON.stringify({ path: "src/problem.tsx" })}
  >
    {region && bowl && solution
      ? (
        <ProblemFigure
          region={region}
          bowl={bowl}
          solution={solution}
          steps={steps}
        />
      )
      : null}
  </figure>
);

const DualBars = ({ solution }: { solution?: Solution }) => {
  if (!solution) {
    return null;
  }
  const largest = Math.max(...solution.duals, 1e-9);
  return (
    <ol
      className="duals"
      data-marimo-lens-inputs="solution-data"
      data-marimo-lens-label="Dual values"
      data-marimo-lens-render-source={JSON.stringify({ path: "src/App.tsx" })}
    >
      {solution.duals.map((dual, index) => (
        <li key={index} data-active={solution.active[index]}>
          <span className="dual-name">
            g<sub>{index + 1}</sub>
          </span>
          <span
            className="dual-bar"
            style={{ inlineSize: `${(dual / largest) * 100}%` }}
          />
          <span className="dual-value">{dual.toFixed(2)}</span>
        </li>
      ))}
    </ol>
  );
};

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
  const region = useMarimoValue<Region>("region");
  const bowl = useMarimoValue<Bowl>("bowl");
  const solution = useMarimoValue<Solution>("solution");
  const problem = {
    region: region.value,
    bowl: bowl.value,
    solution: solution.value,
  };

  return (
    <Deck
      className="studio-deck"
      deckRef={deck}
      config={{
        controls: true,
        height: 720,
        keyboardCondition,
        margin: 0.06,
        progress: true,
        scrollActivationWidth: 0,
        transition: "fade",
        width: 1280,
      }}
    >
      <Slide className="split title-slide">
        <span ref={region.hostRef} id="region-data" hidden mo-value="region" />
        <span ref={bowl.hostRef} id="bowl-data" hidden mo-value="bowl" />
        <span
          ref={solution.hostRef}
          id="solution-data"
          hidden
          mo-value="solution"
        />
        <div>
          <p className="deck-kicker">Convex optimization</p>
          <h1>Quadratic programs</h1>
          <p className="deck-lede">A visual introduction</p>
        </div>
        <Figure {...problem} />
      </Slide>

      <Slide>
        <marimo-cell name="standard_form" />
      </Slide>

      <Slide>
        <marimo-cell name="why_quadratic" />
      </Slide>

      <Slide>
        <marimo-cell name="portfolio_example" />
      </Slide>

      <Slide className="split">
        <div className="stack">
          <marimo-cell name="example_context" />
          <marimo-cell name="plot_reading" />
        </div>
        <Figure {...problem} steps />
      </Slide>

      <Slide className="split explore">
        <div className="stack">
          <h2>Interactive example</h2>
          <marimo-cell name="exploration_prompt" />
          <marimo-cell className="slide-scale" name="curvature" />
          <marimo-cell className="slide-scale" name="pull_direction" />
        </div>
        <div className="stack">
          <Figure {...problem} />
          <marimo-cell name="solution_summary" />
        </div>
      </Slide>

      <Slide className="split">
        <marimo-cell name="duality" />
        <DualBars solution={problem.solution} />
      </Slide>

      <Slide className="split">
        <marimo-cell name="sensitivity_context" />
        <marimo-cell name="sensitivity_plot" />
      </Slide>

      <Slide>
        <marimo-cell name="takeaways" />
      </Slide>
    </Deck>
  );
};
