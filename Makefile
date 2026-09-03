PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)

.PHONY: dev start email-worker migrate install

dev:
	$(PYTHON) -m uvicorn app.main:app --reload

start:
	test "$${APP_ENV}" = "production" || (echo "APP_ENV=production is required for make start"; exit 1)
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $${PORT:-8000} --no-server-header --proxy-headers --forwarded-allow-ips "$${FORWARDED_ALLOW_IPS:-127.0.0.1}"

email-worker:
	test "$${APP_ENV}" = "production" || (echo "APP_ENV=production is required for the email worker"; exit 1)
	$(PYTHON) -m app.email_worker

migrate:
	$(PYTHON) -m alembic upgrade head

install:
	$(PYTHON) -m pip install -r requirements.txt
