import pytest
from app.database import Base, engine
from app.services.auth_service import pin_security_manager
from app.services.notification_service import NotificationService


@pytest.fixture(autouse=True)
def clean_test_database():
    """Ensure every test runs against a clean, isolated database schema and security state."""
    pin_security_manager._failures.clear()
    pin_security_manager._lockouts.clear()
    NotificationService.clear_sent_messages()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    pin_security_manager._failures.clear()
    pin_security_manager._lockouts.clear()
    NotificationService.clear_sent_messages()
