# Patches Layered on Top of Upstream

In this plan (foundation, v0.1.0-rc1) the engine is **unmodified** from the
pinned upstream commit recorded in `UPSTREAM.md`. The only deltas vs upstream
are:

- Upstream's `.github/` workflows have been removed (we run our own in the
  monorepo root's `.github/workflows/`).
- Upstream's `.git/` directory is absent (flat copy, see `UPSTREAM.md`).

Plan 2 (bio-languages) will add per-language patches for R, Julia, MATLAB,
Perl — each documented as a numbered entry below when it lands.
