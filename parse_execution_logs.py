#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 minn0x
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
"""
mt5-execution-analyzer

parse_execution_logs.py

Place this script in your MetaQuotes/Terminal/ root folder.
It recursively finds all logs/*.log files inside every terminal
installation subfolder, parses MT5 trade execution lines, and writes:

  execution_matches.txt  - every matched trade line
  execution_summary.txt  - stats per terminal, per account, per symbol,
                           global totals, spike analysis, hourly breakdown
  execution_spikes.txt   - quick-glance spike report
"""

import os
import re
import statistics
from collections import Counter
from datetime import datetime

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

OUTPUT_DIR   = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILES = {
    "execution_matches.txt",
    "execution_summary.txt",
    "execution_spikes.txt",
}

SPIKE_PERCENTILE = 95    # top N% flagged as spikes
SPIKE_MIN_MS     = 5000  # absolute spike floor (ms)

# ---------------------------------------------------------------------------
# Regex  (MT5 Trades journal line)
# Example:
#   OH  0  07:58:34.079  Trades  '245672': order #175189152
#       buy 0.91 / 0.91 EURUSD at market done in 13013.700 ms
# ---------------------------------------------------------------------------

LINE_PATTERN = re.compile(
    r"\S+\s+\d+\s+"
    r"(\d{2}:\d{2}:\d{2}\.\d+)\s+"    # timestamp  (group 1)
    r"\S+\s+"
    r"'(\d+)':\s+"                      # account    (group 2)
    r".+?"
    r"\b(buy|sell)\s+"                   # direction  (group 3)
    r"([\d.]+)\s*/\s*([\d.]+)\s+"     # lots req/filled (groups 4,5)
    r"([A-Za-z]{6,8})\s+"                # pair       (group 6)
    r"at\s+market\s+done\s+in\s+"
    r"([\d.]+)\s*ms",                   # exec ms    (group 7)
    re.IGNORECASE
)

# ---------------------------------------------------------------------------
# Encoding detection
# ---------------------------------------------------------------------------

def detect_encoding(filepath):
    with open(filepath, "rb") as f:
        bom = f.read(4)
    if bom[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if bom[:4] in (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff"):
        return "utf-32"
    if bom[:2] == b"\xff\xfe":
        return "utf-16-le"
    if bom[:2] == b"\xfe\xff":
        return "utf-16-be"
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            f.read()
        return "utf-8"
    except UnicodeDecodeError:
        return "latin-1"

# ---------------------------------------------------------------------------
# Discovery: only files inside a "logs" subfolder
# ---------------------------------------------------------------------------

def find_log_files(root):
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        norm = dirpath.replace("\\", "/").lower()
        if norm.endswith("/logs"):
            terminal_id = os.path.basename(os.path.dirname(dirpath))
            for fname in filenames:
                if fname.lower().endswith(".log") and fname not in OUTPUT_FILES:
                    found.append((terminal_id, os.path.join(dirpath, fname)))
    return found

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def stats_block(times, indent="  "):
    if not times:
        return f"{indent}(no data)\n"
    sd = statistics.stdev(times) if len(times) > 1 else 0.0
    return (
        f"{indent}count  : {len(times)}\n"
        f"{indent}min    : {min(times):>12.3f} ms\n"
        f"{indent}max    : {max(times):>12.3f} ms\n"
        f"{indent}avg    : {statistics.mean(times):>12.3f} ms\n"
        f"{indent}median : {statistics.median(times):>12.3f} ms\n"
        f"{indent}stdev  : {sd:>12.3f} ms\n"
    )

def spike_threshold(times):
    if len(times) < 2:
        return SPIKE_MIN_MS
    p = sorted(times)
    return max(p[int(len(p) * SPIKE_PERCENTILE / 100)], SPIKE_MIN_MS)

def section(title, width=64):
    bar = "=" * width
    return f"\n{bar}\n  {title}\n{bar}\n"

def subsection(title, width=58):
    bar = "-" * width
    return f"\n{bar}\n  {title}\n{bar}\n"

def pair_row(label, times, indent="    "):
    """One-line symbol/direction stats row."""
    return (
        f"{indent}{label:<12}  count={len(times):>4}  "
        f"min={min(times):>10.3f} ms  max={max(times):>10.3f} ms  "
        f"avg={statistics.mean(times):>10.3f} ms  "
        f"med={statistics.median(times):>10.3f} ms\n"
    )

def spike_row(label, total_rows, spike_rows, indent="  "):
    """One-line spike summary row (used in spikes file)."""
    if not spike_rows:
        return ""
    sp_times = [r["exec_ms"] for r in spike_rows]
    pct = 100 * len(spike_rows) / len(total_rows)
    return (
        f"{indent}{label:<38}  {len(spike_rows):>4} spike(s) / "
        f"{len(total_rows):>4} trades ({pct:.1f}%)  "
        f"worst={max(sp_times):>10.3f} ms  "
        f"avg={statistics.mean(sp_times):>10.3f} ms\n"
    )

# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

source_dir  = os.path.dirname(os.path.abspath(__file__))
log_entries = find_log_files(source_dir)

print(f"Scanning from  : {source_dir}")
print(f"Log files found: {len(log_entries)}")
print()

all_matches  = []
term_summary = {}   # terminal_id -> {files, matches, errors}

for terminal_id, filepath in sorted(log_entries):
    if terminal_id not in term_summary:
        term_summary[terminal_id] = {"files": 0, "matches": 0, "errors": 0}
    encoding = detect_encoding(filepath)
    filename = os.path.basename(filepath)
    term_summary[terminal_id]["files"] += 1
    try:
        with open(filepath, "r", encoding=encoding, errors="replace") as fh:
            for lineno, line in enumerate(fh, 1):
                m = LINE_PATTERN.search(line)
                if m:
                    ts          = m.group(1)
                    account     = m.group(2)
                    direction   = m.group(3).lower()
                    lots_req    = m.group(4)
                    lots_filled = m.group(5)
                    pair        = m.group(6).upper()
                    exec_ms     = float(m.group(7))
                    all_matches.append({
                        "terminal":    terminal_id,
                        "account":     account,
                        "file":        filename,
                        "line":        lineno,
                        "timestamp":   ts,
                        "hour":        int(ts.split(":")[0]),
                        "direction":   direction,
                        "lots_req":    lots_req,
                        "lots_filled": lots_filled,
                        "pair":        pair,
                        "exec_ms":     exec_ms,
                        "raw":         line.rstrip()
                    })
                    term_summary[terminal_id]["matches"] += 1
    except Exception as e:
        term_summary[terminal_id]["errors"] += 1
        print(f"  WARNING: {filepath}: {e}")

for term, info in sorted(term_summary.items()):
    err_str = f"  {info['errors']} error(s)" if info["errors"] else ""
    print(f"  {term}  ({info['files']} file(s), {info['matches']} match(es)){err_str}")

print()
print(f"Trade executions matched: {len(all_matches)}")

# ---------------------------------------------------------------------------
# Pre-compute shared datasets once
# ---------------------------------------------------------------------------

times_all    = [r["exec_ms"] for r in all_matches]
all_accounts = sorted(set(r["account"]  for r in all_matches))
all_pairs    = sorted(set(r["pair"]     for r in all_matches))
terminals    = sorted(set(r["terminal"] for r in all_matches))
spike_thresh = spike_threshold(times_all) if times_all else SPIKE_MIN_MS
spikes_all   = [r for r in all_matches if r["exec_ms"] >= spike_thresh]

# ---------------------------------------------------------------------------
# Write execution_matches.txt
# ---------------------------------------------------------------------------

matches_path = os.path.join(OUTPUT_DIR, "execution_matches.txt")
with open(matches_path, "w", encoding="utf-8") as out:
    out.write(f"Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    out.write(f"Source    : {source_dir}\n\n")
    out.write(
        f"{'Terminal':<36} {'Account':<10} {'File':<16} {'Ln':>5}  "
        f"{'Time':>12}  {'Dir':<5} {'Lots':>9}  {'Pair':<10} {'Exec ms':>12}\n"
    )
    out.write("-" * 124 + "\n")
    for r in all_matches:
        out.write(
            f"{r['terminal']:<36} {r['account']:<10} {r['file']:<16} {r['line']:>5}  "
            f"{r['timestamp']:>12}  {r['direction']:<5} "
            f"{r['lots_req']:>4}/{r['lots_filled']:<4}  "
            f"{r['pair']:<10} {r['exec_ms']:>12.3f}\n"
        )
    out.write(f"\nTotal matches: {len(all_matches)}\n")

# ---------------------------------------------------------------------------
# Write execution_summary.txt
# ---------------------------------------------------------------------------

summary_path = os.path.join(OUTPUT_DIR, "execution_summary.txt")
with open(summary_path, "w", encoding="utf-8") as out:

    out.write(section("EXECUTION TIME SUMMARY"))
    out.write(f"  Generated      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    out.write(f"  Source         : {source_dir}\n")
    out.write(f"  Log files      : {len(log_entries)}\n")
    out.write(f"  Terminals      : {len(terminals)}\n")
    out.write(f"  Accounts       : {len(all_accounts)}\n")
    out.write(f"  Total trades   : {len(all_matches)}\n")
    out.write(f"  Spike threshold: > {spike_thresh:.0f} ms "
              f"(top {100-SPIKE_PERCENTILE}% or > {SPIKE_MIN_MS} ms)\n")

    if not all_matches:
        out.write("\n  No matching trade execution lines found.\n")
    else:

        # ====================================================================
        # SECTION 1 — Per terminal
        # ====================================================================
        out.write(section("1. PER-TERMINAL BREAKDOWN"))

        for term in terminals:
            t_rows   = [r for r in all_matches if r["terminal"] == term]
            t_times  = [r["exec_ms"] for r in t_rows]
            t_thresh = spike_threshold(t_times)
            t_spikes = [r for r in t_rows if r["exec_ms"] >= t_thresh]
            t_accts  = sorted(set(r["account"] for r in t_rows))

            out.write(subsection(f"Terminal: {term}"))
            out.write(f"  Accounts in this terminal: {", ".join(t_accts)}\n\n")
            out.write(stats_block(t_times))

            out.write("\n  Per account:\n")
            for acct in t_accts:
                a_rows  = [r for r in t_rows if r["account"] == acct]
                a_times = [r["exec_ms"] for r in a_rows]
                a_pairs = sorted(set(r["pair"] for r in a_rows))
                out.write(f"\n    Account {acct}  ({len(a_times)} trade(s))\n")
                out.write(stats_block(a_times, indent="      "))
                out.write(f"      Symbols: {", ".join(a_pairs)}\n")
                for direction in ("buy", "sell"):
                    dt = [r["exec_ms"] for r in a_rows if r["direction"] == direction]
                    if dt:
                        out.write(pair_row(direction.upper(), dt, indent="      "))

            out.write("\n  Per symbol (all accounts in terminal):\n")
            for pair in sorted(set(r["pair"] for r in t_rows)):
                pt = [r["exec_ms"] for r in t_rows if r["pair"] == pair]
                out.write(pair_row(pair, pt))

            if t_spikes:
                out.write(f"\n  Spikes (> {t_thresh:.0f} ms)  [{len(t_spikes)} event(s)]:\n")
                for sp in sorted(t_spikes, key=lambda x: x["exec_ms"], reverse=True):
                    out.write(
                        f"    {sp['exec_ms']:>10.3f} ms  {sp['timestamp']}  "
                        f"acct={sp['account']}  {sp['direction'].upper():<5} "
                        f"{sp['pair']:<10}  {sp['file']}\n"
                    )
            else:
                out.write(f"\n  No spikes above {t_thresh:.0f} ms.\n")

        # ====================================================================
        # SECTION 2 — Per account (cross-terminal)
        # ====================================================================
        out.write(section("2. PER-ACCOUNT BREAKDOWN (CROSS-TERMINAL)"))

        for acct in all_accounts:
            a_rows   = [r for r in all_matches if r["account"] == acct]
            a_times  = [r["exec_ms"] for r in a_rows]
            a_thresh = spike_threshold(a_times)
            a_spikes = [r for r in a_rows if r["exec_ms"] >= a_thresh]
            a_terms  = sorted(set(r["terminal"] for r in a_rows))

            out.write(subsection(f"Account: {acct}"))
            out.write(f"  Seen in terminals: {", ".join(a_terms)}\n\n")
            out.write(stats_block(a_times))

            out.write("\n  Per symbol:\n")
            for pair in sorted(set(r["pair"] for r in a_rows)):
                pt = [r["exec_ms"] for r in a_rows if r["pair"] == pair]
                out.write(pair_row(pair, pt))

            out.write("\n  Direction split:\n")
            for direction in ("buy", "sell"):
                dt = [r["exec_ms"] for r in a_rows if r["direction"] == direction]
                if dt:
                    out.write(pair_row(direction.upper(), dt))

            if a_spikes:
                out.write(f"\n  Spikes (> {a_thresh:.0f} ms)  [{len(a_spikes)} event(s)]:\n")
                for sp in sorted(a_spikes, key=lambda x: x["exec_ms"], reverse=True):
                    out.write(
                        f"    {sp['exec_ms']:>10.3f} ms  {sp['timestamp']}  "
                        f"{sp['direction'].upper():<5} {sp['pair']:<10}  "
                        f"{sp['terminal']}  {sp['file']}\n"
                    )
            else:
                out.write(f"\n  No spikes above {a_thresh:.0f} ms.\n")

        # ====================================================================
        # SECTION 3 — Global symbol summary
        # ====================================================================
        out.write(section("3. GLOBAL SYMBOL SUMMARY (ALL TERMINALS + ACCOUNTS)"))

        for pair in all_pairs:
            pt = [r["exec_ms"] for r in all_matches if r["pair"] == pair]
            out.write(subsection(f"Symbol: {pair}"))
            out.write(stats_block(pt))
            out.write("  Per account:\n")
            for acct in all_accounts:
                at = [r["exec_ms"] for r in all_matches
                      if r["pair"] == pair and r["account"] == acct]
                if at:
                    out.write(pair_row(f"acct {acct}", at))
            out.write("  Per terminal:\n")
            for term in terminals:
                tt = [r["exec_ms"] for r in all_matches
                      if r["pair"] == pair and r["terminal"] == term]
                if tt:
                    out.write(pair_row(term[:12], tt))

        # ====================================================================
        # SECTION 4 — Global totals
        # ====================================================================
        out.write(section("4. GLOBAL TOTALS"))
        out.write(stats_block(times_all))
        mn_entry = min(all_matches, key=lambda x: x["exec_ms"])
        mx_entry = max(all_matches, key=lambda x: x["exec_ms"])
        out.write(f"\n  Fastest trade:\n    {mn_entry['raw']}\n")
        out.write(f"\n  Slowest trade:\n    {mx_entry['raw']}\n")

        # ====================================================================
        # SECTION 5 — Spike analysis
        # ====================================================================
        out.write(section(f"5. SPIKE ANALYSIS  (threshold: > {spike_thresh:.0f} ms)"))
        pct = 100 * len(spikes_all) / len(all_matches)
        out.write(f"  Total spikes : {len(spikes_all)} of {len(all_matches)} ({pct:.1f}%)\n\n")

        if spikes_all:
            out.write(
                f"  {'Exec ms':>12}  {'Timestamp':>12}  {'Acct':<10} "
                f"{'Dir':<5} {'Pair':<10} {'Terminal':<36}  File\n"
            )
            out.write("  " + "-" * 108 + "\n")
            for sp in sorted(spikes_all, key=lambda x: x["exec_ms"], reverse=True):
                out.write(
                    f"  {sp['exec_ms']:>12.3f}  {sp['timestamp']:>12}  "
                    f"{sp['account']:<10} {sp['direction'].upper():<5} "
                    f"{sp['pair']:<10} {sp['terminal']:<36}  {sp['file']}\n"
                )
            out.write(subsection("Spikes per symbol"))
            for pair in all_pairs:
                sp_pair = [r for r in spikes_all if r["pair"] == pair]
                if sp_pair:
                    sp_times = [r["exec_ms"] for r in sp_pair]
                    out.write(
                        f"  {pair:<10}  {len(sp_pair):>4} spike(s)  "
                        f"max={max(sp_times):>10.3f} ms  "
                        f"avg={statistics.mean(sp_times):>10.3f} ms\n"
                    )
            out.write(subsection("Spikes per account"))
            for acct in all_accounts:
                sp_acct = [r for r in spikes_all if r["account"] == acct]
                if sp_acct:
                    sp_times = [r["exec_ms"] for r in sp_acct]
                    out.write(
                        f"  acct {acct:<12}  {len(sp_acct):>4} spike(s)  "
                        f"max={max(sp_times):>10.3f} ms  "
                        f"avg={statistics.mean(sp_times):>10.3f} ms\n"
                    )

        # ====================================================================
        # SECTION 6 — Hourly breakdown
        # ====================================================================
        out.write(section("6. HOURLY BREAKDOWN (Server Time)"))
        out.write(
            f"  {'Hour':>5}  {'Count':>6}  {'Min ms':>12}  "
            f"{'Max ms':>12}  {'Avg ms':>12}  {'Spikes':>7}\n"
        )
        out.write("  " + "-" * 65 + "\n")
        for hour in range(24):
            h_rows = [r for r in all_matches if r["hour"] == hour]
            if not h_rows:
                continue
            h_times  = [r["exec_ms"] for r in h_rows]
            h_spikes = sum(1 for t in h_times if t >= spike_thresh)
            out.write(
                f"  {hour:02d}:xx  {len(h_rows):>6}  "
                f"{min(h_times):>12.3f}  {max(h_times):>12.3f}  "
                f"{statistics.mean(h_times):>12.3f}  {h_spikes:>7}\n"
            )
        spike_hours = sorted(set(r["hour"] for r in spikes_all)) if spikes_all else []
        if spike_hours:
            out.write(f"\n  Hours with spikes: {", ".join(f'{h:02d}:xx' for h in spike_hours)}\n")

    out.write("\n" + "=" * 64 + "\n")

# ---------------------------------------------------------------------------
# Write execution_spikes.txt
# ---------------------------------------------------------------------------

spikes_path = os.path.join(OUTPUT_DIR, "execution_spikes.txt")
with open(spikes_path, "w", encoding="utf-8") as out:

    out.write(section("SPIKE QUICK-GLANCE REPORT"))
    out.write(f"  Generated      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    out.write(f"  Source         : {source_dir}\n")
    out.write(f"  Spike threshold: > {spike_thresh:.0f} ms "
              f"(top {100-SPIKE_PERCENTILE}% or > {SPIKE_MIN_MS} ms)\n")
    out.write(f"  Total trades   : {len(all_matches)}\n")
    out.write(f"  Total spikes   : {len(spikes_all)} "
              f"({100*len(spikes_all)/max(len(all_matches),1):.1f}%)\n")

    if not spikes_all:
        out.write("\n  No spikes detected.\n")
    else:

        # ── Top 10 worst spikes ──────────────────────────────────────────────
        out.write(subsection("TOP 10 WORST EXECUTIONS"))
        top10 = sorted(spikes_all, key=lambda x: x["exec_ms"], reverse=True)[:10]
        out.write(f"  {'#':>3}  {'Exec ms':>12}  {'Timestamp':>12}  {'Account':<10} "
                  f"{'Dir':<5} {'Pair':<10} {'Terminal':<36}  Date\n")
        out.write("  " + "-" * 106 + "\n")
        for i, sp in enumerate(top10, 1):
            date = sp["file"].replace(".log", "")
            out.write(
                f"  {i:>3}  {sp['exec_ms']:>12.3f}  {sp['timestamp']:>12}  "
                f"{sp['account']:<10} {sp['direction'].upper():<5} "
                f"{sp['pair']:<10} {sp['terminal']:<36}  {date}\n"
            )

        # ── Spike count per account ───────────────────────────────────────────
        out.write(subsection("SPIKES PER ACCOUNT"))
        for acct in all_accounts:
            row = spike_row(
                f"Account {acct}",
                [r for r in all_matches if r["account"] == acct],
                [r for r in spikes_all  if r["account"] == acct]
            )
            if row:
                out.write(row)

        # ── Spike count per symbol ───────────────────────────────────────────
        out.write(subsection("SPIKES PER SYMBOL"))
        for pair in all_pairs:
            row = spike_row(
                pair,
                [r for r in all_matches if r["pair"] == pair],
                [r for r in spikes_all  if r["pair"] == pair]
            )
            if row:
                out.write(row)

        # ── Spike count per terminal ─────────────────────────────────────────
        out.write(subsection("SPIKES PER TERMINAL"))
        for term in terminals:
            row = spike_row(
                term,
                [r for r in all_matches if r["terminal"] == term],
                [r for r in spikes_all  if r["terminal"] == term]
            )
            if row:
                out.write(row)

        # ── Spike hours heatmap ──────────────────────────────────────────────
        out.write(subsection("SPIKE HOURS (Server Time)"))
        out.write("  Hour    Spikes  Bar\n")
        out.write("  " + "-" * 50 + "\n")
        hour_counts = [sum(1 for r in spikes_all if r["hour"] == h) for h in range(24)]
        max_h = max(hour_counts) if any(hour_counts) else 1
        for hour, count in enumerate(hour_counts):
            if count == 0:
                continue
            bar = "#" * int(count / max_h * 30)
            out.write(f"  {hour:02d}:xx   {count:>5}  {bar}\n")

        # ── Spike day heatmap ────────────────────────────────────────────────
        out.write(subsection("SPIKE DATES (worst days)"))
        day_counts = Counter(r["file"].replace(".log", "") for r in spikes_all)
        out.write("  Date        Spikes  Bar\n")
        out.write("  " + "-" * 50 + "\n")
        max_d = max(day_counts.values()) if day_counts else 1
        for date, count in sorted(day_counts.items(), key=lambda x: -x[1])[:20]:
            bar = "#" * int(count / max_d * 30)
            out.write(f"  {date}   {count:>5}  {bar}\n")

        # ── Full spike list ────────────────────────────────────────────────
        out.write(subsection("FULL SPIKE LIST (most recent date first)"))
        out.write(f"  {'Exec ms':>12}  {'Date':<12} {'Timestamp':>12}  {'Account':<10} "
                  f"{'Dir':<5} {'Pair':<10} {'Terminal'}\n")
        out.write("  " + "-" * 106 + "\n")
        for sp in sorted(spikes_all, key=lambda x: (x["file"], x["timestamp"]), reverse=True):
            date = sp["file"].replace(".log", "")
            out.write(
                f"  {sp['exec_ms']:>12.3f}  {date:<12} {sp['timestamp']:>12}  "
                f"{sp['account']:<10} {sp['direction'].upper():<5} "
                f"{sp['pair']:<10} {sp['terminal']}\n"
            )

    out.write("\n" + "=" * 64 + "\n")

# ---------------------------------------------------------------------------
# Console
# ---------------------------------------------------------------------------

print(f"\nOutput written to:")
print(f"  {matches_path}")
print(f"  {summary_path}")
print(f"  {spikes_path}")
if times_all:
    print(
        f"\nGlobal: {len(all_matches)} trade(s)  "
        f"{len(terminals)} terminal(s)  "
        f"{len(all_accounts)} account(s)\n"
        f"  min={min(times_all):.3f} ms  max={max(times_all):.3f} ms  "
        f"avg={statistics.mean(times_all):.3f} ms  "
        f"med={statistics.median(times_all):.3f} ms\n"
        f"  spikes (>{spike_thresh:.0f} ms): {len(spikes_all)}"
    )
else:
    print("\nNo matching trade execution lines found.")
