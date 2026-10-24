PY ?= python3
export PYTHONPATH := core:.

.PHONY: test evals compile demo selftest image release fleet clean-check

test:
	$(PY) -m pytest -q

evals:
	$(PY) -m evals.runner

compile:
	$(PY) build/compile.py

demo:
	rm -f demo.db && DATABASE_URL=sqlite:///demo.db $(PY) -m gtm_core.cli init && \
	DATABASE_URL=sqlite:///demo.db $(PY) -m gtm_core.cli import signal-scout accounts data/sample/accounts.csv && \
	DATABASE_URL=sqlite:///demo.db $(PY) -m gtm_core.cli import signal-scout signals data/sample/signals.csv && \
	DATABASE_URL=sqlite:///demo.db $(PY) -m gtm_core.cli run signal-scout daily_sweep

selftest:
	$(PY) -m gtm_core.cli selftest

image:
	docker build -t gtm-agents:$$(grep '^version' pyproject.toml | cut -d'"' -f2) .

fleet:
	$(PY) netclaw/build.py $(if $(PROFILE),--profile $(PROFILE),)

clean-check:
	$(PY) netclaw/check_clean.py

release: clean-check test evals compile image fleet
