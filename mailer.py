"""Send the ledger workbook by email.

Two transports, chosen from the environment:

* **Gmail API** (``GMAIL_CLIENT_ID`` + ``GMAIL_CLIENT_SECRET`` +
  ``GMAIL_REFRESH_TOKEN``). Talks HTTPS on port 443, so it works on Render's
  free plan, which blocks outbound SMTP ports (25, 465, 587). Get the refresh
  token once with ``python gmail_auth.py``.
* **SMTP** (``SMTP_USER`` + ``SMTP_PASSWORD``, a Gmail *app password*). Works
  locally and on a paid Render instance; blocked on a free one.

Neither set means mail is not configured; the dialog then offers the
"Open in Gmail" fallback instead.
"""
import base64
import json
import os
import re
import smtplib
import ssl
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

XLSX_MIME = ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet")
MAX_RECIPIENTS = 20

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")


class MailError(Exception):
    """A send that failed for a reason worth showing the admin."""


def parse_recipients(raw) -> list:
    """Split a free-typed address list (; , spaces or newlines) into clean,
    de-duplicated addresses. Raises MailError on anything that is not an email."""
    seen, out = set(), []
    for part in re.split(r"[;,\s]+", raw or ""):
        address = part.strip().strip("<>").lower()
        if not address:
            continue
        if len(address) > 254 or not _EMAIL_RE.match(address):
            raise MailError(f"“{part.strip()}” is not a valid email address.")
        if address not in seen:
            seen.add(address)
            out.append(address)
    if len(out) > MAX_RECIPIENTS:
        raise MailError(f"At most {MAX_RECIPIENTS} recipients per email.")
    return out


def transport() -> str:
    """'gmail', 'smtp', or '' when mail is not configured."""
    env = os.environ
    if all(env.get(k, "").strip() for k in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")):
        return "gmail"
    if env.get("SMTP_USER", "").strip() and env.get("SMTP_PASSWORD", "").strip():
        return "smtp"
    return ""


def build_message(recipients, subject, body, attachment, filename) -> EmailMessage:
    sender = os.environ.get("MAIL_FROM", "").strip() or os.environ.get("SMTP_USER", "").strip()
    sender_name = os.environ.get("MAIL_FROM_NAME", "Bail's Cricket Ground").strip()
    msg = EmailMessage()
    if sender:
        msg["From"] = formataddr((sender_name, sender))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)
    msg.add_attachment(attachment, maintype=XLSX_MIME[0], subtype=XLSX_MIME[1], filename=filename)
    return msg


def deliver(msg: EmailMessage) -> None:
    """Send a built message with whichever transport is configured."""
    kind = transport()
    if kind == "gmail":
        _send_gmail_api(msg)
    elif kind == "smtp":
        _send_smtp(msg)
    else:
        raise MailError("Email is not set up on this server.")


def _post(url, data: bytes, headers: dict) -> dict:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            payload = json.loads(exc.read().decode("utf-8"))
            error = payload.get("error")
            detail = (error.get("message") if isinstance(error, dict) else error) or ""
            detail = detail or payload.get("error_description", "")
        except (ValueError, AttributeError):
            pass
        raise MailError(f"Gmail refused the request ({exc.code}){': ' + detail if detail else ''}.")
    except (urllib.error.URLError, TimeoutError) as exc:
        raise MailError(f"Could not reach Gmail: {getattr(exc, 'reason', exc)}.")


def _send_gmail_api(msg: EmailMessage) -> None:
    env = os.environ
    token = _post(
        "https://oauth2.googleapis.com/token",
        urllib.parse.urlencode({
            "client_id": env["GMAIL_CLIENT_ID"].strip(),
            "client_secret": env["GMAIL_CLIENT_SECRET"].strip(),
            "refresh_token": env["GMAIL_REFRESH_TOKEN"].strip(),
            "grant_type": "refresh_token",
        }).encode(),
        {"Content-Type": "application/x-www-form-urlencoded"},
    ).get("access_token")
    if not token:
        raise MailError("Gmail did not issue an access token. Re-run gmail_auth.py.")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")
    _post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        json.dumps({"raw": raw}).encode(),
        {"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )


def _send_smtp(msg: EmailMessage) -> None:
    env = os.environ
    host = env.get("SMTP_HOST", "smtp.gmail.com").strip() or "smtp.gmail.com"
    port = int(env.get("SMTP_PORT", "587") or 587)
    user, password = env["SMTP_USER"].strip(), env["SMTP_PASSWORD"].strip()
    context = ssl.create_default_context()
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as server:
                server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        raise MailError("The mail server rejected the login. For Gmail, use an app password.")
    except (smtplib.SMTPException, OSError) as exc:
        raise MailError(f"Could not send through {host}:{port} ({exc}). "
                        "On Render's free plan SMTP is blocked; use the Gmail API instead.")
