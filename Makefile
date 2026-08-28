.PHONY: install test eval demo clean

install:
	uv sync --all-extras

test:
	uv run --package munim pytest packages/classify/tests -q

eval:
	uv run --package munim --directory packages/classify python eval/run_eval.py

demo: ## init and import the fixture into your real ~/.munim store, then show a report
	uv run --package munim munim init && \
	uv run --package munim munim import packages/classify/eval/fixtures/synthetic_in.csv

clean:
	rm -rf packages/*/build packages/*/dist packages/*/*.egg-info *.egg-info .pytest_cache .venv
