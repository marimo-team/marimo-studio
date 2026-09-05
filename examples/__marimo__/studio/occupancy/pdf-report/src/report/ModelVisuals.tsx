import {
  Circle,
  G,
  Line,
  Path,
  Rect,
  Svg,
  Text,
  View,
} from "@react-pdf/renderer";

import { palette, typefaces } from "./theme.ts";
import type { ModelReport, ThresholdPoint } from "./types.ts";

const seriesPath = (
  rows: readonly ThresholdPoint[],
  key: "accuracy" | "precision" | "recall",
  left: number,
  plotWidth: number,
  top: number,
  plotHeight: number,
  thresholdMin: number,
  thresholdMax: number,
) =>
  rows.map((row, index) => {
    const x = left + (row.threshold - thresholdMin) /
        Math.max(thresholdMax - thresholdMin, 0.01) * plotWidth;
    const y = top + plotHeight - row[key] * plotHeight;
    return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  }).join(" ");

export const ThresholdChart = (
  { model, showRecall = true }: { model: ModelReport; showRecall?: boolean },
) => {
  const width = 500;
  const height = 116;
  const left = 27;
  const right = 7;
  const top = 8;
  const bottom = 88;
  const plotWidth = width - left - right;
  const plotHeight = bottom - top;
  const thresholdMin = model.curve.at(0)?.threshold ?? model.threshold;
  const thresholdMax = model.curve.at(-1)?.threshold ?? model.threshold;
  const thresholdX = (threshold: number) =>
    left + (threshold - thresholdMin) /
      Math.max(thresholdMax - thresholdMin, 0.01) * plotWidth;
  const currentX = thresholdX(model.threshold);
  const thresholdTicks = [thresholdMin, model.threshold, thresholdMax].filter(
    (value, index, values) =>
      values.findIndex((candidate) => Math.abs(candidate - value) < 0.001) ===
        index,
  );
  const legendItems = [
    { label: "Accuracy", color: palette.ink, dash: undefined },
    { label: "Precision", color: palette.slate, dash: "5 2" },
    { label: "Recall", color: palette.orange, dash: undefined },
  ].filter((item) => showRecall || item.label !== "Recall");

  return (
    <View>
      <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
        {[0, 0.5, 1].map((ratio) => (
          <G key={ratio}>
            <Line
              x1={left}
              y1={bottom - ratio * plotHeight}
              x2={width - right}
              y2={bottom - ratio * plotHeight}
              stroke={palette.rule}
              strokeWidth={0.8}
            />
            <Text
              x={0}
              y={bottom - ratio * plotHeight + 2}
              style={{
                fill: palette.fog,
                fontFamily: typefaces.body,
                fontSize: 5.5,
                fontWeight: 500,
              }}
            >
              {`${ratio * 100}%`}
            </Text>
          </G>
        ))}
        <Line
          x1={currentX}
          y1={top}
          x2={currentX}
          y2={bottom}
          stroke={palette.orange}
          strokeWidth={1.2}
          strokeDasharray="4 3"
        />
        <Path
          d={seriesPath(
            model.curve,
            "accuracy",
            left,
            plotWidth,
            top,
            plotHeight,
            thresholdMin,
            thresholdMax,
          )}
          fill="none"
          stroke={palette.ink}
          strokeWidth={2}
        />
        <Path
          d={seriesPath(
            model.curve,
            "precision",
            left,
            plotWidth,
            top,
            plotHeight,
            thresholdMin,
            thresholdMax,
          )}
          fill="none"
          stroke={palette.slate}
          strokeWidth={1.3}
          strokeDasharray="7 3"
        />
        {showRecall
          ? (
            <Path
              d={seriesPath(
                model.curve,
                "recall",
                left,
                plotWidth,
                top,
                plotHeight,
                thresholdMin,
                thresholdMax,
              )}
              fill="none"
              stroke={palette.orange}
              strokeWidth={1.5}
            />
          )
          : null}
        <Circle
          cx={currentX}
          cy={top + plotHeight - model.accuracy * plotHeight}
          r={3.2}
          fill={palette.paper}
          stroke={palette.ink}
          strokeWidth={1.5}
        />
        {thresholdTicks.map((threshold) => (
          <Text
            key={threshold}
            x={thresholdX(threshold)}
            y={103}
            textAnchor={Math.abs(threshold - thresholdMin) < 0.001
              ? "start"
              : Math.abs(threshold - thresholdMax) < 0.001
              ? "end"
              : "middle"}
            style={{
              fill: Math.abs(threshold - model.threshold) < 0.001
                ? palette.orange
                : palette.fog,
              fontFamily: typefaces.body,
              fontWeight: 500,
              fontSize: 5.5,
            }}
          >
            {threshold.toFixed(2)}
          </Text>
        ))}
      </Svg>
      <View style={{ flexDirection: "row", gap: 16 }}>
        {legendItems.map(({ label, color, dash }) => (
          <View
            key={label}
            style={{ flexDirection: "row", alignItems: "center", gap: 5 }}
          >
            <Svg width={15} height={5} viewBox="0 0 15 5">
              <Line
                x1={0}
                y1={2.5}
                x2={15}
                y2={2.5}
                stroke={color}
                strokeWidth={1.3}
                strokeDasharray={dash}
              />
            </Svg>
            <Text style={{ color: palette.fog, fontSize: 6.5 }}>{label}</Text>
          </View>
        ))}
        {showRecall ? null : (
          <Text
            style={{ marginLeft: "auto", color: palette.fog, fontSize: 6.5 }}
          >
            Recall unavailable for this scope
          </Text>
        )}
      </View>
    </View>
  );
};

export const ConfusionMatrix = ({ model }: { model: ModelReport }) => {
  const values = [
    {
      label: "Correct occupied",
      value: model.true_positive,
      fill: palette.paper,
      accent: false,
    },
    {
      label: "Missed occupancy",
      value: model.false_negative,
      fill: palette.orangeWash,
      accent: true,
    },
    {
      label: "False occupancy alert",
      value: model.false_positive,
      fill: palette.orangeWash,
      accent: true,
    },
    {
      label: "Correct vacant",
      value: model.true_negative,
      fill: palette.paper,
      accent: false,
    },
  ];

  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 5 }}>
      {values.map((entry) => (
        <View
          key={entry.label}
          style={{
            width: "48.8%",
            minHeight: 45,
            padding: 8,
            backgroundColor: entry.fill,
            borderWidth: 0.6,
            borderColor: palette.rule,
            borderRadius: 5,
          }}
        >
          <Text
            style={{
              color: entry.accent ? palette.orange : palette.ink,
              fontFamily: typefaces.display,
              fontSize: 16,
              lineHeight: 1,
            }}
          >
            {entry.value.toLocaleString("en")}
          </Text>
          <Text
            style={{
              marginTop: 5,
              color: palette.slate,
              fontSize: 6.5,
            }}
          >
            {entry.label}
          </Text>
        </View>
      ))}
    </View>
  );
};

export const ScoreGlyph = (
  { score, threshold }: { score: number; threshold: number },
) => (
  <Svg width={55} height={10} viewBox="0 0 55 10">
    <Rect x={0} y={4} width={55} height={2} rx={1} fill={palette.rule} />
    <Line
      x1={threshold * 55}
      y1={0}
      x2={threshold * 55}
      y2={10}
      stroke={palette.ink}
      strokeWidth={1}
    />
    <Circle cx={score * 55} cy={5} r={3} fill={palette.orange} />
  </Svg>
);
