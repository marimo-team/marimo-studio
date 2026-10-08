const integer = new Intl.NumberFormat("en", { maximumFractionDigits: 0 });
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export const grouped = (value: number) => integer.format(value);

export const fixed = (value: number, digits: number) => value.toFixed(digits);

export const percent = (share: number, digits = 1) => `${(share * 100).toFixed(digits)}%`;

const parts = (stamp: string) => {
  const date = new Date(`${stamp.slice(0, 10)}T00:00:00Z`);
  return { date, month: MONTHS[date.getUTCMonth()], day: date.getUTCDate() };
};

/** `2015-02-04` or `2015-02-04T17:51:00` as `Feb 4`. */
export const dayLabel = (stamp: string) => {
  const { month, day } = parts(stamp);
  return `${month} ${day}`;
};

/** `2015-02-04` as `Wed`. */
export const weekday = (stamp: string) => WEEKDAYS[parts(stamp).date.getUTCDay()];

/** `2015-02-04 17:51` as `Feb 4, 17:51`. */
export const momentLabel = (stamp: string) => `${dayLabel(stamp)}, ${stamp.slice(11, 16)}`;
