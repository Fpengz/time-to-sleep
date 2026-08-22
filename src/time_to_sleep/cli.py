import argparse
import asyncio
import os
import sys

import httpx

from time_to_sleep.domain import UsageSnapshot


def _get_port() -> int:
    return int(os.environ.get("PORT", 4141))


async def fetch_usage(
    port: int | None = None, *, force_refresh: bool = False
) -> list[UsageSnapshot]:
    target_port = port or _get_port()
    url = f"http://127.0.0.1:{target_port}/v1/usage"
    if force_refresh:
        url += "?force_refresh=true"

    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(url)
            if response.status_code == 200:
                data = response.json()
                accounts_data = data.get("accounts", [])
                return [UsageSnapshot.model_validate(acc) for acc in accounts_data]
    except Exception:
        pass

    # Direct fallback if server not running
    from time_to_sleep.api import _build_services

    _, usage_service, _, _ = _build_services()
    return await usage_service.collect(force_refresh=force_refresh)


def _color(text: str, code: str) -> str:
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def format_table(snapshots: list[UsageSnapshot]) -> str:
    if not snapshots:
        return "No accounts configured."

    headers = ["PROVIDER", "ACCOUNT ID", "STATUS", "USAGE / WINDOWS", "RESETS AT"]
    rows = []

    for s in snapshots:
        provider = s.provider.capitalize()
        acc_id = s.account_id
        status_str = s.status.value.upper()
        if s.status.value == "live":
            status_display = _color(status_str, "32")  # green
        elif s.status.value in ("rate_limited", "unavailable"):
            status_display = _color(status_str, "31")  # red
        else:
            status_display = _color(status_str, "33")  # yellow/orange

        windows_str = []
        resets_str = []
        for w in s.windows:
            pct_val = f"{w.used_percent:.1f}%"
            if w.used_percent >= 90:
                pct_val = _color(pct_val, "31;1")
            elif w.used_percent >= 75:
                pct_val = _color(pct_val, "33")

            w_id = w.id.replace("_", " ").title()
            windows_str.append(f"{w_id}: {pct_val}")

            if w.resets_at:
                try:
                    resets_str.append(w.resets_at.strftime("%a %H:%M"))
                except Exception:
                    resets_str.append(str(w.resets_at))

        windows_display = ", ".join(windows_str) if windows_str else (s.message or "-")
        resets_display = ", ".join(resets_str) if resets_str else "-"

        rows.append([provider, acc_id, status_display, windows_display, resets_display])

    # Calculate column widths
    # Note: strip ANSI codes when measuring length
    import re

    ansi_escape = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

    def visible_len(val: str) -> int:
        return len(ansi_escape.sub("", val))

    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            col_widths[i] = max(col_widths[i], visible_len(cell))

    def pad(val: str, width: int) -> str:
        v_len = visible_len(val)
        return val + " " * (width - v_len)

    header_line = "  ".join(pad(h, col_widths[i]) for i, h in enumerate(headers))
    sep_line = "  ".join("-" * col_widths[i] for i in range(len(headers)))
    row_lines = ["  ".join(pad(cell, col_widths[i]) for i, cell in enumerate(row)) for row in rows]

    return "\n".join([header_line, sep_line] + row_lines)


def format_prompt(snapshots: list[UsageSnapshot], format_type: str = "compact") -> str:
    import json as pyjson

    if not snapshots:
        if format_type == "json":
            return pyjson.dumps({"accounts": [], "max_used_percent": 0.0, "needs_attention": False})
        elif format_type == "waybar":
            return pyjson.dumps(
                {
                    "text": "No accounts",
                    "tooltip": "No accounts configured",
                    "class": "empty",
                    "percentage": 0,
                }
            )
        return ""

    short_names = {
        "codex": "Codex",
        "claude": "Claude",
        "antigravity": "AGY",
    }

    accounts_data = []
    parts = []
    max_pct = 0.0
    needs_attention = False

    for s in snapshots:
        name = short_names.get(s.provider, s.provider[:3].upper())
        if len(snapshots) > 1 and s.account_id.endswith("-secondary"):
            name += "2"

        if s.status.value != "live":
            needs_attention = True
            parts.append(f"{name}:!")
            accounts_data.append(
                {
                    "account_id": s.account_id,
                    "provider": s.provider,
                    "status": s.status.value,
                    "used_percent": 0.0,
                    "email": s.configured_email,
                }
            )
            continue

        if not s.windows:
            parts.append(f"{name}:0%")
            accounts_data.append(
                {
                    "account_id": s.account_id,
                    "provider": s.provider,
                    "status": s.status.value,
                    "used_percent": 0.0,
                    "email": s.configured_email,
                }
            )
            continue

        max_w = max(s.windows, key=lambda w: w.used_percent)
        pct = max_w.used_percent
        max_pct = max(max_pct, pct)
        rounded_pct = int(round(pct))
        parts.append(f"{name}:{rounded_pct}%")
        accounts_data.append(
            {
                "account_id": s.account_id,
                "provider": s.provider,
                "status": s.status.value,
                "used_percent": pct,
                "email": s.configured_email,
            }
        )

    joined = " | ".join(parts)

    if format_type == "json":
        return pyjson.dumps(
            {
                "accounts": accounts_data,
                "max_used_percent": max_pct,
                "needs_attention": needs_attention,
                "summary": joined,
            },
            indent=2,
        )

    if format_type == "waybar":
        status_class = "critical" if max_pct >= 90 else "warning" if max_pct >= 80 else "normal"
        tooltip_lines = []
        for s in snapshots:
            pct = max((w.used_percent for w in s.windows), default=0.0)
            tooltip_lines.append(
                f"{s.provider.capitalize()} ({s.account_id}): {pct:.1f}% [{s.status.value}]"
            )
        return pyjson.dumps(
            {
                "text": joined,
                "tooltip": "\n".join(tooltip_lines),
                "class": status_class,
                "percentage": int(round(max_pct)),
            }
        )

    if format_type == "sketchybar":
        icon = "󰚩" if max_pct < 80 else ""
        return f"{icon} {joined}"

    if format_type == "starship" or format_type == "compact":
        return f"[{joined}]"
    elif format_type == "tmux":
        return f"#[fg=cyan]{joined}#[default]"
    return joined


def _draw_progress_bar(percent: float, width: int = 14) -> str:
    filled = int(round((max(0.0, min(100.0, percent)) / 100.0) * width))
    empty = width - filled
    bar = "█" * filled + "░" * empty
    if percent >= 90:
        return _color(bar, "31;1")
    elif percent >= 75:
        return _color(bar, "33")
    return _color(bar, "32")


def run_tui(port: int | None = None) -> None:
    import contextlib
    import curses
    import time
    from typing import Any

    def tui_main(stdscr: Any) -> None:
        curses.curs_set(0)
        stdscr.nodelay(True)
        stdscr.timeout(1000)

        force = False
        last_fetch = 0.0
        snapshots: list[UsageSnapshot] = []

        while True:
            now = time.time()
            if now - last_fetch > 10.0 or force or not snapshots:
                stdscr.clear()
                stdscr.addstr(0, 2, "Fetching usage data...", curses.A_DIM)
                stdscr.refresh()

                snapshots = asyncio.run(fetch_usage(port=port, force_refresh=force))
                force = False
                last_fetch = now

            stdscr.clear()
            h, w = stdscr.getmaxyx()

            # Title
            title = "═══ TIME-TO-SLEEP TUI · Usage Observatory ═══"
            stdscr.addstr(1, max(0, (w - len(title)) // 2), title, curses.A_BOLD)
            stdscr.addstr(2, 2, "Controls: [r] Refresh  [f] Force Refresh  [q] Quit", curses.A_DIM)
            stdscr.addstr(3, 0, "─" * w)

            row = 4
            for s in snapshots:
                if row >= h - 4:
                    break

                prov_name = s.provider.capitalize()
                if s.account_id.endswith("-secondary"):
                    prov_name += " (Secondary)"
                else:
                    prov_name += " (Primary)"

                status_attr = curses.A_NORMAL
                if s.status.value == "live":
                    status_str = "[LIVE]"
                elif s.status.value in ("rate_limited", "unavailable"):
                    status_str = f"[{s.status.value.upper()}]"
                    status_attr = curses.A_STANDOUT
                else:
                    status_str = f"[{s.status.value.upper()}]"

                stdscr.addstr(
                    row, 2, f"{prov_name:<20} {s.configured_email:<26} {status_str}", status_attr
                )
                row += 1

                for win in s.windows:
                    if row >= h - 4:
                        break
                    win_label = win.id.replace("_", " ").title()
                    filled = int(round((max(0.0, min(100.0, win.used_percent)) / 100.0) * 12))
                    bar_txt = "[" + "#" * filled + "-" * (12 - filled) + "]"
                    reset_txt = (
                        f" (Resets: {win.resets_at.strftime('%a %H:%M')})" if win.resets_at else ""
                    )
                    stdscr.addstr(
                        row, 6, f"{win_label:<20} {bar_txt} {win.used_percent:5.1f}%{reset_txt}"
                    )
                    row += 1
                row += 1

            # Footer
            stdscr.addstr(
                h - 2,
                2,
                f"Last update: {time.strftime('%X')} · Auto-refreshing every 10s",
                curses.A_DIM,
            )
            stdscr.refresh()

            try:
                ch = stdscr.getch()
                if ch in (ord("q"), ord("Q"), 27):  # 27 = ESC
                    break
                elif ch in (ord("r"), ord("R")):
                    force = False
                    last_fetch = 0.0
                elif ch in (ord("f"), ord("F")):
                    force = True
                    last_fetch = 0.0
            except Exception:
                pass

    with contextlib.suppress(KeyboardInterrupt):
        curses.wrapper(tui_main)


def main(args: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="time-to-sleep",
        description="Local usage retrieval for AI coding assistants.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # serve command
    serve_parser = subparsers.add_parser("serve", help="Start the FastAPI backend server")
    serve_parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload")

    # status command
    status_parser = subparsers.add_parser("status", help="Print tabular usage ledger in terminal")
    status_parser.add_argument("--port", type=int, default=None, help="Port of running backend")
    status_parser.add_argument(
        "-f", "--force-refresh", action="store_true", help="Bypass cached snapshots"
    )

    # tui command
    tui_parser = subparsers.add_parser("tui", help="Launch interactive terminal dashboard")
    tui_parser.add_argument("--port", type=int, default=None, help="Port of running backend")

    # prompt command
    prompt_parser = subparsers.add_parser(
        "prompt", help="Output compact status for shell prompt / statusline"
    )
    prompt_parser.add_argument(
        "--format",
        choices=["compact", "starship", "tmux", "raw", "json", "sketchybar", "waybar"],
        default="compact",
    )
    prompt_parser.add_argument("--port", type=int, default=None, help="Port of running backend")

    # discover command
    discover_parser = subparsers.add_parser(
        "discover", help="Scan local system for AI assistant accounts"
    )
    discover_parser.add_argument(
        "--apply",
        action="store_true",
        help="Automatically add discovered accounts to configuration",
    )
    discover_parser.add_argument(
        "--json", action="store_true", help="Output results in JSON format"
    )

    parsed = parser.parse_args(args)

    if parsed.command == "status":
        snapshots = asyncio.run(fetch_usage(port=parsed.port, force_refresh=parsed.force_refresh))
        print(format_table(snapshots))
    elif parsed.command == "tui":
        run_tui(port=parsed.port)
    elif parsed.command == "prompt":
        snapshots = asyncio.run(fetch_usage(port=parsed.port))
        print(format_prompt(snapshots, format_type=parsed.format))
    elif parsed.command == "discover":
        from time_to_sleep.config import load_settings, save_settings
        from time_to_sleep.discovery import discover_accounts
        from time_to_sleep.domain import Settings

        settings = load_settings()
        existing_ids = {a.id for a in settings.accounts}
        discovered = discover_accounts(existing_ids)

        if parsed.json:
            import json as pyjson

            print(pyjson.dumps([a.model_dump(mode="json") for a in discovered], indent=2))
        else:
            if not discovered:
                print("No new AI assistant accounts discovered.")
            else:
                print(f"Discovered {len(discovered)} new account(s):")
                for acc in discovered:
                    print(f"  • {acc.provider.capitalize()} ({acc.id}): {acc.email} [{acc.home}]")

                if parsed.apply:
                    new_settings = Settings(accounts=list(settings.accounts) + discovered)
                    save_settings(new_settings)
                    print(f"\nSuccessfully added {len(discovered)} account(s) to configuration.")
                else:
                    print("\nRun with '--apply' to automatically add these accounts.")

    else:
        # Default action: run server
        import uvicorn
        from dotenv import load_dotenv

        load_dotenv()
        port = parsed.port if hasattr(parsed, "port") and parsed.port else _get_port()
        reload_flag = getattr(parsed, "reload", False)
        uvicorn.run("time_to_sleep.api:app", host="127.0.0.1", port=port, reload=reload_flag)
