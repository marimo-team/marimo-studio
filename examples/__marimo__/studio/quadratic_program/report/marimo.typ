// Read notebook values, outputs, and cells that Studio passes to this document.
//
// marimo_value("selector") returns the current notebook value. The selector
// names a notebook variable, optionally followed by .field and [index] steps.
// Outside Studio, or while a value is unavailable, marimo_value() returns
// `default`.
#let _values = json(bytes(sys.inputs.at("marimo-values", default: "{}")))

#let marimo_value(selector, default: none) = _values.at(selector, default: default)

#let _image(paths, target, default, args) = {
  let path = paths.at(target, default: none)
  if path == none { default } else { image(path, ..args) }
}

// marimo_output("selector") places a notebook value, such as a matplotlib
// figure or an Altair chart, as an image with image(). Studio renders it as a
// PDF, or as SVG, PNG, JPEG, WebP, or GIF when the value has no PDF form.
// Named arguments such as width, height, fit, and alt pass through to image().
// Outside Studio, or while the output is unavailable, marimo_output() returns
// `default`.
#let _outputs = json(bytes(sys.inputs.at("marimo-outputs", default: "{}")))

#let marimo_output(selector, default: none, ..args) = _image(_outputs, selector, default, args)

// marimo_cell("name") places the output of the notebook cell with that name as
// marimo shows it, when that output is an image, such as a matplotlib figure.
// Named arguments pass through to image(). Outside Studio, or while the cell
// shows no image, marimo_cell() returns `default`.
#let _cells = json(bytes(sys.inputs.at("marimo-cells", default: "{}")))

#let marimo_cell(name, default: none, ..args) = _image(_cells, name, default, args)
