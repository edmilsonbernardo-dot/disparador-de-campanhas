"""Modelos do banco de dados."""
import uuid
from datetime import datetime

from extensions import db


def gen_token():
    return uuid.uuid4().hex


class Settings(db.Model):
    """Configuração única (linha id=1) com os dados da caixa de e-mail."""

    id = db.Column(db.Integer, primary_key=True)
    sender_name = db.Column(db.String(120), default="")
    sender_email = db.Column(db.String(255), default="")
    smtp_host = db.Column(db.String(255), default="smtp.gmail.com")
    smtp_port = db.Column(db.Integer, default=587)
    smtp_user = db.Column(db.String(255), default="")
    smtp_password_encrypted = db.Column(db.Text, default="")
    use_tls = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get():
        settings = Settings.query.get(1)
        if not settings:
            settings = Settings(id=1)
            db.session.add(settings)
            db.session.commit()
        return settings

    @property
    def is_configured(self):
        return bool(self.smtp_user and self.smtp_password_encrypted and self.sender_email)


class Campaign(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    subject = db.Column(db.String(300), nullable=False)
    body_html = db.Column(db.Text, nullable=False)

    scheduled_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="scheduled")  # scheduled | sending | sent
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Follow-up automático disparado quando o contato abre o e-mail original
    followup_enabled = db.Column(db.Boolean, default=False)
    followup_subject = db.Column(db.String(300), default="")
    followup_body_html = db.Column(db.Text, default="")
    followup_delay_minutes = db.Column(db.Integer, default=10)

    contacts = db.relationship(
        "Contact", backref="campaign", lazy="dynamic", cascade="all, delete-orphan"
    )

    # --- estatísticas ---
    @property
    def total_contacts(self):
        return self.contacts.count()

    @property
    def total_sent(self):
        return self.contacts.filter(Contact.sent_at.isnot(None)).count()

    @property
    def total_opened(self):
        return self.contacts.filter(Contact.opened_at.isnot(None)).count()

    @property
    def total_followup_sent(self):
        return self.contacts.filter(Contact.followup_sent_at.isnot(None)).count()

    @property
    def open_rate(self):
        sent = self.total_sent
        if not sent:
            return 0
        return round(100 * self.total_opened / sent, 1)


class Contact(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaign.id"), nullable=False)

    name = db.Column(db.String(200))
    email = db.Column(db.String(255), nullable=False)
    token = db.Column(db.String(40), unique=True, default=gen_token)

    sent_at = db.Column(db.DateTime)
    send_error = db.Column(db.Text)

    opened_at = db.Column(db.DateTime)
    last_opened_at = db.Column(db.DateTime)
    open_count = db.Column(db.Integer, default=0)

    followup_sent_at = db.Column(db.DateTime)
    followup_error = db.Column(db.Text)

    @property
    def status_label(self):
        if self.followup_sent_at:
            return "Seguimento enviado"
        if self.opened_at:
            return "Aberto"
        if self.sent_at:
            return "Enviado"
        if self.send_error:
            return "Erro no envio"
        return "Aguardando"
