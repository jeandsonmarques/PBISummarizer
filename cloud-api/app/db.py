import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def _get_database_url() -> str:
    raw = os.environ.get("DATABASE_URL") or os.environ.get("URL_DO_BANCO_DE_DADOS", "")
    if not raw:
        raise RuntimeError("DATABASE_URL or URL_DO_BANCO_DE_DADOS not set")
    return _normalize_db_url(raw)


engine = create_engine(_get_database_url(), pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
