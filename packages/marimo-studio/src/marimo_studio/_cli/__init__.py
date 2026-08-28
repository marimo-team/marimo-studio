"""Expose Marimo Studio's installed command-line workflows.

The command line covers notebook inspection, cell binding, provider and starter
discovery, view creation and removal, source inspection, builds, validation,
showing a page in a connected browser, and static export. Each command uses the
same Studio services as the Python, agent, and browser entry points.

Human-facing commands produce readable terminal output and recovery guidance.
Automation can request stable JSON results, JSON Lines diagnostics, and exit
codes that identify usage errors, expected Studio failures, and interrupts.
"""

from marimo_studio._cli.main import cli as cli
from marimo_studio._cli.main import main as main
