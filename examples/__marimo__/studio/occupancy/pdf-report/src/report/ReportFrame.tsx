import { Text, View } from "@react-pdf/renderer";
import type { ReactNode } from "react";

import { styles } from "./styles.ts";

export const Topline = ({ section }: { section: string }) => (
  <View key={section} style={styles.topline} fixed wrap={false}>
    <Text style={[styles.meta, { width: "100%", textAlign: "right" }]}>
      ROOM 01 · {section} · OCCUPANCY FIELD REPORT
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
