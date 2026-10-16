import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
PDF_EXPORT_DIR = os.path.join(BASE_DIR, "exports")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(PDF_EXPORT_DIR, exist_ok=True)

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "academic-coordinator-secret-key-2026-secure")
    
    # Defaults to local SQLite file for immediate zero-config plug-and-play,
    # or takes DATABASE_URL for institutional PostgreSQL instances
    DATABASE_URL = os.getenv(
        "DATABASE_URL", 
        f"sqlite:///{os.path.join(DATA_DIR, 'academic_coordinator.db')}"
    )
    
    # Compliance & Grace Period Rules
    LATE_GRACE_PERIOD_MINUTES = int(os.getenv("LATE_GRACE_PERIOD_MINUTES", 10))
    EARLY_DISCONNECT_GRACE_MINUTES = int(os.getenv("EARLY_DISCONNECT_GRACE_MINUTES", 10))
    MIN_ATTENDANCE_PCT_FOR_CREDIT = float(os.getenv("MIN_ATTENDANCE_PCT_FOR_CREDIT", 75.0))
    MAX_UNEXCUSED_ABSENCE_THRESHOLD = int(os.getenv("MAX_UNEXCUSED_ABSENCE_THRESHOLD", 3))

    # Supported Academic Roles
    ROLES = [
        "Dean",
        "Professor",
        "Teaching Assistant",
        "Student",
        "Auditor"
    ]
