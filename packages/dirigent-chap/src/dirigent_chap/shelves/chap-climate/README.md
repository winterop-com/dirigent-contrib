# Chap with the open climate service

Documents that feed Chap from the open climate service: climate data aggregated to org units
by the `climate.*` blocks of `dirigent-climate`, imported into Chap by the `chap.*` blocks.
An instance needs both packs installed, and the engine's `storage.read`.

| File | The operation |
| --- | --- |
| [climate-to-chap-backtest.yaml](climate-to-chap-backtest.yaml) | Aggregate rainfall to Chap CSV, import it beside the case counts, and backtest. |
