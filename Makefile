PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || command -v python3.10 2>/dev/null || command -v python3)

.PHONY: check-python demo demo-ops demo-audit benchmark test pytest lint package

check-python:
	@$(PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Assaystone requires Python 3.10+; set PYTHON to a newer interpreter")'

demo: check-python
	$(PYTHON) -m assaystone demo

demo-ops: check-python
	$(PYTHON) -m assaystone demo ops

demo-audit: check-python
	$(PYTHON) -m assaystone demo audit

benchmark: check-python
	$(PYTHON) -m assaystone benchmark failure-zoo --md docs/failure-zoo.md

test: check-python
	$(PYTHON) -m unittest discover -s tests -t . -v

pytest: check-python
	$(PYTHON) -m pytest

lint: check-python
	$(PYTHON) -m ruff check assaystone tests

package: check-python
	$(PYTHON) -m build
