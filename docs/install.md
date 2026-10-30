# Install

Each pack is its own distribution on PyPI. Install the one a deployment needs, or both, into
the environment dirigent runs in:

```bash
uv tool install dirigent-cli --with dirigent-chap --with dirigent-climate
```

or add them to a project:

```bash
uv add dirigent-chap dirigent-climate
```

Installing a pack is the whole of the configuration. The `dirigent.plugins.v1` entry point in
its `pyproject.toml` is what an instance discovers it by, so after a restart its blocks are in
`dg blocks`, its connection kind is one `dg connection create` takes, and its example shelves
are in `dg examples list`. There is no config file to edit and no registry to touch.

```bash
dg blocks
dg examples list --plugin chap
dg examples list --plugin climate
```

A pack's version is the dirigent version it was built and tested against, and an instance
installs a matching pair; see [Releases](releases.md).

## The documents that use another pack

Two shelves compose packs: `chap-climate` in `dirigent-chap` reads the open climate service
before it writes to Chap, and `climate-dhis2` in `dirigent-climate` imports into DHIS2 through
`dirigent-dhis2`. Each names every block it uses under `requires.blocks`, so an instance without
the other pack refuses the document at apply, by name, rather than failing a run half way.
