"""The alerts digest by e-mail: one message per session, sent only when alerts.json
says its changes are news (``email.due``).

SMTP settings come from the environment only, never the config or the repo:
ALERT_SMTP_USER and ALERT_SMTP_PASSWORD (for Gmail, the address and an app
password), ALERT_EMAIL_TO (one or more addresses, comma-separated), and
optionally ALERT_SMTP_HOST / ALERT_SMTP_PORT (Gmail's SSL endpoint by default).
With any of the first three missing the step says so and sends nothing.
"""

from __future__ import annotations

from email.message import EmailMessage
from html import escape
import json
import os
from pathlib import Path
import smtplib
import ssl

from .alerts import FILE
from .config import ARTIFACT_DIR

STATE_TITLES = [("NEW", "New"), ("ACTIVE", "Active (first build, nothing to compare)"), ("EASED", "Eased"), ("CLEARED", "Cleared")]


def _line(e: dict) -> str:
    line = f" ({e['line']})" if e.get("line") else ""
    return f"{e['label']}: {e['value']}{line}"


def compose(payload: dict) -> tuple[str, str, str]:
    """(subject, plain text, HTML) for a payload's events, high first, then by state."""
    events = payload.get("events") or []
    # Only what this build adds to the session's published alerts (a rerun's news).
    fresh = (payload.get("email") or {}).get("fresh")
    if fresh is not None:
        events = [e for e in events if e["key"] in set(fresh)]
    site = payload.get("site", "").rstrip("/")
    subject = (payload.get("email") or {}).get("subject") or f"Market Recap alerts · {payload.get('as_of')}"
    high = [e for e in events if e["severity"] == "high"]
    sections = ([("High", high)] if high else []) + [
        (title, [e for e in events if e["state"] == state and e not in high]) for state, title in STATE_TITLES]
    sections = [(title, items) for title, items in sections if items]
    compared = payload.get("compared_with")
    intro = f"Session {payload.get('as_of')}" + (f", compared with {compared}" if compared else "") + "."
    text = [subject, "", intro, ""]
    for title, items in sections:
        text.append(title.upper())
        text += [f"  - [{e['group']}] {_line(e)}" + (f"  {site}/{e['link']}" if e.get("link") else "") for e in items]
        text.append("")
    text.append("Each alert is a fixed rule crossing a line; a reading that stays past it is not repeated. Not a forecast.")
    html = [f"<p style='font-family:Menlo,monospace;font-size:13px'>{escape(intro)}</p>"]
    for title, items in sections:
        html.append(f"<h3 style='font-family:Menlo,monospace;font-size:13px;margin:14px 0 4px'>{escape(title.upper())}</h3><table "
                    "style='font-family:Menlo,monospace;font-size:13px;border-collapse:collapse'>")
        for e in items:
            colour = "#c0392b" if e["severity"] == "high" or e["state"] == "NEW" else "#555"
            link = f"<a href='{escape(site + '/' + e['link'])}'>open</a>" if e.get("link") else ""
            html.append(f"<tr><td style='padding:2px 8px;color:#888'>{escape(e['group'])}</td>"
                        f"<td style='padding:2px 8px;color:{colour}'>{escape(_line(e))}</td><td style='padding:2px 8px'>{link}</td></tr>")
        html.append("</table>")
    html.append("<p style='font-family:Menlo,monospace;font-size:11px;color:#888'>Each alert is a fixed rule crossing a line; "
                "a reading that stays past it is not repeated. Descriptive, not a forecast.</p>")
    return subject, "\n".join(text), "\n".join(html)


def send(*, root: Path | None = None, dry_run: bool = False, force: bool = False) -> dict:
    """Send this session's digest when it is due (or ``force``). ``dry_run`` composes only."""
    path = (root or ARTIFACT_DIR) / FILE
    if not path.exists():
        return {"sent": False, "why": f"no {FILE} in this build"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not ((payload.get("email") or {}).get("due") or force):
        return {"sent": False, "why": "nothing new this session, or already sent"}
    subject, text, html = compose(payload)
    if dry_run:
        return {"sent": False, "why": "dry run", "subject": subject, "text": text}
    user, password, to = (os.environ.get(k, "").strip() for k in ("ALERT_SMTP_USER", "ALERT_SMTP_PASSWORD", "ALERT_EMAIL_TO"))
    if not (user and password and to):
        return {"sent": False, "why": "ALERT_SMTP_USER / ALERT_SMTP_PASSWORD / ALERT_EMAIL_TO not set"}
    message = EmailMessage()
    message["Subject"], message["From"], message["To"] = subject, user, to
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    host = os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com")
    port = int(os.environ.get("ALERT_SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(message)
    return {"sent": True, "subject": subject, "events": len(payload.get("events") or [])}
