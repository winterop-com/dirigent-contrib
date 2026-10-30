# dirigent-contrib

Block packs for [dirigent](https://github.com/winterop-com/dirigent) that reach outside systems,
one package per system:

- `dirigent-chap` -- the Chap modelling platform: datasets, backtests and predictions.
- `dirigent-climate` -- the open climate service: climate data aggregated to org units, and
  delivered to DHIS2.

A pack is installed beside dirigent and found through its entry point with nothing to
configure:

```bash
uv tool install dirigent-cli --with dirigent-chap --with dirigent-climate
```
