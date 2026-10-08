// Palette and number formatting of the report.

#let ink = rgb("#171717")
#let muted = rgb("#666666")
#let rule = rgb("#e4e4e4")
#let region-fill = rgb("#eef0f3")
#let data = rgb("#b33a2e")

// Fixed decimals with a true minus sign. Values within rounding of zero print
// as zero, so solver residue such as 2e-9 reads as 0.000.
#let num(value, digits: 3) = {
  let scaled = calc.round(value, digits: digits)
  if calc.abs(scaled) < calc.pow(10.0, -digits) / 2 { scaled = 0.0 }
  let text = str(calc.abs(scaled))
  let parts = text.split(".")
  let decimals = if parts.len() > 1 { parts.at(1) } else { "" }
  let body = if digits == 0 { parts.first() } else {
    parts.first() + "." + decimals + "0" * calc.max(digits - decimals.len(), 0)
  }
  if scaled < 0 { "−" + body } else { body }
}
