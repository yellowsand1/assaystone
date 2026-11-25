"""Fee calculation, old and new.

``old`` is the branch in production. ``new`` is the refactor under review.
The shadow oracle runs both on the same orders and compares the JSON.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


def fee_cents(amount_cents: int, region: str, version: str) -> int:
    if version == "old":
        if region == "us":
            basis_points = 290
        elif region == "eu":
            basis_points = 250
        else:
            basis_points = 250
    else:
        rules = {"us": 290, "eu": 250}
        basis_points = rules.get(region, 250)
    return amount_cents * basis_points // 10000


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "new"
    orders = json.loads(Path("orders.json").read_text(encoding="utf-8"))
    print(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(
                    timespec="seconds"
                ),
                "version": version,
                "fees": [
                    {
                        "order_id": item["order_id"],
                        "fee_cents": fee_cents(
                            item["amount_cents"], item["region"], version
                        ),
                    }
                    for item in orders
                ],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
