# Third-party verifier pack examples

Two minimal packs that register verifiers outside the `assaystone` package. They
exist to prove that the protocol is not a private interface: the scorecard
consumes a declaration, not an implementation detail.

| directory | verifier | catches |
|---|---|---|
| `todo_guard/` | `example.no_new_todo` | new `TODO` / `FIXME` markers |
| `secret_guard/` | `example.no_new_secrets` | added credentials matching a declared pattern |

Each directory is a standalone package with its own `pyproject.toml` and entry
point. Install one editable and it appears in the catalog:

```bash
cd examples/third_party_pack/todo_guard
pip install -e .
assaystone protocol | grep example.no_new_todo
```

To use a verifier in a contract, add its name and declare the tag it covers:

```json
{
  "required_defects": ["new-todo"],
  "verifiers": [{"name": "example.no_new_todo", "required": true}]
}
```

Both packs declare their blind spots, as the protocol requires. `todo_guard`
does not see markers in non-Python files; `secret_guard` does not see encoded or
split secrets, or a format outside its pattern list.
