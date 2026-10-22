"""Configuration via variables d'environnement (préfixe BESEDER_)."""

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_list(name: str, default: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.environ.get("BESEDER_DATA_DIR", "data")))
    host: str = field(default_factory=lambda: os.environ.get("BESEDER_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: int(os.environ.get("BESEDER_PORT", "8000")))
    # Hôtes acceptés dans l'en-tête Host (protège contre le DNS rebinding).
    allowed_hosts: list[str] = field(
        default_factory=lambda: _env_list("BESEDER_ALLOWED_HOSTS", "localhost,127.0.0.1,*.ts.net")
    )
    sync_interval: int = field(default_factory=lambda: int(os.environ.get("BESEDER_SYNC_INTERVAL", "300")))
    # Premier import : on ne remonte pas plus loin que N jours / N mails par boîte.
    initial_days: int = field(default_factory=lambda: int(os.environ.get("BESEDER_INITIAL_DAYS", "30")))
    initial_max: int = field(default_factory=lambda: int(os.environ.get("BESEDER_INITIAL_MAX", "500")))
    # Au-delà de cette taille, on ne télécharge que les en-têtes.
    max_message_bytes: int = field(
        default_factory=lambda: int(os.environ.get("BESEDER_MAX_MESSAGE_BYTES", str(10 * 1024 * 1024)))
    )
    run_scheduler: bool = field(default_factory=lambda: os.environ.get("BESEDER_SCHEDULER", "1") == "1")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "beseder.db"

    @property
    def key_path(self) -> Path:
        return self.data_dir / "secret.key"
