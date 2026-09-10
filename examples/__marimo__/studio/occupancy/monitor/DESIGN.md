# Environmental monitor

The monitor lets facilities staff select an observation scope and sensor, read
the current measurements, and compare the signal with its rolling baseline.

## Color

Use a cool neutral canvas (`#f8f9fb`), white chart surfaces, slate text
(`#273444`), muted labels (`#647181`), and fine gray rules (`#dfe4ea`). Blue
(`#426e86`) identifies sensor readings and occupancy bars. The baseline is gray
(`#8793a0`) and anomaly markers are muted amber (`#a26d36`). Keep amber local to
anomaly values and plotted evidence. ECharts reads these CSS tokens.

## Layout and typography

Use DM Sans for headings, labels, and measurements, with tabular numerals for
comparing values. Keep the scope and reading count as plain text beside the
title. Place the native scope and signal controls in one compact filter row.

Arrange the four measurements in a strip separated by fine rules. Show sensor
history directly after those measurements, in one white panel with a fine border
and four-pixel corners. Place the daily occupancy profile below the chart, using
aligned columns and short bars.

On phones, stack the header and controls, use two metric columns when they fit,
and wrap supporting text. At the narrowest widths, metrics and daily readings
form one column. Preserve touch targets and readable chart labels.

## Behavior

The notebook owns the data, baseline, anomaly definitions, and native controls.
The view formats those results and renders ECharts. Keep loading and error
messages visible. Honor reduced motion and release chart observers on unmount.
