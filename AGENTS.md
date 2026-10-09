# AGENTS.md — Universal Real Estate Hunter

Operational and architectural guide for AI coding agents working on Universal Real Estate Hunter.

---

## 1. Evidence & Finish Classification

Treat every source according to what it can establish. Seller descriptions are unverified claims; photos show only visible details and may be stale, staged, or from another unit; official registries are authoritative for their recorded facts but may be incomplete or outdated; portal tags are unverified metadata. Preserve material contradictions with their source in `discrepancies`.

For finish-condition definitions and edge cases, read [`CONTEXT.md` §§2–3](CONTEXT.md) whenever changing filters, LLM/Vision prompts, or result presentation. Keep code and prompts aligned with that domain contract. Prompt files are executable instructions, not an independent source of domain truth.

## 2. Filtering & Qualification Architecture

The pipeline processes listings in 3 cascading stages:

1. **Stage 1: Hard Rules** (`src/filters/stage1_hard_rules.py`): Zero-cost fast reject for budget, property type, and location rules.
2. **Stage 2: Semantic Regex** (`src/filters/stage2_semantic.py`): Fast extraction of utilities, road conditions, finish state, and segment subtype.
3. **Stage 3: LLM Enrichment** (`src/filters/llm_analyzer.py` & `src/filters/__init__.py`): LLM output is a typed proposal. Validate its fields before applying it, and compare seller claims with portal tags and other evidence.

---

## 3. Verification & Quality Gates

Every code change touching scrapers, models, filters, or web interface must satisfy:

1. **Test Suite**: `pytest` (all tests must pass).
2. **Type Checking**: `mypy src/ tests/` (zero errors).
3. **Linter**: `ruff check src/ tests/` (zero warnings/errors).
4. **Container Rebuild** (when services or dependencies change): `docker compose build && docker compose up -d`

---

## Agent skills

### Issue tracker

GitHub issues via `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Canonical roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`CONTEXT.md` + `docs/adr/`). See `docs/agents/domain.md`.
