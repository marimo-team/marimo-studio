import { Page, Text, View } from "@react-pdf/renderer";

import { Metric, SectionHeading, Topline, TwoColumn } from "./ReportFrame.tsx";
import {
  ConfusionMatrix,
  ScoreGlyph,
  ThresholdChart,
} from "./ModelVisuals.tsx";
import { styles } from "./styles.ts";
import { formatPercent, formatTimestamp, palette, typefaces } from "./theme.ts";
import type { OccupancyReportData, ReportError } from "./types.ts";

const ErrorTable = ({
  errors,
  threshold,
}: {
  errors: readonly ReportError[];
  threshold: number;
}) => (
  <View style={{ borderTopWidth: 0.6, borderTopColor: palette.ink }}>
    <View
      style={{
        flexDirection: "row",
        paddingVertical: 6,
        borderBottomWidth: 0.6,
        borderBottomColor: palette.rule,
      }}
    >
      {[
        ["Timestamp", 1.45],
        ["Outcome", 1.2],
        ["Score", 1],
        ["CO2", 0.62],
        ["Light", 0.62],
        ["Temp", 0.58],
      ].map(([label, flex]) => (
        <Text key={String(label)} style={[styles.meta, { flex: Number(flex) }]}>
          {label}
        </Text>
      ))}
    </View>
    {errors.map((row) => (
      <View
        key={`${String(row.date)}-${row.outcome}`}
        style={{
          flexDirection: "row",
          alignItems: "center",
          minHeight: 20,
          borderBottomWidth: 0.6,
          borderBottomColor: palette.rule,
        }}
      >
        <Text
          style={{
            flex: 1.45,
            fontFamily: typefaces.body,
            fontSize: 6.4,
            fontWeight: 500,
          }}
        >
          {formatTimestamp(row.date)}
        </Text>
        <Text style={{ flex: 1.2, color: palette.orange, fontSize: 6.5 }}>
          {row.outcome === "false positive"
            ? "false alert"
            : "missed occupancy"}
        </Text>
        <View style={{ flex: 1 }}>
          <ScoreGlyph score={row.score} threshold={threshold} />
        </View>
        <Text style={{ flex: 0.62, fontSize: 6.5 }}>{row.CO2.toFixed(0)}</Text>
        <Text style={{ flex: 0.62, fontSize: 6.5 }}>
          {row.Light.toFixed(0)}
        </Text>
        <Text style={{ flex: 0.58, fontSize: 6.5 }}>
          {row.Temperature.toFixed(1)}°
        </Text>
      </View>
    ))}
  </View>
);

export const ModelPage = ({ report }: { report: OccupancyReportData }) => {
  const model = report.model;
  const errors = model.false_positive + model.false_negative;
  const hasOccupiedReadings = report.period.occupied > 0;

  return (
    <Page size="A4" style={styles.page}>
      <Topline section="03 / 03 · Occupancy score" />
      <Text style={styles.pageTitle}>
        How the occupancy score works.
      </Text>
      <Text style={[styles.pageLead, { width: "100%" }]}>
        Light is normalized from zero to this scope's 99th percentile. CO2 is
        normalized from this scope's minimum to its 99th percentile. The score
        combines them at 70% and 30%. A reading at or above{" "}
        {model.threshold.toFixed(2)}{" "}
        is classified as occupied, so the threshold is scope-specific.{" "}
        {hasOccupiedReadings
          ? "Precision shows how often occupied classifications are correct, and recall shows how many occupied readings are detected."
          : "This scope has no occupied readings, so recall is unavailable. Precision still measures the share of occupied classifications that are correct."}
      </Text>

      <View style={[styles.metricRow, { marginTop: 14 }]}>
        <Metric label="Threshold" value={model.threshold.toFixed(2)} accent />
        <Metric
          label="In-sample accuracy"
          value={formatPercent(model.accuracy)}
        />
        <Metric label="Precision" value={formatPercent(model.precision)} />
        <Metric
          label="Recall"
          value={hasOccupiedReadings ? formatPercent(model.recall) : "n/a"}
          last
        />
      </View>

      <View style={{ marginTop: 12 }}>
        <SectionHeading
          index="03.1 / THRESHOLD SWEEP"
          title={hasOccupiedReadings
            ? "Accuracy, precision, and recall by threshold"
            : "Accuracy and precision by threshold"}
          note={`The orange rule marks the selected threshold of ${
            model.threshold.toFixed(2)
          }.`}
        />
        <ThresholdChart model={model} showRecall={hasOccupiedReadings} />
      </View>

      <View style={{ marginTop: 11 }}>
        <TwoColumn
          gap={18}
          left={
            <View>
              <SectionHeading
                index="03.2 / CLASSIFICATION COUNTS"
                title={`Results at ${model.threshold.toFixed(2)}`}
              />
              <ConfusionMatrix model={model} />
            </View>
          }
          right={
            <View style={[styles.panel, { minHeight: 112 }]}>
              <Text style={styles.panelLabel}>CLASSIFICATION ERRORS</Text>
              <Text
                style={{
                  fontFamily: typefaces.display,
                  fontSize: 14,
                  lineHeight: 1.3,
                }}
              >
                The score misclassifies {errors.toLocaleString("en")} of{" "}
                {report.period.observations.toLocaleString("en")}{" "}
                selected readings at this threshold.
              </Text>
              <Text style={[styles.body, { marginTop: 9 }]}>
                If this score drives building controls, false alerts can trigger
                unnecessary ventilation or conditioning, while missed occupancy
                can delay fresh-air response. Review the errors farthest from
                the threshold before changing it.
              </Text>
            </View>
          }
        />
      </View>

      <View style={{ marginTop: 11 }}>
        <SectionHeading
          index="03.3 / ERROR REVIEW"
          title="Errors farthest from the threshold"
          note={`Orange dot: score. Ink tick: the ${
            model.threshold.toFixed(2)
          } threshold.`}
        />
        <ErrorTable errors={model.errors} threshold={model.threshold} />
      </View>

      <Text style={[styles.caption, { marginTop: 4 }]}>
        Data: Luis Candanedo, UCI Occupancy Detection training split (CC BY
        4.0). Analysis: Building Occupancy Marimo notebook. Document: React PDF
        4.8.1.
      </Text>
    </Page>
  );
};
