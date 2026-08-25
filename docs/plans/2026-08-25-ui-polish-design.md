# UI/UX polish pass — web dashboard + macOS menu bar app

## Scope

Polish pass, not a redesign: keep current layout and information architecture on
both surfaces, improve visual consistency, fix two data-display bugs found while
screenshotting, and reduce control clutter on web account cards. No changes to
API contracts or account data.

## Bug fixes

- **Trends page stat lines** (`static/app.js`, trends rendering): labels and
  values render with no separator (`Current0.0%`, `Peak0.0%`, `Net Change+0.0%`).
  Add `: ` between label and value.
- **Trends page window sub-labels**: Antigravity reports separate 5-hour and
  weekly windows under the same category name (`Gemini`, `Claude & GPT`), so two
  blocks can show an identical heading with nothing to tell them apart. Add a
  5-hour/weekly sub-label next to the category name (mirrors the `windowBadge`
  badge the macOS app already shows per window).
- **Footer text** (`static/index.html`): `Time-to-Sleep FastAPI · local usage
  retrieval` still names the archived Python backend. Update to reflect the
  Rust backend.

## Shared visual language

The two surfaces currently use unrelated accent colors: web's brand accent is
sky-blue (`--accent: #38bdf8` / `#0284c7` light), the macOS app's is olive-green
(`Palette.accent = 0x8FB02E`) — and that same green is also reused as the
Antigravity provider color in the mac app, an accidental collision between
"generic UI accent" and "one specific provider's brand color."

Fix: retint `Palette.accent` in `macOS/Sources/Views.swift` to a blue matching
the web's `--accent-strong` family, and give Antigravity its own distinct hue
so it no longer doubles as the app's neutral accent. Per-provider colors
(Codex, Claude, Antigravity) stay distinct on both surfaces — only the
*neutral/brand* accent is harmonized.

## Web account card decluttering

Each account card's action row currently stacks a status pill + "Retry usage"
button + "Delete" button inline (`static/app.js` account card renderer,
`static/styles.css` `.account-card` rules). Collapse "Retry usage" and "Delete"
into a single "⋮" menu per card, opening a small popover with both actions.
Status pill/ring stays inline (it's information, not a control). This mirrors
the calmer per-card footprint the macOS app already has (no inline destructive
controls — management lives in Preferences there).

## General polish

Typography and spacing tightening pass on both surfaces — consistent vertical
rhythm in cards, alert boxes, and summary tiles. No structural/layout changes
beyond the kebab-menu consolidation above.

## Out of scope

- Fixing the Claude provider's `HTTP error 400 Bad Request` (functional bug,
  not a UI issue — flagged separately).
- Any change to account data, API routes, or the login/accounts backend work
  done earlier in this session.
- Full redesign / new information architecture (explicitly declined).
