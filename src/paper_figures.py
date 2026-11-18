"""Paper-style figures drawn from the same signals and fills as the backtest."""

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from math import ceil, floor, log2, nan
from statistics import mean

from matplotlib.dates import DateFormatter, HourLocator, MinuteLocator, MonthLocator, YearLocator
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter, PercentFormatter

from src.backtest import (
    BUY_AND_HOLD, EFFICIENCY_FILTERED, INITIAL_EQUITY, LOOKBACK, VOLATILITY_TARGETED,
    Costs, DailyResult, Fill, decisions, noise_bounds, simulate_day,
)
from src.market_data import MINUTE, NY, Bar, SessionGap
from src.reporting import equity_and_drawdown

FULL_SESSION_MINUTES = 390
COLORS = {
    "Opposite band": "#191919",
    "Band + VWAP": "#578b21",
    VOLATILITY_TARGETED: "#1546d9",
    "Confirmed breakout": "#805799",
    EFFICIENCY_FILTERED: "#087d88",
    BUY_AND_HOLD: "#cb342e",
}


@dataclass(frozen=True)
class CaseSession:
    bars: list[Bar]
    previous_close: float
    boundaries: list[tuple[float, float]]
    signals: dict[int, tuple[float, float, float]]


def case_sessions(
    sessions: Iterable[list[Bar] | SessionGap], dates: set[date]
) -> dict[date, CaseSession]:
    """Rebuild the historical minute envelope for the requested example dates."""
    moves: dict[int, deque[float]] = defaultdict(lambda: deque(maxlen=LOOKBACK))
    previous_close = None
    examples = {}
    for bars in sessions:
        if isinstance(bars, SessionGap):
            previous_close = bars.observed_close
            continue
        opening = bars[0]
        day = opening.timestamp.date()
        if day in dates and previous_close is not None:
            boundaries = []
            for bar in bars:
                slot = (bar.timestamp - opening.timestamp) // MINUTE + 1
                observations = moves.get(slot, ())
                boundaries.append(
                    noise_bounds(opening.open, previous_close, mean(observations))
                    if len(observations) == LOOKBACK else (nan, nan)
                )
            examples[day] = CaseSession(
                bars, previous_close, boundaries, decisions(bars, moves, previous_close)
            )
            if examples.keys() == dates:
                return examples
        for bar in bars:
            slot = (bar.timestamp - opening.timestamp) // MINUTE + 1
            # An early closing bar does not contribute to a later trading decision.
            if bar is bars[-1] and slot < FULL_SESSION_MINUTES:
                continue
            moves[slot].append(abs(bar.close / opening.open - 1))
        previous_close = bars[-1].close
    absent = ", ".join(day.isoformat() for day in sorted(dates - examples.keys()))
    raise ValueError(f"Could not build the intraday examples for {absent}")


def _noise_area(axis, example: CaseSession, *, relative: bool) -> None:
    opening = example.bars[0].open
    times = [bar.timestamp + MINUTE for bar in example.bars]
    upper, lower = zip(*example.boundaries)
    if relative:
        upper = [price / opening - 1 for price in upper]
        lower = [price / opening - 1 for price in lower]
    axis.fill_between(times, lower, upper, color="#fff5a1", alpha=0.75, label="Noise area")
    axis.plot(times, upper, color="#6aa6c4", linewidth=0.75, label="Upper band" if relative else None)
    axis.plot(times, lower, color="#cf8067", linewidth=0.75, label="Lower band" if relative else None)
    prior = example.previous_close / opening - 1 if relative else example.previous_close
    axis.axhline(prior, color="#777777", linestyle="--", linewidth=0.8, label="Previous close")
    axis.set_xlim(example.bars[0].timestamp, times[-1])
    axis.grid(axis="x", color="#dddddd", linewidth=0.6, linestyle=":")
    axis.xaxis.set_major_formatter(DateFormatter("%H:%M", tz=NY))
    axis.set_xlabel("Time of day (New York)")
    axis.set_ylabel("Move from open" if relative else "SPY price (USD)")


def noise_figure(example: CaseSession, title: str) -> Figure:
    figure = Figure(figsize=(7, 4.5), layout="constrained")
    axis = figure.subplots()
    _noise_area(axis, example, relative=True)
    axis.xaxis.set_major_locator(MinuteLocator(byminute=(0, 30), tz=NY))
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.legend(fontsize=8, loc="best")
    axis.set_title(title)
    return figure


def examples_figure(
    cases: dict[date, CaseSession],
    results: list[DailyResult],
    panels: list[tuple[date, str]],
    costs: Costs,
    title: str,
) -> Figure:
    """Plot observed SPY, the noise area and actual simulated executions."""
    figure = Figure(figsize=(6 * len(panels), 4.6), layout="constrained")
    figure.suptitle(title)
    axes = figure.subplots(1, len(panels), squeeze=False)[0]
    daily = {}
    prior_equity = defaultdict(lambda: INITIAL_EQUITY)
    for row in results:
        daily[row.date, row.strategy] = (row, prior_equity[row.strategy])
        prior_equity[row.strategy] = row.equity
    for axis, (day, strategy) in zip(axes, panels):
        example = cases[day]
        row, initial = daily[day, strategy]
        fills: list[Fill] = []
        ending, traded, _ = simulate_day(
            example.bars, example.signals, strategy, initial, costs, fills=fills
        )
        if abs(ending - row.equity) > 1e-7 or traded != row.traded_shares:
            raise ValueError(f"Case-study fills disagree with the backtest for {day}, {strategy}")
        _noise_area(axis, example, relative=False)
        axis.set_xlim(example.bars[0].timestamp - MINUTE, example.bars[-1].timestamp + 2 * MINUTE)
        axis.xaxis.set_major_locator(HourLocator(tz=NY))
        axis.xaxis.set_minor_locator(MinuteLocator(byminute=30, tz=NY))
        axis.grid(axis="x", which="minor", color="#dddddd", linewidth=0.6, linestyle=":")
        axis.plot([bar.timestamp + MINUTE for bar in example.bars],
                  [bar.close for bar in example.bars], color="#222222", linewidth=0.9, label="SPY")
        if strategy != "Opposite band":
            axis.plot([example.bars[index].timestamp for index in example.signals],
                      [values[2] for values in example.signals.values()], marker=".",
                      color="#d87221", linewidth=0.9, linestyle="--", label="VWAP at checks")
        for buying, marker, color, label in (
            (True, "^", "#578b21", "Buy"), (False, "v", "#c0392b", "Sell"),
        ):
            orders = [fill for fill in fills if (fill.shares > 0) == buying]
            if orders:
                axis.scatter([fill.timestamp for fill in orders], [fill.price for fill in orders],
                             marker=marker, c=color, edgecolors="black", linewidths=0.35,
                             s=40, label=label, zorder=5)
        axis.legend(fontsize=8, loc="best")
        axis.set_title(f"{day:%d %b %Y}  ·  {strategy}\nNet strategy return {row.net_return:+.2%}",
                       fontsize=10)
    return figure


def dollar_equity_figure(
    results: list[DailyResult], strategies: tuple[str, ...], title: str, *,
    log_scale: bool = False, test_only: bool = False, drawdown: bool = False,
) -> Figure:
    """Plot dollar equity using the paper's strategy colors and scale conventions."""
    figure = Figure(figsize=(8, 6.3 if drawdown else 4.7), layout="constrained")
    if drawdown:
        axis, risk = figure.subplots(2, 1, sharex=True, height_ratios=(2, 1))
    else:
        axis = figure.subplots()
        risk = None
    first_test = next(row.date for row in results if row.split == "test")
    for strategy in strategies:
        rows = [row for row in results if row.strategy == strategy
                and (not test_only or row.split == "test")]
        dates = [row.date for row in rows]
        capital, depths = equity_and_drawdown([row.net_return for row in rows])
        equity = [value * INITIAL_EQUITY for value in capital]
        axis.plot(dates, equity, label=strategy, color=COLORS[strategy], linewidth=1.2)
        if risk is not None:
            risk.plot(dates, depths, color=COLORS[strategy], linewidth=0.9)
    if not test_only:
        axis.axvline(first_test, color="#888888", linewidth=0.8, linestyle="--", label="Test begins")
    if log_scale:
        axis.set_yscale("log", base=2)
        low, high = axis.get_ylim()
        levels = range(ceil(log2(low / INITIAL_EQUITY)), floor(log2(high / INITIAL_EQUITY)) + 1)
        axis.yaxis.set_major_locator(FixedLocator([INITIAL_EQUITY * 2 ** level for level in levels]))
    axis.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"${value:,.0f}"))
    axis.set_ylabel("Net portfolio value (USD)")
    axis.set_title(title)
    axis.legend(fontsize=8, loc="best")
    axis.grid(alpha=0.24, linewidth=0.6)
    bottom = axis if risk is None else risk
    if risk is not None:
        risk.yaxis.set_major_formatter(PercentFormatter(1))
        risk.set_ylabel("Drawdown")
        risk.grid(alpha=0.24, linewidth=0.6)
    if (dates[-1] - dates[0]).days >= 730:
        bottom.xaxis.set_major_locator(YearLocator())
        bottom.xaxis.set_major_formatter(DateFormatter("%Y"))
    else:
        bottom.xaxis.set_major_locator(MonthLocator())
        bottom.xaxis.set_major_formatter(DateFormatter("%b %Y"))
    return figure


def commission_figure(commissions: list[float], total_returns: list[float], title: str) -> Figure:
    figure = Figure(figsize=(8, 4.4), layout="constrained")
    axis = figure.subplots()
    axis.bar(range(len(commissions)), total_returns, color="#1976a4", width=0.72)
    axis.set_xticks(range(len(commissions)), [f"${value:.4f}" for value in commissions])
    axis.yaxis.set_major_formatter(PercentFormatter(1))
    axis.set_xlabel("Commission per share per side (USD)")
    axis.set_ylabel("Held-out total return")
    axis.set_title(title)
    axis.axhline(0, color="#333333", linewidth=0.8)
    axis.grid(axis="y", alpha=0.25, linewidth=0.6)
    return figure
