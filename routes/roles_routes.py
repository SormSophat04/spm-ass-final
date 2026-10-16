import datetime
import json
from flask import Blueprint, request, jsonify
from database import db_session
from models import (
    Course, User, CourseEnrollment, TAPermissionScope, AuditLog
)

roles_bp = Blueprint("roles", __name__, url_prefix="/api/roles")

# Academic Role Matrix Definition (Module 6)
ROLE_PERMISSIONS_MATRIX = {
    "Dean": {
        "description": "Highest institutional executive authority. Full oversight of all faculty courses, accreditation audits, and policy overrides.",
        "can_view_all_courses": True,
        "can_schedule_sessions": True,
        "can_override_attendance": True,
        "can_publish_grades": True,
        "can_manage_roles": True,
        "can_view_audit_trail": True,
        "can_seal_notes": True
    },
    "Professor": {
        "description": "Primary course authority with full gradebook management, attendance verification, and syllabus certification rights.",
        "can_view_all_courses": False,
        "can_schedule_sessions": True,
        "can_override_attendance": True,
        "can_publish_grades": True,
        "can_manage_roles": False,
        "can_view_audit_trail": True,
        "can_seal_notes": True
    },
    "Teaching Assistant": {
        "description": "Academic delegate. Permitted to verify attendance and co-edit lecture minutes; grade publishing restricted by institutional default.",
        "can_view_all_courses": False,
        "can_schedule_sessions": False,
        "can_override_attendance": True,
        "can_publish_grades": False,
        "can_manage_roles": False,
        "can_view_audit_trail": False,
        "can_seal_notes": False
    },
    "Student": {
        "description": "Enrolled learner. Access restricted strictly to enrolled course sections, personal attendance records, live quizzes, and study guides.",
        "can_view_all_courses": False,
        "can_schedule_sessions": False,
        "can_override_attendance": False,
        "can_publish_grades": False,
        "can_manage_roles": False,
        "can_view_audit_trail": False,
        "can_seal_notes": False
    },
    "Auditor": {
        "description": "Observer / Institutional QA inspector. Read-only access to syllabus materials and lecture archives; excluded from graded cohort curves.",
        "can_view_all_courses": False,
        "can_schedule_sessions": False,
        "can_override_attendance": False,
        "can_publish_grades": False,
        "can_manage_roles": False,
        "can_view_audit_trail": True,
        "can_seal_notes": False
    }
}

@roles_bp.route("/matrix", methods=["GET"])
def get_roles_matrix():
    """Module 6: Configure Academic Roles - Returns permission matrix for Dean, Professor, TA, Student, Auditor"""
    return jsonify({
        "success": True,
        "roles_matrix": ROLE_PERMISSIONS_MATRIX
    })

@roles_bp.route("/courses/<int:course_id>/authorities", methods=["GET"])
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

    return jsonify({
        "success": True,
        "course": course.to_dict(),
        "primary_instructor": course.primary_instructor.to_dict() if course.primary_instructor else None,
        "ta_scopes": [s.to_dict() for s in ta_scopes],
        "enrollments_count": len(enrollments)
    })

@roles_bp.route("/courses/<int:course_id>/assign-authority", methods=["PUT"])
def assign_course_authority(course_id):
    """Module 6: Assign Course Authority - Designates primary instructors with full override rights"""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json() or {}
    new_instructor_id = data.get("instructor_id")
    actor_id = data.get("actor_id", 1) # Dean

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
def update_ta_permission_scope(scope_id):
    """Module 6: Set TA Permission Scopes (Take attendance, co-edit notes, restrict grade publishing)"""
    scope = db_session.query(TAPermissionScope).filter(TAPermissionScope.id == scope_id).first()
    if not scope:
        return jsonify({"success": False, "message": "TA scope not found"}), 404

    data = request.get_json() or {}
    actor_id = data.get("actor_id", 2)
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
def revoke_course_access(enrollment_id):
    """Module 6: Revoke Course Access - Terminates access upon course drop or completion"""
    enrollment = db_session.query(CourseEnrollment).filter(CourseEnrollment.id == enrollment_id).first()
    if not enrollment:
        return jsonify({"success": False, "message": "Enrollment record not found"}), 404

    data = request.get_json() or {}
    reason = data.get("reason", "Official course withdrawal or semester completion.")
    actor_id = data.get("actor_id", 1) # Dean/Registrar

    now = datetime.datetime.utcnow()
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
        change_before=json.dumps({"status": "active"}),
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
