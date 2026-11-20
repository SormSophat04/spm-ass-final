import os

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.abspath(os.path.dirname(__file__)), ".env"))
except ImportError:
    pass

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

    # Real Email & OTP Authentication Settings
    OTP_LENGTH = int(os.getenv("OTP_LENGTH", 6))
    OTP_EXPIRY_MINUTES = int(os.getenv("OTP_EXPIRY_MINUTES", 5))
    OTP_RESEND_COOLDOWN_SECONDS = int(os.getenv("OTP_RESEND_COOLDOWN_SECONDS", 45))
    OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", 5))

    # Email Delivery Transport ("auto", "smtp", or "resend")
    MAIL_PROVIDER = os.getenv("MAIL_PROVIDER", "auto").strip().lower()
    SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").strip().lower() in ("1", "true", "yes", "on")
    SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").strip().lower() in ("1", "true", "yes", "on")
    SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "").strip()
    SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "AcadCoord Institutional Portal").strip()

    # Optional Resend HTTP API transport
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "").strip()
    RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", "").strip()

    # Supported Academic Roles
    ROLES = [
        "Dean",
        "Professor",
        "Teaching Assistant",
        "Student",
        "Auditor"
    ]
