/// <reference path="./marimo-studio.d.ts" />

import { type ErrorCase, ErrorEvidence } from "./components/ErrorEvidence.tsx";
import {
  formatRate,
  ThresholdCurve,
  type ThresholdMetric,
} from "./components/ThresholdCurve.tsx";
import { useMarimoValue } from "./lib/use-marimo-value.ts";

const Metric = ({ label, value }: { label: string; value?: string }) => (
  <article className="metric">
    <span>{label}</span>
    <strong>{value ?? "…"}</strong>
  </article>
);

type ScopeSummary = {
  readonly scope_label: string;
  readonly observations: number;
  readonly occupied: number;
};

type OccupancyAnalysis = {
  readonly summary: ScopeSummary;
  readonly model: ThresholdMetric & {
    readonly curve: ThresholdMetric[];
    readonly errors: ErrorCase[];
  };
};

const ConfusionCounts = ({ summary }: { summary?: ThresholdMetric }) => (
  <article
    className="panel confusion-panel"
    aria-labelledby="confusion-heading"
  >
    <div className="panel-heading">
      <div>
        <p className="section-index">03 / Classification</p>
        <h2 id="confusion-heading">Confusion counts</h2>
      </div>
    </div>
    <table className="confusion-table">
      <caption>Observed occupancy by predicted occupancy</caption>
      <thead>
        <tr>
          <th>Observed</th>
          <th>Predicted occupied</th>
          <th>Predicted empty</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th>Occupied</th>
          <td>
            <span>True positive</span>
            <strong>{summary?.true_positive ?? "…"}</strong>
          </td>
          <td className="error-count">
            <span>False negative</span>
            <strong>{summary?.false_negative ?? "…"}</strong>
          </td>
        </tr>
        <tr>
          <th>Empty</th>
          <td className="error-count">
            <span>False positive</span>
            <strong>{summary?.false_positive ?? "…"}</strong>
          </td>
          <td>
            <span>True negative</span>
            <strong>{summary?.true_negative ?? "…"}</strong>
          </td>
        </tr>
      </tbody>
    </table>
  </article>
);

export const App = () => {
  const analysis = useMarimoValue<OccupancyAnalysis>("occupancy_analysis");
  const scope = analysis.value?.summary;
  const model = analysis.value?.model;
  const curve = model?.curve ?? [];
  const errorRows = model?.errors ?? [];
  const unavailable = analysis.error;
  const loading = !unavailable && analysis.value === undefined;

  return (
    <>
      <span
        ref={analysis.hostRef}
        aria-hidden="true"
        hidden
        mo-value="occupancy_analysis"
      />

      <main className="review" aria-busy={loading}>
        {loading
          ? (
            <div className="review-loader" role="status">
              <span className="review-loader-sheet" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
              Preparing model evidence
            </div>
          )
          : null}
        <header className="review-header">
          <div>
            <p className="eyebrow">Building occupancy · Training review</p>
            <h1>Threshold behavior and training errors</h1>
          </div>
          <p className="method-note">
            Each scope uses its own light and CO₂ normalization. The score
            weights normalized light at 70% and normalized CO₂ at 30%.
          </p>
        </header>

        {unavailable
          ? (
            <p className="data-status" role="alert">
              Model results could not be loaded. Reload the page to retry.
            </p>
          )
          : null}

        <section className="control-strip" aria-labelledby="threshold-heading">
          <div>
            <p className="section-index">01 / Operating point</p>
            <h2 id="threshold-heading">Choose scope and threshold</h2>
            <p className="scope-note" aria-live="polite">
              {scope
                ? `${scope.scope_label} · ${
                  scope.observations.toLocaleString("en")
                } readings`
                : "Loading observation scope"}
            </p>
          </div>
          <div className="control-strip-controls">
            <marimo-cell name="analysis_scope_control" />
            <marimo-cell name="threshold_control" />
          </div>
        </section>

        <section className="metric-grid" aria-label="Current threshold metrics">
          <Metric
            label="Threshold"
            value={model?.threshold.toFixed(2)}
          />
          <Metric
            label="In-sample accuracy"
            value={model && formatRate(model.accuracy)}
          />
          <Metric
            label="In-sample precision"
            value={model && formatRate(model.precision)}
          />
          <Metric
            label="In-sample recall"
            value={model && scope
              ? scope.occupied > 0 ? formatRate(model.recall) : "n/a"
              : undefined}
          />
        </section>

        <section className="analysis-grid">
          <article
            className="panel curve-panel"
            aria-labelledby="curve-heading"
          >
            <div className="panel-heading">
              <div>
                <p className="section-index">02 / Threshold sweep</p>
                <h2 id="curve-heading">Metric curve</h2>
              </div>
              <p>The vertical marker shows the selected threshold.</p>
            </div>
            <ThresholdCurve
              current={model?.threshold}
              metrics={curve}
              showRecall={(scope?.occupied ?? 0) > 0}
            />
          </article>

          <ConfusionCounts summary={model} />
        </section>

        <ErrorEvidence
          rows={errorRows}
          total={model
            ? model.false_positive + model.false_negative
            : undefined}
        />
        <footer className="source-note">
          Source:{"  "}
          <a
            href="https://doi.org/10.24432/C5X01N"
            target="_blank"
            rel="noreferrer"
          >
            Luis Candanedo, UCI Occupancy Detection training split
          </a>{" "}
          ·{"  "}
          <a
            href="https://creativecommons.org/licenses/by/4.0/"
            target="_blank"
            rel="noreferrer"
          >
            CC BY 4.0
          </a>
        </footer>
      </main>
    </>
  );
};
