"""Criptografia simples da senha de app do SMTP antes de salvar no banco."""
import os

from cryptography.fernet import Fernet

_KEY_FILE = os.path.join(os.path.dirname(__file__), "instance", "secret.key")


def _load_or_create_key(configured_key: str) -> bytes:
    if configured_key:
        return configured_key.encode()

    # Sem ENCRYPTION_KEY definida no ambiente: gera e persiste uma localmente,
    # para que a senha salva no banco continue legível entre reinícios.
    os.makedirs(os.path.dirname(_KEY_FILE), exist_ok=True)
    if os.path.exists(_KEY_FILE):
        with open(_KEY_FILE, "rb") as f:
            return f.read().strip()

    key = Fernet.generate_key()
    with open(_KEY_FILE, "wb") as f:
        f.write(key)
    return key


_fernet = None


def init_fernet(configured_key: str):
    global _fernet
    _fernet = Fernet(_load_or_create_key(configured_key))


def encrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet.encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    if not value:
        return ""
    return _fernet.decrypt(value.encode()).decode()
