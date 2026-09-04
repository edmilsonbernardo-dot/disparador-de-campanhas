"""Agendador em segundo plano: dispara campanhas na hora marcada e envia
e-mails de seguimento automaticamente quando um contato abre o e-mail original.
"""
import logging
import time
from datetime import datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

import mailer
from extensions import db
from models import Campaign, Contact, Settings

logger = logging.getLogger("scheduler")

_scheduler = None


def _send_campaign(app, campaign_id: int):
    with app.app_context():
        campaign = Campaign.query.get(campaign_id)
        if not campaign:
            return
        settings = Settings.get()
        if not settings.is_configured:
            logger.warning(
                "Campanha '%s' está agendada mas a caixa de envio não foi configurada.",
                campaign.name,
            )
            return

        campaign.status = "sending"
        db.session.commit()

        pending = campaign.contacts.filter(Contact.sent_at.is_(None)).all()
        for contact in pending:
            body = mailer.render_body(
                campaign.body_html, contact.name, app.config["BASE_URL"], contact.token
            )
            try:
                mailer.send_email(settings, contact.email, contact.name, campaign.subject, body)
                contact.sent_at = datetime.utcnow()
                contact.send_error = None
            except Exception as exc:  # noqa: BLE001
                contact.send_error = str(exc)
                logger.exception("Falha ao enviar para %s", contact.email)
            db.session.commit()
            time.sleep(app.config["SEND_THROTTLE_SECONDS"])

        campaign.status = "sent"
        db.session.commit()


def _poll_scheduled_campaigns(app):
    with app.app_context():
        now = datetime.utcnow()
        due = Campaign.query.filter(
            Campaign.status == "scheduled", Campaign.scheduled_at <= now
        ).all()
        for campaign in due:
            _send_campaign(app, campaign.id)


def _poll_followups(app):
    with app.app_context():
        settings = Settings.get()
        if not settings.is_configured:
            return

        candidates = (
            Contact.query.join(Campaign)
            .filter(
                Campaign.followup_enabled.is_(True),
                Contact.opened_at.isnot(None),
                Contact.followup_sent_at.is_(None),
            )
            .all()
        )
        now = datetime.utcnow()
        for contact in candidates:
            campaign = contact.campaign
            delay = timedelta(minutes=campaign.followup_delay_minutes or 0)
            if contact.opened_at + delay > now:
                continue
            body = mailer.render_body(
                campaign.followup_body_html, contact.name, app.config["BASE_URL"], contact.token
            )
            try:
                mailer.send_email(
                    settings, contact.email, contact.name, campaign.followup_subject, body
                )
                contact.followup_sent_at = datetime.utcnow()
                contact.followup_error = None
            except Exception as exc:  # noqa: BLE001
                contact.followup_error = str(exc)
                logger.exception("Falha ao enviar seguimento para %s", contact.email)
            db.session.commit()
            time.sleep(app.config["SEND_THROTTLE_SECONDS"])


def init_scheduler(app):
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    executors = {"default": ThreadPoolExecutor(max_workers=2)}
    _scheduler = BackgroundScheduler(executors=executors, timezone="UTC")
    _scheduler.add_job(
        _poll_scheduled_campaigns,
        "interval",
        seconds=30,
        args=[app],
        id="poll_scheduled_campaigns",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.add_job(
        _poll_followups,
        "interval",
        seconds=60,
        args=[app],
        id="poll_followups",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Agendador iniciado.")
    return _scheduler
