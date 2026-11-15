from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from app.config import settings

def normalize_database_url(url: str) -> str:
    """Normalize database connection string for SQLAlchemy 2.0 with psycopg2.
    
    Render sets DATABASE_URL with 'postgres://' or 'postgresql://'.
    In SQLAlchemy 2.0, 'postgresql://' defaults to the 'psycopg' (v3) driver.
    Normalizing to 'postgresql+psycopg2://' explicitly instructs SQLAlchemy
    to use the psycopg2 driver installed via psycopg2-binary.
    """
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


# Normalize database URL for PostgreSQL compatibility
db_url = normalize_database_url(settings.database_url)

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
