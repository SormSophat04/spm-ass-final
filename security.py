import base64
import hashlib
import hmac
import json
import secrets
import time
from functools import wraps
from flask import g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import db_session

DEFAULT_DEMO_PASSWORD = "Academic@2026"
SESSION_COOKIE_NAME = "acad_session"
TOKEN_TTL_SECONDS = 60 * 60 * 24  # 24 hours

# Canonical Role Matrix Definition (Shared across Module 6, Auth & Route Guards)
ROLE_PERMISSIONS_MATRIX = {
    "Dean": {
        "description": "Highest institutional executive authority. Full oversight of all faculty courses, accreditation audits, and policy overrides.",
        "can_view_all_courses": True,
        "can_schedule_sessions": True,
        "can_override_attendance": True,
        "can_publish_grades": True,
        "can_manage_roles": True,
        "can_view_audit_trail": True,
        "can_seal_notes": True,
    },
    "Professor": {
        "description": "Primary course authority with full gradebook management, attendance verification, and syllabus certification rights.",
        "can_view_all_courses": False,
        "can_schedule_sessions": True,
        "can_override_attendance": True,
        "can_publish_grades": True,
        "can_manage_roles": False,
        "can_view_audit_trail": True,
        "can_seal_notes": True,
    },
    "Teaching Assistant": {
        "description": "Academic delegate. Permitted to verify attendance and co-edit lecture minutes; grade publishing restricted by institutional default.",
        "can_view_all_courses": False,
        "can_schedule_sessions": False,
        "can_override_attendance": True,
        "can_publish_grades": False,
        "can_manage_roles": False,
        "can_view_audit_trail": False,
        "can_seal_notes": False,
    },
    "Student": {
        "description": "Enrolled learner. Access restricted strictly to enrolled course sections, personal attendance records, live quizzes, and study guides.",
        "can_view_all_courses": False,
        "can_schedule_sessions": False,
        "can_override_attendance": False,
        "can_publish_grades": False,
        "can_manage_roles": False,
        "can_view_audit_trail": False,
        "can_seal_notes": False,
    },
    "Auditor": {
        "description": "Observer / Institutional QA inspector. Read-only access to syllabus materials and lecture archives; excluded from graded cohort curves.",
        "can_view_all_courses": False,
        "can_schedule_sessions": False,
        "can_override_attendance": False,
        "can_publish_grades": False,
        "can_manage_roles": False,
        "can_view_audit_trail": True,
        "can_seal_notes": False,
    },
}

ROLE_ALLOWED_MODULES = {
    "Dean": ["lifecycle", "attendance", "leaves", "notes", "quizzes", "roles", "audit"],
    "Professor": ["lifecycle", "attendance", "leaves", "notes", "quizzes", "audit"],
    "Teaching Assistant": ["lifecycle", "attendance", "notes", "quizzes"],
    "Student": ["lifecycle", "attendance", "leaves", "notes", "quizzes"],
    "Auditor": ["lifecycle", "notes", "audit"],
}


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(pw_hash: str, password: str) -> bool:
    if not pw_hash or not password:
        return False
    return check_password_hash(pw_hash, password)


def generate_otp_code(length: int = 6) -> str:
    """Generate a cryptographically secure numeric OTP code of the requested length."""
    digits = max(4, min(int(length), 8))
    return f"{secrets.randbelow(10 ** digits):0{digits}d}"


def hash_otp_code(email: str, otp_code: str) -> str:
    """Compute a keyed HMAC-SHA256 digest for an email + OTP pair."""
    normalized = f"otp:{email.strip().lower()}:{otp_code.strip()}".encode("utf-8")
    return hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        normalized,
        hashlib.sha256,
    ).hexdigest()


def verify_otp_hash(email: str, otp_code: str, expected_hash: str) -> bool:
    if not email or not otp_code or not expected_hash:
        return False
    candidate = hash_otp_code(email, otp_code)
    return hmac.compare_digest(candidate, expected_hash)


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def create_access_token(user_id: int, role: str, ttl_seconds: int = TOKEN_TTL_SECONDS) -> str:
    now = int(time.time())
    payload = {
        "uid": user_id,
        "role": role,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        payload_b64.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def decode_access_token(token: str):
    if not token or "." not in token:
        return None
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        expected_sig = hmac.new(
            Config.SECRET_KEY.encode("utf-8"),
            payload_b64.encode("ascii"),
            hashlib.sha256,
        ).digest()
        provided_sig = _b64url_decode(sig_b64)
        if not hmac.compare_digest(expected_sig, provided_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def extract_token_from_flask_request() -> str | None:
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    cookie_token = request.cookies.get(SESSION_COOKIE_NAME)
    if cookie_token:
        return cookie_token.strip()
    query_token = request.args.get("token", "").strip()
    if query_token:
        return query_token
    return None


def resolve_user_from_token(token: str | None):
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload:
        return None
    uid = payload.get("uid")
    if not uid:
        return None
    from models import User
    user = db_session.query(User).filter(User.id == uid, User.is_active == True).first()
    return user


def get_current_authenticated_user():
    if hasattr(g, "current_user") and g.current_user is not None:
        return g.current_user
    token = extract_token_from_flask_request()
    user = resolve_user_from_token(token)
    g.current_user = user
    return user


def get_allowed_modules_for_role(role: str) -> list[str]:
    return list(ROLE_ALLOWED_MODULES.get(role, []))


def get_user_effective_permissions(user) -> dict:
    base_perms = dict(ROLE_PERMISSIONS_MATRIX.get(user.role, ROLE_PERMISSIONS_MATRIX["Student"]))
    base_perms["allowed_modules"] = get_allowed_modules_for_role(user.role)
    return base_perms


def build_user_auth_payload(user) -> dict:
    from models import CourseEnrollment, TAPermissionScope

    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.user_id == user.id,
        CourseEnrollment.status == "active",
    ).all()

    ta_scopes = []
    if user.role == "Teaching Assistant":
        scopes = db_session.query(TAPermissionScope).filter(
            TAPermissionScope.ta_id == user.id
        ).all()
        ta_scopes = [s.to_dict() for s in scopes]

    user_dict = user.to_dict()
    user_dict["enrolled_courses"] = [
        {
            "course_id": e.course_id,
            "course_code": e.course.code,
            "course_title": e.course.title,
            "role_scope": e.role_scope,
        }
        for e in enrollments
        if e.course
    ]
    user_dict["permissions"] = get_user_effective_permissions(user)
    user_dict["allowed_modules"] = get_allowed_modules_for_role(user.role)
    user_dict["ta_scopes"] = ta_scopes
    return user_dict


def has_ta_scope(user, course_id: int, scope_flag: str) -> bool:
    if not user or user.role != "Teaching Assistant":
        return False
    from models import TAPermissionScope
    scope = db_session.query(TAPermissionScope).filter(
        TAPermissionScope.course_id == course_id,
        TAPermissionScope.ta_id == user.id,
    ).first()
    if not scope:
        return False
    return bool(getattr(scope, scope_flag, False))


def require_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = get_current_authenticated_user()
        if not user:
            return jsonify({
                "success": False,
                "authenticated": False,
                "message": "Authentication required. Please sign in with your institutional credentials.",
            }), 401
        return fn(*args, **kwargs)
    return wrapper


def require_roles(*allowed_roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_authenticated_user()
            if not user:
                return jsonify({
                    "success": False,
                    "authenticated": False,
                    "message": "Authentication required. Please sign in with your institutional credentials.",
                }), 401
            if user.role not in allowed_roles:
                return jsonify({
                    "success": False,
                    "message": f"Access Denied: Role '{user.role}' is not authorized to perform this action.",
                    "required_roles": list(allowed_roles),
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def require_module(module_name: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = get_current_authenticated_user()
            if not user:
                return jsonify({
                    "success": False,
                    "authenticated": False,
                    "message": "Authentication required. Please sign in with your institutional credentials.",
                }), 401
            allowed = get_allowed_modules_for_role(user.role)
            if module_name not in allowed:
                return jsonify({
                    "success": False,
                    "message": f"Access Denied: Module '{module_name}' is not accessible to role '{user.role}'.",
                    "required_module": module_name,
                }), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
