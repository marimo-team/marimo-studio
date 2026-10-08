#import "marimo.typ": marimo_output, marimo_value
#import "style.typ": *

#let solution = marimo_value("solution", default: none)
#let region = marimo_value("region", default: none)
#let bowl = marimo_value("bowl", default: none)
#let sweep = marimo_value("sweep", default: none)
#let P = marimo_value("curvature.value", default: none)
#let direction = marimo_value("pull_direction.value", default: none)
#let ready = (solution, region, bowl, sweep, P, direction).all(item => item != none)

// The unit normal g and offset h of each wall, recovered from the two
// endpoints the notebook draws: the midpoint of a wall is g scaled by h.
#let wall-normals(region) = region.walls.map(((start, end)) => {
  let mx = (start.at(0) + end.at(0)) / 2
  let my = (start.at(1) + end.at(1)) / 2
  let h = calc.sqrt(mx * mx + my * my)
  (g: (mx / h, my / h), h: h)
})

#set document(title: "Quadratic programs: one bowl, four walls")
#set page(
  paper: "a4",
  margin: (x: 2.3cm, top: 2.2cm, bottom: 2.4cm),
  footer: context {
    set text(7.5pt, fill: muted)
    grid(
      columns: (1fr, auto),
      [Quadratic programs · One bowl, four walls],
      counter(page).display("1 / 1", both: true),
    )
  },
)
#set text(font: "New Computer Modern", size: 10.5pt, fill: ink, lang: "en")
#set par(justify: true, leading: 0.62em, spacing: 0.95em)
#show math.equation: set text(font: "New Computer Modern Math")
#set heading(numbering: "1.")
#show heading.where(level: 1): it => block(above: 1.5em, below: 0.75em, text(size: 12pt, weight: "bold", it))
#set figure(gap: 0.9em)
#show figure: set block(above: 1.6em, below: 1.4em)
#show figure.caption: it => block(width: 92%, align(left, text(size: 9pt, fill: muted)[*#it.supplement #context it.counter.display(it.numbering).* #it.body]))
#set table(stroke: none)

// --- Title ------------------------------------------------------------------

#align(center)[
  #v(0.4em)
  #text(size: 8pt, tracking: 0.14em, fill: muted)[A WORKED EXAMPLE]
  #v(0.5em)
  #text(size: 22pt)[Quadratic programs]
  #v(0.25em)
  #text(size: 13pt, style: "italic", fill: muted)[One bowl, four walls]
]
#v(1em)

#block(inset: (x: 2.2em))[
  #set text(size: 9.5pt)
  #set par(justify: true)
  #align(center, text(size: 8pt, weight: "bold", tracking: 0.08em)[ABSTRACT])
  #v(0.2em)
  A quadratic program minimizes a convex quadratic objective subject to affine
  constraints. We solve one instance in two variables, where every part of the
  problem can be drawn: the objective is a bowl, the constraints are walls, and
  the solution is the lowest point of the bowl that the walls allow. We read
  the dual solution as the price of each wall, and sweep the direction of the
  linear term to see which walls hold the solution.
]

#if not ready {
  v(2em)
  block(width: 100%, inset: 14pt, fill: region-fill, radius: 2pt)[
    *Solving the program.* The figures and tables appear when the solver
    finishes.
  ]
} else {

let normals = wall-normals(region)
let (x1, x2) = solution.optimum
let (c1, c2) = solution.center
let angle = direction * 1deg
let (q1, q2) = (7 * calc.cos(angle), 7 * calc.sin(angle))
let active = range(normals.len()).filter(index => solution.active.at(index))
let inside = active.len() == 0

[
= Standard form

A quadratic program in standard form is

$
  "minimize"   quad & (1 slash 2) x^T P x + q^T x \
  "subject to" quad & G x <= h, quad A x = b,
$

where $P in bb(S)^n_+$ is positive semidefinite, $q in bb(R)^n$,
$G in bb(R)^(m times n)$, $h in bb(R)^m$, $A in bb(R)^(p times n)$, and
$b in bb(R)^p$ are problem data, and $x in bb(R)^n$ is the variable. The
inequality $G x <= h$ holds elementwise. Quadratic programs generalize both
least squares and linear programming, and solvers handle them efficiently and
reliably, even in real time.

= The example

The example has $n = 2$ variables and $m = 4$ walls $g_i^T x <= h_i$. Each
$g_i$ is a unit vector, so $h_i$ is the distance from the origin to wall $i$.
The curvature and the pull of the linear term are

$
  P = mat(#num(P.at(0).at(0), digits: 1), #num(P.at(0).at(1), digits: 1) ; #num(P.at(1).at(0), digits: 1), #num(P.at(1).at(1), digits: 1)),
  quad
  q = 7 vec(cos #direction degree, sin #direction degree) = vec(#num(q1, digits: 2), #num(q2, digits: 2)).
$

#grid(
  columns: (1fr, 228pt),
  column-gutter: 18pt,
  [
    $P$ sets the shape of the bowl, and $q$ moves its bottom to the
    unconstrained minimizer $-P^(-1) q = (#num(c1), #num(c2))$, drawn as a
    hollow point. The walls decide whether that point is feasible.

    In @problem, the shaded region satisfies every inequality, and the gray
    ellipses are level curves of the objective around the bottom of the bowl.
    The solution $x^star$ is the point where the smallest reachable level
    curve, in red, touches the region.#if not inside [ Red walls are active:
    they hold the solution in place.] else [ Here the bottom of the bowl is
    already feasible, so no wall is active.]
  ],
  [
    #figure(
      marimo_output("problem_figure", width: 100%),
      caption: [The region, level curves, and solution.],
    ) <problem>
  ],
)
]

pagebreak()

[
= Solution

The solver reaches the optimal value $p^star = #num(solution.value, digits: 4)$
at $x^star = (#num(x1), #num(x2))$.
#if inside [
  No wall is active: the bottom of the bowl lies inside the region, so the
  constrained and unconstrained minimizers coincide.
] else if active.len() == 1 [
  One wall is active, $g_#(active.first() + 1)$, so $x^star$ lies on that
  wall where it is tangent to a level curve of the objective.
] else [
  #("Two", "Three", "Four").at(active.len() - 2) walls are active, so $x^star$ sits at a corner of the region.
]
@walls lists each wall with its slack $h_i - g_i^T x^star$ and its dual
value $lambda_i^star$.

#figure(
  table(
    columns: (auto, auto, auto, auto, auto, auto),
    align: (center, right, right, right, right, left),
    inset: (x: 9pt, y: 5pt),
    table.hline(stroke: 0.8pt + ink),
    table.header(
      [Wall], [Normal angle], [$h_i$], [Slack], [$lambda_i^star$], [Status],
    ),
    table.hline(stroke: 0.4pt + ink),
    ..normals.enumerate().map(((index, wall)) => {
      let (gx, gy) = wall.g
      let slack = wall.h - (gx * x1 + gy * x2)
      let degrees = calc.round(calc.atan2(gx, gy).deg())
      let degrees = if degrees < 0 { degrees + 360 } else { degrees }
      let is-active = solution.active.at(index)
      let shade(body) = if is-active { text(fill: data, body) } else { body }
      (
        shade($g_#(index + 1)$),
        shade[#num(degrees, digits: 0)°],
        shade(num(wall.h, digits: 2)),
        shade(num(slack)),
        shade(num(solution.duals.at(index))),
        shade(if is-active [active] else [inactive]),
      )
    }).flatten(),
    table.hline(stroke: 0.8pt + ink),
  ),
  caption: [Walls, slacks, and dual values at the solution. An active wall
  has zero slack and a positive dual value.],
) <walls>

= Duality

Solving the program also yields a dual solution $lambda^star$, one entry per
wall. A positive $lambda_i^star$ means that wall $i$ holds the solution, and
it prices the wall: moving wall $i$ outward by a small $delta$ lowers the
optimal value by about $lambda_i^star delta$.
#if not inside {
  let strongest = active.fold(active.first(), (best, index) => if solution.duals.at(index) > solution.duals.at(best) { index } else { best })
  [
    Here wall $g_#(strongest + 1)$ carries $lambda_#(strongest + 1)^star = #num(solution.duals.at(strongest))$,
    so moving it out by $0.1$ would lower $p^star$ by about
    #num(solution.duals.at(strongest) * 0.1).
  ]
} else [
  Here every dual value is zero: no wall holds the solution, so moving any
  wall slightly changes nothing.
]

= Sensitivity to the direction of $q$

Solving the program again for every direction of the linear term, in steps
of $2 degree$ with $P$ and the walls fixed, traces how the optimal value rises
as $q$ pulls the bowl into a wall. @sweep also shows which walls hold the
solution along the way.

#figure(
  marimo_output("sweep_figure", width: 88%),
  caption: [
    Optimal value against the direction of $q$. The lower strip marks, for
    each wall, the directions in which it is active. The vertical line marks
    the direction used in this report, #direction°.
  ],
) <sweep>

= Key ideas

- The objective is a bowl shaped by $P$, and the constraints are walls.
- The solution is where the smallest reachable level curve touches the region.
- A positive dual value marks a wall that holds the solution. It is the rate at
  which moving that wall changes the optimal value.

#v(1fr)
#line(length: 100%, stroke: 0.4pt + rule)
#text(size: 8pt, fill: muted)[
  Adapted from “Quadratic program” in marimo learn
  (#link("https://github.com/marimo-team/learn")[github.com/marimo-team/learn]),
  © 2026 marimo, MIT License.
]
]
}
