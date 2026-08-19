# Time-to-Sleep Dark Editorial Dashboard Design

## Goal

Refine the existing Time-to-Sleep dashboard into a dark editorial observatory that makes provider health, quota usage, and next actions easy to understand at a glance. Preserve the existing FastAPI runtime, API contract, provider behavior, Codex setup lifecycle, and theme persistence while improving visual hierarchy, responsive behavior, feedback states, and accessibility.

## Scope

### In scope

- Rework the static dashboard layout and styling around a dark-first editorial observatory direction.
- Keep the existing header controls and improve their hierarchy and accessible labels.
- Replace the current hero/summary presentation with a narrative hero, signal strip, and provider ledger while retaining the current account data.
- Improve loading, refresh, partial-failure, stale, rate-limited, unavailable, and empty states.
- Improve the inline Codex setup panel for pending, success, cancelled, expired, and error states without changing its API calls.
- Preserve and verify the system-aware light/dark theme behavior and explicit local override.
- Adapt the layout for narrow viewports without hiding critical actions or introducing horizontal scrolling.
- Extend browser smoke coverage where the visual/interaction changes require updated expectations.

### Out of scope

- Changes to provider retrieval, authentication, login endpoints, domain models, or backend response shapes.
- Adding a frontend framework, build step, or new runtime.
- Introducing new dashboard features such as historical charts, notifications, account editing, or user-configurable layouts.
- Changing the semantics of usage percentages, reset timestamps, status codes, or diagnostic messages.

## Product direction

The dashboard should feel like a late-night operations report: calm, editorial, and information-dense without looking like a generic admin panel. The memorable element is the narrative hero, which turns raw provider state into a concise nightly report. Operational detail remains available immediately below in a compact ledger.

The dark theme is the primary expression: ink-green background, raised ledger surfaces, lime live/healthy accent, warm amber attention accent, and thin rules. The light theme mirrors the same system with warm paper neutrals. Serif display typography is reserved for headlines and key figures; a readable sans-serif carries account and status data.

## Layout and component structure

The existing static shell remains the entry point and keeps its stable selectors for browser tests and JavaScript behavior.

1. Header
   - Brand and home link remain left aligned.
   - Last-sync time, theme toggle, and refresh action remain available at the top level.
   - Refresh exposes a clear pending label and remains keyboard accessible.

2. Editorial hero
   - A small observatory/report eyebrow establishes context.
   - The main headline summarizes the current state in editorial language without replacing the underlying status information.
   - Supporting copy explains the overall health in one short sentence.
   - Earliest reset is elevated as the key time-sensitive datum.

3. Signal strip
   - Three compact metrics show live accounts, accounts needing attention, and last sync.
   - Metrics use text labels and values; color is supplemental only.
   - The strip becomes a vertical rhythm on narrow screens.

4. Provider ledger
   - Each configured account remains visible as an individual row.
   - Each row includes provider/account identity, configured email, status text, observation/source metadata, usage window meter(s), reset timing, diagnostic copy, and the applicable action.
   - On wide screens, identity, usage, and reset/action information align as a ledger.
   - On narrow screens, rows stack into readable identity, usage, and action blocks.

5. Inline setup panel
   - The panel remains below the ledger and is shown only when an account setup flow is active.
   - It retains browser and device-code choices, authorization links, verification URL, copyable user code, polling, and cancellation.
   - Copy and status feedback are made more explicit while credentials and local paths remain excluded.

## State and interaction behavior

The existing client state and endpoint calls remain the source of truth. Changes should be targeted to rendering and feedback:

- Initial load shows ledger-shaped placeholders. Existing successful data is kept visible during a manual refresh instead of being replaced by an empty screen.
- A manual refresh disables the button, announces progress, and restores the control in all completion paths.
- If usage or account metadata fails independently, the successful sibling result remains rendered and the failure is explained near the affected content.
- Live, cached, stale, rate-limited, and unavailable states each retain an explicit text label and diagnostic context.
- Codex setup exposes a clear next step before authorization details. Pending polling communicates that the attempt is active; success, cancellation, expiry, and errors each receive distinct copy and visual treatment.
- Device-code copy feedback remains immediate and temporary, with a fallback message if clipboard access is unavailable.
- Theme switching continues to use `time-to-sleep-theme` in `localStorage`; system preference is used only when no explicit override exists.
- Motion remains limited to useful state changes such as entry, meter updates, and refresh feedback. Reduced-motion users receive effectively static transitions.

## Accessibility and responsive requirements

- Status is conveyed through text, semantic labels, and color together; no state depends on color alone.
- Progress meters retain accessible `progressbar` semantics and bounded numeric values.
- Buttons and links retain visible `:focus-visible` treatment with sufficient contrast in both themes.
- Theme and setup controls expose current/next action through accessible labels and titles.
- Live-region announcements cover refresh and setup lifecycle outcomes without forcing focus away from the current task.
- Links that open authorization pages retain safe new-tab attributes.
- Text remains readable when account emails, provider labels, or diagnostic messages are long.
- The dashboard works at the existing minimum width and at mobile widths without horizontal overflow.
- Critical actions remain visible on mobile; layout changes are structural rather than simple content hiding.

## Implementation boundaries

Expected production changes are limited to:

- `src/time_to_sleep/static/index.html` for semantic layout and stable landmarks.
- `src/time_to_sleep/static/styles.css` for tokens, editorial layout, responsive rules, state styles, and motion/accessibility refinements.
- `src/time_to_sleep/static/app.js` for copy, state rendering, refresh feedback, and setup-flow presentation improvements.
- `tests/browser_dashboard.py` for updated text/structure assertions and any new state coverage required by the revised UI.
- `README.md` only if the user-facing dashboard behavior or verification instructions change.

The backend files under `src/time_to_sleep/api.py`, `domain.py`, `services.py`, and `providers/` should not require changes for this refinement.

## Verification plan

Run the existing Python and static checks, then run the browser smoke test against the FastAPI app. Browser verification should cover:

- initial rendering of all configured accounts;
- dark/light toggle and persisted override;
- manual refresh pending and completion announcements;
- retained healthy data during partial failure;
- status and action rendering for stale, unavailable, and rate-limited accounts;
- Codex setup start, challenge details, copy feedback, polling completion, and cancellation;
- no console errors or page errors;
- desktop and narrow viewport layout with no horizontal overflow;
- visible keyboard focus and reduced-motion behavior.

Success means the revised dashboard communicates the same backend data more clearly, preserves the existing setup workflow, passes the project checks, and remains usable across the supported themes and viewport sizes.
