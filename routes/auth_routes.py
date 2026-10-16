from flask import Blueprint, request, jsonify, session
from database import db_session
from models import User, CourseEnrollment

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

# In-memory default active user tracker for session convenience
_CURRENT_USER_ID = 2  # Default to Prof. Alan Turing-Ward (Professor)

@auth_bp.route("/users", methods=["GET"])
def get_all_users():
    role_filter = request.args.get("role")
    query = db_session.query(User).filter(User.is_active == True)
    if role_filter:
        query = query.filter(User.role == role_filter)
    users = query.all()
    return jsonify({
        "success": True,
        "users": [u.to_dict() for u in users]
    })

@auth_bp.route("/current", methods=["GET"])
def get_current_user():
    global _CURRENT_USER_ID
    user = db_session.query(User).filter(User.id == _CURRENT_USER_ID).first()
    if not user:
        user = db_session.query(User).first()
        if user:
            _CURRENT_USER_ID = user.id

    if not user:
        return jsonify({"success": False, "message": "No users found"}), 404

    # Fetch enrolled courses
    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.user_id == user.id,
        CourseEnrollment.status == "active"
    ).all()

    user_dict = user.to_dict()
    user_dict["enrolled_courses"] = [
        {
            "course_id": e.course_id,
            "course_code": e.course.code,
            "course_title": e.course.title,
            "role_scope": e.role_scope
        } for e in enrollments if e.course
    ]

    return jsonify({
        "success": True,
        "user": user_dict
    })

@auth_bp.route("/switch-user", methods=["POST"])
def switch_user():
    global _CURRENT_USER_ID
    data = request.get_json() or {}
    user_id = data.get("user_id")
    if not user_id:
        return jsonify({"success": False, "message": "user_id is required"}), 400

    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    _CURRENT_USER_ID = user.id
    return jsonify({
        "success": True,
        "message": f"Active role switched to {user.name} ({user.role})",
        "user": user.to_dict()
    })

@auth_bp.route("/verify-institutional-identity", methods=["POST"])
def verify_identity():
    """Verify entrance gate compliance: student ID and institutional email format"""
    data = request.get_json() or {}
    institutional_id = data.get("institutional_id", "").strip()
    email = data.get("email", "").strip()

    user = db_session.query(User).filter(
        (User.institutional_id == institutional_id) | (User.email == email)
    ).first()

    if not user:
        return jsonify({
            "success": False,
            "verified": False,
            "reason": "Institutional ID or university email is not registered in the SIS directory."
        }), 403

    return jsonify({
        "success": True,
        "verified": True,
        "user": user.to_dict()
    })
