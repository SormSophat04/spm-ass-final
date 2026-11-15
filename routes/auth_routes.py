from flask import Blueprint, g, jsonify, request
from sqlalchemy import func
from database import db_session
from models import AuditLog, User
from security import (
    SESSION_COOKIE_NAME,
    TOKEN_TTL_SECONDS,
    build_user_auth_payload,
    create_access_token,
    require_auth,
    require_roles,
    verify_password,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")


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
    users = db_session.query(User).filter(User.is_active == True).order_by(User.id.asc()).all()
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
