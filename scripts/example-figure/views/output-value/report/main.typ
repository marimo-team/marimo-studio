#set page(width: 12cm, height: auto, margin: 1.2cm)
#set text(font: "Libertinus Serif", size: 11pt)

#import "marimo.typ": marimo_output, marimo_value

#marimo_output("problem_figure", width: 100%)
The optimal value is #marimo_value("solution.value", default: 0).
