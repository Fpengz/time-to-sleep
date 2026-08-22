from pathlib import Path
from unittest.mock import patch

from time_to_sleep.discovery import discover_accounts


def test_discover_accounts_mocked_home(tmp_path: Path) -> None:
    fake_home = tmp_path / "user"
    gemini_dir = fake_home / ".gemini" / "antigravity-cli"
    gemini_dir.mkdir(parents=True)

    claude_dir = fake_home / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "config.json").write_text('{"email": "claude_user@test.org"}', encoding="utf-8")

    codex_dir = fake_home / ".codex"
    codex_dir.mkdir(parents=True)
    (codex_dir / "config.json").write_text('{"email": "codex_user@test.org"}', encoding="utf-8")

    with patch("time_to_sleep.discovery.Path.home", return_value=fake_home):
        discovered = discover_accounts()
        assert len(discovered) == 3
        provs = {a.provider for a in discovered}
        assert provs == {"antigravity", "claude", "codex"}

        # Existing account ids ignored
        disc_filtered = discover_accounts(existing_account_ids={"antigravity", "claude-primary"})
        assert len(disc_filtered) == 1
        assert disc_filtered[0].provider == "codex"
