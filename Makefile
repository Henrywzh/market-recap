# Every routine action, so none of them lives only in someone's shell history.
PYTHON ?= python3
REFRESH_FLAGS ?=
SITE_URL = https://market-recap-b5p.pages.dev
WRANGLER_DEPLOY = ./node_modules/.bin/wrangler pages deploy dist --project-name market-recap --branch main --commit-dirty=true
export PYTHONPATH := src

.PHONY: help install refresh refresh-fast validate site serve serve-live deploy deploy-only test lock prune clean status run-now snapshot-options snapshot-expectations

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install: ## Install the package and its dependencies (Python + pinned wrangler)
	$(PYTHON) -m pip install -e ".[dev]"
	npm install

refresh: ## Full pipeline: fetch, build, validate, prune (the nightly job adds --strict)
	$(PYTHON) -m market_recap.cli refresh --history 10y $(REFRESH_FLAGS)

refresh-fast: ## Same, without the SEC panels (FINANCIALS, VALUATION, DCF)
	$(PYTHON) -m market_recap.cli refresh --history 10y --skip-sec $(REFRESH_FLAGS)

validate: ## Re-check the artifacts already on disk
	$(PYTHON) -m market_recap.cli validate

test: ## Run the test suite (Python, and the browser-side maths under node)
	$(PYTHON) -m pytest tests/ -q
	node --test 'tests/js/*.test.mjs'

site: ## Assemble dist/ from the artifacts already on disk
	$(PYTHON) -m market_recap.cli site

serve: ## Serve dist/ for local development (the same tree that deploys)
	$(PYTHON) scripts/serve.py

serve-live: site ## Serve dist/ with the live-quote function, as Cloudflare runs it
	./node_modules/.bin/wrangler pages dev dist --port 8788

deploy: refresh ## Refresh, then publish dist/ to Cloudflare Pages
	$(PYTHON) scripts/guard_deploy.py $(SITE_URL)
	$(WRANGLER_DEPLOY)

deploy-only: site ## Publish what is already built, without refetching
	$(PYTHON) scripts/guard_deploy.py $(SITE_URL)
	$(WRANGLER_DEPLOY)

lock: ## Re-resolve requirements.lock to the newest versions pyproject allows
	rm -rf .lockvenv && $(PYTHON) -m venv .lockvenv
	.lockvenv/bin/pip install -q -e ".[dev]"
	{ grep '^#' requirements.lock; .lockvenv/bin/pip freeze --exclude-editable; } > requirements.lock.new
	mv requirements.lock.new requirements.lock && rm -rf .lockvenv
	@echo "requirements.lock updated -- run 'make test refresh' before committing it"

snapshot-options: ## Record today's option chains into data/snapshots (inside the New York window only)
	$(PYTHON) -m market_recap.cli snapshot options

snapshot-expectations: ## Record rates futures and event-market pricing into data/snapshots
	$(PYTHON) -m market_recap.cli snapshot expectations

prune: ## Delete expired cache entries
	$(PYTHON) -m market_recap.cli prune

clean: ## Delete the whole cache, forcing a cold rebuild
	$(PYTHON) -m market_recap.cli prune --all

status: ## Recent nightly runs, and what the live site is showing
	@gh run list --workflow refresh.yml --limit 5
	@printf 'live: '; curl -fsS $(SITE_URL)/artifacts/manifest.json \
	  | $(PYTHON) -c 'import json,sys; m=json.load(sys.stdin); print("as_of", m["as_of"], " generated_at", m["generated_at"])'

run-now: ## Trigger the nightly job on GitHub now
	gh workflow run refresh.yml
