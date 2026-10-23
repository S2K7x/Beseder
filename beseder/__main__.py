import getpass
import logging
import sys

import uvicorn

from .config import Config
from .main import create_app


def restore(path: str) -> None:
    """python -m beseder restore FILE: puts a backup back. Stop Beseder first."""
    from .backup import restore as do_restore

    config = Config()
    if config.db_path.exists() and input(f"This replaces everything in {config.data_dir}. Type yes: ") != "yes":
        sys.exit("Cancelled")
    try:
        with open(path, "rb") as f:
            do_restore(f.read(), getpass.getpass("Backup passphrase: "), config.data_dir)
    except (OSError, ValueError) as e:
        sys.exit(f"Restore failed: {e}")
    print("Restored. Start Beseder again.")


if __name__ == "__main__":
    if sys.argv[1:2] == ["restore"] and len(sys.argv) == 3:
        restore(sys.argv[2])
        sys.exit(0)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config()
    # Open event streams (/api/events) must not hold a restart for long.
    uvicorn.run(create_app(config), host=config.host, port=config.port, proxy_headers=True,
                timeout_graceful_shutdown=3)
