# mt5-execution-analyzer

A zero-dependency Python script that recursively scans MetaTrader 5 terminal log folders, extracts all `at market done in X ms` trade execution entries, and produces three structured plain-text reports covering execution time statistics broken down by terminal, account, and symbol.

---

## What it does

MT5 writes a timestamped journal line every time an order fills at market, recording the exact execution time in milliseconds. This script collects all of those lines across every terminal installation and account in one pass, then reports:

- Min / max / avg / median / stdev execution times
- Breakdowns per terminal, per account, per currency pair, and per direction (buy/sell)
- Cross-terminal account tracking — useful when the same account runs on multiple VPS instances
- Spike detection: fills that land in the slowest 5% or exceed 5,000 ms are flagged automatically
- Hourly heatmap to identify which server-time hours produce the worst latency

---

## Requirements

- Python 3.10 or newer
- No third-party packages — standard library only (`os`, `re`, `statistics`, `collections`, `datetime`)

---

## Usage

1. Place `parse_execution_logs.py` in your MetaQuotes `Terminal` root folder:

```
C:\Users\<you>\AppData\Roaming\MetaQuotes\Terminal\
├── DDF819BCA69FB509\
│   └── logs\
│       ├── 20260522.log
│       └── 20260521.log
├── A3F92C1B44D7E110\
│   └── logs\
│       └── 20260522.log
└── parse_execution_logs.py   ← place here
```

2. Run it:

```bash
python parse_execution_logs.py
```

3. Three output files are written to the same folder.

---

## Output files

| File | Contents |
|------|----------|
| `execution_matches.txt` | Every matched trade line with terminal, account, file, timestamp, direction, lots, pair, and execution time |
| `execution_summary.txt` | Full statistical breakdown — per terminal, per account, per symbol, global totals, spike analysis, hourly breakdown |
| `execution_spikes.txt` | Quick-glance spike report — top 10 worst fills, spike counts per account/symbol/terminal, ASCII heatmaps by hour and date |

---

## Console output

```
Scanning from  : C:\...\MetaQuotes\Terminal
Log files found: 20

  DDF819BCA69FB509  (12 file(s), 342 match(es))
  A3F92C1B44D7E110  (8 file(s), 219 match(es))

Trade executions matched: 561

Output written to:
  execution_matches.txt
  execution_summary.txt
  execution_spikes.txt

Global: 561 trade(s)  2 terminal(s)  3 account(s)
  min=412.100 ms  max=18340.200 ms  avg=1823.441 ms  med=1540.300 ms
  spikes (>5000 ms): 12
```

---

## Configuration

Two constants at the top of the script control spike detection:

```python
SPIKE_PERCENTILE = 95    # top N% flagged as spikes
SPIKE_MIN_MS     = 5000  # absolute spike floor (ms)
```

A fill is flagged as a spike if it exceeds **both** the percentile threshold **and** the absolute floor. Adjust these to suit your broker and strategy.

---

## Log line format

The script expects the standard MT5 Trades journal format:

```
OH  0  07:58:34.079  Trades  '243560': order #175119352 buy 0.1 / 0.1 EURUSD at market done in 13013.700 ms
```

Fields extracted: timestamp, account number, direction, requested lots, filled lots, symbol, execution time.

---

## License

Copyright (C) 2026 minn0x  
Licensed under the [GNU General Public License v3.0](LICENSE)
