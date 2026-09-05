/// <reference path="./marimo-studio.d.ts" />

import { usePDF } from "@react-pdf/renderer";
// @deno-types="npm:@types/react@19.2.10"
import { useMemo } from "react";

import { useMarimoValue } from "./lib/use-marimo-value.ts";
import { ReportViewer } from "./ReportViewer.tsx";
import { OccupancyReport } from "./report/OccupancyReport.tsx";
import type {
  DailyReading,
  HourlyReading,
  OccupancyReportData,
  OccupancySummary,
  PreparedModel,
  RoomProfileSummary,
  SensorProfile,
} from "./report/types.ts";

interface OccupancyAnalysis {
  readonly selection: {
    readonly scope: string;
  };
  readonly summary: OccupancySummary;
  readonly hourly_room_profile: readonly HourlyReading[];
  readonly daily_room_profile: readonly DailyReading[];
  readonly sensor_profiles: readonly SensorProfile[];
  readonly profile_summary: RoomProfileSummary;
  readonly model: PreparedModel;
}

const LoadingReport = () => (
  <div className="loading-report" role="status">
    <span className="loading-sheet" aria-hidden="true">
      <i />
      <i />
      <i />
      <i />
    </span>
    <span>Composing the facilities report</span>
  </div>
);

const ReportWorkbench = ({
  report,
  unavailable,
}: {
  report?: OccupancyReportData;
  unavailable: boolean;
}) => {
  const document = useMemo(
    () => report ? <OccupancyReport report={report} /> : undefined,
    [report],
  );
  const [instance] = usePDF({ document });
  const ready = document !== undefined && instance.blob !== null &&
    instance.url !== null && !instance.loading && instance.error === null;
  const pageSummaries = report
    ? [
      `${report.room} executive summary for ${report.period.scope_label}. ${
        (report.period.occupancy_rate * 100).toFixed(1)
      }% occupied across ${
        report.period.observations.toLocaleString("en")
      } readings.`,
      report.period.occupied > 0
        ? "Environmental profile comparing occupied and vacant carbon dioxide, light, temperature, and humidity readings."
        : "Environmental profile for a scope with no occupied observations. Vacant sensor readings provide the reference profile.",
      report.period.occupied > 0
        ? `Model evidence at threshold ${
          report.model.threshold.toFixed(2)
        }, with ${(report.model.accuracy * 100).toFixed(1)}% accuracy and ${
          (report.model.recall * 100).toFixed(1)
        }% recall.`
        : `Model evidence at threshold ${
          report.model.threshold.toFixed(2)
        }, with ${
          (report.model.accuracy * 100).toFixed(1)
        }% accuracy. Recall is unavailable for this scope.`,
    ]
    : [];

  return (
    <main className="report-workbench" aria-busy={!ready}>
      <header className="workbench-header">
        <div className="workbench-title">
          <p>{report?.room ?? "Room"}</p>
          <h1>Occupancy field report</h1>
        </div>
        <div className="workbench-actions">
          <span className="document-spec">A4 · 3 pages</span>
          {ready
            ? (
              <a
                className="download-report"
                href={instance.url ?? undefined}
                download="room-01-occupancy-report.pdf"
              >
                Download PDF
              </a>
            )
            : (
              <span className="download-report is-disabled">
                Preparing PDF
              </span>
            )}
        </div>
      </header>

      {unavailable || instance.error
        ? (
          <div className="report-error" role="alert">
            The notebook report data could not be loaded. Reload the view to
            retry.
          </div>
        )
        : null}

      <section className="scope-strip" aria-label="Observation scope">
        <marimo-cell name="analysis_scope_control" />
        <p className="scope-readout" aria-live="polite">
          <span>Included in PDF</span>
          <strong>
            {report
              ? `${report.period.observations.toLocaleString("en")} readings`
              : "Preparing data"}
          </strong>
        </p>
      </section>

      <section
        className="viewer-stage"
        aria-label="A4 occupancy report preview"
      >
        {ready
          ? (
            <ReportViewer
              instance={instance}
              pageSummaries={pageSummaries}
            />
          )
          : <LoadingReport />}
      </section>
    </main>
  );
};

export const App = () => {
  const analysis = useMarimoValue<OccupancyAnalysis>("occupancy_analysis");
  const report = useMemo<OccupancyReportData | undefined>(() => {
    const value = analysis.value;
    if (value === undefined) return undefined;
    const selectedModel = value.model.evidence.find((row) =>
      Math.abs(row.threshold - value.model.default_threshold) < 0.001
    );
    if (selectedModel === undefined) return undefined;

    return {
      room: value.summary.room,
      period: {
        start: value.summary.period_start,
        end: value.summary.period_end,
        scope_label: value.summary.scope_label,
        observations: value.summary.observations,
        occupied: value.summary.occupied,
        occupancy_rate: value.summary.occupancy_rate,
        reading_interval_minutes: value.summary.reading_interval_minutes,
        estimated_occupied_hours: value.summary.estimated_occupied_hours,
      },
      hourly: value.hourly_room_profile,
      daily: value.daily_room_profile,
      sensors: value.sensor_profiles,
      profile_summary: value.profile_summary,
      model: {
        ...selectedModel,
        co2_weight: value.model.co2_weight,
        light_weight: value.model.light_weight,
        normalization: value.model.normalization,
        normalization_quantile: value.model.normalization_quantile,
        threshold_maximum: value.model.threshold_maximum,
        threshold_minimum: value.model.threshold_minimum,
        threshold_step: value.model.threshold_step,
        curve: value.model.evidence,
        errors: selectedModel.errors.slice(0, 6),
      },
    };
  }, [analysis.value]);
  const reportRevision = useMemo(
    () => report ? JSON.stringify(report) : "loading",
    [report],
  );

  return (
    <>
      <span
        ref={analysis.hostRef}
        aria-hidden="true"
        hidden
        mo-value="occupancy_analysis"
      />
      <ReportWorkbench
        key={reportRevision}
        report={report}
        unavailable={analysis.error}
      />
    </>
  );
};
