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
	$(PY) scripts/demo_all.py

selftest:
	$(PY) -m gtm_core.cli selftest

image:
	docker build -t gtm-agents:$$(grep '^version' pyproject.toml | cut -d'"' -f2) .

fleet:
	$(PY) netclaw/build.py --config $(or $(CONFIG),config)

clean-check:
	$(PY) netclaw/check_clean.py

release: clean-check test evals compile image fleet
