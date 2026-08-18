import os
import tomllib
from pathlib import Path
from typing import Any

from time_to_sleep.domain import AccountConfig, Settings


def default_config_path() -> Path:
    configured = os.environ.get("TIME_TO_SLEEP_CONFIG")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "config" / "accounts.toml"


def load_settings(path: str | Path | None = None) -> Settings:
    config_path = Path(path).expanduser() if path is not None else default_config_path()
    with config_path.open("rb") as handle:
        document: dict[str, Any] = tomllib.load(handle)

    raw_accounts = document.get("accounts")
    if not isinstance(raw_accounts, list):
        raise ValueError("configuration must define an accounts array")

    accounts = [AccountConfig.model_validate(raw) for raw in raw_accounts]
    account_ids = [account.id for account in accounts]
    if len(account_ids) != len(set(account_ids)):
        raise ValueError("duplicate account id in configuration")
    return Settings(accounts=accounts)
