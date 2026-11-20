import datetime
import re
import secrets
from flask import Blueprint, g, jsonify, request
from sqlalchemy import func
from config import Config
from database import db_session
from email_service import EmailDeliveryError, get_email_delivery_status, send_otp_email
from models import AuditLog, Course, CourseEnrollment, EmailOTP, User
from security import (
    SESSION_COOKIE_NAME,
    TOKEN_TTL_SECONDS,
    build_user_auth_payload,
    create_access_token,
    generate_otp_code,
    hash_otp_code,
    hash_password,
    require_auth,
    require_roles,
    verify_otp_hash,
    verify_password,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+$")


def _normalize_valid_email(raw_email: str) -> str | None:
    email = (raw_email or "").strip().lower()
    if not email or len(email) > 128 or not _EMAIL_RE.match(email):
        return None
    return email


def _mask_email(email: str) -> str:
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        return f"{local[0]}***@{domain}"
    return f"{local[:2]}{'*' * min(6, max(2, len(local) - 2))}@{domain}"


def _derive_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0]
    parts = [p for p in re.split(r"[._\-+]+", local) if p]
    cleaned = " ".join(p.capitalize() if any(ch.isalpha() for ch in p) else p for p in parts).strip()
    return (cleaned or "University Student")[:120]


def _generate_student_institutional_id() -> str:
    existing_ids = [
        row[0]
        for row in db_session.query(User.institutional_id)
        .filter(User.institutional_id.like("STU-2026-%"))
        .all()
    ]
    max_seq = 200
    for item in existing_ids:
        suffix = item.rsplit("-", 1)[-1]
        if suffix.isdigit():
            max_seq = max(max_seq, int(suffix))
    seq = max_seq + 1
    while True:
        candidate = f"STU-2026-{seq:03d}"
        exists = db_session.query(User.id).filter(User.institutional_id == candidate).first()
        if not exists:
            return candidate
        seq += 1


def _attach_session_cookie(response, token: str):
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=TOKEN_TTL_SECONDS,
        httponly=True,
        samesite="Lax",
        path="/",
    )
    return response


@auth_bp.route("/otp/status", methods=["GET"])
def get_otp_status():
    """Public check reporting whether real email OTP delivery (SMTP or Resend) is configured."""
    status = get_email_delivery_status()
    return jsonify({
        "success": True,
        "configured": status["configured"],
        "provider": status["provider"],
        "expiry_minutes": status["expiry_minutes"],
        "resend_cooldown_seconds": status["resend_cooldown_seconds"],
        "otp_length": status["otp_length"],
    })


@auth_bp.route("/otp/request", methods=["POST"])
def request_email_otp():
    """Generate and deliver a real 6-digit login OTP to any valid email address."""
    data = request.get_json(silent=True) or {}
    email = _normalize_valid_email(data.get("email") or "")
    requested_name = (data.get("name") or "").strip()[:120]

    if not email:
        return jsonify({
            "success": False,
            "code": "invalid_email",
            "message": "Please enter a valid email address (for example, name@gmail.com).",
        }), 400

    existing_user = db_session.query(User).filter(func.lower(User.email) == email).first()
    if existing_user and not existing_user.is_active:
        return jsonify({
            "success": False,
            "code": "account_inactive",
            "message": "This institutional account has been deactivated. Please contact the Registrar or Dean.",
        }), 403

    status = get_email_delivery_status()
    otp_length = status["otp_length"]
    expiry_minutes = status["expiry_minutes"]
    cooldown_seconds = status["resend_cooldown_seconds"]
    max_attempts = Config.OTP_MAX_ATTEMPTS

    now = datetime.datetime.utcnow()
    latest_otp = (
        db_session.query(EmailOTP)
        .filter(EmailOTP.email == email, EmailOTP.purpose == "login")
        .order_by(EmailOTP.created_at.desc())
        .first()
    )
    if latest_otp and latest_otp.created_at:
        elapsed = (now - latest_otp.created_at).total_seconds()
        if elapsed < cooldown_seconds:
            retry_after = max(1, int(cooldown_seconds - elapsed + 0.999))
            return jsonify({
                "success": False,
                "code": "otp_cooldown",
                "retry_after_seconds": retry_after,
                "message": f"Please wait {retry_after}s before requesting another verification code.",
            }), 429

    otp_code = generate_otp_code(otp_length)
    recipient_display_name = existing_user.name if existing_user else (requested_name or None)

    try:
        delivery = send_otp_email(
            recipient_email=email,
            otp_code=otp_code,
            expiry_minutes=expiry_minutes,
            user_name=recipient_display_name,
        )
    except EmailDeliveryError as exc:
        http_status = 503 if exc.code == "email_not_configured" else 502
        return jsonify({
            "success": False,
            "code": exc.code,
            "message": exc.message,
        }), http_status

    # Invalidate previous unused OTPs for this email now that the new email has been delivered
    (
        db_session.query(EmailOTP)
        .filter(EmailOTP.email == email, EmailOTP.purpose == "login", EmailOTP.is_used == False)
        .update({"is_used": True})
    )

    otp_record = EmailOTP(
        email=email,
        code_hash=hash_otp_code(email, otp_code),
        purpose="login",
        attempts=0,
        max_attempts=max_attempts,
        is_used=False,
        expires_at=now + datetime.timedelta(minutes=expiry_minutes),
        created_at=now,
        ip_address=request.remote_addr or "127.0.0.1",
    )
    db_session.add(otp_record)

    audit = AuditLog(
        actor_id=existing_user.id if existing_user else None,
        actor_name=existing_user.name if existing_user else (requested_name or email),
        actor_role=existing_user.role if existing_user else "Prospective Student",
        event_type="otp_requested",
        target_entity="User",
        target_id=existing_user.id if existing_user else None,
        justification=f"Delivered {otp_length}-digit login OTP to {email} via {delivery['provider'].upper()}.",
        ip_address=request.remote_addr or "127.0.0.1",
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"A {otp_length}-digit verification code has been sent to {email}.",
        "email": email,
        "masked_email": _mask_email(email),
        "account_exists": bool(existing_user),
        "existing_role": existing_user.role if existing_user else None,
        "existing_name": existing_user.name if existing_user else None,
        "expires_in_seconds": expiry_minutes * 60,
        "resend_cooldown_seconds": cooldown_seconds,
        "provider": delivery["provider"],
    })


@auth_bp.route("/otp/verify", methods=["POST"])
def verify_email_otp():
    """Verify a 6-digit email OTP, auto-provision new real-email Students, and start an authenticated session."""
    data = request.get_json(silent=True) or {}
    email = _normalize_valid_email(data.get("email") or "")
    raw_otp = str(data.get("otp") or "")
    otp_clean = re.sub(r"[\s-]+", "", raw_otp)
    provided_name = (data.get("name") or "").strip()[:120]

    if not email:
        return jsonify({
            "success": False,
            "code": "invalid_email",
            "message": "A valid email address is required.",
        }), 400

    expected_len = get_email_delivery_status()["otp_length"]
    if not otp_clean.isdigit() or len(otp_clean) != expected_len:
        return jsonify({
            "success": False,
            "code": "invalid_otp_format",
            "message": f"Enter the {expected_len}-digit verification code sent to your email.",
        }), 400

    otp_record = (
        db_session.query(EmailOTP)
        .filter(
            EmailOTP.email == email,
            EmailOTP.purpose == "login",
            EmailOTP.is_used == False,
        )
        .order_by(EmailOTP.created_at.desc())
        .first()
    )

    if not otp_record:
        return jsonify({
            "success": False,
            "code": "otp_not_found",
            "message": "No active verification code was found for this email. Please request a new code.",
        }), 400

    now = datetime.datetime.utcnow()
    if now > otp_record.expires_at:
        otp_record.is_used = True
        db_session.commit()
        return jsonify({
            "success": False,
            "code": "otp_expired",
            "message": "This verification code has expired. Please request a new code.",
        }), 400

    if otp_record.attempts >= otp_record.max_attempts:
        otp_record.is_used = True
        db_session.commit()
        return jsonify({
            "success": False,
            "code": "otp_max_attempts",
            "attempts_remaining": 0,
            "message": "Too many incorrect attempts. Please request a fresh verification code.",
        }), 429

    if not verify_otp_hash(email, otp_clean, otp_record.code_hash):
        otp_record.attempts += 1
        remaining = max(0, otp_record.max_attempts - otp_record.attempts)
        if remaining == 0:
            otp_record.is_used = True
        db_session.commit()
        return jsonify({
            "success": False,
            "code": "otp_invalid" if remaining > 0 else "otp_max_attempts",
            "attempts_remaining": remaining,
            "message": (
                f"Incorrect verification code. {remaining} attempt(s) remaining."
                if remaining > 0
                else "Too many incorrect attempts. Please request a fresh verification code."
            ),
        }), (401 if remaining > 0 else 429)

    # Mark OTP consumed
    otp_record.is_used = True
    otp_record.used_at = now

    user = db_session.query(User).filter(func.lower(User.email) == email).first()
    is_new_user = False

    if user:
        if not user.is_active:
            db_session.commit()
            return jsonify({
                "success": False,
                "code": "account_inactive",
                "message": "This institutional account has been deactivated.",
            }), 403
        user.email_verified = True
    else:
        is_new_user = True
        display_name = provided_name or _derive_name_from_email(email)
        inst_id = _generate_student_institutional_id()
        user = User(
            institutional_id=inst_id,
            name=display_name,
            email=email,
            role="Student",
            department="Computer Science & Engineering",
            password_hash=hash_password(secrets.token_urlsafe(24)),
            email_verified=True,
            auth_source="email_otp",
            is_active=True,
        )
        db_session.add(user)
        db_session.flush()

        # Auto-enroll newly verified Student into active institutional courses so all modules are immediately usable
        active_courses = db_session.query(Course).all()
        for course in active_courses:
            db_session.add(CourseEnrollment(
                course_id=course.id,
                user_id=user.id,
                role_scope="student",
                status="active",
            ))

        provision_audit = AuditLog(
            actor_id=user.id,
            actor_name=user.name,
            actor_role=user.role,
            event_type="user_auto_provisioned",
            target_entity="User",
            target_id=user.id,
            justification=(
                f"Auto-provisioned Student account {inst_id} for verified email {email} "
                f"and enrolled in {len(active_courses)} active course(s)."
            ),
            ip_address=request.remote_addr or "127.0.0.1",
        )
        db_session.add(provision_audit)

    login_audit = AuditLog(
        actor_id=user.id,
        actor_name=user.name,
        actor_role=user.role,
        event_type="user_otp_login",
        target_entity="User",
        target_id=user.id,
        justification=f"Email OTP verified sign-in opened for {user.name} ({user.role}) via {email}.",
        ip_address=request.remote_addr or "127.0.0.1",
    )
    db_session.add(login_audit)
    db_session.commit()

    token = create_access_token(user.id, user.role)
    payload = build_user_auth_payload(user)

    resp = jsonify({
        "success": True,
        "message": (
            f"Email verified! Welcome {user.name} ({user.institutional_id})."
            if is_new_user
            else f"Email verified! Signed in as {user.name} ({user.role})."
        ),
        "token": token,
        "user": payload,
        "is_new_user": is_new_user,
    })
    return _attach_session_cookie(resp, token)


@auth_bp.route("/login", methods=["POST"])
def login():
    """Login-only endpoint verifying institutional email or ID + password."""
    data = request.get_json(silent=True) or {}
    identifier = (
        data.get("identifier")
        or data.get("email")
        or data.get("institutional_id")
        or ""
    ).strip()
    password = data.get("password") or ""

    if not identifier or not password:
        return jsonify({
            "success": False,
            "message": "Institutional email / ID and password are required.",
        }), 400

    ident_lower = identifier.lower()
    ident_upper = identifier.upper()
    user = db_session.query(User).filter(
        User.is_active == True,
        (func.lower(User.email) == ident_lower) | (func.upper(User.institutional_id) == ident_upper),
    ).first()

    if not user or not verify_password(user.password_hash, password):
        return jsonify({
            "success": False,
            "message": "Invalid institutional credentials. Please verify your ID/email and password.",
        }), 401

    token = create_access_token(user.id, user.role)
    payload = build_user_auth_payload(user)

    audit = AuditLog(
        actor_id=user.id,
        actor_name=user.name,
        actor_role=user.role,
        event_type="user_login",
        target_entity="User",
        target_id=user.id,
        justification=f"Authenticated session opened for {user.name} ({user.role}).",
        ip_address=request.remote_addr or "127.0.0.1",
    )
    db_session.add(audit)
    db_session.commit()

    resp = jsonify({
        "success": True,
        "message": f"Signed in as {user.name} ({user.role})",
        "token": token,
        "user": payload,
    })
    return _attach_session_cookie(resp, token)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    """Sign out and clear HTTP-only session cookie."""
    resp = jsonify({
        "success": True,
        "message": "Signed out cleanly.",
    })
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return resp


@auth_bp.route("/users", methods=["GET"])
@require_auth
def get_all_users():
    role_filter = request.args.get("role")
    query = db_session.query(User).filter(User.is_active == True)
    if role_filter:
        query = query.filter(User.role == role_filter)
    users = query.all()
    return jsonify({
        "success": True,
        "users": [u.to_dict() for u in users],
    })


@auth_bp.route("/demo-accounts", methods=["GET"])
def get_demo_accounts():
    """Public directory of provisioned institutional accounts for quick role testing on the login page."""
    from security import DEFAULT_DEMO_PASSWORD, get_allowed_modules_for_role
    users = (
        db_session.query(User)
        .filter(
            User.is_active == True,
            (User.auth_source == None) | (User.auth_source != "email_otp"),
        )
        .order_by(User.id.asc())
        .all()
    )
    accounts = []
    for u in users:
        mods = get_allowed_modules_for_role(u.role)
        accounts.append({
            "id": u.id,
            "role": u.role,
            "name": u.name,
            "institutional_id": u.institutional_id,
            "institutionalId": u.institutional_id,
            "email": u.email,
            "department": u.department,
            "modulesCount": len(mods),
            "allowed_modules": mods,
            "allowedModules": mods,
        })
    return jsonify({
        "success": True,
        "default_password": DEFAULT_DEMO_PASSWORD,
        "accounts": accounts,
    })


@auth_bp.route("/current", methods=["GET"])
@require_auth
def get_current_user():
    payload = build_user_auth_payload(g.current_user)
    return jsonify({
        "success": True,
        "authenticated": True,
        "user": payload,
    })


@auth_bp.route("/switch-user", methods=["POST"])
@require_roles("Dean")
def switch_user():
    """Dean-only impersonation / account switch with signed token reissue."""
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required"}), 400

    user = db_session.query(User).filter(User.id == user_id, User.is_active == True).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    token = create_access_token(user.id, user.role)
    payload = build_user_auth_payload(user)
    resp = jsonify({
        "success": True,
        "message": f"Active role switched to {user.name} ({user.role})",
        "token": token,
        "user": payload,
    })
    return _attach_session_cookie(resp, token)


@auth_bp.route("/verify-institutional-identity", methods=["POST"])
@require_auth
def verify_identity():
    """Verify entrance gate compliance: student ID and institutional email format."""
    data = request.get_json(silent=True) or {}
    institutional_id = (data.get("institutional_id") or "").strip()
    email = (data.get("email") or "").strip().lower()

    if not institutional_id and not email:
        return jsonify({
            "success": False,
            "verified": False,
            "reason": "Institutional ID or university email is required.",
        }), 400

    query = db_session.query(User)
    if institutional_id and email:
        user = query.filter(
            User.institutional_id == institutional_id,
            func.lower(User.email) == email,
        ).first()
    elif institutional_id:
        user = query.filter(User.institutional_id == institutional_id).first()
    else:
        user = query.filter(func.lower(User.email) == email).first()

    if not user:
        return jsonify({
            "success": False,
            "verified": False,
            "reason": "Institutional ID or university email is not registered in the SIS directory.",
        }), 403

    return jsonify({
        "success": True,
        "verified": True,
        "user": user.to_dict(),
    })
