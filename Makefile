# The gates CI runs, once per package, then the docs.
PACKAGES := dirigent-chap dirigent-climate
UV := env -u VIRTUAL_ENV uv

.PHONY: sync check test docs

sync:
	$(UV) sync --all-packages

check:
	$(UV) run ruff format --check packages
	$(UV) run ruff check packages
	$(UV) run pyright packages
	for package in $(PACKAGES); do $(UV) run mypy packages/$$package/src packages/$$package/tests || exit 1; done

test:
	for package in $(PACKAGES); do $(UV) run pytest packages/$$package || exit 1; done

docs:
	NO_MKDOCS_2_WARNING=1 $(UV) run mkdocs build --strict
