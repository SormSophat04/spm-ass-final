import importlib.util
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from config import Config

# Normalize PostgreSQL URLs and pick an installed driver (SQLAlchemy 2.1 defaults
# bare postgresql:// to psycopg v3, whereas older setups may only have psycopg2).
db_url = Config.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

has_psycopg = importlib.util.find_spec("psycopg") is not None
has_psycopg2 = importlib.util.find_spec("psycopg2") is not None

if db_url.startswith("postgresql://"):
    if not has_psycopg and has_psycopg2:
        db_url = db_url.replace("postgresql://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql+psycopg://") and not has_psycopg and has_psycopg2:
    db_url = db_url.replace("postgresql+psycopg://", "postgresql+psycopg2://", 1)
elif db_url.startswith("postgresql+psycopg2://") and not has_psycopg2 and has_psycopg:
    db_url = db_url.replace("postgresql+psycopg2://", "postgresql+psycopg://", 1)

# SQLite multi-threaded support vs PostgreSQL pooling
engine_args = {}
if db_url.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
else:
    engine_args["pool_size"] = 10
    engine_args["max_overflow"] = 20
    engine_args["pool_pre_ping"] = True

engine = create_engine(db_url, **engine_args)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()

def init_db():
    import models  # Ensure all models are registered
    from sqlalchemy import inspect, text
    from werkzeug.security import generate_password_hash

    Base.metadata.create_all(bind=engine)

    # Lightweight schema backfill for existing databases created prior to auth/OTP columns
    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("users")}
        with engine.begin() as conn:
            if "password_hash" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"))
            if "email_verified" not in columns:
                default_bool = "0" if engine.dialect.name == "sqlite" else "FALSE"
                conn.execute(text(f"ALTER TABLE users ADD COLUMN email_verified BOOLEAN DEFAULT {default_bool}"))
            if "auth_source" not in columns:
                conn.execute(text("ALTER TABLE users ADD COLUMN auth_source VARCHAR(32) DEFAULT 'institutional'"))

        users_missing_pw = db_session.query(models.User).filter(
            (models.User.password_hash == None) | (models.User.password_hash == "")
        ).all()
        if users_missing_pw:
            default_hash = generate_password_hash("Academic@2026")
            for u in users_missing_pw:
                u.password_hash = default_hash
            db_session.commit()
