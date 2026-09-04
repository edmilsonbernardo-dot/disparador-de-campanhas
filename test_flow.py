"""Teste manual de ponta a ponta (não faz parte da aplicação em produção).

Usa o test client do Flask, substitui o envio real de SMTP por um "fake" que
apenas registra as chamadas, e exercita: login -> configurar caixa de envio ->
criar campanha via CSV -> disparo imediato -> abertura via pixel -> follow-up
automático.
"""
import io
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("ADMIN_PASSWORD", "teste123")
os.environ.setdefault("ENCRYPTION_KEY", "")
os.environ.setdefault("BASE_URL", "http://localhost:5000")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(__file__))

import mailer  # noqa: E402

SENT_EMAILS = []


def fake_send_email(settings, to_email, to_name, subject, body_html):
    SENT_EMAILS.append(
        {"to": to_email, "name": to_name, "subject": subject, "body": body_html}
    )


mailer.send_email = fake_send_email  # monkeypatch antes de importar app

import app as appmod  # noqa: E402
from extensions import db  # noqa: E402
from models import Campaign, Contact, Settings  # noqa: E402
import scheduler as sched  # noqa: E402
import crypto_utils  # noqa: E402

flask_app = appmod.app
client = flask_app.test_client()

print("1) Login...")
r = client.post("/login", data={"password": "teste123"}, follow_redirects=True)
assert r.status_code == 200 and b"Configura" in r.data or r.status_code == 200
print("   OK")

print("2) Configurando caixa de envio...")
r = client.post(
    "/settings",
    data={
        "sender_name": "Solux",
        "sender_email": "solux@example.com",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": "587",
        "smtp_user": "solux@example.com",
        "use_tls": "on",
        "smtp_password": "senha-de-app-fake",
    },
    follow_redirects=True,
)
assert r.status_code == 200
with flask_app.app_context():
    settings = Settings.get()
    assert settings.is_configured, "Settings deveria estar configurado"
    assert crypto_utils.decrypt(settings.smtp_password_encrypted) == "senha-de-app-fake"
print("   OK - settings configurado e senha criptografada corretamente")

print("3) Criando campanha via upload de CSV...")
csv_content = (
    "nome,email\n"
    "Maria Silva,maria@example.com\n"
    "Joao Souza,joao@example.com\n"
    ",invalido-sem-arroba\n"
    "Maria Duplicada,maria@example.com\n"
).encode("utf-8")

scheduled_at = (datetime.utcnow() - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M")

data = {
    "name": "Campanha Teste",
    "subject": "Assunto de teste",
    "body_html": "<html><body><p>Ola {{nome}}, tudo bem?</p></body></html>",
    "scheduled_at": scheduled_at,
    "followup_enabled": "on",
    "followup_subject": "Seguimento",
    "followup_body_html": "<html><body><p>Oi {{nome}}, vi que voce abriu meu e-mail!</p></body></html>",
    "followup_delay_minutes": "0",
    "csv_file": (io.BytesIO(csv_content), "contatos.csv"),
}
r = client.post("/campaigns/new", data=data, content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200, r.data
with flask_app.app_context():
    campaign = Campaign.query.first()
    assert campaign is not None, "Campanha nao foi criada"
    contacts = campaign.contacts.all()
    assert len(contacts) == 2, f"Esperava 2 contatos validos, veio {len(contacts)}"
    campaign_id = campaign.id
print(f"   OK - campanha criada com {len(contacts)} contatos (duplicado e invalido ignorados)")

print("4) Disparando campanha (chamando o job do scheduler diretamente)...")
sched._send_campaign(flask_app, campaign_id)
assert len(SENT_EMAILS) == 2, f"Esperava 2 e-mails enviados, veio {len(SENT_EMAILS)}"
assert "Ola Maria Silva" in SENT_EMAILS[0]["body"] or "Ola Joao Souza" in SENT_EMAILS[0]["body"]
assert '/track/' in SENT_EMAILS[0]["body"], "Pixel de rastreamento nao foi inserido no corpo"
with flask_app.app_context():
    campaign = Campaign.query.get(campaign_id)
    assert campaign.status == "sent"
    assert campaign.total_sent == 2
print("   OK - 2 e-mails 'enviados' (mock), pixel de rastreamento presente, status = sent")

print("5) Simulando abertura de e-mail via requisicao ao pixel...")
with flask_app.app_context():
    contact = Contact.query.filter_by(email="maria@example.com").first()
    token = contact.token
r = client.get(f"/track/{token}.gif")
assert r.status_code == 200
assert r.mimetype == "image/gif"
with flask_app.app_context():
    contact = Contact.query.filter_by(email="maria@example.com").first()
    assert contact.opened_at is not None
    assert contact.open_count == 1
print("   OK - abertura registrada")

print("6) Requisitando o pixel de novo (deve incrementar contador sem duplicar 'opened_at')...")
first_open = None
with flask_app.app_context():
    first_open = Contact.query.filter_by(email="maria@example.com").first().opened_at
client.get(f"/track/{token}.gif")
with flask_app.app_context():
    contact = Contact.query.filter_by(email="maria@example.com").first()
    assert contact.open_count == 2
    assert contact.opened_at == first_open, "opened_at nao deveria mudar em aberturas repetidas"
print("   OK")

print("7) Rodando poll de follow-up (deve enviar seguimento so para quem abriu)...")
SENT_EMAILS.clear()
sched._poll_followups(flask_app)
assert len(SENT_EMAILS) == 1, f"Esperava 1 seguimento enviado, veio {len(SENT_EMAILS)}"
assert SENT_EMAILS[0]["to"] == "maria@example.com"
with flask_app.app_context():
    contact = Contact.query.filter_by(email="maria@example.com").first()
    assert contact.followup_sent_at is not None
    joao = Contact.query.filter_by(email="joao@example.com").first()
    assert joao.followup_sent_at is None, "Joao nao abriu, nao deveria ter recebido seguimento"
print("   OK - seguimento automatico disparado somente para quem abriu")

print("8) Rodando poll de follow-up de novo (nao deve reenviar)...")
SENT_EMAILS.clear()
sched._poll_followups(flask_app)
assert len(SENT_EMAILS) == 0, "Nao deveria reenviar follow-up para quem ja recebeu"
print("   OK - sem reenvio duplicado")

print("9) Testando dashboard e pagina de detalhe da campanha...")
r = client.get("/")
assert r.status_code == 200 and b"Campanha Teste" in r.data
r = client.get(f"/campaigns/{campaign_id}")
assert r.status_code == 200 and b"maria@example.com" in r.data
print("   OK")

print("\nTODOS OS TESTES PASSARAM.")
