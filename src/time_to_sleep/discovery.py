import json
from pathlib import Path

from time_to_sleep.domain import AccountConfig


def discover_accounts(existing_account_ids: set[str] | None = None) -> list[AccountConfig]:
    """Scan the user's home directory and common config locations for AI tool configurations."""
    existing_ids = existing_account_ids or set()
    discovered: list[AccountConfig] = []
    user_home = Path.home()

    # 1. Antigravity / Gemini
    gemini_dir = user_home / ".gemini"
    if gemini_dir.exists() and "antigravity" not in existing_ids:
        email = "user@antigravity.local"
        antigravity_cfg = gemini_dir / "antigravity-cli"
        if antigravity_cfg.exists():
            discovered.append(
                AccountConfig(
                    id="antigravity",
                    provider="antigravity",
                    email=email,
                    home=str(user_home / ".gemini"),
                )
            )

    # 2. Claude Code
    claude_dirs = [
        user_home / ".claude",
        user_home / ".config" / "claude",
    ]
    claude_files = [
        user_home / ".claude.json",
        user_home / ".claude" / "config.json",
    ]
    for cdir in claude_dirs:
        if cdir.exists() and "claude-primary" not in existing_ids and "claude" not in existing_ids:
            email = "user@anthropic.local"
            for cfile in claude_files:
                if cfile.exists():
                    try:
                        data = json.loads(cfile.read_text(encoding="utf-8"))
                        if isinstance(data, dict):
                            detected = (
                                data.get("email")
                                or data.get("user", {}).get("email")
                                or data.get("account", {}).get("email")
                            )
                            if detected:
                                email = str(detected)
                                break
                    except Exception:
                        pass

            discovered.append(
                AccountConfig(
                    id="claude-primary",
                    provider="claude",
                    email=email,
                    home=str(cdir),
                )
            )
            break

    # 3. Codex / ChatGPT
    codex_dirs = [
        (user_home / ".codex", "codex-primary"),
        (user_home / ".config" / "codex", "codex-primary"),
        (user_home / ".config" / "opencode", "opencode-primary"),
    ]
    for cdir, proposed_id in codex_dirs:
        if cdir.exists() and proposed_id not in existing_ids and "codex" not in existing_ids:
            email = "user@openai.local"
            cfg_file = cdir / "config.json"
            if cfg_file.exists():
                try:
                    data = json.loads(cfg_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        detected = data.get("email") or data.get("user", {}).get("email")
                        if detected:
                            email = str(detected)
                except Exception:
                    pass

            discovered.append(
                AccountConfig(
                    id=proposed_id,
                    provider="codex",
                    email=email,
                    home=str(cdir),
                )
            )
            break

    return discovered
