import base64
import logging
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
    Response,
)

import crypto_utils
import mailer
from config import Config
from extensions import db
from models import Campaign, Contact, Settings
from scheduler import init_scheduler
from utils import parse_contacts_csv

logging.basicConfig(level=logging.INFO)

# GIF transparente 1x1 usado como pixel de rastreamento.
TRACKING_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBTAA7"
)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    crypto_utils.init_fernet(app.config["ENCRYPTION_KEY"])

    with app.app_context():
        db.create_all()
        Settings.get()

    register_routes(app)

    # O agendador roda em thread própria dentro do mesmo processo web.
    # Em plataformas com múltiplos "workers" (ex: gunicorn -w 2+), rode com
    # apenas 1 worker web ou mova o agendador para um processo dedicado
    # (veja o README, seção "Produção").
    init_scheduler(app)

    return app


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def register_routes(app):
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            password = request.form.get("password", "")
            if password and password == app.config["ADMIN_PASSWORD"]:
                session["logged_in"] = True
                next_url = request.args.get("next") or url_for("dashboard")
                return redirect(next_url)
            flash("Senha incorreta.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        campaigns = Campaign.query.order_by(Campaign.scheduled_at.desc()).all()
        settings = Settings.get()
        return render_template("dashboard.html", campaigns=campaigns, settings=settings)

    @app.route("/settings", methods=["GET", "POST"])
    @login_required
    def settings_view():
        settings = Settings.get()
        if request.method == "POST":
            settings.sender_name = request.form.get("sender_name", "").strip()
            settings.sender_email = request.form.get("sender_email", "").strip()
            settings.smtp_host = request.form.get("smtp_host", "").strip() or "smtp.gmail.com"
            settings.smtp_port = int(request.form.get("smtp_port") or 587)
            settings.smtp_user = request.form.get("smtp_user", "").strip()
            settings.use_tls = bool(request.form.get("use_tls"))

            new_password = request.form.get("smtp_password", "")
            if new_password:
                settings.smtp_password_encrypted = crypto_utils.encrypt(new_password)

            db.session.commit()
            flash("Configurações salvas.", "success")
            return redirect(url_for("settings_view"))

        return render_template("settings.html", settings=settings)

    @app.route("/settings/test", methods=["POST"])
    @login_required
    def settings_test():
        settings = Settings.get()
        to_email = request.form.get("test_email", "").strip()
        if not to_email:
            flash("Informe um e-mail para o teste.", "error")
            return redirect(url_for("settings_view"))
        try:
            mailer.send_test_email(settings, to_email)
            flash(f"E-mail de teste enviado para {to_email}.", "success")
        except Exception as exc:  # noqa: BLE001
            flash(f"Falha ao enviar e-mail de teste: {exc}", "error")
        return redirect(url_for("settings_view"))

    @app.route("/campaigns/new", methods=["GET", "POST"])
    @login_required
    def campaign_new():
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            subject = request.form.get("subject", "").strip()
            body_html = request.form.get("body_html", "").strip()
            scheduled_at_raw = request.form.get("scheduled_at", "").strip()
            followup_enabled = bool(request.form.get("followup_enabled"))
            followup_subject = request.form.get("followup_subject", "").strip()
            followup_body_html = request.form.get("followup_body_html", "").strip()
            followup_delay_minutes = int(request.form.get("followup_delay_minutes") or 10)

            csv_file = request.files.get("csv_file")

            errors = []
            if not name:
                errors.append("Informe um nome para a campanha.")
            if not subject:
                errors.append("Informe o assunto do e-mail.")
            if not body_html:
                errors.append("Informe o corpo do e-mail.")
            if not scheduled_at_raw:
                errors.append("Informe a data e hora de disparo.")
            if not csv_file or not csv_file.filename:
                errors.append("Envie um arquivo CSV com os contatos.")
            if followup_enabled and (not followup_subject or not followup_body_html):
                errors.append("Preencha assunto e corpo do e-mail de seguimento.")

            contacts = []
            if csv_file and csv_file.filename and not errors:
                try:
                    contacts, warnings = parse_contacts_csv(csv_file)
                except ValueError as exc:
                    errors.append(str(exc))
                else:
                    if not contacts:
                        errors.append("Nenhum contato válido foi encontrado no CSV.")
                    for w in warnings[:20]:
                        flash(w, "warning")

            try:
                scheduled_at = datetime.fromisoformat(scheduled_at_raw)
            except ValueError:
                scheduled_at = None
                errors.append("Data/hora de disparo inválida.")

            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("campaign_new.html", form=request.form)

            campaign = Campaign(
                name=name,
                subject=subject,
                body_html=body_html,
                scheduled_at=scheduled_at,
                status="scheduled",
                followup_enabled=followup_enabled,
                followup_subject=followup_subject,
                followup_body_html=followup_body_html,
                followup_delay_minutes=followup_delay_minutes,
            )
            db.session.add(campaign)
            db.session.flush()

            for c in contacts:
                db.session.add(Contact(campaign_id=campaign.id, name=c["name"], email=c["email"]))

            db.session.commit()
            flash(f"Campanha '{name}' criada com {len(contacts)} contato(s).", "success")
            return redirect(url_for("campaign_detail", campaign_id=campaign.id))

        return render_template("campaign_new.html", form={})

    @app.route("/campaigns/<int:campaign_id>")
    @login_required
    def campaign_detail(campaign_id):
        campaign = Campaign.query.get_or_404(campaign_id)
        contacts = campaign.contacts.order_by(Contact.id).all()
        return render_template("campaign_detail.html", campaign=campaign, contacts=contacts)

    @app.route("/campaigns/<int:campaign_id>/send-now", methods=["POST"])
    @login_required
    def campaign_send_now(campaign_id):
        campaign = Campaign.query.get_or_404(campaign_id)
        campaign.scheduled_at = datetime.utcnow()
        db.session.commit()
        flash("Disparo agendado para agora — o envio começa em instantes.", "success")
        return redirect(url_for("campaign_detail", campaign_id=campaign.id))

    @app.route("/campaigns/<int:campaign_id>/delete", methods=["POST"])
    @login_required
    def campaign_delete(campaign_id):
        campaign = Campaign.query.get_or_404(campaign_id)
        db.session.delete(campaign)
        db.session.commit()
        flash("Campanha excluída.", "success")
        return redirect(url_for("dashboard"))

    @app.route("/track/<token>.gif")
    def track_open(token):
        contact = Contact.query.filter_by(token=token).first()
        if contact:
            now = datetime.utcnow()
            if contact.opened_at is None:
                contact.opened_at = now
            contact.last_opened_at = now
            contact.open_count = (contact.open_count or 0) + 1
            db.session.commit()

        resp = Response(TRACKING_GIF, mimetype="image/gif")
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"] = "no-cache"
        return resp

    @app.route("/health")
    def health():
        return {"status": "ok"}


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
