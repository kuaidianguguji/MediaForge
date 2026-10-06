import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("VIO_DATA_DIR", ROOT / "data")).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{(DATA_DIR / 'videoimage.db').as_posix()}")
MAX_UPLOAD = int(os.environ.get("VIO_MAX_UPLOAD_MB", "200")) * 1024 * 1024
USER_QUOTA = int(os.environ.get("VIO_USER_QUOTA_MB", "2048")) * 1024 * 1024
SECURE_COOKIE = os.environ.get("VIO_SECURE_COOKIE", "0") == "1"
SESSION_SECONDS = 12 * 3600
