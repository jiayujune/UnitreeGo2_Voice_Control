"""
Compute pipeline metrics from the voice-command log (Stage 4: demo + metrics).

Reads the JSONL log written by local_voice_to_robot_ssh.py and reports:
  - per-stage latency (STT / intent parse / total): mean, median, p95, min, max
  - command-mapping success: how many spoken commands mapped to a recognized,
    executable robot action, and how many were actually sent.
  - breakdowns by action and by parser.

Usage:
    python3 pipeline_metrics.py [voice_command_log.jsonl] [--json out.json]
"""

import argparse
import json
from collections import Counter
from pathlib import Path

DEFAULT_LOG = "voice_command_log.jsonl"
LATENCY_KEYS = ("stt_ms", "parse_ms", "total_ms")


def load_events(path: Path):
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = int(rank)
    frac = rank - low
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * frac


def latency_stats(events):
    out = {}
    for key in LATENCY_KEYS:
        vals = [e[key] for e in events if isinstance(e.get(key), (int, float))]
        if not vals:
            out[key] = None
            continue
        out[key] = {
            "n": len(vals),
            "mean": round(sum(vals) / len(vals), 1),
            "median": round(_percentile(vals, 50), 1),
            "p95": round(_percentile(vals, 95), 1),
            "min": round(min(vals), 1),
            "max": round(max(vals), 1),
        }
    return out


def success_stats(events):
    total = len(events)
    recognized = sum(1 for e in events if (e.get("intent") or {}).get("intent") not in (None, "unknown"))
    executable = sum(1 for e in events if (e.get("intent") or {}).get("executable"))
    sent = sum(1 for e in events if e.get("sent_to_robot"))

    def rate(n):
        return round(n / total, 3) if total else None

    return {
        "total_commands": total,
        "recognized": recognized, "recognized_rate": rate(recognized),
        "executable": executable, "executable_rate": rate(executable),
        "sent_to_robot": sent, "sent_rate": rate(sent),
    }


def breakdowns(events):
    actions = Counter((e.get("intent") or {}).get("action", "none") for e in events)
    parsers = Counter(e.get("parser_mode") or (e.get("intent") or {}).get("parser") or "?" for e in events)
    return {"by_action": dict(actions.most_common()), "by_parser": dict(parsers.most_common())}


def build_report(events):
    return {
        "events": len(events),
        "latency_ms": latency_stats(events),
        "success": success_stats(events),
        "breakdown": breakdowns(events),
    }


def print_report(report):
    print("\n=== Voice Pipeline Metrics ===")
    print(f"events: {report['events']}")

    print("\n[Latency, ms]")
    lat = report["latency_ms"]
    print(f"  {'stage':<10}{'n':>5}{'mean':>9}{'median':>9}{'p95':>9}{'min':>9}{'max':>9}")
    labels = {"stt_ms": "STT", "parse_ms": "intent", "total_ms": "total"}
    any_lat = False
    for key in LATENCY_KEYS:
        s = lat.get(key)
        if not s:
            continue
        any_lat = True
        print(f"  {labels[key]:<10}{s['n']:>5}{s['mean']:>9}{s['median']:>9}"
              f"{s['p95']:>9}{s['min']:>9}{s['max']:>9}")
    if not any_lat:
        print("  (no latency fields in this log - run the pipeline after the timing update)")

    print("\n[Command-mapping success]")
    s = report["success"]
    print(f"  total commands:   {s['total_commands']}")
    print(f"  recognized:       {s['recognized']}  ({_pct(s['recognized_rate'])})")
    print(f"  executable:       {s['executable']}  ({_pct(s['executable_rate'])})")
    print(f"  sent to robot:    {s['sent_to_robot']}  ({_pct(s['sent_rate'])})")

    print("\n[By action]")
    for action, n in report["breakdown"]["by_action"].items():
        print(f"  {action:<14}{n}")
    print("\n[By parser]")
    for parser, n in report["breakdown"]["by_parser"].items():
        print(f"  {parser:<14}{n}")
    print()


def _pct(rate):
    return f"{rate * 100:.1f}%" if rate is not None else "n/a"


def main():
    parser = argparse.ArgumentParser(description="Pipeline latency + success metrics from the log.")
    parser.add_argument("log", nargs="?", default=DEFAULT_LOG, help=f"JSONL log path (default {DEFAULT_LOG}).")
    parser.add_argument("--json", help="Optional path to write the report as JSON.")
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.exists():
        parser.error(f"log not found: {log_path}")

    events = load_events(log_path)
    report = build_report(events)
    print_report(report)
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Wrote report to {args.json}")


if __name__ == "__main__":
    main()
