# Pricing change fixture

A third domain for the acceptance plane: the agent refactored the fee
calculation, and the gate must show that the refactor is behaviour preserving.

- `seed.py` materialises `ledger.db` from `orders.json` (the database is a
  build artifact, not a committed binary).
- `fee.py old` is the branch in production; `fee.py new` is the refactor.
- `ledger` is a `sql` oracle: 3 orders, 12300 cents.
- `parity` is a `shadow` oracle: same orders through both branches, JSON
  compared with `generated_at` ignored.
- `tests` is a `command` oracle.
- `approvals.json` is the pricing owner's publish approval.

The core does not know what a fee is. `pricing.json` binds four generic
primitives.
