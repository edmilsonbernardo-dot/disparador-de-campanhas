"""Envio de e-mails via SMTP, com pixel de rastreamento embutido."""
import smtplib
import socket
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

import crypto_utils


class SMTPNotConfigured(Exception):
    pass


# Algumas plataformas de nuvem (ex.: Render) atribuem endereço IPv6 ao
# container mas não têm rota de saída IPv6 funcional. O resolvedor padrão do
# Python pode devolver o endereço IPv6 do Gmail primeiro e a conexão falha
# com "[Errno 101] Network is unreachable" antes de tentar o IPv4. Forçamos
# a resolução para IPv4 apenas (afeta só as conexões feitas por este
# processo, e só o envio de e-mail usa rede externa aqui).
_original_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_ipv4_only


def build_tracking_pixel_html(base_url: str, token: str) -> str:
    url = f"{base_url}/track/{token}.gif"
    return (
        f'<img src="{url}" width="1" height="1" alt="" '
        f'style="display:block;border:0;width:1px;height:1px;" />'
    )


def render_body(body_html: str, contact_name: str, base_url: str, token: str) -> str:
    """Substitui {{nome}} pelo nome do contato e adiciona o pixel no final do corpo."""
    html = body_html.replace("{{nome}}", contact_name or "").replace("{{name}}", contact_name or "")
    pixel = build_tracking_pixel_html(base_url, token)
    if "</body>" in html.lower():
        # insere antes do fechamento do body, preservando o restante do html
        idx = html.lower().rfind("</body>")
        html = html[:idx] + pixel + html[idx:]
    else:
        html = html + pixel
    return html


def send_email(settings, to_email: str, to_name: str, subject: str, body_html: str) -> None:
    """Envia um e-mail HTML único via SMTP usando as configurações salvas.

    Levanta exceção em caso de falha (o chamador decide como registrar o erro).
    """
    if not settings or not settings.is_configured:
        raise SMTPNotConfigured("A caixa de e-mail de envio ainda não foi configurada.")

    password = crypto_utils.decrypt(settings.smtp_password_encrypted)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.sender_name or settings.sender_email, settings.sender_email))
    msg["To"] = formataddr((to_name or "", to_email))

    # Versão texto simples como fallback (clientes que bloqueiam HTML).
    text_fallback = "Este e-mail requer um cliente compatível com HTML para ser exibido."
    msg.attach(MIMEText(text_fallback, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.ehlo()
        if settings.use_tls:
            server.starttls(context=context)
            server.ehlo()
        server.login(settings.smtp_user, password)
        server.sendmail(settings.sender_email, [to_email], msg.as_string())


def send_test_email(settings, to_email: str) -> None:
    body = "<p>Este é um e-mail de teste do seu sistema de disparo de campanhas.</p>"
    send_email(settings, to_email, "", "Teste de configuração", body)
