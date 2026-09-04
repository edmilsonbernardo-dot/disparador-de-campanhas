"""Instâncias compartilhadas (evita import circular entre app/models/scheduler)."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
