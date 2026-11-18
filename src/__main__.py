"""CLI for downloading data and reproducing the SPY comparison."""

import argparse
import csv
from dataclasses import astuple, fields
from datetime import date
from math import isfinite
from pathlib import Path

from src.alpaca import download
from src.backtest import Costs, DailyResult, run_backtest
from src.market_data import SessionGap, read_sessions
from src.reporting import Performance, comparison_figure, equity_figure, summarize


def write_report(
    results: list[DailyResult], output: Path, gaps: list[SessionGap] | None = None
) -> None:
    """Write daily accounting, split metrics and a three-panel comparison."""
    output.mkdir(parents=True, exist_ok=False)
    with (output / "daily.csv").open("w", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(field.name for field in fields(DailyResult))
        writer.writerows(map(astuple, results))

    summary = summarize(results)
    with (output / "metrics.csv").open("w", newline="") as target:
        writer = csv.writer(target)
        writer.writerow(field.name for field in fields(Performance))
        writer.writerows(map(astuple, summary))

    comparison_figure(summary, "SPY strategy comparison").savefig(output / "comparison.png", dpi=170)
    equity_figure(results, "SPY net equity and drawdown").savefig(output / "equity.png", dpi=170)
    if gaps is not None:
        with (output / "data_gaps.csv").open("w", newline="") as target:
            writer = csv.writer(target)
            writer.writerow(("session", "missing_minute", "session_excluded"))
            for gap in gaps:
                writer.writerows((gap.date, minute.isoformat(), gap.excluded)
                                 for minute in gap.missing_minutes)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    fetch = commands.add_parser("download", help="Download historical Alpaca SIP minute bars")
    backtest = commands.add_parser("backtest", help="Compare all strategies from a local CSV")
    for command in (fetch, backtest):
        command.add_argument("--start", type=date.fromisoformat, required=True)
        command.add_argument("--end", type=date.fromisoformat, required=True)
        command.add_argument("--output", type=Path, required=True)
    backtest.add_argument("--input", type=Path, required=True)
    backtest.add_argument("--test-start", type=date.fromisoformat, required=True)
    backtest.add_argument("--commission", type=float, default=Costs.commission)
    backtest.add_argument("--slippage", type=float, default=Costs.slippage)
    backtest.add_argument("--audit-gaps", action="store_true",
                          help="Audit missing bars and simulate only with observed prices")
    args = parser.parse_args()
    try:
        if args.command == "download":
            print(f"Downloaded {download(args.start, args.end, args.output):,} bars to {args.output}")
        else:
            costs = Costs(args.commission, args.slippage)
            if not all(isfinite(cost) and cost >= 0 for cost in astuple(costs)):
                raise ValueError("Commission and slippage must be finite and nonnegative")
            if not args.start < args.test_start <= args.end:
                raise ValueError("Test start must follow start and be on or before end")
            gaps: list[SessionGap] | None = [] if args.audit_gaps else None
            sessions = read_sessions(args.input, args.start, args.end, gaps=gaps)
            write_report(run_backtest(sessions, args.test_start, costs), args.output, gaps)
            print(f"Wrote daily results, metrics and comparison plot to {args.output}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
