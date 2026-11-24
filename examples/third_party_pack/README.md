# Third-party verifier pack example

A minimal pack that registers one verifier outside the `assaystone` package.
It exists to prove that the protocol is not a private interface: the scorecard
consumes a declaration, not an implementation detail.

```bash
cd examples/third_party_pack
pip install -e .
assaystone protocol | grep example.no_new_todo
assaystone coverage --contract ../../examples/code_agent/contracts/hardened.json --require new-todo
```

The verifier is `example.no_new_todo`: it fails when a changed Python file adds a
`TODO`, `FIXME`, or `XXX` line. Its `blind_spots` name what it cannot see, as the
protocol requires.

To use it in a contract, add:

```json
{"name": "example.no_new_todo", "required": true}
```

and list `new-todo` in the contract's `required_defects`.
