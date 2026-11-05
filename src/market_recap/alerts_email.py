"""The alerts digest by e-mail: one message per session, sent only when alerts.json
says its changes are news (``email.due``).

SMTP settings come from the environment only, never the config or the repo:
ALERT_SMTP_USER and ALERT_SMTP_PASSWORD (for Gmail, the address and an app
password), ALERT_EMAIL_TO (one or more addresses, comma-separated), and
optionally ALERT_SMTP_HOST / ALERT_SMTP_PORT (Gmail's SSL endpoint by default).
With any of the first three missing the step says so and sends nothing.
"""

from __future__ import annotations

from datetime import date
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

# Inline styles only: Gmail drops <style> blocks in many clients and every class.
# Unquoted family names: the styles sit in single-quoted attributes.
SANS = "-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica,Arial,sans-serif"
MONO = "SF Mono,Menlo,Consolas,Liberation Mono,monospace"
INK, DIM, FAINT, RULE, PAPER = "#1d2433", "#5d6676", "#8a93a3", "#e4e6ea", "#f3f4f6"
# (accent, tint) for a section's bar, badge and value.
TONE = {"High": ("#b42318", "#fef3f2"), "NEW": ("#b54708", "#fffaeb"), "ACTIVE": ("#b54708", "#fffaeb"),
        "EASED": ("#475467", "#f2f4f7"), "CLEARED": ("#067647", "#ecfdf3")}
FOOTNOTE = ("Each alert is a fixed rule crossing a line; a reading that stays past it is not repeated. "
            "Held: back inside its line but within the rule's reset margin, so not yet cleared. Descriptive, not a forecast.")


def _line(e: dict) -> str:
    line = f" ({e['line']})" if e.get("line") else ""
    return f"{e['label']}: {e['value']}{line}"


def _day(as_of: str | None) -> str:
    try:
        return date.fromisoformat(as_of).strftime("%a %-d %b %Y")
    except (TypeError, ValueError):
        return as_of or ""


def _sections(payload: dict) -> tuple[list[tuple[str, str, list[dict]]], list[dict]]:
    """([(title, tone key, events)], standing) for the e-mail, high first, then by state."""
    events = payload.get("events") or []
    # Only what this build adds to the session's published alerts (a rerun's news).
    fresh = (payload.get("email") or {}).get("fresh")
    if fresh is not None:
        events = [e for e in events if e["key"] in set(fresh)]
    high = [e for e in events if e["severity"] == "high"]
    sections = ([("High", "High", high)] if high else []) + [
        (title, state, [e for e in events if e["state"] == state and e not in high]) for state, title in STATE_TITLES]
    return [s for s in sections if s[2]], payload.get("standing") or []


def _standing_line(e: dict) -> str:
    if not e.get("line"):
        return ""
    return f"held · line {e['line']}" if e.get("held") else f"past {e['line']}"


def _href(site: str, e: dict) -> str:
    return escape(f"{site}/{e['link']}") if e.get("link") else escape(site + "/")


def _alert_row(e: dict, accent: str, site: str) -> str:
    note = f"<div style='font-size:12px;color:{FAINT};margin-top:2px'>{escape(e['note'])}</div>" if e.get("note") else ""
    word = "was" if e.get("state") in ("CLEARED", "EASED") else "line"
    line = f"<div style='font-size:11px;color:{FAINT};margin-top:2px'>{word} {escape(e['line'])}</div>" if e.get("line") else ""
    return (f"<tr><td style='padding:10px 0;border-top:1px solid {RULE};vertical-align:top'>"
            f"<div style='font-size:10px;letter-spacing:.08em;color:{FAINT};text-transform:uppercase'>{escape(e['group'])}</div>"
            f"<a href='{_href(site, e)}' style='font-size:15px;font-weight:600;color:{INK};text-decoration:none'>{escape(e['label'])}</a>"
            f"{note}</td>"
            f"<td style='padding:10px 0 10px 12px;border-top:1px solid {RULE};vertical-align:top;text-align:right;white-space:nowrap'>"
            f"<div style='font-family:{MONO};font-size:17px;font-weight:600;color:{accent}'>{escape(e['value'])}</div>{line}</td></tr>")


def _html(payload: dict, subject: str, sections, standing, preheader: str) -> str:
    site = payload.get("site", "").rstrip("/")
    compared = payload.get("compared_with")
    edition = (payload.get("edition") or "").upper()
    meta = " · ".join(x for x in (edition, f"vs {compared}" if compared else "first build") if x)
    chips = "".join(
        f"<span style='display:inline-block;margin:0 6px 6px 0;padding:3px 8px;border-radius:10px;font-size:11px;"
        f"font-weight:600;letter-spacing:.04em;color:{TONE[tone][0]};background:{TONE[tone][1]}'>{len(items)} {escape(title.split(' (')[0].upper())}</span>"
        for title, tone, items in sections)
    if standing:
        chips += (f"<span style='display:inline-block;margin:0 6px 6px 0;padding:3px 8px;border-radius:10px;font-size:11px;"
                  f"font-weight:600;letter-spacing:.04em;color:{DIM};background:{PAPER}'>{len(standing)} STILL PAST A LINE</span>")
    body = []
    for title, tone, items in sections:
        accent, tint = TONE[tone]
        rows = "".join(_alert_row(e, accent, site) for e in items)
        body.append(f"<tr><td style='padding:18px 24px 0'>"
                    f"<div style='border-left:3px solid {accent};padding-left:10px;font-size:12px;font-weight:700;letter-spacing:.08em;"
                    f"color:{accent}'>{escape(title.upper())}</div>"
                    f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;margin-top:6px'>{rows}</table>"
                    f"</td></tr>")
    if standing:
        rows = "".join(
            f"<tr><td style='padding:5px 0;border-top:1px solid {RULE};font-size:13px;color:{DIM}'>"
            f"<a href='{_href(site, e)}' style='color:{DIM};text-decoration:none'>{escape(e['label'])}</a></td>"
            f"<td style='padding:5px 0 5px 12px;border-top:1px solid {RULE};text-align:right;white-space:nowrap;font-family:{MONO};font-size:13px;color:{INK}'>"
            f"{escape(e['value'])}<div style='color:{FAINT};font-family:{SANS};font-size:11px'>{escape(_standing_line(e))}</div></td></tr>"
            for e in standing)
        body.append(f"<tr><td style='padding:22px 24px 0'>"
                    f"<div style='font-size:12px;font-weight:700;letter-spacing:.08em;color:{DIM}'>STILL PAST A LINE · NOT NEWS TODAY</div>"
                    f"<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='border-collapse:collapse;margin-top:6px'>{rows}</table>"
                    f"</td></tr>")
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='color-scheme' content='light only'><title>{escape(subject)}</title></head>
<body style='margin:0;padding:0;background:{PAPER}'>
<div style='display:none;max-height:0;overflow:hidden;opacity:0;color:{PAPER}'>{escape(preheader)}&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;&#847;&zwnj;&nbsp;</div>
<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='background:{PAPER}'><tr><td align='center' style='padding:20px 12px'>
<table role='presentation' width='100%' cellpadding='0' cellspacing='0' style='max-width:600px;background:#ffffff;border:1px solid {RULE};border-radius:6px;font-family:{SANS};color:{INK}'>
<tr><td style='padding:20px 24px 14px;border-bottom:1px solid {RULE}'>
<div style='font-size:11px;font-weight:700;letter-spacing:.12em;color:{FAINT}'>MARKET RECAP · ALERTS</div>
<div style='font-size:20px;font-weight:600;margin:4px 0 2px'>{escape(_day(payload.get('as_of')))}</div>
<div style='font-size:12px;color:{DIM};margin-bottom:10px'>{escape(meta)}</div>{chips}</td></tr>
{''.join(body)}
<tr><td style='padding:22px 24px 6px'><a href='{escape(site + "/")}' style='display:inline-block;padding:9px 16px;border-radius:4px;background:{INK};color:#ffffff;font-size:13px;font-weight:600;text-decoration:none'>Open the dashboard</a></td></tr>
<tr><td style='padding:10px 24px 20px;font-size:11px;line-height:1.5;color:{FAINT}'>{escape(FOOTNOTE)}</td></tr>
</table></td></tr></table></body></html>"""


def compose(payload: dict) -> tuple[str, str, str]:
    """(subject, plain text, HTML) for a payload's events, high first, then by state."""
    sections, standing = _sections(payload)
    site = payload.get("site", "").rstrip("/")
    subject = (payload.get("email") or {}).get("subject") or f"Market Recap alerts · {payload.get('as_of')}"
    compared = payload.get("compared_with")
    intro = f"Session {payload.get('as_of')}" + (f", compared with {compared}" if compared else "") + "."
    text = [subject, "", intro, ""]
    for title, _, items in sections:
        text.append(title.upper())
        text += [f"  - [{e['group']}] {_line(e)}" + (f"  {site}/{e['link']}" if e.get("link") else "") for e in items]
        text.append("")
    if standing:
        text.append("STILL PAST A LINE (not news today)")
        text += [f"  - [{e['group']}] {e['label']}: {e['value']}" + (f" ({_standing_line(e)})" if e.get("line") else "") for e in standing]
        text.append("")
    text.append(FOOTNOTE)
    # The inbox preview line: what crossed, by name, before any boilerplate.
    preheader = " · ".join(f"{e['label']} {e['value']}" for _, _, items in sections for e in items[:3])[:180] or intro
    return subject, "\n".join(text), _html(payload, subject, sections, standing, preheader)


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
