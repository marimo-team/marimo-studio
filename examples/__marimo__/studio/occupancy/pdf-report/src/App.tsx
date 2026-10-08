/// <reference path="./marimo-studio.d.ts" />

// @deno-types="npm:@types/react@19.2.10"
import { useEffect, useMemo, useState } from "react";

import { useMarimoValue } from "./lib/use-marimo-value.ts";
import { renderReport } from "./report/render.tsx";
import { grouped, percent } from "./report/format.ts";
import type { OccupancyAnalysis } from "./report/types.ts";
import { type PdfInstance, ReportViewer } from "./ReportViewer.tsx";

const LOADING: PdfInstance = { blob: null, error: null, loading: true, url: null };

/** Render the report whenever the notebook's snapshot changes. */
const useReportPdf = (analysis: OccupancyAnalysis | undefined): PdfInstance => {
  const [instance, setInstance] = useState<PdfInstance>(LOADING);

  useEffect(() => {
    if (analysis === undefined) {
      setInstance(LOADING);
      return;
    }
    let active = true;
    let url: string | null = null;
    setInstance((current) => ({ ...current, loading: true }));
    renderReport(analysis).then(
      (blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setInstance({ blob, error: null, loading: false, url });
      },
      (error: unknown) => {
        if (!active) return;
        console.error(error);
        setInstance({ blob: null, error: String(error), loading: false, url: null });
      },
    );
    return () => {
      active = false;
      if (url !== null) URL.revokeObjectURL(url);
    };
  }, [analysis]);

  return instance;
};

const LoadingReport = () => (
  <div className="loading-report" role="status">
    <span className="loading-sheet" aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
    </span>
    <span>Composing the field report</span>
  </div>
);

export const App = () => {
  const analysis = useMarimoValue<OccupancyAnalysis>("occupancy_analysis");
  const report = analysis.value;
  const instance = useReportPdf(report);
  const ready = instance.blob !== null && instance.url !== null && !instance.loading;
  const pageSummaries = useMemo(() => {
    if (report === undefined) return [];
    const { summary, model } = report;
    const selected = model.evidence.find((row) => Math.abs(row.threshold - model.default_threshold) < 1e-6);
    return [
      `${summary.room} room use for ${summary.scope_label}: ${percent(summary.occupancy_rate)} occupied across ${
        grouped(summary.observations)
      } readings.`,
      summary.occupied > 0
        ? "Sensor conditions comparing occupied and vacant carbon dioxide, light, temperature, and humidity, with the daily register."
        : "Sensor conditions for a scope with no occupied readings, with the daily register.",
      selected === undefined
        ? "Occupancy score evidence."
        : `Occupancy score evidence at threshold ${model.default_threshold.toFixed(2)}, with ${
          percent(selected.accuracy)
        } accuracy${
          summary.occupied > 0
            ? ` and ${percent(selected.recall)} recall.`
            : ". Recall is unavailable because no reading is occupied."
        }`,
    ];
  }, [report]);

  return (
    <>
      <span ref={analysis.hostRef} aria-hidden="true" hidden id="analysis-data" mo-value="occupancy_analysis" />
      <span id="report-summary" hidden mo-value="occupancy_analysis.summary" />
      <span id="report-hourly" hidden mo-value="occupancy_analysis.hourly_room_profile" />
      <span id="report-daily" hidden mo-value="occupancy_analysis.daily_room_profile" />
      <span id="report-sensors" hidden mo-value="occupancy_analysis.sensor_profiles" />
      <span id="report-profile" hidden mo-value="occupancy_analysis.profile_summary" />
      <span id="report-model" hidden mo-value="occupancy_analysis.model" />

      <main data-marimo-lens-inputs="analysis-data" className="report-workbench" aria-busy={!ready}>
        <header className="workbench-header">
          <div className="workbench-title">
            <p>{report?.summary.room ?? "Room"}</p>
            <h1>Occupancy field report</h1>
          </div>
          <div className="workbench-actions">
            <span className="document-spec">A4 · 3 pages</span>
            {ready
              ? (
                <a className="download-report" href={instance.url ?? undefined} download="room-01-occupancy-report.pdf">
                  Download PDF
                </a>
              )
              : <span className="download-report is-disabled">Preparing PDF</span>}
          </div>
        </header>

        {analysis.error || instance.error
          ? (
            <div className="report-error" role="alert">
              The report could not be composed. Reload the page to retry.
            </div>
          )
          : null}

        <section className="scope-strip" aria-label="Observation scope">
          <marimo-cell name="analysis_scope_control" />
          <p className="scope-readout" aria-live="polite">
            <span hidden mo-value="occupancy_analysis.summary.observations" />
            <span>Included in PDF</span>
            <strong>{report ? `${grouped(report.summary.observations)} readings` : "Preparing data"}</strong>
          </p>
        </section>

        <section className="viewer-stage" aria-label="A4 occupancy report preview">
          {ready ? <ReportViewer instance={instance} pageSummaries={pageSummaries} /> : <LoadingReport />}
        </section>
      </main>
    </>
  );
};
