"""The settings file (ytm-hygiene.toml), shared by the CLI and the app."""

import json
import os
import tomllib
from pathlib import Path

CONFIG_NAME = "ytm-hygiene.toml"
AUTH_NAME = "browser.json"
KEYS = ("vault", "inbox", "rotation", "expire_days")


def app_dir() -> Path:
    """Where the app keeps browser.json, settings, backups and undo logs: the
    current folder when it already holds them (running from the repo), otherwise
    %APPDATA%/ytm-hygiene."""
    here = Path.cwd()
    if (here / CONFIG_NAME).exists() or (here / AUTH_NAME).exists():
        return here
    return Path(os.environ.get("APPDATA") or Path.home()) / "ytm-hygiene"


def load(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def save(path: Path, settings: dict) -> None:
    """Write the known keys. JSON string quoting is valid TOML for these flat values."""
    lines = [f"{key} = {json.dumps(settings[key])}" for key in KEYS if settings.get(key) not in (None, "")]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
