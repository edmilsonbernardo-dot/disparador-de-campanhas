import os

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin")
    ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", "")
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'app.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB por upload de CSV

    # Intervalo (segundos) entre envios individuais, para não estourar limites do provedor.
    SEND_THROTTLE_SECONDS = float(os.environ.get("SEND_THROTTLE_SECONDS", "2"))
