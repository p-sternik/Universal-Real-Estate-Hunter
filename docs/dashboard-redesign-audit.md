# Dashboard Redesign Audit — Universal Real Estate Hunter

Scope: `src/services/templates/` (self-hosted aiohttp web UI). Stack: single
`dashboard.html` + `dashboard.css` (≈4.6k lines) + 3 vanilla JS files, Leaflet for
maps, no build step, no external CDN dependencies.

## Summary

The dashboard is already at a premium level: dark off-black canvas (`#090a0f`),
strict neutral palette, 1px hairline borders, sub-pixel inner-light edges,
tabular numerics, `:focus-visible` on buttons, `100dvh` viewport fallbacks,
hover/active states, and smooth scroll. The header comment self-describes it as a
"Linear / Raycast / Bloomberg" analytics panel — and it largely lives up to that.

The audit below records what passed, what was already sound, and the specific
gaps that were fixed in this pass.

## Fixes applied

| Area | Before | After |
| :--- | :--- | :--- |
| Typography | System font stack (`-apple-system … Inter, Roboto …`) | Self-hosted **IBM Plex Sans** (400/500/600) + **IBM Plex Mono** (400/500), `.woff2`, `font-display: swap` |
| Empty states | Inline-styled strings in JS (`<div style="text-align:center;…">`) | Composed `.empty-state` component (icon + title + desc + optional action) |
| Loading state | Inline-styled text placeholder | Skeleton cards mirroring the 16:9 card shape, shimmer animation, `prefers-reduced-motion` guard |
| Error state | Inline-styled div + emoji (`⚠️`) | `.empty-state--error` variant with inline SVG alert icon |
| `window.alert()` | `alert('Brak ofert do eksportu.')` | `showToast(...)` (existing toast system) |
| Focus visibility | Only `.btn:focus-visible` | Global `:where(a, button, select, input, textarea, summary, [role="button"]):focus-visible` ring |
| AI gradient | `.btn-ai-audit` blue→violet 135° gradient | Single-accent blue treatment (`--blue-*` tokens) |
| Z-index | Hardcoded, undocumented values | `--z-*` scale tokens in `:root` documenting the stacking layers |
| Hallucinated class | `class="btn btn-secondary"` (no such CSS rule) | `class="btn"` |
| Decorative emoji | `🤖` (AI buttons/badges), `🚀` (release links), `🖨️` (print), `🔄` (refresh), `✅`/`❌` (notif test) | Inline SVG (sparkles / refresh / printer), or plain text where color already signals status |

## Full checklist status

### Typography
- [x] Distinctive self-hosted font (IBM Plex Sans) — replaced system stack
- [x] Weight range 400/500/600 in use (Medium + SemiBold, not just Regular/Bold)
- [x] Tabular figures via `font-variant-numeric: tabular-nums` on all numeric content
- [x] Negative tracking on display sizes, positive tracking on all-caps labels
- [x] `text-wrap` not needed (dense data UI, not marketing prose)
- [~] Mono font only used in a few spots (`.kbd-badge`, `.card-media-count`, `.results-avg`) — acceptable for a data panel

### Color & surfaces
- [x] Off-black background (`#090a0f`), not pure `#000`
- [x] Single primary accent (blue); semantic hues (green/amber/red) are functional, not decorative
- [~] Violet retained only as a semantic tag color (`--violet`) — the blue→violet *gradient* was removed
- [x] Consistent cool-gray family throughout
- [x] No glow; shadows tinted dark, sub-pixel inner edge instead of outer glow
- [x] No noise/grain — intentional; the panel is flat by design, not by omission

### Layout
- [x] Grid layout (`auto-fill minmax(330px,1fr)`), not three equal flex columns
- [x] `100dvh` with `100vh` fallback (no pure `100vh`)
- [x] Max-width container (1920px)
- [x] Asymmetric split mode (map + feed), not centered-symmetric
- [x] Varying card content allowed (grid `align-items: stretch`, `content-visibility: auto`)

### Interactivity & states
- [x] Hover + active/pressed states present on buttons
- [x] Smooth transitions (150–300ms)
- [x] `:focus-visible` now global (was buttons-only)
- [x] Empty state composed (was inline string)
- [x] Skeleton loader (was text placeholder)
- [x] Error state composed (was inline + emoji)
- [x] No `window.alert()` (was one instance)

### Content
- [x] Polish copy throughout, no lorem ipsum, no AI clichés
- [x] No fake round numbers (tabular real data)
- [~] Emoji still present in a few table action buttons (`🤖 Raport`, `★`) — out of scope for this pass

### Component patterns
- [x] Cards use background + 1px border, no heavy shadow
- [x] Semantic HTML (`<header>`, `<main>`, `<section>`, `<nav>`-like topbar)
- [x] No pill "New/Beta" badges; live chip is a functional status indicator
- [x] Favicon + manifest + theme-color present

### Code quality
- [x] No inline styles for state markup (was the main offender)
- [x] No hallucinated classes
- [x] Semantic tags, alt text on images
- [~] Z-index scale now documented via `--z-*` tokens (Leaflet-coupled values left as-is)

## Remaining opportunities (not addressed — low value / high risk)

1. **Violet tag color** could be folded into the blue accent, but it serves as a
   distinct "custom tag" semantic — changing it would make tags visually collide
   with blue filter tokens.
2. **`⚠️` warning marker** is retained in content (`cons` strings, vision
   discrepancy notes, rejection reasons) — it is a *data-level* signal that also
   flows to Discord/Telegram/CSV, not UI chrome. Cleaning it would be a
   backend/data migration, not a frontend change.
3. **Leaflet map tiles** load from OpenStreetMap CDN (`tile.openstreetmap.org`),
   a rare exception to the self-hosted asset policy (map tiles are impractical to
   self-host).
4. **Font preload** was intentionally omitted: the HTML asset-versioner rewrites
   `href="/assets/…"` (adding `?v=`), which would diverge from the un-versioned
   `url()` in CSS and cause a double fetch. Self-hosted same-origin fonts +
   `font-display: swap` are fast enough without it.
