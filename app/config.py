from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent

_CONF = Path("/app/config")
if not _CONF.exists() or not os.access(str(_CONF), os.W_OK):
    _CONF = BASE_DIR / "config"
    _CONF.mkdir(parents=True, exist_ok=True)

CONFIG_DIR = _CONF
DATA_VIDEOS = Path("/data/videos")
DATA_OUTPUT = Path("/data/output")
DATA_THUMBNAILS = Path("/data/thumbnails")
TEMP_DIR = Path("/tmp/compress_workers")

BOT_API_URL = "http://127.0.0.1:8081/bot"
BOT_API_ENV_FILE = CONFIG_DIR / "bot-api.env"
DATABASE_URL = f"sqlite+aiosqlite:///{CONFIG_DIR}/app.db"
