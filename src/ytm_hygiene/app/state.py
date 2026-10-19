"""What every screen shares: the settings file and where the app keeps its files."""

from dataclasses import dataclass, field
from pathlib import Path

from .. import settings


@dataclass
class AppState:
    base: Path
    settings: dict = field(default_factory=dict)

    @classmethod
    def load(cls, base: Path) -> "AppState":
        return cls(base, settings.load(base / settings.CONFIG_NAME))

    @property
    def auth_path(self) -> Path:
        return self.base / settings.AUTH_NAME

    @property
    def signed_in(self) -> bool:
        return self.auth_path.exists()

    def save(self) -> None:
        settings.save(self.base / settings.CONFIG_NAME, self.settings)
