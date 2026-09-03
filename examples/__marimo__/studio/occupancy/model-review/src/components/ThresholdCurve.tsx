import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type ThresholdMetric = {
  threshold: number;
  accuracy: number;
  precision: number;
  recall: number;
  true_positive: number;
  true_negative: number;
  false_positive: number;
  false_negative: number;
};

const rate = new Intl.NumberFormat("en", {
  style: "percent",
  maximumFractionDigits: 1,
});
const labels: Record<string, string> = {
  accuracy: "Accuracy",
  precision: "Precision",
  recall: "Recall",
};

export const formatRate = (value: number) => rate.format(value);

export const ThresholdCurve = ({
  current,
  metrics,
  showRecall = true,
}: {
  current?: number;
  metrics: ThresholdMetric[];
  showRecall?: boolean;
}) => (
  <div
    className="chart"
    role="img"
    aria-label={showRecall
      ? "In-sample accuracy, precision, and recall by occupancy threshold"
      : "In-sample accuracy and precision by occupancy threshold. Recall is unavailable for this scope."}
  >
    {metrics.length > 0
      ? (
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={metrics}
            margin={{ top: 8, right: 16, bottom: 8, left: 0 }}
            accessibilityLayer
          >
            <CartesianGrid
              stroke="#ddd9d2"
              strokeDasharray="2 4"
              vertical={false}
            />
            <XAxis
              dataKey="threshold"
              type="number"
              domain={[0.1, 0.9]}
              tickFormatter={(value) => Number(value).toFixed(1)}
            />
            <YAxis
              domain={[0, 1]}
              tickFormatter={(value) => formatRate(Number(value))}
              width={48}
            />
            <Tooltip
              formatter={(value, name) => [
                formatRate(Number(value)),
                labels[String(name)] ?? String(name),
              ]}
              labelFormatter={(value) =>
                `Threshold ${Number(value).toFixed(2)}`}
            />
            <Legend
              verticalAlign="top"
              height={34}
              formatter={(value) => labels[String(value)] ?? String(value)}
            />
            {current === undefined ? null : (
              <ReferenceLine
                x={current}
                stroke="#121212"
                strokeDasharray="5 4"
              />
            )}
            <Line
              type="monotone"
              dataKey="accuracy"
              stroke="#4b7654"
              strokeWidth={2.5}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="precision"
              stroke="#31543a"
              strokeDasharray="8 4"
              strokeWidth={2.5}
              dot={false}
              isAnimationActive={false}
            />
            {showRecall
              ? (
                <Line
                  type="monotone"
                  dataKey="recall"
                  stroke="#7b8e72"
                  strokeDasharray="2 4"
                  strokeWidth={2.5}
                  dot={false}
                  isAnimationActive={false}
                />
              )
              : null}
          </LineChart>
        </ResponsiveContainer>
      )
      : <p className="empty-state">No threshold metrics are available.</p>}
  </div>
);
