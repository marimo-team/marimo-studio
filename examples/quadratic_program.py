# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "clarabel>=0.11.1",
#     "cvxpy-base>=1.8.2",
#     "marimo>=0.25.0",
#     "matplotlib>=3.10.8",
#     "numpy>=2.4.3",
# ]
#
# [tool.marimo-studio]
# default = "explainer"
# runtimes = ["server", "zero-python"]
# show_cell_logs = false
#
# [tool.marimo-studio.cells]
# ///

import marimo

__generated_with = "0.25.0"
app = marimo.App(width="medium", app_title="Quadratic Programs")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def introduction(mo):
    mo.md(r"""
    # Quadratic programs

    A quadratic program is an optimization problem with a quadratic objective and
    affine equality and inequality constraints. This notebook builds the geometry
    of one small example. The objective is a bowl, the constraints are walls, and
    the solution is the lowest point of the bowl that the walls allow.
    """)
    return


@app.cell(hide_code=True)
def standard_form(mo):
    mo.md(r"""
    ## Standard form

    \[
        \begin{array}{ll}
        \text{minimize}   & (1/2)x^TPx + q^Tx \\
        \text{subject to} & Gx \leq h \\
                          & Ax = b
        \end{array}
    \]

    Here $P \in \mathcal{S}^{n}_+$, $q \in \mathcal{R}^n$,
    $G \in \mathcal{R}^{m \times n}$, $h \in \mathcal{R}^m$,
    $A \in \mathcal{R}^{p \times n}$, and $b \in \mathcal{R}^p$ are problem data,
    and $x \in \mathcal{R}^{n}$ is the optimization variable. The inequality
    constraint $Gx \leq h$ is elementwise.
    """)
    return


@app.cell(hide_code=True)
def why_quadratic(mo):
    mo.md(r"""
    ## Why quadratic programming?

    Quadratic programs are convex optimization problems that generalize both least
    squares and linear programming. They can be solved efficiently and reliably,
    even in real time.
    """)
    return


@app.cell(hide_code=True)
def portfolio_example(mo):
    mo.md(r"""
    ## An example from finance

    Suppose we have $n$ different stocks, an estimate $r \in \mathcal{R}^n$ of the
    expected return on each stock, and an estimate $\Sigma \in \mathcal{S}^{n}_+$
    of the covariance of the returns. The problem

    \[
        \begin{array}{ll}
        \text{minimize}   & (1/2)x^T\Sigma x - r^Tx \\
        \text{subject to} & x \geq 0 \\
                          & \mathbf{1}^Tx = 1
        \end{array}
    \]

    finds a nonnegative portfolio allocation $x \in \mathcal{R}^n_+$ that optimally
    balances expected return and variance of return.
    """)
    return


@app.cell(hide_code=True)
def duality(mo):
    mo.md(r"""
    ## Duality

    Solving a quadratic program also yields a dual solution $\lambda^\star$, one
    entry for each inequality constraint. A positive entry $\lambda^\star_i$ means
    that the constraint $g_i^Tx \leq h_i$ holds with equality at the solution
    $x^\star$. Moving that wall would change the optimal value, at a rate of
    $\lambda^\star_i$ per unit.
    """)
    return


@app.cell(hide_code=True)
def example_context(mo):
    mo.md(r"""
    ## A two-dimensional example

    We solve a problem in two variables with CVXPY, so every part of it can be
    drawn. Four walls $g_i^Tx \leq h_i$ enclose a region around the origin. Each
    $g_i$ is a unit vector, so $h_i$ is the distance from the origin to wall $i$.
    """)
    return


@app.cell
def _():
    from itertools import combinations

    import cvxpy as cp
    import matplotlib.pyplot as plt
    import numpy as np

    return combinations, cp, np, plt


@app.cell
def problem_data(np):
    wall_angles = np.radians([15, 110, 205, 295])
    G = np.column_stack([np.cos(wall_angles), np.sin(wall_angles)])
    h = np.array([1.5, 1.25, 1.75, 1.4])
    pull_strength = 7.0


    def pull(direction):
        """Return the linear term q pointing `direction` degrees from the x-axis."""
        radians = np.radians(direction)
        return pull_strength * np.array([np.cos(radians), np.sin(radians)])

    return G, h, pull


@app.cell(hide_code=True)
def objective_context(mo):
    mo.md(r"""
    ## The objective

    $P$ sets the shape of the bowl. The linear term $q$ pulls the bottom of the
    bowl away from the origin, toward and sometimes past the walls.
    """)
    return


@app.cell
def curvature(mo):
    curvature = mo.ui.radio(
        options={
            "Round": [[3.0, 0.0], [0.0, 3.0]],
            "Stretched": [[6.0, 0.0], [0.0, 1.5]],
            "Tilted": [[4.0, -1.4], [-1.4, 4.0]],
            "Narrow valley": [[5.0, 4.5], [4.5, 5.0]],
        },
        value="Tilted",
        label="Shape of $P$",
    )
    curvature
    return (curvature,)


@app.cell
def objective_matrix(curvature, np):
    P = np.array(curvature.value)
    return (P,)


@app.cell
def bowl(P, np):
    eigenvalues, eigenvectors = np.linalg.eigh(P)


    def level_radii(rise):
        """Semi-axes of the level set lying `rise` above the bottom of the bowl."""
        return np.sqrt(2 * max(rise, 0.0) / eigenvalues).tolist()


    bowl = {
        "angle": float(np.degrees(np.arctan2(eigenvectors[1, 0], eigenvectors[0, 0]))),
        "levels": [level_radii(step**2 / 2) for step in range(1, 7)],
    }
    return bowl, level_radii


@app.cell
def pull_direction(mo):
    pull_direction = mo.ui.slider(
        0,
        330,
        step=30,
        value=210,
        label="Direction of $q$ (degrees)",
        show_value=True,
    )
    pull_direction
    return (pull_direction,)


@app.cell
def linear_term(pull, pull_direction):
    q = pull(pull_direction.value)
    return (q,)


@app.cell(hide_code=True)
def problem_context(mo):
    mo.md(r"""
    Next, we specify the problem. Notice that we use the `quad_form` function from
    CVXPY to create the quadratic form $x^TPx$. The problem is written as a function
    of the linear term, so it can be solved for any $q$.
    """)
    return


@app.cell
def solver(G, P, cp, h, level_radii, np):
    def solve(q):
        """Solve the program for the linear term q and describe the solution."""
        x = cp.Variable(2)
        walls = G @ x <= h
        problem = cp.Problem(
            cp.Minimize((1 / 2) * cp.quad_form(x, P) + q @ x),
            [walls],
        )
        problem.solve(solver=cp.CLARABEL)
        center = np.linalg.solve(P, -q)
        bottom = (1 / 2) * q @ center
        duals = walls.dual_value
        return {
            "value": float(problem.value),
            "optimum": x.value.tolist(),
            "center": center.tolist(),
            "contact": level_radii(problem.value - bottom),
            "duals": duals.tolist(),
            "active": (duals > 1e-6).tolist(),
        }

    return (solve,)


@app.cell
def solution(q, solve):
    solution = solve(q)
    return (solution,)


@app.cell(hide_code=True)
def solution_summary(mo, solution):
    _active = [f"$g_{i + 1}$" for i, active in enumerate(solution["active"]) if active]
    _held = (
        f"Active constraints: {', '.join(_active)}."
        if _active
        else "No constraint is active, so the unconstrained minimum is feasible."
    )
    _x1, _x2 = solution["optimum"]
    mo.md(
        rf"""
        The optimal value is **{solution["value"]:.4f}** at
        $x^\star = ({_x1:.3f}, {_x2:.3f})$. {_held}
        """
    )
    return


@app.cell
def feasible_region(G, combinations, h, np):
    def corners_of(G, h):
        """Return the corners of the region Gx <= h in counterclockwise order."""
        corners = []
        for i, j in combinations(range(len(h)), 2):
            if abs(np.linalg.det(G[[i, j]])) > 1e-9:
                corner = np.linalg.solve(G[[i, j]], h[[i, j]])
                if np.all(G @ corner <= h + 1e-9):
                    corners.append(corner)
        middle = np.mean(corners, axis=0)
        return sorted(corners, key=lambda corner: np.arctan2(*reversed(corner - middle)))


    region = {
        "corners": [corner.tolist() for corner in corners_of(G, h)],
        "walls": [
            [(g * offset + span * np.array([-g[1], g[0]])).tolist() for span in (-4, 4)]
            for g, offset in zip(G, h)
        ],
    }
    return (region,)


@app.cell
def level_curves(bowl, draw_problem, region, solution):
    draw_problem(region, bowl, solution)
    return


@app.cell(hide_code=True)
def plot_reading(mo):
    mo.md(r"""
    In this plot, the shaded region satisfies every inequality, and the ellipses are
    level curves of the objective around the bottom of the bowl. The solution is the
    point where the smallest reachable ellipse touches the region.
    """)
    return


@app.cell(hide_code=True)
def exploration_prompt(mo):
    mo.md(r"""
    **Try it.** Change the shape of $P$ and the direction of $q$. When does the
    solution move from the interior to a constraint? When are two constraints
    active at once?
    """)
    return


@app.cell(hide_code=True)
def matrix_summary(P, mo):
    mo.md(rf"""
    The level curves above were generated with

    \[
    P = \begin{{bmatrix}}
    {P[0, 0]:.01f} & {P[0, 1]:.01f} \\
    {P[1, 0]:.01f} & {P[1, 1]:.01f} \\
    \end{{bmatrix}}
    \]
    """)
    return


@app.cell(hide_code=True)
def sensitivity_context(mo):
    mo.md(r"""
    ## Sensitivity to the direction of $q$

    The sweep solves the program again for every direction of the linear term,
    keeping $P$ and the walls fixed. It shows how the optimal value rises as $q$
    pulls the bowl into a wall, and which walls hold the solution along the way.
    """)
    return


@app.cell
def sweep(pull, solve):
    sweep = [
        {"direction": direction, **solve(pull(direction))}
        for direction in range(0, 360, 2)
    ]
    return (sweep,)


@app.cell
def sensitivity_plot(draw_sweep, pull_direction, sweep):
    draw_sweep(sweep, pull_direction.value)
    return


@app.cell(hide_code=True)
def takeaways(mo):
    mo.md(r"""
    ## Key ideas

    - The objective is a bowl shaped by $P$, and the constraints are walls.
    - The solution is where the smallest reachable level curve touches the region.
    - A positive dual value marks a wall that holds the solution. It is the rate at
      which moving that wall changes the optimal value.
    """)
    return


@app.cell(hide_code=True)
def source(mo):
    mo.md(r"""
    Adapted from the
    [quadratic program notebook](https://github.com/marimo-team/learn/blob/main/optimization/04_quadratic_program.py)
    in marimo's learn repository, copyright 2026 marimo, under the
    [MIT License](https://github.com/marimo-team/learn/blob/main/LICENSE).
    """)
    return


@app.cell(hide_code=True)
def figures(np, plt):
    from matplotlib.patches import Ellipse, Polygon

    INK = "#1b1d22"
    MUTED = "#9aa0a8"
    REGION = "#eef0f3"
    ACCENT = "#b33a2e"


    def draw_problem(region, bowl, solution):
        """Draw the feasible region, the level curves, and the solution."""
        figure, axes = plt.subplots(figsize=(6, 6))
        axes.add_patch(Polygon(region["corners"], facecolor=REGION, edgecolor="none"))
        for index, (start, end) in enumerate(region["walls"]):
            color = ACCENT if solution["active"][index] else MUTED
            axes.plot(*zip(start, end), color=color, linewidth=1)
        for radii in bowl["levels"]:
            axes.add_patch(
                Ellipse(
                    solution["center"],
                    2 * radii[0],
                    2 * radii[1],
                    angle=bowl["angle"],
                    fill=False,
                    edgecolor=MUTED,
                    linewidth=0.8,
                )
            )
        if solution["contact"][0] > 0:
            axes.add_patch(
                Ellipse(
                    solution["center"],
                    2 * solution["contact"][0],
                    2 * solution["contact"][1],
                    angle=bowl["angle"],
                    fill=False,
                    edgecolor=ACCENT,
                    linewidth=1.4,
                )
            )
        axes.plot(*solution["center"], "o", markerfacecolor="white", markeredgecolor=INK)
        axes.plot(*solution["optimum"], "o", color=ACCENT)
        away = np.subtract(solution["optimum"], solution["center"])
        distance = np.linalg.norm(away)
        axes.annotate(
            "$x^*$",
            solution["optimum"],
            xytext=14 * away / distance if distance > 1e-3 else (10, 10),
            textcoords="offset points",
            ha="center",
            va="center",
            fontsize=12,
        )
        axes.set(xlim=(-3, 3), ylim=(-3, 3), aspect="equal", xlabel="$x_1$", ylabel="$x_2$")
        style_axes(axes)
        return axes


    def draw_sweep(sweep, direction):
        """Plot the optimal value and the walls holding the optimum against the direction of q."""
        figure, (values, holding) = plt.subplots(
            2, 1, figsize=(7, 3.6), sharex=True, height_ratios=(3, 1)
        )
        directions = [row["direction"] for row in sweep]
        values.plot(directions, [row["value"] for row in sweep], color=INK, linewidth=1.4)
        values.set(ylabel="Optimal value")
        for wall in range(len(sweep[0]["active"])):
            held = [row["direction"] for row in sweep if row["active"][wall]]
            holding.scatter(held, [wall + 1] * len(held), marker="|", color=ACCENT, s=40)
        holding.set(
            xlim=(0, 358),
            xticks=range(0, 361, 90),
            ylim=(0.5, len(sweep[0]["active"]) + 0.5),
            yticks=range(1, len(sweep[0]["active"]) + 1),
            yticklabels=[f"$g_{wall + 1}$" for wall in range(len(sweep[0]["active"]))],
            xlabel="Direction of $q$ (degrees)",
        )
        for axes in (values, holding):
            axes.axvline(direction, color=MUTED, linewidth=1)
            style_axes(axes)
        figure.tight_layout()
        return figure


    def style_axes(axes):
        """Draw light axes on a transparent background that keep the data in front."""
        axes.set_facecolor("none")
        axes.figure.patch.set_alpha(0)
        for side in ("top", "right"):
            axes.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            axes.spines[side].set_color(MUTED)
        axes.tick_params(colors=MUTED, labelcolor=INK)

    return draw_problem, draw_sweep


if __name__ == "__main__":
    app.run()
