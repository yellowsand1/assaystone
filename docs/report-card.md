# Report card: hardened

**PASS** — coverage 100%, resistance 67%, recall 100%

## Protocol

Contract and verifiers conform to the protocol.

## Coverage

| metric | value |
|---|---|
| declared defect classes | 8 |
| decided by an independent check | 100% |
| at risk | 0 |

## Recall (labelled traces)

| defects | caught | escaped | routed | false alarms | catch rate | false-alarm rate | avg cost |
|---|---|---|---|---|---|---|---|
| 4 | 4 | 0 | 0 | 0 | 100% | 0% | $0.000813 |

## Resistance (Goodhart suite)

| family | defective | caught | escalated | escaped | resistance |
|---|---|---|---|---|---|
| `mechanical` | 3 | 3 | 0 | 0 | 100% |
| `ops_lineage` | 1 | 1 | 0 | 0 | 100% |
| `semantic` | 2 | 0 | 0 | 2 | 0% |

Declared escape rate: **100%**. Broken claims: **0**. Surprises: **0**.
