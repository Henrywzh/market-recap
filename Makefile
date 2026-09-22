# Every routine action, so none of them lives only in someone's shell history.
PYTHON ?= python3
export PYTHONPATH := src

.PHONY: help install refresh refresh-fast validate site serve deploy deploy-only test prune clean schedule unschedule schedule-check schedule-status schedule-run logs

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install: ## Install the package and its dependencies (Python + pinned wrangler)
	$(PYTHON) -m pip install -e .
	npm install

refresh: ## Full pipeline: fetch, build, validate, prune (what the scheduler runs)
	$(PYTHON) -m market_recap.cli refresh --history 10y

refresh-fast: ## Same, without the SEC fundamentals bake
	$(PYTHON) -m market_recap.cli refresh --history 10y --skip-dcf

validate: ## Re-check the artifacts already on disk
	$(PYTHON) -m market_recap.cli validate

test: ## Run the test suite
	$(PYTHON) -m pytest tests/ -q

site: ## Assemble dist/ from the artifacts already on disk
	$(PYTHON) -m market_recap.cli site

serve: ## Serve dist/ for local development (the same tree that deploys)
	$(PYTHON) scripts/serve.py

deploy: refresh ## Refresh, then publish dist/ to Cloudflare Pages
	./node_modules/.bin/wrangler pages deploy dist --project-name market-recap --branch main --commit-dirty=true

deploy-only: site ## Publish what is already built, without refetching
	./node_modules/.bin/wrangler pages deploy dist --project-name market-recap --branch main --commit-dirty=true

prune: ## Delete expired cache entries
	$(PYTHON) -m market_recap.cli prune

clean: ## Delete the whole cache, forcing a cold rebuild
	$(PYTHON) -m market_recap.cli prune --all

schedule: ## Install the daily post-close refresh + deploy (macOS launchd)
	./scripts/schedule.sh install

unschedule: ## Remove the scheduled refresh
	./scripts/schedule.sh uninstall

schedule-check: ## Report what the next scheduled run will be able to do
	./scripts/schedule.sh check

schedule-status: ## Show whether launchd has the job loaded
	./scripts/schedule.sh status

schedule-run: ## Run the scheduled job now, exactly as launchd would
	./scripts/schedule.sh run

logs: ## Tail the scheduled job's log
	tail -f data/logs/refresh.log
