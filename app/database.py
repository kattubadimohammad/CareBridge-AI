from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

# Normalize database URL for PostgreSQL compatibility (e.g., Render sets DATABASE_URL with postgres://)
db_url = settings.database_url
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Configure SQLite-specific args vs PostgreSQL args
connect_args = {}
engine_kwargs = {
    "echo": (settings.environment == "development"),
}

if db_url.startswith("sqlite"):
    connect_args["check_same_thread"] = False
else:
    # Enable pool pre-ping on cloud databases to automatically recycle stale dropped connections
    engine_kwargs["pool_pre_ping"] = True

engine = create_engine(
    db_url,
    connect_args=connect_args,
    **engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Dependency yield for request-scoped database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
