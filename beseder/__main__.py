import logging

import uvicorn

from .config import Config
from .main import create_app

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = Config()
    uvicorn.run(create_app(config), host=config.host, port=config.port, proxy_headers=True)
