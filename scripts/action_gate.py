"""Turn a gate JSON report into GitHub Action outputs and a step summary."""
from __future__ import annotations

import json
import os
import pathlib
import sys


def main(report_path: str) -> int:
    path = pathlib.Path(report_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    outcome = str(data.get("outcome") or "escalate")
    results = data.get("results") or []
    findings = sum(1 for item in results if item.get("outcome") != "pass")
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as handle:
        handle.write(f"verdict={outcome}\n")
        handle.write(f"findings={findings}\n")
        handle.write("traces=0\n")
    if outcome == "fail":
        print("::error::acceptance gate failed")
    elif outcome == "escalate":
        print("::warning::acceptance gate escalated to a human")
    for reason in data.get("reasons") or []:
        print(f"::notice::{reason}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        lines = [
            f"## Assaystone gate: {outcome}",
            "",
            "| oracle | type | outcome | reason |",
            "|---|---|---|---|",
        ]
        for item in results:
            reason = (item.get("reasons") or [""])[0].replace("|", "\\|")
            lines.append(
                f"| `{item.get('oracle')}` | {item.get('type')} | "
                f"{item.get('outcome')} | {reason} |"
            )
        for gap in data.get("gap") or []:
            lines.append(
                f"\n> assurance gap: `{gap.get('criterion')}` "
                f"({gap.get('severity')}) is not gated at this stage"
            )
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
