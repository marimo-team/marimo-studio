import { Line, Rect, Svg, Text, View } from "@react-pdf/renderer";
// @deno-types="npm:@types/react@19.2.10"
import type { ReactNode } from "react";

import { styles } from "./styles.ts";
import { capCenter } from "./theme.ts";

export const Topline = ({ section }: { section: string }) => (
  <View key={section} style={styles.topline} fixed wrap={false}>
    <Text
      style={[styles.meta, {
        width: "100%",
        textAlign: "right",
        textTransform: "uppercase",
      }]}
    >
      Room 01 · {section} · Occupancy field report
    </Text>
  </View>
);

export const SectionHeading = ({
  index,
  title,
  note,
}: {
  index: string;
  title: string;
  note?: string;
}) => (
  <View style={styles.sectionHeading} minPresenceAhead={40}>
    <View>
      <Text style={styles.sectionIndex}>{index}</Text>
      <Text style={styles.sectionTitle}>{title}</Text>
    </View>
    {note ? <Text style={styles.sectionNote}>{note}</Text> : null}
  </View>
);

export const Metric = ({
  label,
  value,
  accent = false,
  last = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
  last?: boolean;
}) => (
  <View style={[styles.metric, last ? styles.metricLast : {}]}>
    <Text style={styles.metricLabel}>{label}</Text>
    <Text style={[styles.metricValue, accent ? styles.metricValueOrange : {}]}>
      {value}
    </Text>
  </View>
);

export const TwoColumn = ({
  left,
  right,
  gap = 14,
}: {
  left: ReactNode;
  right: ReactNode;
  gap?: number;
}) => (
  <View style={{ flexDirection: "row", gap }}>
    <View style={{ flex: 1 }}>{left}</View>
    <View style={{ flex: 1 }}>{right}</View>
  </View>
);

const LEGEND_SIZE = 6.5;
const MARK = { width: 14, height: 6 };

export type LegendMark = "bar" | "line" | "dash";

/** Chart legend whose marks center on the capitals of their labels. */
export const Legend = ({
  items,
  note,
}: {
  items: readonly { label: string; color: string; mark: LegendMark }[];
  note?: string;
}) => (
  <View style={{ flexDirection: "row", alignItems: "flex-start", gap: 16 }}>
    {items.map(({ label, color, mark }) => (
      <View key={label} style={{ flexDirection: "row", gap: 5 }}>
        <Svg
          width={MARK.width}
          height={MARK.height}
          viewBox={`0 0 ${MARK.width} ${MARK.height}`}
          style={{ marginTop: capCenter(LEGEND_SIZE) - MARK.height / 2 }}
        >
          {mark === "bar"
            ? (
              <Rect
                x={0}
                y={0.5}
                width={MARK.width}
                height={MARK.height - 1}
                fill={color}
              />
            )
            : (
              <Line
                x1={0}
                y1={MARK.height / 2}
                x2={MARK.width}
                y2={MARK.height / 2}
                stroke={color}
                strokeWidth={mark === "dash" ? 1.3 : 1.5}
                strokeDasharray={mark === "dash" ? "4 2" : undefined}
              />
            )}
        </Svg>
        <Text style={styles.legendLabel}>{label}</Text>
      </View>
    ))}
    {note
      ? <Text style={[styles.legendLabel, { marginLeft: "auto" }]}>{note}</Text>
      : null}
  </View>
);
