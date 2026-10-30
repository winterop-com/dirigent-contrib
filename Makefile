# The gates CI runs, then the docs.
UV := env -u VIRTUAL_ENV uv

.PHONY: sync check test docs

sync:
	$(UV) sync

check:
	$(UV) run ruff format --check .
	$(UV) run ruff check .
	$(UV) run pyright
	$(UV) run mypy

test:
	$(UV) run pytest

docs:
	NO_MKDOCS_2_WARNING=1 $(UV) run mkdocs build --strict
