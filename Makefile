# Every routine action, so none of them lives only in someone's shell history.
PYTHON ?= python3
export PYTHONPATH := src

.PHONY: help install refresh refresh-fast validate serve test prune clean schedule unschedule

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install: ## Install the package and its dependencies
	$(PYTHON) -m pip install -e .

refresh: ## Full pipeline: fetch, build, validate, prune (what the scheduler runs)
	$(PYTHON) -m market_recap.cli refresh --history 10y

refresh-fast: ## Same, without the SEC fundamentals bake
	$(PYTHON) -m market_recap.cli refresh --history 10y --skip-dcf

validate: ## Re-check the artifacts already on disk
	$(PYTHON) -m market_recap.cli validate

test: ## Run the test suite
	$(PYTHON) -m pytest tests/ -q

serve: ## Serve the site for local development
	$(PYTHON) scripts/serve.py

prune: ## Delete expired cache entries
	$(PYTHON) -m market_recap.cli prune

clean: ## Delete the whole cache, forcing a cold rebuild
	$(PYTHON) -m market_recap.cli prune --all

schedule: ## Install the daily post-close refresh (macOS launchd)
	./scripts/schedule.sh install

unschedule: ## Remove the scheduled refresh
	./scripts/schedule.sh uninstall
