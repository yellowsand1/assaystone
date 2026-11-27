# Support-integrity fixture

A small repository whose test suite imports a shared assertion helper from
`helpers/`, outside the protected `tests/` prefix. It exists so the benchmark can
test whether a check sees tampering with test support code.
