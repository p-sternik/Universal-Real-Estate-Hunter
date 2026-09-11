# Changelog

All notable changes to this project will be documented in this file.

The changelog is maintained automatically by the release workflow.

<!-- version list -->

## v1.8.1 (2026-09-11)

### Bug Fixes

- **scheduler**: Prevent daemon exit and docker restart-loop when scheduler is disabled
  ([`afbf890`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/afbf89049091b8c0e67c63f535112c8922c8ed88))


## v1.8.0 (2026-09-11)

### Features

- Refactor settings modal for mobile RWD, bottom sheet layout, and touch ergonomics
  ([`9c0dd7a`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/9c0dd7aa4e113a205a7abc44032e123c5136bfaa))


## v1.7.0 (2026-09-11)

### Features

- Safety hard-rejects, configurable CAPEX, spatial cache and dashboard UX
  ([`4c6903d`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/4c6903d037e6760e5197f99c305a3f0f4ca7fbbf))


## v1.6.4 (2026-09-11)

### Bug Fixes

- Enforce profile isolation, dynamic city analytics, and multi-provider llm configuration
  ([`cc74ac6`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/cc74ac61dad781ba771cebf8aaa1c2fcb9cd133c))


## v1.6.3 (2026-09-10)

### Bug Fixes

- Resolve sqlite readonly database and lock contention across containers
  ([`1dd0e73`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/1dd0e738aa66342bbeabd62d260952951dbb6abb))


## v1.6.2 (2026-09-10)

### Bug Fixes

- Build and push multi-arch docker images for amd64 and arm64
  ([`8902d60`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/8902d60b7317a3320bcb0e34ec46ea4a707784a3))


## v1.6.1 (2026-09-10)

### Bug Fixes

- Resolve sqlite database locked error and add rich progress logging with live filter
  ([`50e9df2`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/50e9df2c14c001a8d61eab195a94565c98db1253))


## v1.6.0 (2026-09-10)

### Features

- Auto-backfill spatial due diligence for existing listings during sync
  ([`47a1d56`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/47a1d56825015347f2c62e6f5c71990fd399790b))


## v1.5.0 (2026-09-10)

### Features

- Implement 5 advanced spatial checks (SIDUSIS FTTH, parcel OBB geometry, NMT slope, PKA
  walkability, high-voltage lines)
  ([`c7d9897`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/c7d98971597fc815778039265b4d0f35157d7af1))


## v1.4.0 (2026-09-10)

### Features

- Implement Tier 1 geospatial due diligence and spatial audit integration
  ([`4b070d8`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/4b070d88ca0eec005c388a084c0639fecef8a716))


## v1.3.0 (2026-09-10)

### Code Style

- Apply pre-commit lint and format fixes
  ([`18bd44a`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/18bd44a15a8b27749897ca76e18d760377f822ff))

### Features

- Negotiation intelligence, scrape cancellation, and dashboard static split
  ([`295fc61`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/295fc6189a19f0f614925c5e7b73306cac8d5c84))


## v1.2.0 (2026-09-10)

### Documentation

- **license**: Update license to PolyForm Noncommercial 1.0.0
  ([`3db9089`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/3db90890d0da53054cdce7ca8e84b3678918a595))

### Features

- Integrate MPZP zoning and ISOK flood risk audit with LLM due-diligence
  ([`94f145c`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/94f145c40441626ffb32fc05751b4b40e2ed3341))


## v1.1.0 (2026-09-10)

### Features

- Overhaul LLM due-diligence prompt and add dashboard DB reset
  ([`bdc3657`](https://github.com/p-sternik/Universal-Real-Estate-Hunter/commit/bdc36570e569a117a2c108c7ed6dcde3ddd59b09))


## v1.0.0 (2026-09-10)

- Initial Release
