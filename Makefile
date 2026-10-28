SHELL := /bin/bash
PY ?= .venv/bin/python
TFLOCAL ?= $(CURDIR)/.venv/bin/tflocal
ENDPOINT ?= http://localhost:4566
SOURCE ?= books
RUN_ID ?=
AWSL := AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_DEFAULT_REGION=us-east-1 AWS_ENDPOINT_URL=$(ENDPOINT)
TF_LOCAL := cd infra && $(AWSL) "$(CURDIR)/$(PY)" "$(TFLOCAL)"

.PHONY: up build deploy-local crawl crawl-js reprocess inspect test test-int lint deploy-aws destroy-aws down

up:
	docker compose up -d localstack
	./scripts/wait_localstack.sh

build:
	./scripts/build_lambda.sh

deploy-local:
	$(TF_LOCAL) init -input=false
	$(TF_LOCAL) apply -auto-approve -input=false -var-file=envs/local.tfvars

crawl:
	$(AWSL) $(PY) -m scraper.cli crawl --source $(SOURCE)

crawl-js:
	docker compose --profile js up -d --build selenium-worker
	$(AWSL) $(PY) -m scraper.cli crawl --source quotes_js

reprocess:
	$(AWSL) $(PY) -m scraper.cli reprocess --source $(SOURCE) --run-id "$(RUN_ID)"

inspect:
	$(AWSL) $(PY) -m scraper.cli inspect

test:
	$(PY) -m pytest tests/unit --cov=scraper --cov-report=term-missing

test-int:
	$(AWSL) $(PY) -m pytest tests/integration -m integration -v

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	$(PY) -m mypy

deploy-aws:
	cd infra && terraform init -input=false
	cd infra && terraform apply -var-file=envs/aws.tfvars

destroy-aws:
	cd infra && terraform destroy -var-file=envs/aws.tfvars

down:
	docker compose --profile js down
