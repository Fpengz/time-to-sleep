from time_to_sleep.config import load_settings, save_settings
from time_to_sleep.domain import AccountConfig, Settings


def test_load_settings_reads_accounts_from_toml(tmp_path) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        "[[accounts]]\n"
        'id = "codex"\n'
        'provider = "codex"\n'
        'email = "a@example.com"\n'
        'home = "~/.codex"\n',
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.accounts == [
        AccountConfig(id="codex", provider="codex", email="a@example.com", home="~/.codex")
    ]


def test_load_settings_rejects_duplicate_account_ids(tmp_path) -> None:
    path = tmp_path / "accounts.toml"
    path.write_text(
        '[[accounts]]\nid = "same"\nprovider = "codex"\n'
        'email = "a@example.com"\nhome = "~/.codex"\n'
        '[[accounts]]\nid = "same"\nprovider = "claude"\n'
        'email = "b@example.com"\nhome = "~/.claude"\n',
        encoding="utf-8",
    )

    try:
        load_settings(path)
    except ValueError as error:
        assert "duplicate account id" in str(error)
    else:
        raise AssertionError("duplicate account id was accepted")


def test_save_settings_round_trips_special_characters(tmp_path) -> None:
    """Values containing quotes/backslashes/newlines must not corrupt or inject TOML."""
    path = tmp_path / "accounts.toml"
    original = Settings(
        accounts=[
            AccountConfig(
                id='weird "id"',
                provider="codex",
                email="a@example.com",
                home=r"~/with\backslash and \"quote\"",
            )
        ]
    )

    save_settings(original, path)
    reloaded = load_settings(path)

    assert reloaded.accounts == original.accounts
