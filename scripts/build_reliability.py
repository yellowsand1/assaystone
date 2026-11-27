"""Regenerate the packaged reliability profile and its Markdown table.

    python3 scripts/build_reliability.py [--write-json PATH] [--write-md PATH]

The profile is measured, not hand-written. Run it after changing a check or a
corpus, and commit both outputs with the change.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from assaystone.reliability import build, render_markdown  # noqa: E402

DEFAULT_JSON = REPO / "assaystone" / "reliability.json"
DEFAULT_MD = REPO / "docs" / "reliability.md"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-json", default=str(DEFAULT_JSON))
    parser.add_argument("--write-md", default=str(DEFAULT_MD))
    args = parser.parse_args()
    profile = build()
    json_path = Path(args.write_json)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path = Path(args.write_md)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_markdown(profile), encoding="utf-8")
    measured = sum(1 for entry in profile["checks"].values() if entry["status"] == "measured")
    print(f"{measured}/{len(profile['checks'])} checks measured -> {json_path}, {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
