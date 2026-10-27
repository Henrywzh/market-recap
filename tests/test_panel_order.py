"""The build runs each panel after every panel it reads: a dependency built later
is missing (a full build) or a day old (a partial one), and the reader shows blanks."""

from __future__ import annotations

import importlib

from market_recap import build


def test_every_panel_runs_after_the_panels_it_reads():
    order = list(build.PANELS)
    for name in order:
        module = importlib.import_module(build.PANELS[name].__module__)
        for dep in getattr(module, "INPUTS", ()):
            if dep in order:
                assert order.index(dep) < order.index(name), f"{name} reads {dep}, which is built after it"


def test_risk_reads_its_inputs_and_is_read_after_it():
    order = list(build.PANELS)
    from market_recap.panels import risk
    assert set(risk.INPUTS) == {"catalysts", "evidence", "positioning", "valuation"}
    for reader in ("flows", "overview", "today"):
        assert order.index("risk") < order.index(reader)
