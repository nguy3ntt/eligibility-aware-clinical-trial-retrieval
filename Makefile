.PHONY: install test lint format check api infra-up infra-down

install:
	pip install -e ".[dev]"

test:
	pytest

lint:
	ruff check .

format:
	ruff format .

check:
	ruff check .
	ruff format --check .
	pytest
	python -m compileall backend pipelines evaluation

api:
	uvicorn backend.app.main:app --reload

infra-up:
	docker compose -f infrastructure/compose.yaml up -d

infra-down:
	docker compose -f infrastructure/compose.yaml down
