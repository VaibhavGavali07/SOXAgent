"""Notification service – sends email (SMTP) and webhook alerts on new violations."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

logger = logging.getLogger(__name__)


class NotificationService:
    """Delivers email and/or webhook notifications when violations are detected."""

    _SEV_RANK = {"High": 3, "Medium": 2, "Low": 1}

    def __init__(self, settings: dict[str, str]):
        self.smtp_host       = settings.get("smtp_host", "")
        self.smtp_port       = int(settings.get("smtp_port") or 587)
        self.smtp_tls        = settings.get("smtp_tls", "true").lower() not in ("false", "0", "no")
        self.smtp_user       = settings.get("smtp_user", "")
        self.smtp_password   = settings.get("smtp_password", "")
        self.smtp_from       = settings.get("smtp_from", "") or self.smtp_user
        self.smtp_to         = settings.get("smtp_to", "")
        self.webhook_url     = settings.get("webhook_url", "")
        self.notify_severity = settings.get("notify_severity", "High")

        self._email_ok   = bool(self.smtp_host and self.smtp_to)
        self._webhook_ok = bool(self.webhook_url)

    # ── Public API ────────────────────────────────────────────────────────────

    def notify(self, violations: list[dict[str, Any]]) -> None:
        """Send notifications for violations that meet the severity threshold."""
        if not violations:
            return
        filtered = self._filter(violations)
        if not filtered:
            return
        if self._email_ok:
            try:
                self._send_email(filtered)
                logger.info("Email notification sent for %d violation(s).", len(filtered))
            except Exception as exc:
                logger.error("Email notification failed: %s", exc)
        if self._webhook_ok:
            try:
                self._send_webhook(filtered)
                logger.info("Webhook notification sent for %d violation(s).", len(filtered))
            except Exception as exc:
                logger.error("Webhook notification failed: %s", exc)

    def test_email(self, override: dict | None = None) -> dict:
        """Send a test email. Pass override to use form values instead of saved config."""
        cfg = {**self._as_dict(), **(override or {})}
        svc = NotificationService(cfg)
        if not svc._email_ok:
            return {"success": False, "message": "Email not configured – set SMTP Host and To Address"}
        try:
            msg = MIMEText("This is a test notification from SOX Compliance Agent.", "plain")
            msg["Subject"] = "SOX Compliance Agent – Test Notification"
            msg["From"]    = svc.smtp_from
            msg["To"]      = svc.smtp_to
            svc._deliver(msg)
            return {"success": True, "message": f"Test email sent to {svc.smtp_to}"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    def test_webhook(self, url: str | None = None) -> dict:
        """Send a test webhook POST."""
        target = url or self.webhook_url
        if not target:
            return {"success": False, "message": "Webhook URL not configured"}
        try:
            import requests
            resp = requests.post(
                target,
                json={"event": "sox_test_notification", "message": "Test from SOX Compliance Agent"},
                timeout=10,
            )
            resp.raise_for_status()
            return {"success": True, "message": f"Webhook delivered (HTTP {resp.status_code})"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    # ── Private ───────────────────────────────────────────────────────────────

    def _filter(self, violations: list[dict]) -> list[dict]:
        min_rank = self._SEV_RANK.get(self.notify_severity, 3)
        return [v for v in violations if self._SEV_RANK.get(v.get("severity", "Low"), 1) >= min_rank]

    def _as_dict(self) -> dict:
        return {
            "smtp_host": self.smtp_host, "smtp_port": str(self.smtp_port),
            "smtp_tls": str(self.smtp_tls).lower(), "smtp_user": self.smtp_user,
            "smtp_password": self.smtp_password, "smtp_from": self.smtp_from,
            "smtp_to": self.smtp_to,
        }

    def _deliver(self, msg) -> None:
        """Send a pre-built email message."""
        recipients = [a.strip() for a in self.smtp_to.split(",") if a.strip()]
        if self.smtp_tls:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as s:
                s.ehlo()
                s.starttls()
                if self.smtp_user and self.smtp_password:
                    s.login(self.smtp_user, self.smtp_password)
                s.sendmail(self.smtp_from, recipients, msg.as_string())
        else:
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as s:
                if self.smtp_user and self.smtp_password:
                    s.login(self.smtp_user, self.smtp_password)
                s.sendmail(self.smtp_from, recipients, msg.as_string())

    def _send_email(self, violations: list[dict]) -> None:
        high   = sum(1 for v in violations if v.get("severity") == "High")
        medium = sum(1 for v in violations if v.get("severity") == "Medium")
        low    = sum(1 for v in violations if v.get("severity") == "Low")

        subject = f"SOX Compliance Alert: {len(violations)} new violation(s) detected"
        if high:
            subject += f" [{high} HIGH]"

        rows = ""
        for v in violations[:20]:
            sev   = v.get("severity", "")
            color = {"High": "#dc2626", "Medium": "#d97706", "Low": "#2563eb"}.get(sev, "#64748b")
            desc  = (v.get("description") or "")[:120]
            rows += (
                f'<tr>'
                f'<td style="padding:8px;border-bottom:1px solid #e2e8f0;font-family:monospace;font-size:12px">{v.get("ticket_key","N/A")}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #e2e8f0;font-size:12px">{v.get("control_id","")}</td>'
                f'<td style="padding:8px;border-bottom:1px solid #e2e8f0"><span style="color:{color};font-weight:600;font-size:12px">{sev}</span></td>'
                f'<td style="padding:8px;border-bottom:1px solid #e2e8f0;font-size:12px">{desc}</td>'
                f'</tr>'
            )

        html = f"""<html><body style="font-family:sans-serif;color:#1e293b;max-width:700px;margin:0 auto">
  <h2 style="color:#dc2626">&#9888; SOX Compliance Violations Detected</h2>
  <p>{len(violations)} new violation(s) were detected during automated analysis:</p>
  <p>
    <b style="color:#dc2626">High: {high}</b> &nbsp;|&nbsp;
    <b style="color:#d97706">Medium: {medium}</b> &nbsp;|&nbsp;
    <b style="color:#2563eb">Low: {low}</b>
  </p>
  <table style="border-collapse:collapse;width:100%;margin-top:16px">
    <thead>
      <tr style="background:#f8fafc">
        <th style="padding:10px 8px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748b">Ticket</th>
        <th style="padding:10px 8px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748b">Control</th>
        <th style="padding:10px 8px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748b">Severity</th>
        <th style="padding:10px 8px;text-align:left;font-size:11px;text-transform:uppercase;color:#64748b">Description</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="margin-top:24px;color:#64748b;font-size:12px">Log in to your SOX Compliance Agent dashboard to review and take action.</p>
  <p style="color:#94a3b8;font-size:11px">&#x2014; Automated notification from SOX Compliance Agent</p>
</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = self.smtp_from
        msg["To"]      = self.smtp_to
        msg.attach(MIMEText(html, "html"))
        self._deliver(msg)

    def _send_webhook(self, violations: list[dict]) -> None:
        import requests
        payload = {
            "event":      "sox_violations_detected",
            "total":      len(violations),
            "high":       sum(1 for v in violations if v.get("severity") == "High"),
            "medium":     sum(1 for v in violations if v.get("severity") == "Medium"),
            "low":        sum(1 for v in violations if v.get("severity") == "Low"),
            "violations": violations[:50],
        }
        requests.post(self.webhook_url, json=payload, timeout=10).raise_for_status()
