.PHONY: install test eval demo clean

install:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -q

eval:
	python eval/run_eval.py

demo: ## import the fixture into a throwaway store and show a report
	MUNIM_DEMO=1 python -c "print('Try: munim init && munim import eval/fixtures/synthetic_in.csv')"

clean:
	rm -rf build dist *.egg-info .pytest_cache
