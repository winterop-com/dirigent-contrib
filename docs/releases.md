# Releases

The packs follow dirigent's version. Each depends on `dirigent-common` and `dirigent-plugin`
pinned to one release, and carries that release's number: `dirigent-chap` 0.27.1 is the pack
built against dirigent 0.27.1, and the two numbers are never read as independent. The plugin
contract changes directly before 1.0 rather than through compatibility shims, so a pack built
against another dirigent is not supported.

Both packs are released together. A `vX.Y.Z` tag on this repository is checked against every
package's version, tested, and publishes each package to PyPI by trusted publishing, from a
GitHub environment of its own: `pypi-dirigent-chap` and `pypi-dirigent-climate`.

Every release, with its notes, is on
[the repository's releases page](https://github.com/winterop-com/dirigent-contrib/releases).
What changed in the engine under it is in
[dirigent's release notes](https://winterop-com.github.io/dirigent/releases/).

## What each pack was rehearsed against

The systems these packs speak to release on their own schedules, so each pack's pages say
which versions its blocks were built and tested against:
[Chap](chap/index.md#rehearsed-against) and
[the open climate service](climate/index.md#rehearsed-against).
