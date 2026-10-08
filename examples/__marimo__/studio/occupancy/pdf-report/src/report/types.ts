/** The notebook's `occupancy_analysis` snapshot, as JSON. */
export interface OccupancyAnalysis {
  readonly selection: { readonly scope: string };
  readonly summary: {
    readonly room: string;
    readonly scope_label: string;
    readonly period_start: string;
    readonly period_end: string;
    readonly observations: number;
    readonly occupied: number;
    readonly occupancy_rate: number;
    readonly reading_interval_minutes: number;
    readonly estimated_occupied_hours: number;
  };
  readonly hourly_room_profile: readonly HourlyReading[];
  readonly daily_room_profile: readonly DailyReading[];
  readonly sensor_profiles: readonly SensorProfile[];
  readonly profile_summary: {
    readonly highest_occupancy_day: DailyReading;
    readonly widest_sensor_separation: SensorProfile | null;
  };
  readonly model: {
    readonly co2_weight: number;
    readonly light_weight: number;
    readonly default_threshold: number;
    readonly normalization_quantile: number;
    readonly normalization: {
      readonly light_max: number;
      readonly co2_min: number;
      readonly co2_max: number;
    };
    readonly evidence: readonly ThresholdEvidence[];
  };
}

export interface HourlyReading {
  readonly timestamp: string;
  readonly occupancy_rate: number;
  readonly co2: number;
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

export interface ThresholdEvidence {
  readonly threshold: number;
  readonly accuracy: number;
  readonly precision: number;
  readonly recall: number;
  readonly true_positive: number;
  readonly true_negative: number;
  readonly false_positive: number;
  readonly false_negative: number;
  readonly errors: readonly ModelError[];
}

export interface ModelError {
  readonly date: string;
  readonly outcome: "false positive" | "false negative";
  readonly Light: number;
  readonly CO2: number;
  readonly score: number;
  readonly distance: number;
}
