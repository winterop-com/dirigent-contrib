# dirigent-contrib

[![CI](https://github.com/winterop-com/dirigent-contrib/actions/workflows/ci.yaml/badge.svg?branch=main)](https://github.com/winterop-com/dirigent-contrib/actions/workflows/ci.yaml)
[![Docs](https://img.shields.io/badge/docs-winterop--com.github.io%2Fdirigent--contrib-2b2f38)](https://winterop-com.github.io/dirigent-contrib/)

Block packs for [dirigent](https://github.com/winterop-com/dirigent) that reach outside systems,
one package per system:

- [`dirigent-chap`](packages/dirigent-chap) -- the Chap modelling platform: datasets, backtests,
  predictions and their quantiles, configured models, and the endemic channel.
- [`dirigent-climate`](packages/dirigent-climate) -- the open climate service: climate data
  aggregated to org units, batch jobs and their payloads, delivery to DHIS2, and ingesting and
  syncing managed datasets.

A pack is installed beside dirigent and found through its entry point with nothing to
configure:

```bash
uv tool install dirigent-cli --with dirigent-chap --with dirigent-climate
```

Documentation: <https://winterop-com.github.io/dirigent-contrib/>.

## Working on it

The repository is one uv workspace with a package per system under `packages/`. The gates CI
runs, per package:

```bash
make sync
make check
make test
make docs
```

Live checks against a real server only read, and are opt-in:

```bash
DIRIGENT_LIVE=1 uv run pytest -m live
DIRIGENT_LIVE=1 CHAP_LIVE_URL=http://localhost:8000 uv run pytest -m live
```

## Licence

Copyright (c) 2026 Morten Olav Hansen. All rights reserved. The source is published for
reference only: no licence to use, copy, modify or distribute it is granted, and any use
beyond reading requires written permission.
