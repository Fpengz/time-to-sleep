import json
import os
import time

from playwright.sync_api import Browser, Page, sync_playwright

BASE_URL = "http://127.0.0.1:4141"
EXPECTED_HTTP_FAILURE_CONSOLE = (
    "Failed to load resource: the server responded with a status of 503 (Service Unavailable)"
)


def attach_page_error_listeners(
    page: Page, console_errors: list[str], page_errors: list[str]
) -> None:
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on("pageerror", lambda error: page_errors.append(str(error)))


def assert_no_horizontal_overflow(page: Page) -> None:
    dimensions = page.evaluate(
        "({scrollWidth: document.documentElement.scrollWidth, innerWidth: window.innerWidth})"
    )
    assert dimensions["scrollWidth"] <= dimensions["innerWidth"], (
        "horizontal overflow: "
        f"scrollWidth={dimensions['scrollWidth']}, "
        f"innerWidth={dimensions['innerWidth']}"
    )


def assert_dashboard(page: Page) -> None:
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=60_000)
    assert page.locator(".skip-link").get_attribute("href") == "#main-content"
    assert page.locator("#main-content").count() == 1
    assert page.locator("#summary").is_visible()
    assert page.locator("#account-list").is_visible()
    summary_labels = page.locator("#summary .summary-label").all_text_contents()
    for label in ("Live now", "Attention", "Last sync"):
        assert label in summary_labels
    assert page.locator("#page-title").is_visible()
    assert page.locator("#hero-copy").is_visible()
    assert page.locator("#next-reset").is_visible()
    assert page.locator("#summary.signal-strip").is_visible()
    assert page.locator("#provider-ledger").is_visible()
    account_cards = page.locator("#account-list .account-card")
    assert account_cards.count() == 4
    for index in range(account_cards.count()):
        assert account_cards.nth(index).is_visible()

    initial_theme = page.locator("html").get_attribute("data-theme")
    assert initial_theme in {"light", "dark"}
    theme_color = page.locator('meta[name="theme-color"]')
    expected_colors = {"dark": "#0f1413", "light": "#eee9df"}
    assert theme_color.get_attribute("content") == expected_colors[initial_theme]
    page.locator("#theme-toggle").click()
    changed_theme = page.locator("html").get_attribute("data-theme")
    assert changed_theme in {"light", "dark"}
    assert changed_theme != initial_theme
    assert page.evaluate("localStorage.getItem('time-to-sleep-theme')") == changed_theme
    assert theme_color.get_attribute("content") == expected_colors[changed_theme]

    page.locator("#refresh-button").click()
    page.wait_for_function(
        "document.querySelector('#refresh-button').disabled === false",
        timeout=60_000,
    )
    announcement = page.locator("#live-announcement").text_content() or ""
    assert "refreshed" in announcement.lower()
    assert_no_horizontal_overflow(page)


def assert_setup_flow(browser: Browser, console_errors: list[str], page_errors: list[str]) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
    attach_page_error_listeners(page, console_errors, page_errors)
    page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=BASE_URL)
    snapshots = [
        {
            "account_id": "codex-primary",
            "provider": "codex",
            "configured_email": "primary@example.com",
            "status": "live",
            "source": "test",
            "observed_at": "2026-08-18T00:00:00Z",
            "retrieved_at": "2026-08-18T00:00:00Z",
            "windows": [
                {
                    "id": "primary",
                    "used_percent": 18,
                    "resets_at": "2026-08-21T12:00:00Z",
                }
            ],
        },
        {
            "account_id": "codex-secondary",
            "provider": "codex",
            "configured_email": "secondary@example.com",
            "status": "cached",
            "source": "test",
            "observed_at": "2026-08-17T00:00:00Z",
            "retrieved_at": "2026-08-18T00:00:00Z",
            "windows": [{"id": "primary", "used_percent": 42}],
            "message": "The provider could not be queried.",
            "error_code": "not_authenticated",
        },
        {
            "account_id": "claude",
            "provider": "claude",
            "configured_email": "claude@example.com",
            "status": "cached",
            "source": "test",
            "observed_at": "2026-08-18T00:00:00Z",
            "retrieved_at": "2026-08-18T00:00:00Z",
            "windows": [
                {
                    "id": "five_hour",
                    "used_percent": 51,
                    "resets_at": "2026-08-20T12:00:00Z",
                }
            ],
        },
        {
            "account_id": "antigravity",
            "provider": "antigravity",
            "configured_email": "agy@example.com",
            "status": "unavailable",
            "source": "test",
            "observed_at": None,
            "retrieved_at": "2026-08-18T00:00:00Z",
            "windows": [],
        },
    ]
    usage = {"generated_at": "2026-08-18T00:00:00Z", "accounts": snapshots}
    status_reads = 0
    manual_refresh_started = False
    usage_reads = 0
    usage_urls = []
    usage_completed = 0

    def fulfill(route, payload) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def usage_response(route) -> None:
        nonlocal manual_refresh_started, usage_reads, usage_completed
        usage_reads += 1
        usage_urls.append(route.request.url)
        if usage_reads == 2:
            manual_refresh_started = True
        payload = usage
        if usage_reads == 3:
            payload = {
                **usage,
                "accounts": [
                    {**snapshots[0], "configured_email": "logged-in@example.com"},
                    *snapshots[1:],
                ],
            }
        fulfill(route, payload)
        usage_completed += 1

    page.add_init_script(
        """
        (() => {
            const originalFetch = window.fetch.bind(window);
            window.__usageFetchEvents = [];
            let usageResponses = 0;
            window.fetch = async (...args) => {
                const request = typeof args[0] === "string" ? args[0] : args[0].url;
                const response = await originalFetch(...args);
                if (request.includes("/v1/usage")) {
                    usageResponses += 1;
                    window.__usageFetchEvents.push(`received-${usageResponses}`);
                    if (usageResponses === 2) {
                        await new Promise((resolve) => setTimeout(resolve, 2250));
                    }
                    window.__usageFetchEvents.push(`released-${usageResponses}`);
                }
                return response;
            };
        })();
        """
    )
    page.route(f"{BASE_URL}/v1/usage*", usage_response)
    page.route(f"{BASE_URL}/v1/accounts", lambda route: fulfill(route, []))
    page.route(
        f"{BASE_URL}/v1/accounts/codex-secondary/login/start",
        lambda route: fulfill(
            route,
            {
                "attempt_id": "attempt-1",
                "method": "device_code",
                "status": "pending",
                "verification_url": "https://auth.example.test/verify",
                "user_code": "ABCD-EFGH",
            },
        ),
    )

    def login_status(route) -> None:
        nonlocal status_reads
        status_reads += 1
        status = "succeeded" if manual_refresh_started else "pending"
        fulfill(
            route,
            {
                "attempt_id": "attempt-1",
                "account_id": "codex-secondary",
                "method": "device_code",
                "status": status,
                "started_at": "2026-08-18T00:00:00Z",
                "expires_at": "2026-08-18T00:10:00Z",
            },
        )

    page.route(
        f"{BASE_URL}/v1/accounts/codex-secondary/login/attempt-1",
        login_status,
    )
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_load_state("networkidle", timeout=10_000)
    assert usage_reads == 1
    assert usage_urls[0] == f"{BASE_URL}/v1/usage"
    next_reset_detail = page.locator("#next-reset-detail")
    assert "Claude Code" in next_reset_detail.inner_text()
    assert "Five Hour" in next_reset_detail.inner_text()
    assert page.locator(".summary-card").filter(has_text="Next reset").count() == 0
    assert page.get_by_role("button", name="Retry usage").count() == 2
    page.get_by_role("button", name="Retry login").click()
    setup_panel = page.locator("#setup-panel")
    assert setup_panel.get_attribute("aria-live") == "polite"
    assert setup_panel.get_attribute("data-status") == "idle"
    assert "secondary@example.com" in setup_panel.inner_text()
    setup_status = setup_panel.locator('[role="status"]')
    assert setup_status.is_visible()
    assert setup_status.get_attribute("aria-live") == "polite"
    assert "choose a sign-in method" in setup_status.inner_text().lower()
    assert page.locator("#setup-method").input_value() == "device_code"
    page.select_option("#setup-method", "device_code")
    page.get_by_role("button", name="Start login").click()
    page.get_by_text("ABCD-EFGH").wait_for(state="visible", timeout=5_000)
    page.wait_for_function(
        "document.querySelector('#setup-panel')?.dataset.status === 'pending'",
        timeout=5_000,
    )
    assert "login attempt active" in setup_panel.locator('[role="status"]').inner_text().lower()
    assert setup_panel.locator('[role="status"]').get_attribute("aria-live") == "polite"
    copy_button = page.get_by_role("button", name="Copy device code")
    copy_button.click()
    page.wait_for_function("navigator.clipboard.readText().then((value) => value === 'ABCD-EFGH')")
    assert copy_button.inner_text() == "Copied"
    page.evaluate("void window.refresh(false)")
    page.wait_for_function(
        "document.querySelector('#refresh-button').disabled === true",
        timeout=5_000,
    )
    page.wait_for_function(
        "document.querySelector('#setup-panel')?.dataset.status === 'succeeded'",
        timeout=10_000,
    )
    assert (
        setup_panel.locator('[role="status"]').inner_text()
        == "Login verified for the configured account."
    )
    page.wait_for_selector("#setup-panel", state="hidden", timeout=10_000)
    assert (
        page.locator("#live-announcement").inner_text()
        == "Login verified for the configured account."
    )
    assert status_reads >= 2
    assert usage_reads == 3
    assert usage_completed == 3
    assert usage_urls[1] == f"{BASE_URL}/v1/usage"
    assert usage_urls[2].endswith("/v1/usage?force_refresh=true")
    assert "logged-in@example.com" in page.locator("#account-list").inner_text()
    usage_events = page.evaluate("window.__usageFetchEvents")
    for event in (
        "received-1",
        "released-1",
        "received-2",
        "released-2",
        "received-3",
        "released-3",
    ):
        assert event in usage_events
    assert usage_events.index("released-2") < usage_events.index("received-3")
    page.close()


def assert_setup_terminal_states(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
    attach_page_error_listeners(page, console_errors, page_errors)
    snapshots = [
        {
            "account_id": "codex-secondary",
            "provider": "codex",
            "configured_email": "secondary@example.com",
            "status": "unavailable",
            "source": "test",
            "observed_at": "2026-08-18T00:00:00Z",
            "retrieved_at": "2026-08-18T00:00:00Z",
            "windows": [],
        }
    ]
    usage = {"generated_at": "2026-08-18T00:00:00Z", "accounts": snapshots}
    starts = 0
    status_reads: dict[str, int] = {}
    pending_cancel_route = None
    pending_expired_start = None

    def fulfill(route, payload, status: int = 200) -> None:
        route.fulfill(status=status, content_type="application/json", body=json.dumps(payload))

    def login_response(route) -> None:
        nonlocal starts, pending_cancel_route, pending_expired_start
        path = route.request.url.split("/login/", 1)[1]
        if path == "start":
            starts += 1
            attempt_id = {
                1: "attempt-cancel",
                2: "attempt-race",
                3: "attempt-b",
                4: "attempt-failed",
                5: "attempt-expired",
                6: "attempt-error",
            }[starts]
            if attempt_id == "attempt-expired":
                pending_expired_start = route
                return
            fulfill(
                route,
                {
                    "attempt_id": attempt_id,
                    "method": "device_code",
                    "status": "pending",
                    "verification_url": f"https://auth.example.test/{attempt_id}",
                    "user_code": f"{attempt_id.upper()}-CODE",
                },
            )
            return
        if path.endswith("/cancel"):
            if path.startswith("attempt-race/"):
                pending_cancel_route = route
                return
            fulfill(route, {"status": "cancelled"})
            return

        attempt_id = path
        status_reads[attempt_id] = status_reads.get(attempt_id, 0) + 1
        read_number = status_reads[attempt_id]
        if attempt_id in {"attempt-cancel", "attempt-race", "attempt-b"}:
            status = "succeeded" if attempt_id == "attempt-b" and read_number >= 2 else "pending"
            fulfill(route, {"attempt_id": attempt_id, "status": status})
        elif attempt_id == "attempt-failed":
            fulfill(
                route,
                {
                    "attempt_id": attempt_id,
                    "status": "failed",
                    "message": "The configured account did not match.",
                },
            )
        elif attempt_id == "attempt-expired":
            fulfill(
                route,
                {
                    "attempt_id": attempt_id,
                    "status": "expired",
                    "message": "The login window expired.",
                },
            )
        else:
            fulfill(route, {"detail": "Status endpoint failed"}, status=503)

    page.add_init_script(
        """
        (() => {
            const originalFetch = window.fetch.bind(window);
            window.__setupEvents = [];
            window.fetch = async (...args) => {
                const request = typeof args[0] === "string" ? args[0] : args[0].url;
                if (request.includes("/v1/accounts/codex-secondary/login/")) {
                    window.__setupEvents.push(request);
                }
                return originalFetch(...args);
            };
        })();
        """
    )
    page.route(
        f"{BASE_URL}/v1/usage*",
        lambda route: fulfill(route, usage),
    )
    page.route(
        f"{BASE_URL}/v1/accounts",
        lambda route: fulfill(route, []),
    )
    page.route(
        f"{BASE_URL}/v1/accounts/codex-secondary/login/**",
        login_response,
    )

    def open_setup() -> None:
        page.get_by_role("button", name="Set up account").click()
        page.wait_for_function(
            "document.querySelector('#setup-panel')?.dataset.status === 'idle'",
            timeout=5_000,
        )

    def start_login() -> None:
        page.get_by_role("button", name="Start login").click()

    def assert_terminal(status: str, copy: str) -> None:
        page.wait_for_function(
            f"document.querySelector('#setup-panel')?.dataset.status === '{status}'",
            timeout=10_000,
        )
        panel = page.locator("#setup-panel")
        assert panel.get_attribute("data-status") == status
        assert copy.lower() in panel.locator('[role="status"]').inner_text().lower()
        assert page.get_by_role("button", name="Start login").is_enabled()
        assert page.get_by_role("button", name="Close", exact=True).is_visible()
        assert page.locator("#setup-method").is_enabled()
        assert page.locator("#refresh-button").is_enabled()

    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=60_000)

        # Normal cancellation remains visible as a terminal state.
        open_setup()
        start_login()
        page.wait_for_function(
            "document.querySelector('#setup-panel')?.dataset.status === 'pending'",
            timeout=5_000,
        )
        page.get_by_role("button", name="Cancel attempt").click()
        assert_terminal("cancelled", "You can start another attempt")

        # Hold setup A's cancel response, start setup B, then release A. B must
        # keep polling; this exercises instance-scoped generation cleanup.
        start_login()
        page.wait_for_function(
            "document.querySelector('#setup-panel')?.dataset.status === 'pending'",
            timeout=5_000,
        )
        page.get_by_role("button", name="Cancel attempt").click()
        page.wait_for_function(
            "window.__setupEvents.some((url) => url.endsWith('/attempt-race/cancel'))",
            timeout=5_000,
        )
        page.get_by_role("button", name="Close account setup").click()
        page.wait_for_selector("#setup-panel", state="hidden", timeout=5_000)
        open_setup()
        start_login()
        page.wait_for_function(
            "document.querySelector('#setup-panel')?.dataset.status === 'pending'",
            timeout=5_000,
        )
        page.wait_for_function(
            "window.__setupEvents.some((url) => url.endsWith('/attempt-b'))",
            timeout=5_000,
        )
        assert pending_cancel_route is not None
        fulfill(pending_cancel_route, {"status": "cancelled"})
        pending_cancel_route = None
        page.wait_for_function(
            "window.__setupEvents.filter((url) => url.endsWith('/attempt-b')).length >= 2",
            timeout=10_000,
        )
        page.wait_for_selector("#setup-panel", state="hidden", timeout=10_000)

        # Failed, expired, and polling-error states retain explicit copy and
        # settle their controls for another attempt.
        open_setup()
        start_login()
        assert_terminal("failed", "configured account did not match")

        start_login()
        page.wait_for_function(
            "document.querySelector('#setup-panel')?.dataset.status === 'starting'",
            timeout=5_000,
        )
        assert page.locator(".setup-code").count() == 0
        assert page.locator(".setup-link").count() == 0
        assert pending_expired_start is not None
        fulfill(
            pending_expired_start,
            {
                "attempt_id": "attempt-expired",
                "method": "device_code",
                "status": "pending",
                "verification_url": "https://auth.example.test/attempt-expired",
                "user_code": "ATTEMPT-EXPIRED-CODE",
            },
        )
        pending_expired_start = None
        assert_terminal("expired", "login window expired")

        start_login()
        assert_terminal("error", "status endpoint failed")
    finally:
        page.close()


def assert_retained_snapshots_on_refresh_failure(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
    attach_page_error_listeners(page, console_errors, page_errors)
    usage_reads = 0
    account_reads = 0
    snapshot = {
        "account_id": "codex-primary",
        "provider": "codex",
        "configured_email": "initial@example.com",
        "status": "live",
        "source": "test",
        "observed_at": "2026-08-19T00:00:00Z",
        "retrieved_at": "2026-08-19T00:00:00Z",
        "windows": [
            {
                "id": "primary",
                "used_percent": 18,
                "resets_at": "2026-08-21T12:00:00Z",
            }
        ],
    }
    usage = {
        "generated_at": "2026-08-19T00:00:00Z",
        "accounts": [snapshot],
    }

    def usage_response(route) -> None:
        nonlocal usage_reads
        usage_reads += 1
        if usage_reads == 1:
            route.fulfill(status=200, content_type="application/json", body=json.dumps(usage))
            return
        if usage_reads == 2:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({**usage, "generated_at": "2026-08-19T00:01:00Z"}),
            )
            return
        if usage_reads == 3:
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Forced refresh failed"}),
            )
            return
        recovered_snapshot = {**snapshot, "configured_email": "recovered@example.com"}
        recovered_usage = {"generated_at": "2026-08-19T00:03:00Z", "accounts": [recovered_snapshot]}
        route.fulfill(status=200, content_type="application/json", body=json.dumps(recovered_usage))

    def accounts_response(route) -> None:
        nonlocal account_reads
        account_reads += 1
        if account_reads in (2, 3):
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps({"detail": "Account metadata failed"}),
            )
            return
        route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

    page.route(f"{BASE_URL}/v1/usage*", usage_response)
    page.route(f"{BASE_URL}/v1/accounts", accounts_response)
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        account_cards = page.locator("#account-list .account-card")
        assert account_cards.count() == 1
        assert account_cards.first.is_visible()
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None
        assert usage_reads == 1
        assert account_reads == 1

        page.locator("#refresh-button").click()
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=60_000,
        )
        assert account_cards.count() == 1
        assert account_cards.first.is_visible()
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None
        account_only_announcement = page.locator("#live-announcement").inner_text()
        assert "Account metadata failed" in account_only_announcement
        assert "Usage data refreshed." not in account_only_announcement
        assert usage_reads == 2
        assert account_reads == 2

        page.locator("#refresh-button").click()
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=60_000,
        )
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None
        combined_copy = (
            page.locator("#hero-copy").inner_text() + page.locator("#summary").inner_text()
        )
        combined_announcement = page.locator("#live-announcement").inner_text()
        assert "Refresh failed" in combined_announcement
        assert "Forced refresh failed" in combined_announcement
        assert "Account metadata failed" in combined_announcement
        assert "Forced refresh failed" in combined_copy
        assert "Account metadata failed" in combined_copy
        assert account_cards.count() == 1
        assert account_cards.first.is_visible()
        assert usage_reads == 3
        assert account_reads == 3

        page.locator("#refresh-button").click()
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=60_000,
        )
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None
        assert "recovered@example.com" in account_cards.first.inner_text()
        recovered_copy = (
            page.locator("#hero-copy").inner_text() + page.locator("#summary").inner_text()
        )
        assert "Forced refresh failed" not in recovered_copy
        assert "Account metadata failed" not in recovered_copy
        assert "Usage data refreshed." in page.locator("#live-announcement").inner_text()
        assert usage_reads == 4
        assert account_reads == 4
        assert account_cards.count() == 1
        assert account_cards.first.is_visible()
    finally:
        page.close()


def assert_narrow_dark_viewport(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 390, "height": 844}, color_scheme="dark")
    attach_page_error_listeners(page, console_errors, page_errors)
    page.add_init_script("localStorage.removeItem('time-to-sleep-theme');")
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        assert page.locator("html").get_attribute("data-theme") == "dark"
        assert page.locator('meta[name="theme-color"]').get_attribute("content") == "#0f1413"
        assert page.locator("#provider-ledger").is_visible()
        assert page.locator("#account-list").is_visible()
        assert page.locator("#refresh-button").is_visible()
        assert page.locator("#refresh-button").is_enabled()
        page.locator("#theme-toggle").click()
        assert page.locator("html").get_attribute("data-theme") == "light"
        assert page.locator('meta[name="theme-color"]').get_attribute("content") == "#eee9df"
        page.evaluate("localStorage.removeItem('time-to-sleep-theme')")
        assert_no_horizontal_overflow(page)
    finally:
        page.close()


def assert_keyboard_focus_and_reduced_motion(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="dark")
    attach_page_error_listeners(page, console_errors, page_errors)
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        page.locator(".brand").focus()
        page.keyboard.press("Tab")
        assert page.locator("#theme-toggle").evaluate(
            "element => element === document.activeElement && element.matches(':focus-visible')"
        )
        focus_style = page.locator("#theme-toggle").evaluate(
            """
            element => {
                const style = getComputedStyle(element);
                return {
                    outlineStyle: style.outlineStyle,
                    outlineWidth: parseFloat(style.outlineWidth),
                    outlineOffset: parseFloat(style.outlineOffset),
                };
            }
            """
        )
        assert focus_style["outlineStyle"] != "none"
        assert focus_style["outlineWidth"] >= 2
        assert focus_style["outlineOffset"] >= 2
    finally:
        page.close()

    reduced_motion_page = browser.new_page(
        viewport={"width": 1100, "height": 900},
        color_scheme="dark",
        reduced_motion="reduce",
    )
    attach_page_error_listeners(reduced_motion_page, console_errors, page_errors)
    try:
        reduced_motion_page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        reduced_motion_page.wait_for_load_state("networkidle", timeout=60_000)
        reduced_motion_page.locator(".meter-fill").first.wait_for(state="attached")
        motion_style = reduced_motion_page.evaluate(
            """
            () => {
                const meter = getComputedStyle(document.querySelector('.meter-fill'));
                const loadingProbe = document.createElement('span');
                loadingProbe.className = 'loading-line';
                document.body.append(loadingProbe);
                const loading = getComputedStyle(loadingProbe);
                const loadingAnimationDuration = loading.animationDuration;
                const loadingAnimationName = loading.animationName;
                loadingProbe.remove();
                const toMilliseconds = (value) => {
                    const amount = parseFloat(value);
                    return value.endsWith('ms') ? amount : amount * 1000;
                };
                return {
                    meterTransition: toMilliseconds(meter.transitionDuration),
                    loadingAnimationDuration,
                    loadingAnimationName,
                    loadingAnimationDisabled:
                        loadingAnimationName === 'none'
                        || toMilliseconds(loadingAnimationDuration) <= 0.01,
                    scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior,
                };
            }
            """
        )
        assert motion_style["meterTransition"] <= 0.01, motion_style
        assert motion_style["loadingAnimationDisabled"], motion_style
        assert motion_style["scrollBehavior"] == "auto"
    finally:
        reduced_motion_page.close()


def assert_resilient_status_labels(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="dark")
    attach_page_error_listeners(page, console_errors, page_errors)
    snapshots = []
    for account_id, status, message, error_code in (
        ("partial", "cached", "Partial provider response", "partial_response"),
        ("stale", "stale", "Stale usage snapshot", "stale_data"),
        ("rate-limited", "rate_limited", "Provider rate limit reached", "rate_limited"),
        ("unavailable", "unavailable", "Provider unavailable", "provider_unavailable"),
    ):
        snapshots.append(
            {
                "account_id": account_id,
                "provider": "claude",
                "configured_email": f"{account_id}@example.com",
                "status": status,
                "source": "test",
                "observed_at": "2026-08-19T00:00:00Z",
                "retrieved_at": "2026-08-19T00:00:00Z",
                "windows": []
                if status == "unavailable"
                else [{"id": "primary", "used_percent": 42}],
                "message": message,
                "error_code": error_code,
            }
        )
    usage = {"generated_at": "2026-08-19T00:00:00Z", "accounts": snapshots}

    def usage_response(route) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(usage))

    def accounts_response(route) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

    page.route(f"{BASE_URL}/v1/usage*", usage_response)
    page.route(f"{BASE_URL}/v1/accounts", accounts_response)
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_load_state("networkidle", timeout=60_000)
        for account_id, status, label, message, error_code in (
            ("partial", "cached", "Cached", "Partial provider response", "partial response"),
            ("stale", "stale", "Stale", "Stale usage snapshot", "stale data"),
            (
                "rate-limited",
                "rate_limited",
                "Rate limited",
                "Provider rate limit reached",
                "rate limited",
            ),
            (
                "unavailable",
                "unavailable",
                "Unavailable",
                "Provider unavailable",
                "provider unavailable",
            ),
        ):
            card = page.locator(f".account-card.status-{status}").filter(
                has_text=f"{account_id}@example.com"
            )
            assert card.count() == 1
            assert card.is_visible()
            assert label.lower() in card.locator(".status-badge").inner_text().lower(), (
                card.inner_text()
            )
            assert message in card.inner_text(), card.inner_text()
            assert error_code in card.locator(".account-error").inner_text().lower(), (
                card.inner_text()
            )
        summary_text = page.locator("#summary").inner_text().lower()
        assert "attention" in summary_text
        assert "accounts need a look" in summary_text
        assert_no_horizontal_overflow(page)
    finally:
        page.close()


def assert_initial_failure_headline(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
    attach_page_error_listeners(page, console_errors, page_errors)

    def usage_response(route) -> None:
        route.fulfill(
            status=503,
            content_type="application/json",
            body=json.dumps({"detail": "Initial provider failure"}),
        )

    def accounts_response(route) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

    page.route(f"{BASE_URL}/v1/usage*", usage_response)
    page.route(f"{BASE_URL}/v1/accounts", accounts_response)
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=60_000,
        )
        assert "No clear reading" in page.locator("#page-title").inner_text()
        assert "Initial provider failure" in page.locator("#hero-copy").inner_text()
        assert "Initial provider failure" in page.locator("#live-announcement").inner_text()
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None
    finally:
        page.close()


def assert_refresh_coalesces_overlapping_calls(
    browser: Browser, console_errors: list[str], page_errors: list[str]
) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
    attach_page_error_listeners(page, console_errors, page_errors)
    usage_requests = 0
    usage_urls = []
    snapshot = {
        "account_id": "codex-primary",
        "provider": "codex",
        "configured_email": "primary@example.com",
        "status": "live",
        "source": "test",
        "observed_at": "2026-08-19T00:00:00Z",
        "retrieved_at": "2026-08-19T00:00:00Z",
        "windows": [
            {
                "id": "primary",
                "used_percent": 18,
                "resets_at": "2026-08-21T12:00:00Z",
            }
        ],
    }
    usage = {"generated_at": "2026-08-19T00:00:00Z", "accounts": [snapshot]}
    console_start = len(console_errors)
    page_start = len(page_errors)

    def usage_response(route) -> None:
        nonlocal usage_requests
        usage_requests += 1
        usage_urls.append(route.request.url)
        if usage_requests in {2, 3}:
            time.sleep(0.25)
        configured_email = (
            "forced@example.com"
            if "force_refresh=true" in route.request.url
            else "normal@example.com"
        )
        payload = {
            **usage,
            "accounts": [{**snapshot, "configured_email": configured_email}],
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    def accounts_response(route) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps([]))

    page.route(f"{BASE_URL}/v1/usage*", usage_response)
    page.route(f"{BASE_URL}/v1/accounts", accounts_response)
    try:
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=60_000,
        )
        assert usage_requests == 1

        overlap = page.evaluate(
            """
            async () => {
                const settled = [];
                const first = window.refresh(true).then(() => settled.push("first"));
                const second = window.refresh(true).then(() => settled.push("second"));
                await new Promise((resolve) => setTimeout(resolve, 0));
                const during = [...settled];
                await Promise.all([first, second]);
                return { during, settled };
            }
            """
        )
        assert overlap["during"] == []
        assert sorted(overlap["settled"]) == ["first", "second"]
        assert usage_requests == 2
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None

        mixed_start = usage_requests
        mixed_overlap = page.evaluate(
            """
            async () => {
                const settled = [];
                const normal = window.refresh(false).then(() => settled.push("normal"));
                const forced = window.refresh(true).then(() => settled.push("forced"));
                await Promise.all([normal, forced]);
                return settled;
            }
            """
        )
        assert sorted(mixed_overlap) == ["forced", "normal"]
        assert usage_requests == mixed_start + 2
        assert usage_urls[-2] == f"{BASE_URL}/v1/usage"
        assert usage_urls[-1].endswith("/v1/usage?force_refresh=true")
        assert "forced@example.com" in page.locator("#account-list").inner_text()
        assert page.locator("#refresh-button").inner_text() == "Refresh usage"
        assert page.locator("#account-list").get_attribute("aria-busy") is None
        assert console_errors[console_start:] == []
        assert page_errors[page_start:] == []
    finally:
        page.close()


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH"),
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="light")
        attach_page_error_listeners(page, console_errors, page_errors)
        try:
            assert_dashboard(page)
            assert_setup_flow(browser, console_errors, page_errors)
            assert_setup_terminal_states(browser, console_errors, page_errors)
            assert_retained_snapshots_on_refresh_failure(browser, console_errors, page_errors)
            assert_initial_failure_headline(browser, console_errors, page_errors)
            assert_refresh_coalesces_overlapping_calls(browser, console_errors, page_errors)
            assert_narrow_dark_viewport(browser, console_errors, page_errors)
            assert_keyboard_focus_and_reduced_motion(browser, console_errors, page_errors)
            assert_resilient_status_labels(browser, console_errors, page_errors)
        finally:
            browser.close()
    unexpected_console_errors = [
        message for message in console_errors if message != EXPECTED_HTTP_FAILURE_CONSOLE
    ]
    if unexpected_console_errors or page_errors:
        raise AssertionError(
            f"browser errors: console={unexpected_console_errors}, page={page_errors}"
        )


if __name__ == "__main__":
    main()
