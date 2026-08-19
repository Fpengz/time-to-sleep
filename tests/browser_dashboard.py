import json
import os

from playwright.sync_api import Browser, Page, sync_playwright

BASE_URL = "http://127.0.0.1:4141"


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
    page.locator("#theme-toggle").click()
    changed_theme = page.locator("html").get_attribute("data-theme")
    assert changed_theme in {"light", "dark"}
    assert changed_theme != initial_theme
    assert page.evaluate("localStorage.getItem('time-to-sleep-theme')") == changed_theme

    page.locator("#refresh-button").click()
    page.wait_for_function(
        "document.querySelector('#refresh-button').disabled === false",
        timeout=60_000,
    )
    announcement = page.locator("#live-announcement").text_content() or ""
    assert "refreshed" in announcement.lower()
    assert_no_horizontal_overflow(page)


def assert_setup_flow(browser: Browser) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
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

    def fulfill(route, payload) -> None:
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    page.route(f"{BASE_URL}/v1/usage*", lambda route: fulfill(route, usage))
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
        status = "pending" if status_reads == 1 else "succeeded"
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
    next_reset_detail = page.locator("#next-reset-detail")
    assert "Claude Code" in next_reset_detail.inner_text()
    assert "Five Hour" in next_reset_detail.inner_text()
    assert page.locator(".summary-card").filter(has_text="Next reset").count() == 0
    assert page.get_by_role("button", name="Retry usage").count() == 2
    page.get_by_role("button", name="Retry login").click()
    assert "secondary@example.com" in page.locator("#setup-panel").inner_text()
    assert page.locator("#setup-method").input_value() == "device_code"
    page.select_option("#setup-method", "device_code")
    page.get_by_role("button", name="Start login").click()
    page.get_by_text("ABCD-EFGH").wait_for(state="visible", timeout=5_000)
    copy_button = page.get_by_role("button", name="Copy device code")
    copy_button.click()
    page.wait_for_function("navigator.clipboard.readText().then((value) => value === 'ABCD-EFGH')")
    assert copy_button.inner_text() == "Copied"
    page.wait_for_selector("#setup-panel", state="hidden", timeout=10_000)
    assert status_reads >= 2
    page.close()


def assert_retained_snapshots_on_refresh_failure(browser: Browser) -> None:
    page = browser.new_page(viewport={"width": 1100, "height": 900}, color_scheme="light")
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
        assert usage_reads == 1
        assert account_reads == 1

        page.locator("#refresh-button").click()
        page.wait_for_function(
            "document.querySelector('#refresh-button').disabled === false",
            timeout=60_000,
        )
        assert account_cards.count() == 1
        assert account_cards.first.is_visible()
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
        combined_copy = (
            page.locator("#hero-copy").inner_text() + page.locator("#summary").inner_text()
        )
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


def main() -> None:
    console_errors: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH"),
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, color_scheme="light")
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        try:
            assert_dashboard(page)
            assert_setup_flow(browser)
            assert_retained_snapshots_on_refresh_failure(browser)
        finally:
            browser.close()
    if console_errors or page_errors:
        raise AssertionError(f"browser errors: console={console_errors}, page={page_errors}")


if __name__ == "__main__":
    main()
