import logging
from datetime import datetime
from passlib.context import CryptContext
from app.config import settings

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """Security and passcode management."""

    @staticmethod
    def verify_passcode(plain_passcode: str, hashed_passcode: str) -> bool:
        return pwd_context.verify(plain_passcode, hashed_passcode)

    @staticmethod
    def hash_passcode(passcode: str) -> str:
        return pwd_context.hash(passcode)


from app.services.notification_service import NotificationService
from app.services.scheduler_service import SchedulerService
