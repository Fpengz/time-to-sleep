# UI/UX: Quota Command Center

Time-to-Sleep is designed to answer one operational question quickly:

> **Which account is the safest one to use right now?**

The Web dashboard and macOS Menu Bar companion use the same decision-first hierarchy while keeping the existing provider, API, history, analytics, and settings contracts unchanged.

## Information hierarchy

The product surfaces information in this order:

1. **Decision** — recommend the best currently usable account.
2. **Pressure** — show how close each account and quota window is to exhaustion.
3. **History** — expose longer-term trajectories, resets, and raw observations only when requested.
4. **Administration** — keep account discovery, account configuration, and retrieval settings available but visually secondary.

This replaces the previous hierarchy where the hero, summary cards, account gauges, inline sparklines, and analytics page repeated several of the same signals.

## Recommendation safety rule

A primary “use this account” recommendation requires a **live** provider snapshot with at least one readable quota window.

Cached, stale, rate-limited, and unavailable accounts remain visible for context, but they are never promoted as the current best option. If no live readable account exists, both the Web dashboard and macOS companion explicitly say that no live account is ready instead of converting stale information into a confident recommendation.

## Web dashboard

### Overview

The default view is **Overview**.

The top decision panel identifies the account to use next and expresses its remaining headroom as:

```text
headroom = 100 - highest active used_percent for that account
```

The account's highest active quota percentage is deliberately used as its pressure score. This makes a nearly exhausted long-window quota visible even when a shorter window still has plenty of capacity.

When server analytics marks a live account as recommended, the Web UI prefers that recommendation. Otherwise it selects the live account with the lowest pressure score. If there is no live readable account, the recommendation is withheld.

The compact fleet strip then reports:

- best option,
- fleet-wide peak quota pressure,
- next known quota reset,
- accounts that are not fully live.

Account cards are ordered by usefulness rather than configuration order. Live/recommended accounts appear first; among equivalent states, lower pressure appears first.

Each account card emphasizes its actual quota windows. Per-account history sparklines are intentionally hidden from Overview so current quota pressure remains the dominant signal.

### History

The second primary view is **History**. Existing `#ledger` and `#trends` URL hashes remain supported for backward-compatible deep links even though the visible labels are now Overview and History.

History contains:

- 24h / 7d / 30d range controls,
- multi-account trajectory comparison,
- individual account trajectories,
- hourly recorded quota levels,
- expandable raw observations,
- CSV export.

The hourly visualization represents recorded `used_percent` levels, not quota consumed during each hour.

### Administration

The header gives manual Refresh primary visual priority. Add Account, Discover Accounts, and Preferences are grouped into a single workspace menu because they are setup/maintenance actions rather than the main monitoring loop.

Dialogs group related fields semantically:

- provider identity,
- alert thresholds,
- background retrieval,
- provider cache TTLs.

## macOS Menu Bar companion

The Menu Bar popover is optimized for a glance rather than for full analytics.

It shows:

1. the safest currently live account,
2. explicit headroom,
3. compact account rows sorted by usefulness,
4. the active quota windows for each account,
5. Refresh and Preferences actions.

The macOS monitor currently consumes usage/settings/history rather than `/v1/analytics`, so its recommendation is the live account with the lowest account pressure score. This is intentionally transparent and deterministic; the Web UI can additionally honor the server analytics recommendation when one exists.

The redesign does not change notifications, settings persistence, background polling, history-fetch timing, or backend lifecycle behavior.

## Visual system

The command-center visual system favors information density over decorative dashboard chrome:

- neutral near-black / off-white surfaces,
- lime decision accent,
- provider colors used as identification rather than large decorative fills,
- flat cards with restrained shadows,
- compact typography and tabular numeric emphasis,
- progress bars for quota pressure instead of repeated ring gauges,
- one prominent decision card rather than multiple competing summary focal points.

Dark and light themes remain supported.

## Interaction rules

- `R` triggers a forced usage refresh when focus is not inside an input, select, textarea, or editable element.
- Existing account card actions remain available.
- Existing SSE `usage` and `analytics` events continue to update the dashboard.
- Existing deep links `#ledger` and `#trends` remain valid.
- Escape closes the workspace utility menu.
- Clicking outside the workspace utility menu closes it.

## Responsive behavior

The layout progressively reduces density rather than hiding core quota information:

- desktop: four fleet signals and multi-column quota windows,
- tablet: two-column fleet signals,
- narrow screens: stacked decision panel and single-column quota windows,
- administration controls remain reachable from the utility menu.

## Accessibility

The redesign preserves the existing skip link, live announcements, semantic progress bars, dialog labels, and keyboard navigation. It also adds a `prefers-reduced-motion` rule that effectively disables non-essential animation.

Color is not the sole status carrier: status text, percentages, labels, and recommendation text remain visible independently of color.

## Visual QA checklist

CI verifies Rust, Swift, release building, packaging, and regressions, but it does not render the browser UI. Before merging a major visual revision, manually inspect at least:

- dark and light themes,
- desktop widths around 1440px and 1024px,
- a narrow width around 390px,
- zero-account/loading/error states,
- one account with multiple quota windows,
- a mix of live, cached/stale, rate-limited, and unavailable accounts,
- a recommended account near a warning/critical threshold,
- an all-cached/stale state to confirm no account is presented as “use now”,
- Overview ↔ History navigation and browser back/forward behavior,
- account/discovery/preferences dialogs,
- macOS popover with short and long email/account labels.

The design should be judged primarily on **time to answer the next-account decision**, not on the number of metrics visible at once.
