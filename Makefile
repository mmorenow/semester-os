# A mirror of ./semester-os for people who reach for make, plus the developer
# loops. The launcher is the source of truth; nothing here does anything the
# launcher or the documented commands in CONTRIBUTING.md do not.

PYTHON := app/server/.venv/bin/python

.PHONY: help setup start start-bg stop status update doctor test build typecheck dev-server dev-web

help:
	@echo "make setup | start | start-bg | stop | status | update | doctor"
	@echo "make test | build | typecheck | dev-server | dev-web"

setup:
	./semester-os setup --dev

start:
	./semester-os start

start-bg:
	./semester-os start --background

stop:
	./semester-os stop

status:
	./semester-os status

update:
	./semester-os update

doctor:
	./semester-os doctor

test:
	./semester-os setup --dev
	$(PYTHON) -m pytest tests -q

build:
	cd app/web && npm run build

typecheck:
	cd app/web && npm run typecheck

# The API with auto-reload on 127.0.0.1, and the Vite dev server on :5173 that
# proxies /api to it. Run each in its own terminal.
dev-server:
	cd app/server && .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port $${SEMESTER_OS_PORT:-8790} --reload

dev-web:
	cd app/web && npm run dev
