import logging
from datetime import datetime
from email.message import EmailMessage
from typing import Optional, List, Dict, Any
import aiosmtplib
from sqlalchemy.orm import Session

from app.config import settings
from app.models import NotificationLog

logger = logging.getLogger(__name__)


class NotificationService:
    """Outbound email dispatch and notification service supporting both production SMTP and safe test simulation."""

    # In-memory inspection log for automated testing and auditing
    _sent_messages: List[Dict[str, Any]] = []

    @classmethod
    def get_sent_messages(cls) -> List[Dict[str, Any]]:
        """Retrieve sent message history for test verification."""
        return list(cls._sent_messages)

    @classmethod
    def clear_sent_messages(cls):
        """Reset the sent messages inspection queue."""
        cls._sent_messages.clear()

    @classmethod
    async def send_email(
        cls,
        db: Session,
        recipient_email: str,
        recipient_name: Optional[str],
        subject: str,
        body_text: str,
        notification_type: str,
        senior_id: Optional[int] = None,
        related_entity_id: Optional[int] = None,
    ) -> bool:
        """Send an email alert via SMTP or safe test simulation, logging the delivery status to the database.
        
        Returns True ONLY if delivery succeeds or simulation succeeds.
        Never exposes SMTP passwords or credentials in logs.
        """
        # Validate recipient email
        if not recipient_email or "@" not in recipient_email:
            logger.warning(f"Invalid recipient email '{recipient_email}' passed to NotificationService.")
            return False

        message_record = {
            "recipient_email": recipient_email,
            "recipient_name": recipient_name,
            "senior_id": senior_id,
            "notification_type": notification_type,
            "subject": subject,
            "body_text": body_text,
            "related_entity_id": related_entity_id,
            "timestamp": datetime.utcnow(),
        }

        # 1. Mock / Simulated Delivery Mode (Safe for tests and local development)
        if not settings.smtp_enabled:
            logger.info(
                f"[SIMULATED EMAIL NOTIFICATION] To: {recipient_email} ({recipient_name or 'N/A'}) | "
                f"Type: {notification_type} | Subject: {subject}"
            )
            cls._sent_messages.append(message_record)

            log_entry = NotificationLog(
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                senior_id=senior_id,
                notification_type=notification_type,
                subject=subject,
                body_text=body_text,
                status="simulated",
                error_message=None,
                related_entity_id=related_entity_id,
                created_at=datetime.utcnow(),
            )
            db.add(log_entry)
            db.commit()
            return True

        # 2. Real SMTP Outbound Delivery (Production with aiosmtplib)
        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = f"{recipient_name} <{recipient_email}>" if recipient_name else recipient_email
        msg["Subject"] = subject
        msg.set_content(body_text)

        try:
            logger.info(
                f"Attempting SMTP dispatch to {recipient_email} via {settings.smtp_host}:{settings.smtp_port} "
                f"[TLS={settings.smtp_tls}]..."
            )
            use_tls = (settings.smtp_port == 465)
            start_tls = (settings.smtp_tls and settings.smtp_port != 465)

            await aiosmtplib.send(
                msg,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_user if settings.smtp_user else None,
                password=settings.smtp_password if settings.smtp_password else None,
                use_tls=use_tls,
                start_tls=start_tls,
                timeout=settings.smtp_timeout_seconds,
            )

            cls._sent_messages.append(message_record)

            log_entry = NotificationLog(
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                senior_id=senior_id,
                notification_type=notification_type,
                subject=subject,
                body_text=body_text,
                status="sent",
                error_message=None,
                related_entity_id=related_entity_id,
                created_at=datetime.utcnow(),
            )
            db.add(log_entry)
            db.commit()
            logger.info(f"SMTP dispatch successfully confirmed for {recipient_email}.")
            return True

        except Exception as exc:
            # Safe error logging: never expose settings.smtp_password
            err_msg = f"SMTP dispatch failed: {type(exc).__name__}: {str(exc)}"
            logger.error(f"Failed to deliver email to {recipient_email}: {type(exc).__name__}")

            log_entry = NotificationLog(
                recipient_email=recipient_email,
                recipient_name=recipient_name,
                senior_id=senior_id,
                notification_type=notification_type,
                subject=subject,
                body_text=body_text,
                status="failed",
                error_message=err_msg,
                related_entity_id=related_entity_id,
                created_at=datetime.utcnow(),
            )
            db.add(log_entry)
            db.commit()
            return False
