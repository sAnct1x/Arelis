"""#281: plot writes a fresh PNG in the workspace, so it never asks first."""

from arelis.tools.plot import PlotTool
from arelis.tools.policy import describe_call, evaluate_capability, evaluate_confirm


def test_plot_runs_without_confirm_card() -> None:
    args = {"action": "line", "xs": "1,2,3", "ys": "1,4,9", "title": "Squares"}
    assert evaluate_confirm("plot", args, risk=PlotTool.risk) is False
    assert evaluate_capability("plot", args) == "READ"
    assert "chart you can open" not in describe_call("plot", args)
