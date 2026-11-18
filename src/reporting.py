"""Performance summaries and figures shared by the CLI and notebook."""

from dataclasses import dataclass
from itertools import accumulate
from operator import mul

from matplotlib.figure import Figure
from matplotlib.ticker import PercentFormatter

from src.backtest import DailyResult, STRATEGIES, metrics


@dataclass(frozen=True)
class Performance:
    split: str
    strategy: str
    sharpe: float | None
    annualized_return: float
    annualized_volatility: float
    max_drawdown: float
    traded_sessions: int
    traded_shares: int
    total_cost: float


def equity_and_drawdown(returns: list[float]) -> tuple[list[float], list[float]]:
    """Compound returns from one and measure drawdown from each running peak."""
    equity = list(accumulate((1 + value for value in returns), mul, initial=1.0))
    drawdowns = [value / peak - 1 for value, peak in zip(equity, accumulate(equity, max))]
    return equity[1:], drawdowns[1:]


def summarize(results: list[DailyResult]) -> list[Performance]:
    """Calculate net performance and turnover separately for each chronological split."""
    summary = []
    for split in ("train", "test"):
        for strategy in STRATEGIES:
            rows = [row for row in results if row.split == split and row.strategy == strategy]
            returns = [row.net_return for row in rows]
            _, drawdowns = equity_and_drawdown(returns)
            summary.append(Performance(
                split, strategy, *metrics(returns), min(drawdowns),
                sum(row.traded_shares > 0 for row in rows),
                sum(row.traded_shares for row in rows),
                sum(row.cost for row in rows),
            ))
    return summary


def comparison_figure(summary: list[Performance], title: str) -> Figure:
    """Compare train and test Sharpe, annualized return and annualized volatility."""
    comparison = {(row.split, row.strategy): row for row in summary}
    figure = Figure(figsize=(13, 4.5), layout="constrained")
    figure.suptitle(title)
    axes = figure.subplots(1, 3, sharey=True)
    axes[0].set_yticks(range(len(STRATEGIES)), STRATEGIES, fontsize=9)
    axes[0].invert_yaxis()
    for axis, (attribute, label) in zip(
        axes,
        (("sharpe", "Sharpe ratio"), ("annualized_return", "Annualized return"),
         ("annualized_volatility", "Annualized volatility")),
    ):
        for split, offset, color in (("train", -0.18, "#597ba5"), ("test", 0.18, "#d56b3a")):
            for position, strategy in enumerate(STRATEGIES):
                value = getattr(comparison[split, strategy], attribute)
                axis.barh(position + offset, value if value is not None else 0,
                          height=0.34, color=color, label=split if position == 0 else None)
                if value is None:
                    axis.annotate("N/A", (0, position + offset), xytext=(3, 0),
                                  textcoords="offset points", va="center", fontsize=8)
        axis.axvline(0, color="#444444", linewidth=0.7)
        axis.set_title(label)
        if attribute == "sharpe":
            axis.legend(loc="lower center", bbox_to_anchor=(0.5, -0.22), ncols=2)
        else:
            axis.xaxis.set_major_formatter(PercentFormatter(1))
    return figure


def equity_figure(results: list[DailyResult], title: str) -> Figure:
    """Show net equity and drawdown through the chronological split."""
    figure = Figure(figsize=(12, 7), layout="constrained")
    figure.suptitle(title)
    equity_axis, drawdown_axis = figure.subplots(2, 1, sharex=True)
    first_test = next(row.date for row in results if row.split == "test")
    for strategy in STRATEGIES:
        rows = [row for row in results if row.strategy == strategy]
        dates = [row.date for row in rows]
        equity, drawdowns = equity_and_drawdown([row.net_return for row in rows])
        line, = equity_axis.plot(dates, equity, label=strategy)
        drawdown_axis.plot(dates, drawdowns, color=line.get_color())
    for axis in (equity_axis, drawdown_axis):
        axis.axvline(first_test, color="#444444", linestyle="--", linewidth=0.9)
        axis.grid(axis="y", alpha=0.25)
    equity_axis.set_ylabel("Net equity (start = 1)")
    equity_axis.legend(ncols=3, fontsize=9)
    drawdown_axis.set_ylabel("Drawdown")
    drawdown_axis.yaxis.set_major_formatter(PercentFormatter(1))
    drawdown_axis.set_xlabel("Session date · dashed line marks first test session")
    return figure
