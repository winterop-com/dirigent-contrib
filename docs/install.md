# Install

Every pack here is in one distribution on PyPI, `dirigent-contrib`. Install it into the
environment dirigent runs in:

```bash
uv tool install dirigent-cli --with dirigent-contrib
```

or add it to a project:

```bash
uv add dirigent-contrib
```

Installing it is the whole of the configuration. Each pack has a `dirigent.plugins.v1` entry
point of its own, `chap` and `climate`, which is what an instance discovers it by, so after a
restart its blocks are in `dg blocks`, its connection kind is one `dg connection create` takes,
and its example shelves are in `dg examples list`. There is no config file to edit and no
registry to touch.

```bash
dg blocks
dg examples list --plugin chap
dg examples list --plugin climate
```

The package's version is the dirigent version it was built and tested against, and an instance
installs a matching pair; see [Releases](releases.md).

## The documents that use another pack

Three shelves compose packs. `chap-climate` reads the open climate service before it writes to
Chap, and both packs are in this package. `chap-dhis2` messages DHIS2 users and `climate-dhis2`
imports into DHIS2, and both need `dirigent-dhis2` installed as well. Each names every block it
uses under `requires.blocks`, so an instance without the other pack refuses the document at
apply, by name, rather than failing a run half way.
