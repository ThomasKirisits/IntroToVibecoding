# SPY intraday momentum case study

The [assignment](case_study_intraday-1.pdf) asks for a backtest of the intraday momentum strategy in [Zarattini, Aziz and Barbon](ssrn-4824172-2.pdf), plus an original strategy evaluated on the same data and costs. The comparison covers the paper's opposite-band, band-plus-VWAP and volatility-targeted variants, two entry variations, and a SPY buy-and-hold benchmark.

## Reproduce the comparison

Requires Python 3.12 and timezone data. Run from the repository root.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
```

Launch JupyterLab from the repository root with `.venv/bin/python -m jupyterlab` and open [spy_intraday_momentum.ipynb](notebooks/spy_intraday_momentum.ipynb). The notebook defaults to the historical Alpaca CSV. Set `DATA_MODE = "synthetic"` for a seeded offline demonstration. The notebook follows the paper’s progression from noise bands and annotated trading days to equity curves, performance tables, and commission sensitivity. The entry-filter section adds a paired held-out comparison against fixed-size Band + VWAP.

To execute the notebook without opening a browser, use `.venv/bin/python -m nbconvert --to notebook --execute notebooks/spy_intraday_momentum.ipynb --ExecutePreprocessor.timeout=300 --output-dir results --output spy_notebook_executed.ipynb`.

Set `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in your shell or secret manager. You can also create a local `.env` file with the following lines and fill in the quoted values. Git ignores this file.

```bash
export APCA_API_KEY_ID=''
export APCA_API_SECRET_KEY=''
```

Run `source .env` in the same shell as the download command to load the credentials. The downloader uses the market data endpoint for historical consolidated SIP bars. Alpaca's free plan supports historical SIP requests whose end is at least 15 minutes old. [Alpaca Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)

The following proposed run uses 2019–2022 for development and 2023–2025 for evaluation. The strategy settings are fixed before the historical run. The first 15 sessions warm up all strategies so the sizing model has 14 close-to-close returns. Test performance is measured from daily returns beginning on the first trading day on or after the split. Equity and causal price history carry across the split.

```bash
.venv/bin/python -m src download --start 2019-01-01 --end 2025-12-31 --output data/spy.csv
.venv/bin/python -m src backtest --input data/spy.csv --start 2019-01-01 --end 2025-12-31 --test-start 2023-01-01 --audit-gaps --output results/spy
```

The report contains `daily.csv` with net returns, equity, turnover and costs, `metrics.csv` with one row per strategy and split, `comparison.png` with the three main metrics, and `equity.png` with net equity and drawdown. An undefined Sharpe appears blank in CSV and as N/A on the chart. Use a new output path for each run. Record the data vendor, feed, retrieval date, and adjustment mode with the report when sharing it.

A local input CSV also works. Supply ascending, unique minute-start timestamps with explicit UTC offsets, and columns `timestamp,open,high,low,close,volume`. Prices are USD per share and volume is in shares. Supply per-minute `vwap` when available. Missing VWAP values use the bar's typical price, (high + low + close) / 3. The Alpaca download uses split-adjusted, dividend-unadjusted bars and provider VWAP. The exchange calendar defines regular hours in America/New_York, including early closes. Extended-hours rows are ignored.

The CLI rejects missing minutes by default. With `--audit-gaps`, the report lists them in `data_gaps.csv`. The historical notebook uses the same audited mode. Each scheduled decision requires an observed signal close and execution open. VWAP uses observed trades only, and Efficient Breakout requires a complete lookback. The comparison excludes sessions missing their opening or closing bar. If the prior close is missing, the intraday strategies stay flat the next session. The volatility target skips returns without adjacent closing observations. Buy-and-hold marks across any excluded dates at its next available close.

## Strategy and execution

- **Noise area.** At each decision slot, average the absolute return from the session open to that slot over the 14 most recent sessions with that slot. Anchor the upper band to the larger of today's open and yesterday's regular close, then multiply by one plus the average move. Anchor the lower band to the smaller of those prices and multiply by one minus the move. Short sessions contribute observations for slots they can trade.
- **Opposite band.** A completed bar above the upper band enters long and a bar below the lower band enters short. A breach of the opposite band reverses exposure.
- **Band + VWAP.** Keep the same entry rule and close a long below the larger of the current upper band and regular-session VWAP. Close a short above the smaller of the lower band and VWAP. An opposite breakout can reverse the position. VWAP resets at each session open and is computed from cumulative bar VWAP times volume.
- **Volatility-targeted VWAP.** Use the same entries and exits. Multiply daily position size by the ratio of the 2% daily target to the sample volatility of the previous 14 close-to-close returns. Cap leverage at 4× and use the cap when prior volatility is zero.
- **Confirmed breakout.** Keep the band-plus-VWAP exits, and require two consecutive half-hour decisions beyond the same side of the noise area before opening exposure in that direction. A stop can still close immediately at its scheduled check even if the opposite signal lacks confirmation.
- **Efficient breakout.** When price breaks a band, require signed displacement in the breakout direction to be at least 35% of total absolute price changes over the last 30 completed minutes. Use fixed-size Band + VWAP sizing and exits. The rule can enter after a single clean breakout and can skip a breakout produced by a choppy path.
- **SPY buy & hold.** Buy whole shares at the first evaluated open, pay entry costs and mark the open holding to market at each close. This price-only benchmark includes overnight exposure.
- **Execution.** The first signal is evaluated at 10:00 New York time. It uses the 09:59 bar's close and fills at the 10:00 bar's open. Subsequent decisions occur every 30 minutes before the scheduled close. Intraday positions are flattened at each session's last bar close, a proxy for submitting a scheduled closing order. Daily intraday size uses beginning equity and the opening price, with whole shares and $100,000 initial capital. Market moves between that sizing price and execution can change realized exposure.
- **Costs.** Commission defaults to the paper's $0.0035 per share per side. Slippage defaults to $0.01 per share per side, a more conservative assumption than the paper's $0.001. Reversals are charged on twice the position size, and closing trades also incur costs. An optional sensitivity check can use `--slippage 0.001` or a larger value such as `--slippage 0.03` with a separate output directory.
- **Metrics.** Geometrically annualized return compounds net daily returns over 252 sessions. Annualized volatility scales sample daily standard deviation by √252. Sharpe divides annualized arithmetic mean return above a zero cash rate by annualized volatility. Flat sessions are included.

## Discussion

The paper's hypothesis is that unusually large moves can reveal persistent order imbalance. Slow incorporation of news and gradual order execution can sustain intraday trends. Gap-aware bands require a move beyond both today's open and the prior close after allowing for typical time-of-day movement. Semi-hourly checks limit turnover, the VWAP stop can cut reversals earlier, and closing exposure at the end of each day removes overnight positions. Quiet, range-bound sessions can cause false breakouts. Fast reversals or volatile news can also overwhelm half-hour exits and increase realized slippage.

The confirmation rule tests whether persistence across two observations compensates for a later fill. The efficiency rule tests whether cleaner immediate price progress improves entries while keeping sizing and stops fixed. The 35% threshold was chosen as a research assumption. Both rules could miss profitable trades during fast reversals. Evaluate the efficiency rule with the notebook's paired daily return difference and its changes in Sharpe, drawdown, traded shares and costs. A follow-up could compare net performance across predeclared volatility buckets or rerun with quote-derived execution costs.

The paper's VIX and dealer-gamma analyses require additional datasets. The simulator uses bar-level fills and omits dividends, broker minimums, borrow availability and fees, partial fills, cash yield, and size-dependent market impact. The test suite uses synthetic prices and mocked API responses.
