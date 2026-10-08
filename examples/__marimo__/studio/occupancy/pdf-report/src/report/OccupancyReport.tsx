import { Badge } from "../pdf/components/badge/badge.tsx";
import { DataTable } from "../pdf/components/data-table/data-table.tsx";
import { PdfGraph } from "../pdf/components/graph/graph.tsx";
import { Heading } from "../pdf/components/heading/heading.tsx";
import { KeyValue } from "../pdf/components/key-value/key-value.tsx";
import { PdfList } from "../pdf/components/list/list.tsx";
import { PageFooter } from "../pdf/components/page-footer/page-footer.tsx";
import { PageHeader } from "../pdf/components/page-header/page-header.tsx";
import { PageNumber } from "../pdf/components/page-number/page-number.tsx";
import { Section } from "../pdf/components/section/section.tsx";
import { Text } from "../pdf/components/text/text.tsx";
import { PdfcnThemeProvider } from "../pdf/components/theme-provider.tsx";
import { Document, Page, StyleSheet, View } from "../pdf/lib/pdf-primitives.tsx";
import { dayLabel, fixed, grouped, momentLabel, percent, weekday } from "./format.ts";
import { chartColors, fieldReportTheme as theme } from "./theme.ts";
import type { OccupancyAnalysis, ThresholdEvidence } from "./types.ts";

const styles = StyleSheet.create({
  page: {
    backgroundColor: theme.colors.background,
    boxSizing: "border-box",
    minHeight: 841,
    paddingBottom: theme.spacing.page.marginBottom,
    paddingLeft: theme.spacing.page.marginLeft,
    paddingRight: theme.spacing.page.marginRight,
    paddingTop: theme.spacing.page.marginTop,
    position: "relative",
  },
  pageBreak: { breakAfter: "page" },
  kicker: {
    color: theme.colors.accent,
    fontSize: 7,
    fontWeight: 600,
    letterSpacing: 1.2,
    marginBottom: 4,
    textTransform: "uppercase",
  },
  badges: { flexDirection: "row", gap: 6, marginBottom: 14 },
  row: { alignItems: "stretch", flexDirection: "row", gap: 12 },
  col: { flex: 1 },
  metrics: { flexDirection: "row", gap: 8, marginBottom: 16 },
  metric: {
    backgroundColor: theme.colors.muted,
    borderLeftColor: theme.colors.foreground,
    borderLeftWidth: 3,
    borderRadius: 4,
    flex: 1,
    paddingBottom: 9,
    paddingLeft: 10,
    paddingRight: 8,
    paddingTop: 8,
  },
  metricSignal: { borderLeftColor: theme.colors.accent },
  metricLabel: {
    color: theme.colors.mutedForeground,
    fontSize: 6.5,
    fontWeight: 600,
    letterSpacing: 0.8,
    marginBottom: 4,
    textTransform: "uppercase",
  },
  metricValue: { color: theme.colors.foreground, fontSize: 17, fontWeight: 600 },
  metricNote: { color: theme.colors.mutedForeground, fontSize: 7, marginTop: 2 },
  panel: {
    borderColor: theme.colors.border,
    borderRadius: 4,
    borderWidth: 1,
    padding: 12,
  },
  panelTitle: {
    color: theme.colors.mutedForeground,
    fontSize: 7,
    fontWeight: 600,
    letterSpacing: 0.8,
    marginBottom: 6,
    textTransform: "uppercase",
  },
  // Takumi sizes a chart's absolutely positioned labels into its parent, so
  // side-by-side chart panels take a fixed height and clip that overflow.
  chartPanel: { flex: 1, height: 232, overflow: "hidden" },
  formula: { color: theme.colors.foreground, fontSize: 12, fontWeight: 600, marginBottom: 6 },
});

const Kicker = ({ children }: { children: string }) => <Text style={styles.kicker} noMargin>{children}</Text>;

const Metric = (
  { label, value, note, signal = false }: { label: string; value: string; note: string; signal?: boolean },
) => (
  <View style={signal ? [styles.metric, styles.metricSignal] : styles.metric}>
    <Text style={styles.metricLabel} noMargin>{label}</Text>
    <Text style={styles.metricValue} noMargin>{value}</Text>
    <Text style={styles.metricNote} noMargin>{note}</Text>
  </View>
);

const Footer = ({ room }: { room: string }) => (
  <PageFooter
    variant="three-column"
    leftText={`${room} · Occupancy field report`}
    address="Data: L. Candanedo, UCI Occupancy Detection, CC BY 4.0"
    rightText={<PageNumber size="xs" align="right" format="Page {page} of {total}" />}
    sticky
    pagePadding={theme.spacing.page.marginLeft}
  />
);

const thresholdLabel = (row: ThresholdEvidence) => fixed(row.threshold, 1);

/** Thresholds on the 0.1 grid, so the chart labels stay legible. */
const tenths = (rows: readonly ThresholdEvidence[]) =>
  rows.filter((row) => Math.abs(row.threshold * 10 - Math.round(row.threshold * 10)) < 1e-6);

/** Three A4 pages that lay out the notebook's `occupancy_analysis` snapshot. */
export const OccupancyReport = ({ analysis }: { analysis: OccupancyAnalysis }) => {
  const { summary, model } = analysis;
  const occupied = summary.occupied > 0;
  const selected = model.evidence.find((row) => Math.abs(row.threshold - model.default_threshold) < 1e-6) ??
    model.evidence[0];
  const busiest = analysis.profile_summary.highest_occupancy_day;
  const widest = analysis.profile_summary.widest_sensor_separation;
  const period = `${momentLabel(summary.period_start)} – ${momentLabel(summary.period_end)}`;

  return (
    <PdfcnThemeProvider theme={theme}>
      <Document title={`${summary.room} occupancy field report`}>
        {/* Page 1: room use */}
        <Page size="A4" style={[styles.page, styles.pageBreak]}>
          <PageHeader
            variant="two-column"
            title="Occupancy field report"
            subtitle={`${summary.room} · ${summary.scope_label}`}
            rightText={period}
            rightSubText={`${grouped(summary.observations)} one-minute readings`}
            marginBottom={14}
          />
          <View style={styles.badges}>
            <Badge label={summary.scope_label} variant="primary" size="sm" />
            <Badge label="In-sample evidence" variant="outline" size="sm" />
          </View>

          <Kicker>01 / Room use</Kicker>
          <Heading level={2} noMargin>Room use summary</Heading>
          <Text variant="sm" color="mutedForeground">
            {occupied
              ? `${summary.room} was marked occupied in ${percent(summary.occupancy_rate)} of the selected readings. The report summarizes the room-use pattern, compares sensor conditions, and checks the occupancy score.`
              : `No reading in this scope is marked occupied. The report shows the vacant sensor profile and how the occupancy score behaves without occupied readings.`}
          </Text>

          <View style={styles.metrics}>
            <Metric label="Readings" value={grouped(summary.observations)} note={`${summary.reading_interval_minutes} min interval`} />
            <Metric label="Occupied" value={percent(summary.occupancy_rate)} note={`${grouped(summary.occupied)} readings`} signal />
            <Metric label="Occupied time" value={`${fixed(summary.estimated_occupied_hours, 1)} h`} note="Estimated from readings" />
            <Metric label="Score accuracy" value={percent(selected.accuracy)} note={`At threshold ${fixed(model.default_threshold, 2)}`} />
          </View>

          {occupied
            ? (
              <Section padding="none" spacing="sm" noWrap>
                <PdfGraph
                  variant="bar"
                  title="Occupied share by day"
                  subtitle="Share of each day's readings marked occupied"
                  data={analysis.daily_room_profile.map((row) => ({
                    label: `${weekday(row.day)} ${dayLabel(row.day).split(" ")[1]}`,
                    value: Math.round(row.occupancy_rate * 1000) / 10,
                    color: row.day === busiest.day && occupied ? chartColors.occupied : chartColors.vacant,
                  }))}
                  showValues
                  showGrid
                  legend="none"
                  yTicks={5}
                  height={150}
                  fullWidth
                  containerPadding={0}
                  wrapperPadding={0}
                />
              </Section>
            )
            : (
              <View style={[styles.panel, { backgroundColor: theme.colors.muted, borderColor: theme.colors.muted, marginBottom: 14 }]}>
                <Text style={styles.panelTitle} noMargin>Occupied share by day</Text>
                <Text variant="sm" color="mutedForeground" noMargin>
                  {`No reading in ${summary.scope_label.toLowerCase()} is marked occupied, so every day's occupied share is zero.`}
                </Text>
              </View>
            )}

          <View style={styles.row}>
            <View style={[styles.panel, { width: 196 }]}>
              <Text style={styles.panelTitle} noMargin>Readings by room state</Text>
              <PdfGraph
                variant="donut"
                data={[
                  { label: "Occupied", value: summary.occupied, color: chartColors.occupied },
                  { label: "Vacant", value: summary.observations - summary.occupied, color: chartColors.vacant },
                ]}
                centerLabel={percent(summary.occupancy_rate, 0)}
                legend="bottom"
                width={170}
                height={132}
                noWrap
              />
            </View>
            <View style={[styles.panel, styles.col]}>
              <Text style={styles.panelTitle} noMargin>What the record shows</Text>
              <PdfList
                variant="bullet"
                gap="sm"
                items={[
                  {
                    text: occupied
                      ? `${weekday(busiest.day)} ${dayLabel(busiest.day)} has the highest occupied share, at ${percent(busiest.occupancy_rate)} of ${grouped(busiest.observations)} readings.`
                      : `The room stays vacant across all ${grouped(summary.observations)} readings in this scope.`,
                  },
                  {
                    text: widest
                      ? `${widest.label} separates occupied from vacant readings most clearly, ${percent(widest.relative_separation ?? 0, 0)} of its observed range.`
                      : "No sensor separates the room states in this scope, because no reading is occupied.",
                  },
                  {
                    text: occupied
                      ? `At threshold ${fixed(model.default_threshold, 2)} the score finds ${percent(selected.recall)} of occupied readings with ${percent(selected.precision)} precision.`
                      : `At threshold ${fixed(model.default_threshold, 2)} the score stays below the threshold for ${percent(selected.accuracy)} of readings.`,
                  },
                ]}
              />
            </View>
          </View>
          <Footer room={summary.room} />
        </Page>

        {/* Page 2: sensor conditions */}
        <Page size="A4" style={[styles.page, styles.pageBreak]}>
          <Kicker>02 / Sensor conditions</Kicker>
          <Heading level={2} noMargin>Sensor conditions by room state</Heading>
          <Text variant="sm" color="mutedForeground">
            Each row compares the mean reading while the room was occupied with the mean while it was vacant.
            Separation is the gap between the two means as a share of the sensor's observed range.
          </Text>

          <DataTable
            variant="line"
            size="compact"
            columns={[
              { header: "Sensor", key: "label" },
              { align: "right", header: "Vacant mean", key: "vacant" },
              { align: "right", header: "Occupied mean", key: "occupied" },
              { align: "right", header: "Observed range", key: "range" },
              { align: "right", header: "Separation", key: "separation" },
            ]}
            data={analysis.sensor_profiles.map((sensor) => {
              const digits = sensor.key === "Temperature" || sensor.key === "Humidity" ? 1 : 0;
              const value = (reading: number) => `${fixed(reading, digits)} ${sensor.unit}`;
              return {
                label: sensor.label,
                occupied: sensor.occupied === null ? "—" : value(sensor.occupied),
                range: `${fixed(sensor.minimum, digits)}–${fixed(sensor.maximum, digits)} ${sensor.unit}`,
                separation: sensor.relative_separation === null ? "—" : percent(sensor.relative_separation, 0),
                vacant: value(sensor.vacant),
              };
            })}
          />

          <View style={[styles.row, { marginTop: 14 }]}>
            <View style={[styles.panel, styles.chartPanel]}>
              <PdfGraph
                variant="horizontal-bar"
                title="Separation by sensor"
                subtitle="Gap between occupied and vacant means"
                data={analysis.sensor_profiles.map((sensor) => ({
                  label: sensor.label,
                  value: Math.round((sensor.relative_separation ?? 0) * 100),
                  color: widest !== null && sensor.key === widest.key ? chartColors.occupied : chartColors.vacant,
                }))}
                showValues
                legend="none"
                width={226}
                height={160}
              />
            </View>
            <View style={[styles.panel, styles.chartPanel]}>
              <PdfGraph
                variant="area"
                title="Mean CO₂ by day"
                subtitle="ppm, all readings in scope"
                data={analysis.daily_room_profile.map((row) => ({
                  label: weekday(row.day),
                  value: Math.round(row.mean_co2),
                }))}
                colors={[chartColors.ink]}
                showDots
                smooth
                showGrid
                legend="none"
                yTicks={4}
                width={226}
                height={160}
              />
            </View>
          </View>

          <View style={{ marginTop: 16 }}>
            <Text style={styles.panelTitle} noMargin>Daily register</Text>
            <DataTable
              variant="striped"
              size="compact"
              stripe
              columns={[
                { header: "Day", key: "day" },
                { align: "right", header: "Readings", key: "observations" },
                { align: "right", header: "Occupied", key: "occupied" },
                { align: "right", header: "Share", key: "share" },
                { align: "right", header: "Mean CO₂", key: "meanCo2" },
                { align: "right", header: "Peak CO₂", key: "peakCo2" },
                { align: "right", header: "Mean temp", key: "temperature" },
              ]}
              data={analysis.daily_room_profile.map((row) => ({
                day: `${weekday(row.day)} ${dayLabel(row.day)}`,
                meanCo2: `${grouped(row.mean_co2)} ppm`,
                observations: grouped(row.observations),
                occupied: grouped(row.occupied),
                peakCo2: `${grouped(row.peak_co2)} ppm`,
                share: percent(row.occupancy_rate),
                temperature: `${fixed(row.mean_temperature, 1)} °C`,
              }))}
              footer={{
                day: "Scope",
                observations: grouped(summary.observations),
                occupied: grouped(summary.occupied),
                share: percent(summary.occupancy_rate),
              }}
            />
          </View>
          <Footer room={summary.room} />
        </Page>

        {/* Page 3: model evidence */}
        <Page size="A4" style={styles.page}>
          <Kicker>03 / Model evidence</Kicker>
          <Heading level={2} noMargin>Occupancy score evidence</Heading>
          <Text variant="sm" color="mutedForeground">
            A transparent score combines normalized light and CO₂ readings. Readings at or above the threshold
            count as occupied. The evidence is in-sample: the score is checked against the readings it describes.
          </Text>

          <View style={styles.row}>
            <View style={[styles.panel, styles.col, { backgroundColor: theme.colors.muted, borderColor: theme.colors.muted }]}>
              <Text style={styles.panelTitle} noMargin>Score</Text>
              <Text style={styles.formula} noMargin>
                {`score = ${fixed(model.light_weight, 1)} · light + ${fixed(model.co2_weight, 1)} · CO₂`}
              </Text>
              <KeyValue
                size="sm"
                divided
                items={[
                  { key: "Light scale", value: `0–${grouped(model.normalization.light_max)} lux` },
                  { key: "CO₂ scale", value: `${grouped(model.normalization.co2_min)}–${grouped(model.normalization.co2_max)} ppm` },
                  { key: "Scale limit", value: `${percent(model.normalization_quantile, 0)} quantile` },
                ]}
              />
            </View>
            <View style={[styles.panel, styles.col]}>
              <Text style={styles.panelTitle} noMargin>{`At threshold ${fixed(selected.threshold, 2)}`}</Text>
              <KeyValue
                size="sm"
                divided
                items={[
                  { key: "True occupied", value: grouped(selected.true_positive) },
                  { key: "False occupied", value: grouped(selected.false_positive), valueColor: chartColors.occupied },
                  { key: "False vacant", value: grouped(selected.false_negative), valueColor: chartColors.occupied },
                  { key: "True vacant", value: grouped(selected.true_negative) },
                  { key: "Accuracy", value: percent(selected.accuracy) },
                  { key: "Recall", value: occupied ? percent(selected.recall) : "—" },
                ]}
              />
            </View>
          </View>

          <View style={[styles.panel, { marginTop: 14 }]}>
            <PdfGraph
              variant="line"
              title="Classification quality by threshold"
              subtitle="Accuracy, precision, and recall in percent"
              data={[
                { name: "Accuracy", color: chartColors.ink, data: tenths(model.evidence).map((row) => ({ label: thresholdLabel(row), value: Math.round(row.accuracy * 1000) / 10 })) },
                { name: "Precision", color: chartColors.vacant, data: tenths(model.evidence).map((row) => ({ label: thresholdLabel(row), value: Math.round(row.precision * 1000) / 10 })) },
                { name: "Recall", color: chartColors.occupied, data: tenths(model.evidence).map((row) => ({ label: thresholdLabel(row), value: Math.round(row.recall * 1000) / 10 })) },
              ]}
              legend="bottom"
              showGrid
              yTicks={5}
              height={150}
              fullWidth
              containerPadding={24}
              wrapperPadding={12}
              noWrap
            />
          </View>

          <View style={{ marginTop: 16 }}>
            <Text style={styles.panelTitle} noMargin>Errors farthest from the threshold</Text>
            {selected.errors.length === 0
              ? <Text variant="sm" color="mutedForeground">Every reading in this scope is classified correctly at this threshold.</Text>
              : (
                <DataTable
                  variant="line"
                  size="compact"
                  columns={[
                    { header: "Reading", key: "reading" },
                    { header: "Outcome", key: "outcome", width: "22%" },
                    { align: "right", header: "Light", key: "light" },
                    { align: "right", header: "CO₂", key: "co2" },
                    { align: "right", header: "Score", key: "score" },
                    { align: "right", header: "Distance", key: "distance" },
                  ]}
                  data={selected.errors.slice(0, 5).map((row) => ({
                    co2: `${grouped(row.CO2)} ppm`,
                    distance: fixed(row.distance, 2),
                    light: `${grouped(row.Light)} lux`,
                    outcome: row.outcome === "false positive" ? "False occupied" : "False vacant",
                    reading: momentLabel(row.date.replace("T", " ")),
                    score: fixed(row.score, 2),
                  }))}
                />
              )}
          </View>
          <Footer room={summary.room} />
        </Page>
      </Document>
    </PdfcnThemeProvider>
  );
};
