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
    Base.metadata.create_all(bind=engine)
