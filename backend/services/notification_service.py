from __future__ import annotations

import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from sqlalchemy.orm import Session

from backend.storage import crud


class NotificationService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.config = self._load_notification_config()

    def _load_notification_config(self) -> dict[str, Any]:
        for config in crud.list_configs(self.db):
            if config.config_type == "notifications":
                return dict(config.data)
        return {}

    def notify_high_severity(self, run_id: str, alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sent: list[dict[str, Any]] = []
        high_alerts = [a for a in alerts if a["severity"] == "HIGH"]
        if not high_alerts:
            return sent

        # Try email notification
        email_to = self.config.get("email_to") or os.getenv("NOTIFICATION_EMAIL_TO", "")
        smtp_host = self.config.get("smtp_host") or os.getenv("SMTP_HOST", "")
        smtp_port = int(self.config.get("smtp_port") or os.getenv("SMTP_PORT", "587"))
        smtp_user = self.config.get("smtp_user") or os.getenv("SMTP_USER", "")
        smtp_password = self.config.get("smtp_password") or os.getenv("SMTP_PASSWORD", "")
        email_from = self.config.get("email_from") or smtp_user or os.getenv("SMTP_FROM", "sox-agent@localhost")

        if email_to and smtp_host:
            try:
                self._send_email(
                    smtp_host=smtp_host,
                    smtp_port=smtp_port,
                    smtp_user=smtp_user,
                    smtp_password=smtp_password,
                    email_from=email_from,
                    email_to=email_to,
                    run_id=run_id,
                    alerts=high_alerts,
                )
                for alert in high_alerts:
                    payload = {
                        "ticket_id": alert["ticket_id"],
                        "rule_id": alert["rule_id"],
                        "severity": alert["severity"],
                        "detail": alert["detail"],
                    }
                    crud.create_notification(self.db, run_id, "email", alert["severity"], payload, "sent")
                    sent.append({"channel": "email", "status": "sent", "payload": payload})
            except Exception as exc:
                for alert in high_alerts:
                    payload = {
                        "ticket_id": alert["ticket_id"],
                        "rule_id": alert["rule_id"],
                        "severity": alert["severity"],
                        "detail": alert["detail"],
                        "error": str(exc),
                    }
                    crud.create_notification(self.db, run_id, "email", alert["severity"], payload, "failed")
                    sent.append({"channel": "email", "status": "failed", "payload": payload})
        else:
            # Fallback: mock/queued
            for alert in high_alerts:
                status = "mock_sent" if os.getenv("MOCK_MODE", "true").lower() == "true" else "queued"
                payload = {
                    "ticket_id": alert["ticket_id"],
                    "rule_id": alert["rule_id"],
                    "severity": alert["severity"],
                    "detail": alert["detail"],
                }
                crud.create_notification(self.db, run_id, "email", alert["severity"], payload, status)
                sent.append({"channel": "email", "status": status, "payload": payload})

        return sent

    def _send_email(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        email_from: str,
        email_to: str,
        run_id: str,
        alerts: list[dict[str, Any]],
    ) -> None:
        subject = f"⚠️ SOX Compliance Alert — {len(alerts)} HIGH severity violation(s) detected"

        rows = ""
        for alert in alerts:
            rows += f"""
            <tr>
                <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;font-weight:600;">{alert['ticket_id']}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;">{alert['rule_id']}</td>
                <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;">
                    <span style="background:#fee2e2;color:#b91c1c;padding:2px 8px;border-radius:12px;font-size:12px;font-weight:600;">HIGH</span>
                </td>
                <td style="padding:8px 12px;border-bottom:1px solid #e2e8f0;color:#475569;">{alert['detail'][:120]}</td>
            </tr>"""

        html_body = f"""
        <div style="font-family:'Segoe UI',Roboto,Arial,sans-serif;max-width:680px;margin:0 auto;">
            <div style="background:#dc2626;padding:16px 24px;border-radius:12px 12px 0 0;">
                <h2 style="margin:0;color:white;font-size:18px;">⚠️ SOX ITGC Compliance Alert</h2>
            </div>
            <div style="border:1px solid #e2e8f0;border-top:none;padding:20px 24px;border-radius:0 0 12px 12px;">
                <p style="color:#334155;font-size:14px;margin:0 0 8px;">
                    <strong>{len(alerts)}</strong> HIGH severity violation(s) detected during compliance analysis run <code>{run_id[:12]}...</code>
                </p>
                <p style="color:#64748b;font-size:13px;margin:0 0 16px;">
                    Immediate review and remediation is required.
                </p>
                <table style="width:100%;border-collapse:collapse;font-size:13px;color:#1e293b;">
                    <thead>
                        <tr style="background:#f8fafc;">
                            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;">Ticket</th>
                            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;">Rule</th>
                            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;">Severity</th>
                            <th style="padding:8px 12px;text-align:left;border-bottom:2px solid #e2e8f0;">Detail</th>
                        </tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
                <p style="color:#94a3b8;font-size:12px;margin:16px 0 0;">
                    Sent by SOX ITGC Compliance Agent
                </p>
            </div>
        </div>
        """

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = email_from
        msg["To"] = email_to
        plain_text = f"SOX Compliance Alert: {len(alerts)} HIGH severity violations in run {run_id}. Review immediately."
        msg.attach(MIMEText(plain_text, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        recipients = [addr.strip() for addr in email_to.split(",") if addr.strip()]

        if smtp_port == 465:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=15) as server:
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(email_from, recipients, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as server:
                server.ehlo()
                try:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass  # Server doesn't support STARTTLS
                if smtp_user and smtp_password:
                    server.login(smtp_user, smtp_password)
                server.sendmail(email_from, recipients, msg.as_string())

    @staticmethod
    def test_email_connection(
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        email_from: str,
        email_to: str,
    ) -> dict[str, Any]:
        """Test the SMTP connection and optionally send a test email."""
        if not smtp_host:
            return {"ok": False, "message": "SMTP host is required to test email notifications."}
        if not email_to:
            return {"ok": False, "message": "Recipient email (email_to) is required."}

        try:
            if int(smtp_port) == 465:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(smtp_host, int(smtp_port), context=context, timeout=10) as server:
                    if smtp_user and smtp_password:
                        server.login(smtp_user, smtp_password)
                    # Send a test email
                    msg = MIMEText(
                        "This is a test email from the SOX ITGC Compliance Agent.\n\n"
                        "If you received this email, the notification setup is working correctly.",
                        "plain",
                    )
                    msg["Subject"] = "✅ SOX Agent — Email Notification Test"
                    msg["From"] = email_from or smtp_user
                    msg["To"] = email_to
                    recipients = [a.strip() for a in email_to.split(",") if a.strip()]
                    server.sendmail(email_from or smtp_user, recipients, msg.as_string())
            else:
                with smtplib.SMTP(smtp_host, int(smtp_port), timeout=10) as server:
                    server.ehlo()
                    try:
                        server.starttls(context=ssl.create_default_context())
                        server.ehlo()
                    except smtplib.SMTPNotSupportedError:
                        pass
                    if smtp_user and smtp_password:
                        server.login(smtp_user, smtp_password)
                    msg = MIMEText(
                        "This is a test email from the SOX ITGC Compliance Agent.\n\n"
                        "If you received this email, the notification setup is working correctly.",
                        "plain",
                    )
                    msg["Subject"] = "✅ SOX Agent — Email Notification Test"
                    msg["From"] = email_from or smtp_user
                    msg["To"] = email_to
                    recipients = [a.strip() for a in email_to.split(",") if a.strip()]
                    server.sendmail(email_from or smtp_user, recipients, msg.as_string())

            return {
                "ok": True,
                "message": f"SMTP connection successful — test email sent to {email_to}",
            }
        except smtplib.SMTPAuthenticationError as exc:
            return {"ok": False, "message": f"SMTP authentication failed: {exc}"}
        except smtplib.SMTPConnectError as exc:
            return {"ok": False, "message": f"Could not connect to SMTP server: {exc}"}
        except Exception as exc:
            return {"ok": False, "message": f"SMTP connection failed: {exc}"}
