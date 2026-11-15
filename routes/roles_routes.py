import datetime
import json
from flask import Blueprint, g, request, jsonify
from database import db_session
from models import (
    Course, User, CourseEnrollment, TAPermissionScope, AuditLog
)
from security import DEFAULT_DEMO_PASSWORD, ROLE_PERMISSIONS_MATRIX, hash_password, require_auth, require_roles

roles_bp = Blueprint("roles", __name__, url_prefix="/api/roles")

@roles_bp.route("/matrix", methods=["GET"])
@require_auth
def get_roles_matrix():
    """Module 6: Configure Academic Roles - Returns permission matrix for Dean, Professor, TA, Student, Auditor"""
    return jsonify({
        "success": True,
        "roles_matrix": ROLE_PERMISSIONS_MATRIX
    })

@roles_bp.route("/courses/<int:course_id>/authorities", methods=["GET"])
@require_roles("Dean")
def get_course_authorities(course_id):
    """Module 6: Get primary instructor, TAs, and assigned permission scopes"""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    ta_scopes = db_session.query(TAPermissionScope).filter(
        TAPermissionScope.course_id == course_id
    ).all()

    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == course_id
    ).all()

    instructor_enrollments = [
        e.to_dict() for e in enrollments if e.role_scope == "instructor" and e.status == "active"
    ]
    if course.primary_instructor and not any(
        i.get("user_id") == course.primary_instructor_id for i in instructor_enrollments
    ):
        instructor_enrollments.insert(0, {
            "id": 0,
            "user_id": course.primary_instructor.id,
            "user_name": course.primary_instructor.name,
            "institutional_id": course.primary_instructor.institutional_id,
            "role_scope": "instructor",
        })

    return jsonify({
        "success": True,
        "course_id": course.id,
        "course_code": course.code,
        "course_title": course.title,
        "course": course.to_dict(),
        "primary_instructor": course.primary_instructor.to_dict() if course.primary_instructor else None,
        "instructors": instructor_enrollments,
        "ta_scopes": [s.to_dict() for s in ta_scopes],
        "enrollments_count": len(enrollments)
    })

@roles_bp.route("/courses/<int:course_id>/assign-authority", methods=["PUT"])
@require_roles("Dean")
def assign_course_authority(course_id):
    """Module 6: Assign Course Authority - Designates primary instructors with full override rights"""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json(silent=True) or {}
    new_instructor_id = data.get("instructor_id")
    actor_id = g.current_user.id

    if not new_instructor_id:
        return jsonify({"success": False, "message": "instructor_id is required"}), 400

    new_inst = db_session.query(User).filter(User.id == new_instructor_id).first()
    if not new_inst:
        return jsonify({"success": False, "message": "Instructor not found"}), 404

    prev_inst_id = course.primary_instructor_id
    course.primary_instructor_id = new_inst.id
    db_session.commit()

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Dean",
        actor_role=actor.role if actor else "Dean",
        event_type="authority_assigned",
        target_entity="Course",
        target_id=course.id,
        course_id=course.id,
        change_before=json.dumps({"primary_instructor_id": prev_inst_id}),
        change_after=json.dumps({"primary_instructor_id": new_inst.id, "instructor_name": new_inst.name}),
        justification=f"Designated {new_inst.name} as Primary Course Authority with full gradebook and attendance override rights."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Primary course authority assigned to {new_inst.name}",
        "course": course.to_dict()
    })

@roles_bp.route("/ta-scopes/<int:scope_id>", methods=["PUT"])
@require_roles("Dean")
def update_ta_permission_scope(scope_id):
    """Module 6: Set TA Permission Scopes (Take attendance, co-edit notes, restrict grade publishing)"""
    scope = db_session.query(TAPermissionScope).filter(TAPermissionScope.id == scope_id).first()
    if not scope:
        return jsonify({"success": False, "message": "TA scope not found"}), 404

    data = request.get_json(silent=True) or {}
    actor_id = g.current_user.id
    can_take_attendance = data.get("can_take_attendance", scope.can_take_attendance)
    can_coedit_notes = data.get("can_coedit_notes", scope.can_coedit_notes)
    can_launch_polls = data.get("can_launch_polls", scope.can_launch_polls)
    can_publish_grades = data.get("can_publish_grades", scope.can_publish_grades)

    prev_state = {
        "can_take_attendance": scope.can_take_attendance,
        "can_coedit_notes": scope.can_coedit_notes,
        "can_launch_polls": scope.can_launch_polls,
        "can_publish_grades": scope.can_publish_grades
    }

    scope.can_take_attendance = can_take_attendance
    scope.can_coedit_notes = can_coedit_notes
    scope.can_launch_polls = can_launch_polls
    scope.can_publish_grades = can_publish_grades
    db_session.commit()

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Professor",
        actor_role=actor.role if actor else "Professor",
        event_type="ta_scope_modified",
        target_entity="TAPermissionScope",
        target_id=scope.id,
        course_id=scope.course_id,
        change_before=json.dumps(prev_state),
        change_after=json.dumps(scope.to_dict()),
        justification="Calibrated Teaching Assistant privilege scopes."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "TA permission scopes successfully updated",
        "scope": scope.to_dict()
    })

@roles_bp.route("/courses/<int:course_id>/enrollments", methods=["GET"])
@require_roles("Dean")
def get_course_enrollments(course_id):
    """Module 6: Manage Student Enrolment Scopes"""
    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == course_id
    ).all()
    return jsonify({
        "success": True,
        "enrollments": [e.to_dict() for e in enrollments]
    })

@roles_bp.route("/enrollments/<int:enrollment_id>/revoke", methods=["POST"])
@require_roles("Dean")
def revoke_course_access(enrollment_id):
    """Module 6: Revoke Course Access - Terminates access upon course drop or completion"""
    enrollment = db_session.query(CourseEnrollment).filter(CourseEnrollment.id == enrollment_id).first()
    if not enrollment:
        return jsonify({"success": False, "message": "Enrollment record not found"}), 404

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "").strip() or "Official course withdrawal or semester completion."
    actor_id = g.current_user.id

    now = datetime.datetime.utcnow()
    prev_status = enrollment.status
    enrollment.status = "revoked"
    enrollment.revoked_at = now
    enrollment.revocation_reason = reason
    db_session.commit()

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Registrar",
        actor_role=actor.role if actor else "Dean",
        event_type="access_revoked",
        target_entity="CourseEnrollment",
        target_id=enrollment.id,
        course_id=enrollment.course_id,
        change_before=json.dumps({"status": prev_status}),
        change_after=json.dumps({"status": "revoked", "reason": reason}),
        justification=f"Terminated course access for {enrollment.user.name if enrollment.user else 'Student'}: {reason}"
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Course access revoked successfully and logged in institutional audit trail.",
        "enrollment": enrollment.to_dict()
    })


@roles_bp.route("/enrollments/<int:enrollment_id>/restore", methods=["POST"])
@require_roles("Dean", "Professor")
def restore_course_access(enrollment_id):
    """Restore a previously revoked or dropped course enrollment back to active status."""
    enrollment = db_session.query(CourseEnrollment).filter(CourseEnrollment.id == enrollment_id).first()
    if not enrollment:
        return jsonify({"success": False, "message": "Enrollment record not found"}), 404

    prev_status = enrollment.status
    enrollment.status = "active"
    enrollment.revoked_at = None
    enrollment.revocation_reason = None

    actor = g.current_user
    audit = AuditLog(
        actor_id=actor.id,
        actor_name=actor.name,
        actor_role=actor.role,
        event_type="access_restored",
        target_entity="CourseEnrollment",
        target_id=enrollment.id,
        course_id=enrollment.course_id,
        change_before=json.dumps({"status": prev_status}),
        change_after=json.dumps({"status": "active"}),
        justification=f"Reinstated course access for {enrollment.user.name if enrollment.user else 'User'}."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Course enrollment access restored to active.",
        "enrollment": enrollment.to_dict()
    })


@roles_bp.route("/courses/<int:course_id>/enroll", methods=["POST"])
@require_roles("Dean", "Professor")
def enroll_user_in_course(course_id):
    """Enroll an existing user in a course with a specific role_scope (student, ta, auditor, co_instructor)."""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    role_scope = data.get("role_scope", "student")

    if not user_id:
        return jsonify({"success": False, "message": "user_id is required"}), 400

    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    existing = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == course_id,
        CourseEnrollment.user_id == user_id
    ).first()

    if existing:
        existing.role_scope = role_scope
        existing.status = "active"
        existing.revoked_at = None
        existing.revocation_reason = None
        enr = existing
    else:
        enr = CourseEnrollment(
            course_id=course_id,
            user_id=user_id,
            role_scope=role_scope,
            status="active"
        )
        db_session.add(enr)

    if role_scope == "ta":
        existing_scope = db_session.query(TAPermissionScope).filter(
            TAPermissionScope.course_id == course_id,
            TAPermissionScope.ta_id == user_id
        ).first()
        if not existing_scope:
            db_session.add(TAPermissionScope(
                course_id=course_id,
                ta_id=user_id,
                can_take_attendance=True,
                can_coedit_notes=True,
                can_launch_polls=True,
                can_publish_grades=False
            ))

    audit = AuditLog(
        actor_id=g.current_user.id,
        actor_name=g.current_user.name,
        actor_role=g.current_user.role,
        event_type="roster_enrollment",
        target_entity="CourseEnrollment",
        course_id=course_id,
        change_after=json.dumps({"user_id": user_id, "user_name": user.name, "role_scope": role_scope}),
        justification=f"Enrolled {user.name} into {course.code} with scope '{role_scope}'."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Enrolled {user.name} in {course.code} as {role_scope}",
        "enrollment": enr.to_dict()
    }), 201


@roles_bp.route("/courses/<int:course_id>/ta-scopes", methods=["POST"])
@require_roles("Dean", "Professor")
def assign_ta_to_course(course_id):
    """Assign a Teaching Assistant to a course and initialize or update their permission scope."""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json(silent=True) or {}
    ta_id = data.get("ta_id")
    if not ta_id:
        return jsonify({"success": False, "message": "ta_id is required"}), 400

    ta_user = db_session.query(User).filter(User.id == ta_id).first()
    if not ta_user:
        return jsonify({"success": False, "message": "TA user not found"}), 404

    scope = db_session.query(TAPermissionScope).filter(
        TAPermissionScope.course_id == course_id,
        TAPermissionScope.ta_id == ta_id
    ).first()

    if scope:
        scope.can_take_attendance = bool(data.get("can_take_attendance", True))
        scope.can_coedit_notes = bool(data.get("can_coedit_notes", True))
        scope.can_launch_polls = bool(data.get("can_launch_polls", True))
        scope.can_publish_grades = bool(data.get("can_publish_grades", False))
    else:
        scope = TAPermissionScope(
            course_id=course_id,
            ta_id=ta_id,
            can_take_attendance=bool(data.get("can_take_attendance", True)),
            can_coedit_notes=bool(data.get("can_coedit_notes", True)),
            can_launch_polls=bool(data.get("can_launch_polls", True)),
            can_publish_grades=bool(data.get("can_publish_grades", False))
        )
        db_session.add(scope)

    # Ensure active TA enrollment exists
    enr = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == course_id,
        CourseEnrollment.user_id == ta_id
    ).first()
    if not enr:
        db_session.add(CourseEnrollment(
            course_id=course_id,
            user_id=ta_id,
            role_scope="ta",
            status="active"
        ))
    else:
        enr.status = "active"
        enr.role_scope = "ta"

    db_session.flush()
    audit = AuditLog(
        actor_id=g.current_user.id,
        actor_name=g.current_user.name,
        actor_role=g.current_user.role,
        event_type="ta_scope_assigned",
        target_entity="TAPermissionScope",
        target_id=scope.id,
        course_id=course_id,
        change_after=json.dumps(scope.to_dict()),
        justification=f"Delegated TA permission scopes to {ta_user.name} for {course.code}."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Assigned TA {ta_user.name} to {course.code}",
        "scope": scope.to_dict()
    }), 201


@roles_bp.route("/ta-scopes/<int:scope_id>", methods=["DELETE"])
@require_roles("Dean", "Professor")
def remove_ta_scope(scope_id):
    scope = db_session.query(TAPermissionScope).filter(TAPermissionScope.id == scope_id).first()
    if not scope:
        return jsonify({"success": False, "message": "TA scope not found"}), 404
    db_session.delete(scope)
    db_session.commit()
    return jsonify({"success": True, "message": "TA scope removed"})


@roles_bp.route("/users", methods=["POST"])
@require_roles("Dean")
def provision_institutional_user():
    """Provision a new institutional account (Dean, Professor, Teaching Assistant, Student, Auditor)."""
    data = request.get_json(silent=True) or {}
    institutional_id = (data.get("institutional_id") or "").strip().upper()
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    role = (data.get("role") or "Student").strip()
    department = (data.get("department") or "Computer Science & Engineering").strip()
    password = (data.get("password") or DEFAULT_DEMO_PASSWORD).strip()

    if not institutional_id or not name or not email:
        return jsonify({"success": False, "message": "Institutional ID, name, and email are required"}), 400
    if role not in ROLE_PERMISSIONS_MATRIX:
        return jsonify({"success": False, "message": f"Invalid academic role '{role}'"}), 400

    existing = db_session.query(User).filter(
        (User.institutional_id == institutional_id) | (User.email == email)
    ).first()
    if existing:
        return jsonify({"success": False, "message": "User with this Institutional ID or Email already exists"}), 400

    new_user = User(
        institutional_id=institutional_id,
        name=name,
        email=email,
        role=role,
        department=department,
        password_hash=hash_password(password),
        is_active=True
    )
    db_session.add(new_user)
    db_session.flush()

    audit = AuditLog(
        actor_id=g.current_user.id,
        actor_name=g.current_user.name,
        actor_role=g.current_user.role,
        event_type="user_provisioned",
        target_entity="User",
        target_id=new_user.id,
        change_after=json.dumps({"institutional_id": institutional_id, "name": name, "role": role}),
        justification=f"Provisioned new institutional identity {institutional_id} ({name}) with role '{role}'."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Provisioned institutional account for {name} ({role})",
        "user": new_user.to_dict()
    }), 201


@roles_bp.route("/users/<int:user_id>/role", methods=["PUT"])
@require_roles("Dean")
def update_user_role(user_id):
    """Update a user's institutional role tier."""
    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    data = request.get_json(silent=True) or {}
    new_role = (data.get("role") or "").strip()
    if new_role not in ROLE_PERMISSIONS_MATRIX:
        return jsonify({"success": False, "message": f"Invalid role '{new_role}'"}), 400

    prev_role = user.role
    user.role = new_role

    audit = AuditLog(
        actor_id=g.current_user.id,
        actor_name=g.current_user.name,
        actor_role=g.current_user.role,
        event_type="role_permission_update",
        target_entity="User",
        target_id=user.id,
        change_before=json.dumps({"role": prev_role}),
        change_after=json.dumps({"role": new_role}),
        justification=f"Updated academic role for {user.name} ({user.institutional_id}) from {prev_role} to {new_role}."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Role for {user.name} updated to {new_role}",
        "user": user.to_dict()
    })
