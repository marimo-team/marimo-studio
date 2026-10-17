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
// draws a figure at the width, height, or both it is placed at, so its text
// keeps its point size. Named arguments such as width, height, fit, and alt pass through to
// image(). Outside Studio, or while the output is unavailable,
// marimo_output() returns `default`.
#let _outputs = json(bytes(sys.inputs.at("marimo-outputs", default: "{}")))

// Studio's build queries these records for the size each output is placed at.
#let _placed(selector, args, size) = {
  let width = args.at("width", default: auto)
  let height = args.at("height", default: auto)
  let record = (target: selector)
  // A height alone places the output by height, and its aspect ratio sets the
  // width.
  if width != auto or type(height) != length {
    let absolute = if width == auto {
      size.width
    } else if type(width) == ratio {
      width * size.width
    } else if type(width) == relative {
      width.ratio * size.width + width.length
    } else {
      width
    }
    record.insert("width", absolute.to-absolute().pt())
  }
  if type(height) == length { record.insert("height", height.to-absolute().pt()) }
  [#metadata(record) <marimo-size>]
}

// While Studio renders, it queries these records for the part of a page each
// output, cell, and region covers, so a reader can select the part in the
// page and trace it to the cells that computed it. A start and an end record
// mark the top left and bottom right corner of the part, in points from the
// page's top left corner.
#let _regions = sys.inputs.at("marimo-regions", default: none) != none

#let _corner(edge, reads, natural: none, label: none) = context {
  let position = here().position()
  [#metadata((
    edge: edge,
    reads: reads,
    label: label,
    page: position.page,
    x: position.x.pt(),
    y: position.y.pt(),
    natural: natural,
  )) <marimo-region>]
}

// A box keeps inline content in its paragraph, inside Studio and out. An
// image with a fixed width can overflow its container, which clips the box,
// so a placed image also records the size it measures at on its own.
#let _located(reads, body, label: none, picture: false) = box({
  if _regions {
    place(top + left, context {
      let natural = if picture {
        let size = measure(body)
        (width: size.width.pt(), height: size.height.pt())
      }
      _corner("start", reads, natural: natural, label: label)
    })
  }
  body
  if _regions { place(bottom + right, _corner("end", reads)) }
})

#let marimo_output(selector, default: none, ..args) = layout(size => {
  _placed(selector, args.named(), size)
  let path = _outputs.at(selector, default: none)
  if path == none { default } else { _located((selector,), image(path, ..args), picture: true) }
})

// marimo_cell("name") places the output of the notebook cell with that name as
// marimo shows it, when that output is an image, such as a matplotlib figure.
// Named arguments pass through to image(). Outside Studio, or while the cell
// shows no image, marimo_cell() returns `default`.
#let _cells = json(bytes(sys.inputs.at("marimo-cells", default: "{}")))

#let marimo_cell(name, default: none, ..args) = {
  let path = _cells.at(name, default: none)
  if path == none { default } else { _located((name,), image(path, ..args), picture: true) }
}

// marimo_region("selector", ..., body) marks body as the part of the document
// that shows those notebook values, such as a table built from
// marimo_value("rows"). In Studio a reader can select it in the page and trace
// it to the cells that computed them. Each selector names a value the document
// reads with marimo_value(), optionally followed by .field and [index] steps,
// such as "rows[0]". marimo_region() places body in a box, which keeps it in
// its paragraph and on one page.
#let marimo_region(..args, label: none) = {
  assert(args.pos().len() >= 2, message: "marimo_region() takes one or more selectors, then its body")
  let (..reads, body) = args.pos()
  _located(reads, body, label: label)
}
