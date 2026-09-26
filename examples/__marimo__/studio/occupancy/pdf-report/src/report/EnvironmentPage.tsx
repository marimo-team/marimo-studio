import { Page, Text, View } from "@react-pdf/renderer";

import { SectionHeading, Topline } from "./ReportFrame.tsx";
import { RoomDiagram } from "./OccupancyVisuals.tsx";
import { styles } from "./styles.ts";
import {
  formatDay,
  formatMeasure,
  formatPercent,
  palette,
  typefaces,
} from "./theme.ts";
import type { OccupancyReportData, SensorProfile } from "./types.ts";

const SensorRow = ({ sensor }: { sensor: SensorProfile }) => {
  const span = Math.max(sensor.maximum - sensor.minimum, 1);
  const vacant = (sensor.vacant - sensor.minimum) / span;
  const occupied = sensor.occupied === null
    ? null
    : (sensor.occupied - sensor.minimum) / span;
  const vacantPosition = `${Math.min(Math.max(vacant * 100, 0), 99)}%`;
  const occupiedPosition = occupied === null
    ? null
    : `${Math.min(Math.max(occupied * 100, 0), 98)}%`;

  return (
    <View
      style={{
        paddingVertical: 7,
        borderBottomWidth: 0.6,
        borderBottomColor: palette.rule,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "baseline",
          justifyContent: "space-between",
        }}
      >
        <Text
          style={{ fontFamily: typefaces.body, fontSize: 8, fontWeight: 600 }}
        >
          {sensor.label}
        </Text>
        <Text style={styles.meta}>{sensor.unit}</Text>
      </View>
      <View
        style={{
          position: "relative",
          height: 11,
          marginTop: 7,
        }}
      >
        <View
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 5,
            height: 1,
            backgroundColor: palette.rule,
          }}
        />
        <View
          style={{
            position: "absolute",
            left: vacantPosition,
            top: 1.5,
            width: 1.5,
            height: 8,
            backgroundColor: palette.slate,
          }}
        />
        {occupied === null ? null : (
          <View
            style={{
              position: "absolute",
              left: occupiedPosition ?? 0,
              top: 2,
              width: 7,
              height: 7,
              borderRadius: 3.5,
              backgroundColor: palette.orange,
            }}
          />
        )}
      </View>
      <View
        style={{
          flexDirection: "row",
          justifyContent: "space-between",
          marginTop: 2,
        }}
      >
        <Text style={[styles.meta, { color: palette.slate }]}>
          VACANT · {formatMeasure(sensor.vacant, sensor.unit)}
        </Text>
        {sensor.occupied === null
          ? null
          : (
            <Text style={[styles.meta, { color: palette.orange }]}>
              OCCUPIED · {formatMeasure(sensor.occupied, sensor.unit)}
            </Text>
          )}
      </View>
    </View>
  );
};

export const EnvironmentPage = (
  { report }: { report: OccupancyReportData },
) => {
  const hasOccupiedReadings = report.period.occupied > 0;
  const strongestSensor = report.profile_summary.widest_sensor_separation;

  return (
    <Page size="A4" style={styles.page}>
      <Topline section="02 / 03 · Sensor conditions" />
      <View style={{ flexDirection: "row", gap: 18, alignItems: "flex-end" }}>
        <View style={{ flex: 1 }}>
          <Text style={styles.pageTitle}>
            {hasOccupiedReadings
              ? <>Sensor conditions{"\n"}by room state.</>
              : <>Vacant conditions{"\n"}in this scope.</>}
          </Text>
          <Text style={[styles.pageLead, { width: "100%" }]}>
            {hasOccupiedReadings
              ? "Each row compares the mean reading when the room was occupied with the mean when it was vacant. Compare the gap within a row because each sensor uses its own scale."
              : "The selected scope contains no occupied readings. Each row places the vacant mean within that sensor's observed range."}
          </Text>
        </View>
        <View style={{ width: 225 }}>
          <RoomDiagram />
        </View>
      </View>

      <View style={{ marginTop: 11 }}>
        <SectionHeading
          index="02.1 / SENSOR SEPARATION"
          title={hasOccupiedReadings
            ? "Mean readings by room state"
            : "Vacant means within the observed range"}
          note={hasOccupiedReadings
            ? "Slate tick: vacant mean. Orange dot: occupied mean."
            : "The slate tick shows the vacant mean within each sensor's observed range."}
        />
        <View style={[styles.panelWhite, { paddingTop: 3, paddingBottom: 3 }]}>
          {report.sensors.map((sensor) => (
            <SensorRow key={sensor.key} sensor={sensor} />
          ))}
        </View>
      </View>

      <View style={{ marginTop: 15 }}>
        <SectionHeading
          index="02.2 / DAILY REGISTER"
          title="Daily occupancy and CO2"
          note="Each card pairs occupied share with mean and peak CO2."
        />
        <View style={{ flexDirection: "row", gap: 6 }}>
          {report.daily.map((day) => (
            <View
              key={day.day}
              style={{
                flex: 1,
                minHeight: 86,
                padding: 8,
                backgroundColor: palette.paper,
                borderWidth: 0.6,
                borderColor: palette.rule,
                borderRadius: 6,
              }}
            >
              <Text style={styles.meta}>
                {formatDay(day.day).toUpperCase()}
              </Text>
              <Text
                style={{
                  marginTop: 6,
                  color: palette.orange,
                  fontFamily: typefaces.display,
                  fontSize: 19,
                  lineHeight: 1,
                }}
              >
                {formatPercent(day.occupancy_rate, 0)}
              </Text>
              <Text style={[styles.caption, { marginTop: 4 }]}>occupied</Text>
              <View
                style={{
                  marginTop: 6,
                  paddingTop: 5,
                  borderTopWidth: 0.6,
                  borderTopColor: palette.rule,
                }}
              >
                <Text style={[styles.caption, { marginTop: 0 }]}>
                  MEAN {day.mean_co2.toFixed(0)} PPM
                </Text>
                <Text style={[styles.caption, { marginTop: 3 }]}>
                  PEAK {day.peak_co2.toFixed(0)} PPM
                </Text>
              </View>
            </View>
          ))}
        </View>
      </View>

      <View
        wrap={false}
        style={{
          marginTop: 13,
          padding: 12,
          backgroundColor: palette.ink,
          borderRadius: 7,
        }}
      >
        <Text style={[styles.panelLabel, { color: palette.orange }]}>
          INTERPRETATION
        </Text>
        <Text
          style={{
            color: palette.paper,
            fontFamily: typefaces.display,
            fontSize: 11.5,
            letterSpacing: -0.15,
            lineHeight: 1.4,
          }}
        >
          {hasOccupiedReadings
            ? `${
              strongestSensor?.label ?? "The leading sensor"
            } has the widest occupied-vacant gap relative to its observed range. The notebook score combines light and CO2, so review both signals when classifications change.`
            : "These readings form an off-hours vacant reference profile for all four sensors. Compare that profile with an occupied scope before changing the score threshold."}
        </Text>
      </View>
    </Page>
  );
};
