# Remove Redundant Reset Summary

## Goal

Remove the redundant global reset summary and static loopback note from the dashboard hero. Keep reset dates only where they are already specific and useful: inside each configured account's usage window row.

## Scope

- Remove the hero-side `Earliest reset` block from `static/index.html`.
- Remove the static `Loopback only` note from `static/index.html`.
- Remove the now-unused aggregate reset calculation and hero reset rendering from `static/app.js`.
- Remove CSS that exists only for the deleted hero reset and loopback elements.
- Update the browser dashboard test to assert the redundant elements are absent and per-account reset text remains visible.

No API, provider, domain-model, configuration, or account-window behavior changes are required.

## Design

The hero retains the nightly report eyebrow, narrative title, and live account summary. The account ledger remains the sole place where reset timing is rendered. `renderWindow()` continues to format each window's `resets_at` value using the existing `formatReset()` helper, so reset dates remain tied to the account card and window name.

Because the hero no longer has reset DOM nodes, `renderHero()` will only update the title and summary copy. The `resetCandidates()` helper and its related formatting branch will be removed as dead aggregate behavior.

## Verification

- Run the focused browser dashboard test.
- Run the full test suite.
- Confirm the diff contains only the intended frontend, test, and design-spec changes.
