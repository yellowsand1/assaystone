PYTHON ?= $(shell command -v python3.12 2>/dev/null || command -v python3.11 2>/dev/null || command -v python3.10 2>/dev/null || command -v python3)

.PHONY: check-python demo demo-ops demo-audit demo-adversarial demo-plane trial benchmark benchmark-goodhart scorecard leaderboard compose coverage protocol protocol-json growth-snapshot test pytest lint package

check-python:
	@$(PYTHON) -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Assaystone requires Python 3.10+; set PYTHON to a newer interpreter")'

demo: check-python
	$(PYTHON) -m assaystone demo

demo-ops: check-python
	$(PYTHON) -m assaystone demo ops

demo-audit: check-python
	$(PYTHON) -m assaystone demo audit

demo-adversarial: check-python
	$(PYTHON) -m assaystone demo adversarial

demo-plane: check-python
	$(PYTHON) -m assaystone demo plane --output-dir /tmp/assaystone-plane-demo

benchmark: check-python
	$(PYTHON) -m assaystone benchmark failure-zoo --md docs/failure-zoo.md

benchmark-goodhart: check-python
	$(PYTHON) -m assaystone benchmark goodhart --md docs/goodhart.md

scorecard: check-python
	$(PYTHON) -m assaystone scorecard --contract examples/code_agent/contracts/hardened.json --trace examples/code_agent/traces --baseline examples/code_agent/baseline --md docs/report-card.md

leaderboard: check-python
	$(PYTHON) -m assaystone leaderboard --manifest benchmarks/leaderboard.json --md docs/leaderboard.md; test $$? -ne 2

coverage: check-python
	$(PYTHON) -m assaystone coverage --contract examples/code_agent/contracts/hardened.json

protocol: check-python
	$(PYTHON) -m assaystone protocol

protocol-json: check-python
	$(PYTHON) -m assaystone protocol --json > docs/protocol.json

growth-snapshot: check-python
	$(PYTHON) scripts/growth_snapshot.py yellowsand1/assaystone --pypi assaystone

test: check-python
	$(PYTHON) -m unittest discover -s tests -t . -v

pytest: check-python
	$(PYTHON) -m pytest

lint: check-python
	$(PYTHON) -m ruff check assaystone tests scripts

release-prep: check-python
	$(PYTHON) scripts/release_prep.py --version $(VERSION)

trial: check-python
	$(PYTHON) scripts/trial.py --markdown > docs/trial.md

package: check-python
	$(PYTHON) -m build
