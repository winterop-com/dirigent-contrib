# Claude Code Instructions

This repository is `dirigent-contrib`, the one package of packs for outside systems other than
DHIS2, a sibling of dirigent in the same workspace, and follows dirigent's instructions in full:

@../dirigent/CLAUDE.md

## Here

- A new outside system is a subpackage of `dirigent_contrib` and an entry point in the one
  `pyproject.toml`, never a package of its own.
- A change that adds a pack, or makes a block or source reach an outside system the
  architecture model does not show yet, updates `architecture/workspace.dsl` in dirigent in a PR
  there, and regenerates its docs page with `make architecture-export-docs`.
- Run this repository's gates with `env -u VIRTUAL_ENV` when a dirigent venv is active.
