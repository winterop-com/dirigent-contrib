# Chap with the open climate service

Documents that feed Chap from the open climate service: climate data aggregated to org units
by the `climate.*` blocks, imported into Chap by the `chap.*` blocks. An instance needs
`dirigent-contrib`, which carries both packs, and the engine's `storage.read`.

| File | The operation |
| --- | --- |
| [climate-to-chap-backtest.yaml](climate-to-chap-backtest.yaml) | Aggregate rainfall to org units, import it into Chap, and backtest a model. |
