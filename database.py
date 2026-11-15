from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session
from config import Config

# Handle postgresql:// vs postgresql+psycopg2:// if needed
db_url = Config.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# SQLite multi-threaded support
engine_args = {}
if db_url.startswith("sqlite"):
    engine_args["connect_args"] = {"check_same_thread": False}
else:
    engine_args["pool_size"] = 10
    engine_args["max_overflow"] = 20

engine = create_engine(db_url, **engine_args)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()
Base.query = db_session.query_property()

def init_db():
    import models  # Ensure all models are registered
    from sqlalchemy import inspect, text
    from werkzeug.security import generate_password_hash

    Base.metadata.create_all(bind=engine)

    # Lightweight schema backfill for existing SQLite databases created prior to password_hash
    inspector = inspect(engine)
    if "users" in inspector.get_table_names():
        columns = {col["name"] for col in inspector.get_columns("users")}
        if "password_hash" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(256)"))

        users_missing_pw = db_session.query(models.User).filter(
            (models.User.password_hash == None) | (models.User.password_hash == "")
        ).all()
        if users_missing_pw:
            default_hash = generate_password_hash("Academic@2026")
            for u in users_missing_pw:
                u.password_hash = default_hash
            db_session.commit()
