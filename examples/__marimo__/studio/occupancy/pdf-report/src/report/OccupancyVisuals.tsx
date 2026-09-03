import { Circle, G, Line, Path, Rect, Svg, Text } from "@react-pdf/renderer";

import { palette, typefaces } from "./theme.ts";
import type { HourlyReading } from "./types.ts";

const clamp = (value: number, low: number, high: number) =>
  Math.min(Math.max(value, low), high);

export const OccupancyDial = ({ rate }: { rate: number }) => {
  const radius = 43;
  const circumference = 2 * Math.PI * radius;
  const occupied = clamp(rate, 0, 1) * circumference;

  return (
    <Svg width={126} height={126} viewBox="0 0 126 126">
      <Circle
        cx={63}
        cy={63}
        r={radius}
        fill="none"
        stroke={palette.rule}
        strokeWidth={9}
      />
      {occupied > 0
        ? (
          <Circle
            cx={63}
            cy={63}
            r={radius}
            fill="none"
            stroke={palette.orange}
            strokeWidth={9}
            strokeDasharray={`${occupied} ${circumference}`}
            strokeLinecap="round"
            transform="rotate(-90 63 63)"
          />
        )
        : null}
      <Text
        x={63}
        y={70}
        textAnchor="middle"
        style={{
          fill: palette.ink,
          fontFamily: typefaces.display,
          fontSize: 28,
        }}
      >
        {`${(clamp(rate, 0, 1) * 100).toFixed(0)}%`}
      </Text>
    </Svg>
  );
};

type SignalLabelProps = {
  readonly anchor: "start" | "end";
  readonly label: string;
  readonly labelX: number;
  readonly labelY: number;
  readonly lineX: number;
  readonly nodeX: number;
  readonly nodeY: number;
  readonly unit: string;
};

const SignalLabel = ({
  anchor,
  label,
  labelX,
  labelY,
  lineX,
  nodeX,
  nodeY,
  unit,
}: SignalLabelProps) => (
  <G>
    <Line
      x1={lineX}
      y1={labelY - 2}
      x2={nodeX}
      y2={nodeY}
      stroke={palette.fog}
      strokeWidth={0.9}
    />
    <Circle
      cx={nodeX}
      cy={nodeY}
      r={3.4}
      fill={palette.paper}
      stroke={palette.ink}
      strokeWidth={0.9}
    />
    <Circle cx={nodeX} cy={nodeY} r={1.45} fill={palette.orange} />
    <Text
      x={labelX}
      y={labelY}
      textAnchor={anchor}
      style={{
        fill: palette.ink,
        fontFamily: typefaces.body,
        fontSize: 13,
        fontWeight: 600,
        letterSpacing: 0.35,
      }}
    >
      {label}
    </Text>
    <Text
      x={labelX}
      y={labelY + 9}
      textAnchor={anchor}
      style={{
        fill: palette.fog,
        fontFamily: typefaces.body,
        fontSize: 10,
        fontWeight: 500,
        letterSpacing: 0.2,
      }}
    >
      {unit}
    </Text>
  </G>
);

export const RoomDiagram = () => (
  <Svg width="100%" height={118} viewBox="0 0 480 158">
    <Rect
      x={92}
      y={20}
      width={296}
      height={118}
      rx={2}
      fill={palette.mist}
      stroke={palette.ink}
      strokeWidth={1.2}
    />
    <Rect
      x={101}
      y={29}
      width={278}
      height={100}
      fill={palette.paper}
      stroke={palette.rule}
      strokeWidth={0.8}
    />

    <G fill={palette.paper} stroke={palette.slate} strokeWidth={0.9}>
      <Rect x={229} y={38} width={22} height={9} rx={4.5} />
      <Rect x={229} y={111} width={22} height={9} rx={4.5} />
      <Rect x={151} y={68} width={9} height={22} rx={4.5} />
      <Rect x={320} y={68} width={9} height={22} rx={4.5} />
    </G>
    <Rect
      x={169}
      y={54}
      width={142}
      height={50}
      rx={2}
      fill={palette.paper}
      stroke={palette.ink}
      strokeWidth={1}
    />
    <Line
      x1={240}
      y1={54}
      x2={240}
      y2={104}
      stroke={palette.rule}
      strokeWidth={0.8}
    />
    <Text
      x={240}
      y={82}
      textAnchor="middle"
      style={{
        fill: palette.fog,
        fontFamily: typefaces.body,
        fontSize: 11,
        fontWeight: 500,
        letterSpacing: 0.65,
      }}
    >
      ROOM 01
    </Text>

    <Path
      d="M101 108 H117 M117 129 V113 M117 113 A16 16 0 0 1 133 129"
      fill="none"
      stroke={palette.slate}
      strokeWidth={0.9}
    />
    <G fill={palette.orange}>
      <Circle cx={240} cy={116} r={4.2} />
      <Path d="M233 129 C233 121 247 121 247 129 Z" />
    </G>

    <SignalLabel
      anchor="start"
      label="CO2"
      labelX={8}
      labelY={24}
      lineX={51}
      nodeX={110}
      nodeY={35}
      unit="ppm"
    />
    <SignalLabel
      anchor="end"
      label="LIGHT"
      labelX={472}
      labelY={24}
      lineX={426}
      nodeX={370}
      nodeY={35}
      unit="lux"
    />
    <SignalLabel
      anchor="start"
      label="TEMP"
      labelX={8}
      labelY={135}
      lineX={51}
      nodeX={110}
      nodeY={122}
      unit="°C"
    />
    <SignalLabel
      anchor="end"
      label="HUMIDITY"
      labelX={472}
      labelY={135}
      lineX={390}
      nodeX={370}
      nodeY={122}
      unit="% RH"
    />
  </Svg>
);

export const OccupancyTimeline = (
  { rows }: { rows: readonly HourlyReading[] },
) => {
  const width = 500;
  const height = 120;
  const chartTop = 10;
  const chartBottom = 100;
  const plotHeight = chartBottom - chartTop;
  const co2Values = rows.map((row) => row.co2);
  const co2Min = Math.min(...co2Values);
  const co2Max = Math.max(...co2Values);
  const step = width / Math.max(rows.length, 1);
  const points = rows.map((row, index) => {
    const x = index * step + step / 2;
    const ratio = (row.co2 - co2Min) / Math.max(co2Max - co2Min, 1);
    const y = chartBottom - ratio * plotHeight;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  return (
    <Svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
      {[0.5, 1].map((ratio) => (
        <Line
          key={ratio}
          x1={0}
          y1={chartBottom - ratio * plotHeight}
          x2={width}
          y2={chartBottom - ratio * plotHeight}
          stroke={palette.rule}
          strokeWidth={0.7}
        />
      ))}
      {rows.map((row, index) => {
        const barHeight = clamp(row.occupancy_rate, 0, 1) * plotHeight;
        return (
          <Rect
            key={row.timestamp}
            x={index * step + 0.5}
            y={chartBottom - barHeight}
            width={Math.max(step - 1, 1)}
            height={barHeight}
            fill={palette.orange}
            opacity={0.32 + row.occupancy_rate * 0.58}
          />
        );
      })}
      <Path
        d={`M ${points.replaceAll(" ", " L ")}`}
        fill="none"
        stroke={palette.ink}
        strokeWidth={1.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <Line
        x1={0}
        y1={chartBottom}
        x2={width}
        y2={chartBottom}
        stroke={palette.ink}
        strokeWidth={0.8}
      />
    </Svg>
  );
};
