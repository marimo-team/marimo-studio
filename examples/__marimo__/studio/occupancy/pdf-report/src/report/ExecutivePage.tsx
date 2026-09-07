import { Page, Text, View } from "@react-pdf/renderer";

import { Metric, SectionHeading, Topline, TwoColumn } from "./ReportFrame.tsx";
import { OccupancyDial, OccupancyTimeline } from "./OccupancyVisuals.tsx";
import { styles } from "./styles.ts";
import {
  formatCompact,
  formatDay,
  formatPercent,
  formatPeriod,
  palette,
} from "./theme.ts";
import type { OccupancyReportData } from "./types.ts";

export const ExecutivePage = ({ report }: { report: OccupancyReportData }) => {
  const hasOccupiedReadings = report.period.occupied > 0;
  const mostActive = report.profile_summary.highest_occupancy_day;
  const cadence = report.period.reading_interval_minutes === 1
    ? "one-minute"
    : `${report.period.reading_interval_minutes.toFixed(1)}-minute`;

  return (
    <Page size="A4" style={styles.page}>
      <Topline section="01 / 03 · Room use" />

      <View
        style={{
          flexDirection: "row",
          gap: 28,
          marginTop: 23,
          marginBottom: 22,
        }}
      >
        <View style={{ flex: 1 }}>
          <Text style={styles.orangePill}>{report.period.scope_label}</Text>
          <Text style={[styles.pageTitle, { marginTop: 10, fontSize: 42 }]}>
            {hasOccupiedReadings ? "Room use at a glance." : (
              <>
                Room use{"\n"}after hours.
              </>
            )}
          </Text>
          <Text style={[styles.pageLead, { width: "100%" }]}>
            {report.room} was marked occupied in{" "}
            {formatPercent(report.period.occupancy_rate)} of the selected{" "}
            {cadence}{" "}
            readings. The report summarizes this room-use pattern, compares
            sensor conditions, and checks the notebook's occupancy score.
          </Text>
          <Text style={[styles.meta, { marginTop: 16 }]}>
            {formatPeriod(report.period.start, report.period.end)}
          </Text>
        </View>
        <View style={{ width: 150, alignItems: "center" }}>
          <OccupancyDial rate={report.period.occupancy_rate} />
          <Text style={[styles.meta, { marginTop: 4 }]}>OCCUPIED READINGS</Text>
        </View>
      </View>

      <View style={styles.metricRow}>
        <Metric
          label="Selected readings"
          value={formatCompact(report.period.observations)}
        />
        <Metric
          label="Estimated occupied time"
          value={`${report.period.estimated_occupied_hours.toFixed(1)} h`}
          accent
        />
        <Metric
          label="Highest-rate day"
          value={hasOccupiedReadings ? formatDay(mostActive.day) : "None"}
        />
        <Metric
          label="In-sample accuracy"
          value={formatPercent(report.model.accuracy)}
          last
        />
      </View>

      <View style={{ marginTop: 25 }}>
        <SectionHeading
          index="01.1 / HOURLY SIGNAL"
          title="Hourly occupancy and mean CO2"
        />
        <View style={styles.panel}>
          <OccupancyTimeline rows={report.hourly} />
          <View style={{ flexDirection: "row", gap: 18, marginTop: 1 }}>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 5 }}
            >
              <View
                style={{
                  width: 13,
                  height: 5,
                  backgroundColor: palette.orange,
                }}
              />
              <Text style={styles.caption}>Occupancy share</Text>
            </View>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 5 }}
            >
              <View
                style={{ width: 13, height: 1.5, backgroundColor: palette.ink }}
              />
              <Text style={styles.caption}>Mean CO2</Text>
            </View>
          </View>
        </View>
      </View>

      <View style={{ marginTop: 21 }}>
        <SectionHeading index="01.2 / READING" title="What the record shows" />
        <TwoColumn
          left={
            <View style={styles.panelWhite}>
              <Text style={styles.panelLabel}>Usage pattern</Text>
              <Text style={styles.body}>
                {hasOccupiedReadings
                  ? `Occupied readings cluster into clear daily blocks. ${
                    formatDay(mostActive.day)
                  } has the highest occupied share, at ${
                    formatPercent(mostActive.occupancy_rate)
                  }.`
                  : "No readings are marked occupied in this scope. The hourly profile shows how mean CO2 changes while the room remains vacant."}
              </Text>
            </View>
          }
          right={
            <View style={styles.panelWhite}>
              <Text style={styles.panelLabel}>Score result</Text>
              <Text style={styles.body}>
                {hasOccupiedReadings
                  ? `At the default threshold of ${
                    report.model.threshold.toFixed(2)
                  }, the light and CO2 score detects ${
                    formatPercent(report.model.recall)
                  } of occupied readings in this same selection.`
                  : `This scope contains no occupied readings, so recall is unavailable. At the default threshold of ${
                    report.model.threshold.toFixed(2)
                  }, the score marks ${
                    report.model.false_positive.toLocaleString("en")
                  } vacant readings as occupied.`}
              </Text>
            </View>
          }
        />
      </View>
    </Page>
  );
};
