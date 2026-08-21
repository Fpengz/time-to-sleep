# Bugfixes and macOS Improvements

## Goal

Address several critical and moderate issues discovered during a code review:
1. Fix severe DOM thrashing in the vanilla JS frontend caused by indiscriminate `.replaceChildren()` calls.
2. Remove hardcoded user paths (`/Users/zhoufuwang`) from the macOS SwiftUI menubar application.
3. Catch file permission errors during Codex login setup in the FastAPI backend.

## Scope

- Update `api.py` to catch `OSError`.
- Update `app.js` to selectively update the DOM during `pollLogin` and interval refreshes.
- Clean up `index.html` invalid `datetime` attribute.
- Update `BackendRunner.swift` and `Monitor.swift` to resolve paths via `NSHomeDirectory()`.
- Improve `.env` parsing in `Monitor.swift`.

No API, provider, or domain-model behavioral changes are required.

## Design

The changes strictly adhere to the existing architecture:
- **Frontend:** Instead of moving to a Virtual DOM framework, the vanilla JS is patched to selectively update the `#setup-panel .setup-status` text content directly when polling.
- **macOS:** Rather than bundling the python app (which would require a complex build script), the app dynamically resolves the `~/projects/time-to-sleep` directory for local developer use.
- **Backend:** Standard FastAPI exception handling is extended to cover `OSError`.

## Verification

- Run backend tests to ensure syntax and structure are preserved.
- Verify UI stability in browser.
