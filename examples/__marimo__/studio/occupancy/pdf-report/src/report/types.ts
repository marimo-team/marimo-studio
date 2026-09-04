export interface ReportPeriod {
  readonly start: string;
  readonly end: string;
  readonly scope_label: string;
  readonly observations: number;
  readonly occupied: number;
  readonly occupancy_rate: number;
  readonly reading_interval_minutes: number;
  readonly estimated_occupied_hours: number;
}

export interface OccupancySummary {
  readonly room: string;
  readonly scope_label: string;
  readonly period_start: string;
  readonly period_end: string;
  readonly observations: number;
  readonly occupied: number;
  readonly occupancy_rate: number;
  readonly reading_interval_minutes: number;
  readonly estimated_occupied_hours: number;
}

export interface HourlyReading {
  readonly timestamp: string;
  readonly occupancy_rate: number;
  readonly co2: number;
  readonly temperature: number;
  readonly humidity: number;
  readonly light: number;
}

export interface DailyReading {
  readonly day: string;
  readonly observations: number;
  readonly occupied: number;
  readonly occupancy_rate: number;
  readonly mean_co2: number;
  readonly peak_co2: number;
  readonly mean_temperature: number;
}

export interface SensorProfile {
  readonly key: string;
  readonly label: string;
  readonly unit: string;
  readonly vacant: number;
  readonly occupied: number | null;
  readonly minimum: number;
  readonly maximum: number;
  readonly relative_separation: number | null;
}

export interface ThresholdPoint {
  readonly threshold: number;
  readonly accuracy: number;
  readonly precision: number;
  readonly recall: number;
}

export interface ReportError {
  readonly date: Date | string | number | bigint;
  readonly outcome: "false positive" | "false negative";
  readonly score: number;
  readonly Occupancy: number;
  readonly predicted: number;
  readonly Temperature: number;
  readonly Humidity: number;
  readonly Light: number;
  readonly CO2: number;
  readonly distance: number;
}

export interface ModelReport {
  readonly threshold: number;
  readonly accuracy: number;
  readonly precision: number;
  readonly recall: number;
  readonly true_positive: number;
  readonly true_negative: number;
  readonly false_positive: number;
  readonly false_negative: number;
  readonly normalization: {
    readonly light_min: number;
    readonly light_max: number;
    readonly co2_min: number;
    readonly co2_max: number;
  };
  readonly curve: readonly ThresholdPoint[];
  readonly errors: readonly ReportError[];
}

export type ModelEvidence = Omit<ModelReport, "curve" | "normalization">;

export interface PreparedModel {
  readonly default_threshold: number;
  readonly normalization: ModelReport["normalization"];
  readonly evidence: readonly ModelEvidence[];
}

export interface RoomProfileSummary {
  readonly highest_occupancy_day: DailyReading;
  readonly widest_sensor_separation: SensorProfile | null;
}

export interface OccupancyReportData {
  readonly room: string;
  readonly period: ReportPeriod;
  readonly hourly: readonly HourlyReading[];
  readonly daily: readonly DailyReading[];
  readonly sensors: readonly SensorProfile[];
  readonly profile_summary: RoomProfileSummary;
  readonly model: ModelReport;
}
