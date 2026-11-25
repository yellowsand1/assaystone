"""Materialise the ledger from orders.json.

The gate runs this before the SQL oracle, so the database is a build
artifact, not a committed binary.
"""
import json
import sqlite3
from pathlib import Path


def main() -> None:
    orders = json.loads(Path("orders.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect("ledger.db")
    try:
        connection.execute("drop table if exists orders")
        connection.execute(
            "create table orders ("
            "order_id text primary key, amount_cents integer, region text)"
        )
        connection.executemany(
            "insert into orders values (?, ?, ?)",
            [
                (item["order_id"], item["amount_cents"], item["region"])
                for item in orders
            ],
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    main()
