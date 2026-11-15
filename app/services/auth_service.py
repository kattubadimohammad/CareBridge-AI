import time
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User, UserRole, CaregiverLink, CaregiverLinkStatus

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token", auto_error=False)

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_DAYS = 7


class PinSecurityManager:
    """Protects senior PIN authentication against brute-force attacks with lockout tracking."""

    def __init__(self):
        self._failures: dict[int, list[float]] = defaultdict(list)
        self._lockouts: dict[int, float] = {}

    def check_lockout(self, user_id: int):
        now = time.time()
        lockout_expiry = self._lockouts.get(user_id)
        if lockout_expiry and now < lockout_expiry:
            remaining_mins = max(1, int((lockout_expiry - now) / 60) + 1)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account temporarily locked due to consecutive failed attempts. Try again in {remaining_mins} minute(s).",
            )
        elif lockout_expiry and now >= lockout_expiry:
            self._lockouts.pop(user_id, None)
            self._failures.pop(user_id, None)

    def record_failure(self, user_id: int):
        now = time.time()
        window = settings.pin_lockout_minutes * 60
        self._failures[user_id] = [t for t in self._failures[user_id] if now - t < window]
        self._failures[user_id].append(now)

        if len(self._failures[user_id]) >= settings.max_pin_attempts:
            self._lockouts[user_id] = now + (settings.pin_lockout_minutes * 60)
            self._failures.pop(user_id, None)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account locked due to exceeding {settings.max_pin_attempts} failed passcode attempts. Try again in {settings.pin_lockout_minutes} minute(s).",
            )

    def record_success(self, user_id: int):
        self._failures.pop(user_id, None)
        self._lockouts.pop(user_id, None)


pin_security_manager = PinSecurityManager()


class AuthService:
    """Authentication, cryptographic verification, and JWT generation."""

    @staticmethod
    def verify_password(plain: str, hashed: str) -> bool:
        return pwd_context.verify(plain, hashed)

    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
        to_encode = data.copy()
        expire = datetime.utcnow() + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))
        to_encode.update({"exp": expire})
        return jwt.encode(to_encode, settings.app_secret_key, algorithm=ALGORITHM)

    @staticmethod
    def decode_access_token(token: str) -> Optional[dict]:
        try:
            payload = jwt.decode(token, settings.app_secret_key, algorithms=[ALGORITHM])
            return payload
        except JWTError:
            return None


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency to retrieve the authenticated user from Bearer header or HttpOnly cookie."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials or token expired.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    raw_token = token
    if not raw_token:
        raw_token = request.cookies.get("access_token")

    if not raw_token:
        raise credentials_exception

    payload = AuthService.decode_access_token(raw_token)
    if not payload or "sub" not in payload:
        raise credentials_exception

    try:
        user_id = int(payload["sub"])
    except ValueError:
        raise credentials_exception

    user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        raise credentials_exception
    return user


def get_optional_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Retrieve the current user if logged in (via cookie or header), otherwise None."""
    raw_token = request.cookies.get("access_token")
    if not raw_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            raw_token = auth_header.split(" ")[1]

    if not raw_token:
        return None

    payload = AuthService.decode_access_token(raw_token)
    if not payload or "sub" not in payload:
        return None

    try:
        user_id = int(payload["sub"])
    except ValueError:
        return None

    return db.query(User).filter(User.id == user_id, User.is_active == True).first()


def require_roles(allowed_roles: List[str]):
    """Enforce role-based access for an endpoint."""
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation not permitted for role '{current_user.role}'. Required one of: {allowed_roles}",
            )
        return current_user
    return role_checker


def verify_senior_access(
    db: Session,
    current_user: User,
    senior_id: int,
    required_permission: Optional[str] = None,
) -> bool:
    """Verify that current_user has active, approved authorization to access the senior's records."""
    # Senior accessing their own records
    if current_user.id == senior_id:
        return True

    # Admin access
    if current_user.role == UserRole.ADMIN:
        return True

    # Caregiver or Family member check
    link = (
        db.query(CaregiverLink)
        .filter(
            CaregiverLink.senior_id == senior_id,
            CaregiverLink.caregiver_id == current_user.id,
            CaregiverLink.status == CaregiverLinkStatus.APPROVED,
            CaregiverLink.is_active == True,
        )
        .first()
    )

    if not link:
        # Check if there is a pending request awaiting consent
        pending = (
            db.query(CaregiverLink)
            .filter(
                CaregiverLink.senior_id == senior_id,
                CaregiverLink.caregiver_id == current_user.id,
                CaregiverLink.status == CaregiverLinkStatus.PENDING,
            )
            .first()
        )
        if pending:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Caregiver access request is pending approval by the patient.",
            )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have active authorization to access this person's records.",
        )

    if required_permission:
        perm_allowed = getattr(link, required_permission, False)
        if not perm_allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You do not have permission '{required_permission}' for this person.",
            )

    return True
