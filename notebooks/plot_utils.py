"""Shared Plotly theming for the notebooks.

Matches the VS Code "Dark Modern" editor background exactly (no `workbench.colorTheme`
override is set, so that's the active default) and uses the data-viz skill's validated
dark-mode categorical palette (references/palette.md), so charts read consistently
across all three notebooks regardless of which cell built them.
"""
from __future__ import annotations

import plotly.io as pio

# VS Code "Dark Modern" editor.background -- the colour behind notebook cell outputs.
BACKGROUND = "#1f1f1f"

# dataviz skill's validated 8-hue categorical palette, dark-surface steps, with green
# moved to the last slot. Re-validated in this order (worst adjacent Machado-2009 dE
# 10.7) -- never reorder further without re-running scripts/validate_palette.js.
COLORWAY = ["#3987e5", "#199e70", "#c98500", "#9085e9", "#e66767", "#d55181", "#d95926", "#008300"]

GRIDLINE = "#2c2c2a"
AXIS_LINE = "#383835"
TEXT = "#ffffff"

_template = pio.templates["plotly_dark"].to_plotly_json()
_template["layout"]["paper_bgcolor"] = BACKGROUND
_template["layout"]["plot_bgcolor"] = BACKGROUND
_template["layout"]["colorway"] = COLORWAY
_template["layout"]["font"]["color"] = TEXT
for _axis in ("xaxis", "yaxis"):
    _template["layout"].setdefault(_axis, {})
    _template["layout"][_axis].update(gridcolor=GRIDLINE, zerolinecolor=GRIDLINE, linecolor=AXIS_LINE)
pio.templates["vscode_dark"] = _template


def apply() -> None:
    """Register (already done on import) and activate `vscode_dark` as Plotly's default."""
    pio.templates.default = "vscode_dark"
