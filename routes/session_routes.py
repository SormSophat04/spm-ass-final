import datetime
import json
from flask import Blueprint, request, jsonify
from database import db_session
from models import (
    LectureSession, Course, SyllabusModule, SessionCoHost,
    RecurringTimetable, CourseEnrollment, User, AuditLog
)

session_bp = Blueprint("sessions", __name__, url_prefix="/api/sessions")

@session_bp.route("", methods=["GET"])
def get_sessions():
    course_id = request.args.get("course_id", type=int)
    status_filter = request.args.get("status")
    
    query = db_session.query(LectureSession)
    if course_id:
        query = query.filter(LectureSession.course_id == course_id)
    if status_filter:
        query = query.filter(LectureSession.status == status_filter)

    sessions = query.order_by(LectureSession.scheduled_start.desc()).all()
    return jsonify({
        "success": True,
        "count": len(sessions),
        "sessions": [s.to_dict() for s in sessions]
    })

@session_bp.route("/<int:session_id>", methods=["GET"])
def get_session_detail(session_id):
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    # Enrolled students for this course
    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == session.course_id,
        CourseEnrollment.status == "active"
    ).all()

    # Modules for this course
    modules = db_session.query(SyllabusModule).filter(
        SyllabusModule.course_id == session.course_id
    ).order_by(SyllabusModule.module_number).all()

    resp = session.to_dict()
    resp["course_modules"] = [m.to_dict() for m in modules]
    resp["enrolled_students"] = [
        {
            "user_id": e.user_id,
            "name": e.user.name,
            "institutional_id": e.user.institutional_id,
            "email": e.user.email,
            "role_scope": e.role_scope
        } for e in enrollments if e.user
    ]

    return jsonify({"success": True, "session": resp})

@session_bp.route("", methods=["POST"])
def schedule_session():
    """Module 1: Schedule Lecture Session mapped to syllabus modules"""
    data = request.get_json() or {}
    course_id = data.get("course_id")
    title = data.get("title")
    session_type = data.get("session_type", "Lecture")
    module_id = data.get("module_id")
    scheduled_start_str = data.get("scheduled_start")
    scheduled_end_str = data.get("scheduled_end")
    created_by_id = data.get("created_by_id", 2)
    room_security = data.get("room_security_config", {
        "restrict_to_enrolled": True,
        "require_institutional_email": True,
        "grace_period_mins": 10
    })

    if not course_id or not title or not scheduled_start_str or not scheduled_end_str:
        return jsonify({"success": False, "message": "Missing mandatory scheduling fields"}), 400

    try:
        scheduled_start = datetime.datetime.fromisoformat(scheduled_start_str.replace("Z", "+00:00")).replace(tzinfo=None)
        scheduled_end = datetime.datetime.fromisoformat(scheduled_end_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid datetime format: {str(e)}"}), 400

    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    # Generate room code e.g. GATE-CS401-4921
    code_suffix = int(datetime.datetime.utcnow().timestamp()) % 10000
    room_code = f"GATE-{course.code.replace(' ', '')}-{code_suffix}"

    new_session = LectureSession(
        course_id=course_id,
        module_id=module_id if module_id else None,
        title=title,
        session_type=session_type,
        scheduled_start=scheduled_start,
        scheduled_end=scheduled_end,
        status="scheduled",
        virtual_room_code=room_code,
        room_security_config=json.dumps(room_security),
        created_by_id=created_by_id
    )
    db_session.add(new_session)
    db_session.commit()

    # Log audit
    actor = db_session.query(User).filter(User.id == created_by_id).first()
    audit = AuditLog(
        actor_id=created_by_id,
        actor_name=actor.name if actor else "Faculty",
        actor_role=actor.role if actor else "Professor",
        event_type="schedule_lecture",
        target_entity="LectureSession",
        target_id=new_session.id,
        course_id=course_id,
        change_after=json.dumps({"title": title, "room_code": room_code}),
        justification=f"Scheduled new {session_type}: '{title}'"
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Lecture session successfully scheduled",
        "session": new_session.to_dict()
    }), 201

@session_bp.route("/<int:session_id>/security", methods=["PUT"])
def configure_room_security(session_id):
    """Module 1: Configure Academic Room Security"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json() or {}
    actor_id = data.get("actor_id", session.created_by_id)
    security_config = data.get("security_config", {})

    prev_config = session.room_security_config
    session.room_security_config = json.dumps(security_config)
    db_session.commit()

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Staff",
        actor_role=actor.role if actor else "Professor",
        event_type="configure_room_security",
        target_entity="LectureSession",
        target_id=session.id,
        course_id=session.course_id,
        change_before=prev_config,
        change_after=session.room_security_config,
        justification="Updated virtual gate security rules (enrolled whitelist & domain compliance)."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Academic room security updated",
        "room_security_config": security_config
    })

@session_bp.route("/<int:session_id>/start", methods=["POST"])
def start_session(session_id):
    """Module 1: Start Session - Launches virtual lecture room"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    now = datetime.datetime.utcnow()
    session.status = "in_progress"
    session.actual_start = now
    db_session.commit()

    audit = AuditLog(
        actor_id=session.created_by_id,
        actor_name=session.created_by.name if session.created_by else "Instructor",
        actor_role="Professor",
        event_type="session_start",
        target_entity="LectureSession",
        target_id=session.id,
        course_id=session.course_id,
        change_after=json.dumps({"actual_start": now.isoformat(), "status": "in_progress"}),
        justification=f"Virtual gate opened and session '{session.title}' commenced."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Virtual lecture room launched and session started",
        "session": session.to_dict()
    })

@session_bp.route("/<int:session_id>/end", methods=["POST"])
def end_session(session_id):
    """Module 1: End Session - Closes virtual room and finalizes student attendance duration"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    now = datetime.datetime.utcnow()
    session.status = "completed"
    session.actual_end = now
    
    # Calculate scheduled or actual duration
    session_start = session.actual_start or session.scheduled_start
    total_session_duration_mins = max(1.0, (now - session_start).total_seconds() / 60.0)

    # Reconcile unclosed attendance records
    for att in session.attendance_records:
        if att.first_join_time and not att.last_exit_time:
            att.last_exit_time = now
            attended_mins = (now - att.first_join_time).total_seconds() / 60.0
            att.total_duration_minutes = round(attended_mins, 1)
            coverage = min(100.0, (attended_mins / total_session_duration_mins) * 100.0)
            att.lecture_coverage_pct = round(coverage, 1)
            if att.lecture_coverage_pct >= 75.0 and not att.is_late:
                att.automated_status = "present"
            elif att.is_late:
                att.automated_status = "late"
            else:
                att.automated_status = "partial"

    db_session.commit()

    audit = AuditLog(
        actor_id=session.created_by_id,
        actor_name=session.created_by.name if session.created_by else "Instructor",
        actor_role="Professor",
        event_type="session_end",
        target_entity="LectureSession",
        target_id=session.id,
        course_id=session.course_id,
        change_after=json.dumps({"actual_end": now.isoformat(), "status": "completed"}),
        justification=f"Session '{session.title}' concluded; attendance metrics aggregated."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Session concluded successfully and attendance calculated",
        "session": session.to_dict()
    })

@session_bp.route("/<int:session_id>/co-hosts", methods=["POST"])
def assign_co_host(session_id):
    """Module 1: Assign Guest Lecturers/TAs as co-hosts"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json() or {}
    user_id = data.get("user_id")
    host_role = data.get("host_role", "teaching_assistant")

    user = db_session.query(User).filter(User.id == user_id).first()
    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    # Check existing
    existing = db_session.query(SessionCoHost).filter(
        SessionCoHost.session_id == session_id,
        SessionCoHost.user_id == user_id
    ).first()

    if existing:
        existing.host_role = host_role
    else:
        new_cohost = SessionCoHost(
            session_id=session_id,
            user_id=user_id,
            host_role=host_role
        )
        db_session.add(new_cohost)

    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Co-host privileges granted to {user.name} ({host_role})",
        "co_hosts": [ch.to_dict() for ch in session.co_hosts]
    })

@session_bp.route("/<int:session_id>/co-hosts/<int:host_user_id>", methods=["DELETE"])
def remove_co_host(session_id, host_user_id):
    cohost = db_session.query(SessionCoHost).filter(
        SessionCoHost.session_id == session_id,
        SessionCoHost.user_id == host_user_id
    ).first()

    if not cohost:
        return jsonify({"success": False, "message": "Co-host not found"}), 404

    db_session.delete(cohost)
    db_session.commit()
    return jsonify({"success": True, "message": "Co-host privilege revoked"})

@session_bp.route("/<int:session_id>/archive-recording", methods=["POST"])
def archive_recording(session_id):
    """Module 1: Archive Recorded Session linked to course module"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json() or {}
    recording_url = data.get("recording_url", "https://media.university.edu/archives/2026/session.mp4")
    duration_mins = data.get("recording_duration_mins", 90)
    recording_notes = data.get("recording_notes", "Synchronized transcript and video recording.")

    session.recording_url = recording_url
    session.recording_duration_mins = duration_mins
    session.recording_notes = recording_notes
    session.recording_status = "archived"
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Lecture recording successfully archived for asynchronous study",
        "session": session.to_dict()
    })

@session_bp.route("/courses/<int:course_id>/recurring-timetable", methods=["POST"])
def set_recurring_timetable(course_id):
    """Module 1: Set Recurring Timetable (e.g. MWF blocks) and optionally batch schedule sessions"""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json() or {}
    day_of_week = data.get("day_of_week") # e.g. "Monday"
    start_time = data.get("start_time")   # "10:00"
    end_time = data.get("end_time")       # "11:30"
    room_or_gate = data.get("room_or_gate", "Main Auditorium & Virtual Gate")

    if not day_of_week or not start_time or not end_time:
        return jsonify({"success": False, "message": "day_of_week, start_time, and end_time are required"}), 400

    new_tt = RecurringTimetable(
        course_id=course_id,
        day_of_week=day_of_week,
        start_time=start_time,
        end_time=end_time,
        room_or_gate=room_or_gate,
        is_active=True
    )
    db_session.add(new_tt)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Recurring timetable block established for {day_of_week} {start_time}-{end_time}",
        "timetable": new_tt.to_dict()
    }), 201

@session_bp.route("/courses/<int:course_id>/recurring-timetables", methods=["GET"])
def get_course_timetables(course_id):
    timetables = db_session.query(RecurringTimetable).filter(
        RecurringTimetable.course_id == course_id,
        RecurringTimetable.is_active == True
    ).all()
    return jsonify({
        "success": True,
        "timetables": [t.to_dict() for t in timetables]
    })
