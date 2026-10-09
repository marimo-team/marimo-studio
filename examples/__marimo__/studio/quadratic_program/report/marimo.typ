// Read notebook values, outputs, and cells that Studio passes to this document.
//
// marimo_value("selector") returns the current notebook value. The selector
// names a notebook variable, optionally followed by .field and [index] steps.
// A table arrives as an array of row dictionaries, and a date or time as ISO
// 8601 text. Outside Studio, while a value is unavailable, and when it is
// none, marimo_value() returns `default`.
#let _values = json(bytes(sys.inputs.at("marimo-values", default: "{}")))

#let marimo_value(selector, default: none) = {
  let value = _values.at(selector, default: none)
  if value == none { default } else { value }
}

// marimo_output("selector") places a notebook value, such as a matplotlib
// figure or an Altair chart, as an image with image(). Studio renders it as a
// PDF, or as SVG, PNG, JPEG, WebP, or GIF when the value has no PDF form, and
// draws a figure at the width it is placed at, so its text keeps its point
// size. Named arguments such as width, height, fit, and alt pass through to
// image(). Outside Studio, or while the output is unavailable,
// marimo_output() returns `default`.
#let _outputs = json(bytes(sys.inputs.at("marimo-outputs", default: "{}")))

// Studio's build queries these records for the size each output is placed at.
#let _placed(selector, args, size) = {
  let width = args.at("width", default: auto)
  let absolute = if width == auto {
    size.width
  } else if type(width) == ratio {
    width * size.width
  } else if type(width) == relative {
    width.ratio * size.width + width.length
  } else {
    width
  }
  let height = args.at("height", default: auto)
  let record = (target: selector, width: absolute.to-absolute().pt())
  if type(height) == length { record.insert("height", height.to-absolute().pt()) }
  [#metadata(record) <marimo-size>]
}

#let marimo_output(selector, default: none, ..args) = layout(size => {
  _placed(selector, args.named(), size)
  let path = _outputs.at(selector, default: none)
  if path == none { default } else { image(path, ..args) }
})

// marimo_cell("name") places the output of the notebook cell with that name as
// marimo shows it, when that output is an image, such as a matplotlib figure.
// Named arguments pass through to image(). Outside Studio, or while the cell
// shows no image, marimo_cell() returns `default`.
#let _cells = json(bytes(sys.inputs.at("marimo-cells", default: "{}")))

#let marimo_cell(name, default: none, ..args) = {
  let path = _cells.at(name, default: none)
  if path == none { default } else { image(path, ..args) }
}
