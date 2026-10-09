#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: pixi run --locked ./scripts/fetch-tex-packages.sh

Download the TeX packages that the repository's LaTeX documents use into
Tectonic's cache. Tectonic fetches each package on a document's first compile,
which can outlast a LaTeX view's 120 second build budget and its 60 second
render deadline. This script compiles the LaTeX starter's packages and every
example LaTeX view once, without a time limit. Later compiles read the cache.

Run it through `pixi run`, which provides Tectonic. TECTONIC_CACHE_DIR selects
the cache directory.
EOF
}

if [[ $# -gt 0 ]]; then
    usage
    [[ "$1" == "-h" || "$1" == "--help" ]] && exit 0
    exit 2
fi

echo "fetch-tex-packages: compiling the LaTeX starter and example views." >&2
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

compile() {
    (cd "$1" && tectonic -X compile --untrusted --outdir "$work" -- "$2") >"$work/output.txt" 2>&1 || {
        cat "$work/output.txt" >&2
        echo "fetch-tex-packages: $1/$2 did not compile." >&2
        exit 1
    }
}

# The starter's preamble, the packages its instructions name, and the fonts
# that T1 text, math, and the provider tests select.
cp "$root/packages/marimo-studio/src/marimo_studio/view_providers/_builtin/latex/starters/default/files/marimo.sty" "$work/"
cat >"$work/packages.tex" <<'TEX'
\documentclass[11pt]{article}
\usepackage[a4paper, margin=2.5cm]{geometry}
\usepackage[T1,TU]{fontenc}
\usepackage{booktabs}
\usepackage{microtype}
\usepackage{siunitx}
\usepackage{xcolor}
\usepackage[en-GB, calc]{datetime2}
\usepackage{hyperref}
\usepackage{marimo}
\begin{document}
\section*{Packages}
Text \textbf{bold} \textit{italic} \texttt{mono} {\footnotesize small}
\num{0.333} \qty{21.2}{\percent} $\alpha \geq \frac{1}{2}$
\marimonum{share} \marimodate{day} \marimographics[width=4cm]{figure}
{\fontencoding{T1}\selectfont T1 \textdegree{} \textendash{} \guillemotleft{}}
\end{document}
TEX
compile "$work" packages.tex

for manifest in "$root"/examples/__marimo__/studio/*/*/view.toml; do
    if grep -q '^provider = "marimo-studio/latex"' "$manifest"; then
        compile "$(dirname "$manifest")" main.tex
    fi
done
