"""Sending email through any SMTP provider (Resend, Postmark, SES, ...). Standard library only.

EMAIL_BACKEND=off      nothing is sent
EMAIL_BACKEND=console  dev: the message is logged instead of sent
EMAIL_BACKEND=smtp     SMTP_HOST/PORT/USERNAME/PASSWORD, SMTP_SECURITY=starttls|ssl|none
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from .config import get_settings

log = logging.getLogger("mindmesh.email")


@dataclass
class Email:
    to: str
    subject: str
    text: str
    html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class EmailError(Exception):
    pass


def build_message(e: Email, sender: str) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = sender, e.to, e.subject
    m["Date"] = formatdate(localtime=False)
    m["Message-ID"] = make_msgid(domain=sender.rsplit("@", 1)[-1].strip("> ") or "localhost")
    for k, v in e.headers.items():
        m[k] = v
    m.set_content(e.text)
    if e.html:
        m.add_alternative(e.html, subtype="html")
    return m


def send(e: Email) -> bool:
    """Returns True if handed to a transport (or logged in console mode), False when email is off."""
    s = get_settings()
    if s.email_backend == "off":
        return False
    msg = build_message(e, s.email_from)
    if s.email_backend == "console":
        log.info("email (console backend, not sent) to=%s subject=%r\n%s", e.to, e.subject, e.text)
        return True
    if not s.smtp_host:
        raise EmailError("EMAIL_BACKEND=smtp needs SMTP_HOST")
    try:
        ctx = ssl.create_default_context()
        if s.smtp_security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=20, context=ctx)
        else:
            server = smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=20)
        with server:
            if s.smtp_security == "starttls":
                server.starttls(context=ctx)
            if s.smtp_username:
                server.login(s.smtp_username, s.smtp_password or "")
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"SMTP send failed: {type(exc).__name__}") from exc
    return True
