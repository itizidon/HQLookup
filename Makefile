PYTHON ?= python3
HOST ?= 0.0.0.0
PORT ?= 8000

.PHONY: install dev start migrate migration-sql check

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -r requirements.txt

dev:
	$(PYTHON) -m uvicorn app.main:app --reload --host 127.0.0.1 --port $(PORT)

start:
	$(PYTHON) -m uvicorn app.main:app --host $(HOST) --port $(PORT)

migrate:
	$(PYTHON) -m alembic upgrade head

migration-sql:
	$(PYTHON) -m alembic upgrade head --sql

check:
	$(PYTHON) -m compileall -q app alembic
	$(PYTHON) -m alembic heads
	git diff --check
