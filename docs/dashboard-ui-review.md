# Dashboard — UI Review (6-Pillar)

> **Resolution (2026-09-21, impeccable top-3):** P0 color-only signals fixed
> (audit-dot styles + severity labels; map pin tooltips + status legend).
> Emoji→SVG + missing tokens defined (`--purple-*`, `--yellow`, `--accent`,
> `--text`, `--font-weight-bold`, `--r-xl`). Modal `role`/`aria-modal`,
> focus-return, `aria-live` toast, `--text-faint` contrast raised.
> Full ~100-site hex→token dedup + badge reduction + keyboard triage deferred.

**Audited:** 2026-09-21
**Baseline:** abstract 6-pillar standards (no UI-SPEC.md design contract exists in this repo)
**Screenshots:** captured (9 views, Playwright/Chromium) to `%TEMP%\opencode\ui-review\` — **not visually inspected** (audit model has no image input); this is a code-based audit.

**Scope:** `src/services/templates/dashboard.html` + `assets/dashboard.css` + `assets/js/{dashboard,due-diligence,transport}.js`. Views: split / grid / table / map / settings modal / AI drawer / filters popover / mobile.

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Domain-specific Polish copy, but success messages use exclamations and 3 native `alert()`s remain |
| 2. Visuals | 4/4 | Clear focal point, consistent stroke-1.5 SVG iconography, icon buttons carry aria-labels/tooltips |
| 3. Color | 3/4 | Solid token system, but ~100 hardcoded hex values duplicate tokens and a second (violet) accent persists |
| 4. Typography | 3/4 | Clean 11–22px scale + 3 weights, but ~60 hardcoded `font-size` values bypass it (9–26px off-scale) |
| 5. Spacing | 4/4 | Consistent 4px-radius tokens + gap-based layout; dense but appropriate for a data panel |
| 6. Experience Design | 3/4 | Strong states (skeleton, empty, error, disabled, focus), but native `confirm()`/`prompt()` mix with the toast system |

**Overall: 20/24**

---

## Top 3 Priority Fixes

1. **Native `alert()`/`confirm()`/`prompt()` dialogs** (`dashboard.js:902,906,1572,4408,4412`) — they break the otherwise-polished custom UI. User impact: jarring browser-native chrome in an otherwise Linear-grade panel. Fix: route through the existing `showToast()` + a confirmation modal (the reset flow already has a typed-confirm pattern to mirror).

2. **Hardcoded hex colors that duplicate tokens** (~100 sites, e.g. `#3b82f6`/`#22c55e`/`#ef4444` alongside `--blue`/`--green`/`--red`) — maintainability risk and the source of subtle accent drift: `.btn-primary` uses `#2563eb`/`#1d4ed8` (blue-600/700) instead of `--blue`. Fix: replace with `var(--*)` references so a single source of truth holds.

3. **Off-scale `font-size` values** (`9px` at `:4025,4033`, `10px`, `16px`, `18px`, `26px` at `:1979`) — the scale comment claims "minimum 13px for meaningful content", but 9–10px micro-tags fall below WCAG minimums and 26px/18px live outside the declared scale. Fix: extend the token scale with `--font-size-3xs` (10px) and `--font-size-3xl` (26px), then map hardcoded values back to tokens.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

- **Exclamation marks in success copy** — `dashboard.js:1611` `'Wysłano pomyślnie!'` and `:1614` `showToast(... wysłana pomyślnie!)`. The guideline "be confident, not loud" applies; drop the `!`.
- **Native dialog copy is disjointed** — `alert("Nie można usunąć jedynego profilu…")` (`:902`), `alert('Wybierz co najmniej 2 oferty…')` (`:4408`), `alert('Zalecane porównanie to 2–4 oferty…')` (`:4412`). Copy itself is fine; the *delivery mechanism* is the problem (see Pillar 6).
- Otherwise strong: no lorem ipsum, no AI clichés, realistic Polish domain language, composed empty/error copy (rewritten this pass).

### Pillar 2: Visuals (4/4)

- Clear focal point per view (listing card photo → price → title hierarchy).
- Icon-only buttons are paired with `aria-label` + `title` (e.g. topbar refresh/settings at `dashboard.html:70,78`).
- Consistent `stroke-width="1.5"` across all inline SVG icons; semantic status badges (qualified/rejected/whitelist/review).
- Minor: `★`/`☆` star glyph is monochrome and acceptable; no other glyph/emoji inconsistency remains after the emoji-cleanup pass.

### Pillar 3: Color (3/4)

- Strong foundation: off-black `#090a0f` canvas, cool-gray family, single primary accent (`--blue`), semantic status hues, and a `@media print` light-palette override (`dashboard.css:4509+`) for the PDF report.
- **Token duplication** — hardcoded values mirror tokens across ~100 sites. Representative offenders:
  - `#3b82f6` at `:89,118,451,795,3869` (== `--blue`)
  - `#22c55e` at `:94,1181,4391` (== `--green`)
  - `#ef4444` at `:104,3793,3831,4393` (== `--red`)
- **Accent drift** — `.btn-primary` uses `#2563eb` (`:451`) / `#1d4ed8` (`:456`), a darker blue than `--blue #3b82f6`; visually close but not the same hue.
- **Second accent** — violet `#8b5cf6`/`#c084fc` (`:1183,1190,1837,1844,1875,1916`) + `--violet` tokens for tags/AI badges, plus yellow `#eab308` (`:1185,1189,1492`) for favorites. These are semantic, but violet is a de-facto second brand accent.

### Pillar 4: Typography (3/4)

- Declared scale `--font-size-2xs…2xl` = 11/12/13/14/15/16/19/22px; weights 400/500/600; `tabular-nums` on all numeric content; self-hosted IBM Plex Sans + Mono (this pass).
- **Token bypass** — ~60 hardcoded `font-size: Npx` rules. Off-scale values: `9px` (`:4025,4033`), `10px` (many, e.g. `:3643`), `16px` (`:4479`), `18px` (`:2008`), `26px` (`:1979`).
- The 9–10px micro-tags conflict with the stated "minimum 13px for meaningful content" and are below the 12px WCAG-recommended floor for body text (acceptable only for non-essential labels, but worth a conscious `--font-size-3xs` token).

### Pillar 5: Spacing (4/4)

- Radii tokens (`3/4/6/8px`), gap-based flex/grid layout, `auto-fill minmax(330px,1fr)` card grid, `14px` card gap — consistent and intentional.
- No arbitrary-`[px]` class sprawl (vanilla CSS, not Tailwind). Dense spacing is appropriate for a data/analytics dashboard rather than a marketing page.

### Pillar 6: Experience Design (3/4)

- **Present:** skeleton loaders (added this pass) for grid; composed `.empty-state` + `.empty-state--error` (grid, table, error paths); `:disabled` states for `.btn`, scrape-cancel, config inputs, AI-audit (`:448,742,2147,2299,3729`); global `:focus-visible` ring (`dashboard.css` base section); `prefers-reduced-motion` guard on skeleton shimmer.
- **Mixed interaction patterns** — native `confirm()` (`:906`, profile delete) and `prompt()` (`:1572`, type-"RESET" reset) coexist with the custom toast + typed-confirm flow (`showToast('Anulowano — nie wpisano RESET.')` at `:1577`). The native dialogs are functionally safe but stylistically jarring.
- **Observed at runtime:** image proxy returned multiple `502 Bad Gateway` during capture (listing image CDN fetch failures) — cards degrade to placeholder, but this is a backend/upstream concern, not a UI-code defect.

---

## Files Audited

- `src/services/templates/dashboard.html`
- `src/services/templates/assets/dashboard.css`
- `src/services/templates/assets/js/dashboard.js`
- `src/services/templates/assets/js/due-diligence.js`
- `src/services/templates/assets/js/transport.js`

## Recommendation Count

- Priority fixes: 3
- Minor recommendations: 5 (exclamation marks, `--font-size-3xs`/`3xl` tokens, violet-accent decision, `★` glyph decision, image-proxy 502 monitoring)
