import datetime
import json
import secrets
from flask import Blueprint, g, request, jsonify
from database import db_session
from models import (
    LectureSession, Course, SyllabusModule, SessionCoHost,
    RecurringTimetable, CourseEnrollment, User, AuditLog
)
from security import require_auth, require_module, require_roles

session_bp = Blueprint("sessions", __name__, url_prefix="/api/sessions")


@session_bp.route("/courses", methods=["GET"])
@require_auth
def get_courses():
    """Return courses accessible to the current user, including syllabus modules and timetables."""
    user = g.current_user
    query = db_session.query(Course)
    if user.role in ("Student", "Teaching Assistant") and request.args.get("all") != "true":
        enrolled_course_ids = [
            e.course_id for e in db_session.query(CourseEnrollment).filter(
                CourseEnrollment.user_id == user.id,
                CourseEnrollment.status == "active"
            ).all()
        ]
        if not enrolled_course_ids:
            return jsonify({"success": True, "count": 0, "courses": []})
        query = query.filter(Course.id.in_(enrolled_course_ids))

    courses = query.order_by(Course.id.asc()).all()
    out = []
    for c in courses:
        d = c.to_dict()
        d["modules"] = [m.to_dict() for m in c.modules]
        d["timetables"] = [t.to_dict() for t in c.recurring_timetables if t.is_active]
        out.append(d)

    return jsonify({
        "success": True,
        "count": len(out),
        "courses": out
    })


@session_bp.route("/courses", methods=["POST"])
@require_roles("Dean", "Professor")
def create_course():
    """Dynamically create a new institutional course and initial syllabus module."""
    data = request.get_json(silent=True) or {}
    code = (data.get("code") or "").strip().upper()
    title = (data.get("title") or "").strip()
    department = (data.get("department") or g.current_user.department or "Computer Science & Engineering").strip()
    term = (data.get("term") or "Fall 2026").strip()
    credits = int(data.get("credits") or 4)
    room_security_level = data.get("room_security_level") or "enrolled_only"
    syllabus_overview = (data.get("syllabus_overview") or "").strip()
    primary_instructor_id = data.get("primary_instructor_id") or g.current_user.id

    if not code or not title:
        return jsonify({"success": False, "message": "Course code and title are required"}), 400

    existing = db_session.query(Course).filter(Course.code == code).first()
    if existing:
        return jsonify({"success": False, "message": f"Course code '{code}' already exists"}), 400

    course = Course(
        code=code,
        title=title,
        department=department,
        term=term,
        credits=credits,
        primary_instructor_id=primary_instructor_id,
        room_security_level=room_security_level,
        syllabus_overview=syllabus_overview
    )
    db_session.add(course)
    db_session.flush()

    # Enroll primary instructor as co_instructor
    enr = CourseEnrollment(
        course_id=course.id,
        user_id=primary_instructor_id,
        role_scope="co_instructor",
        status="active"
    )
    db_session.add(enr)

    # Create default Module 1 if none provided
    init_module_title = (data.get("initial_module_title") or "Foundations & Core Principles").strip()
    mod = SyllabusModule(
        course_id=course.id,
        module_number=1,
        title=init_module_title,
        description=syllabus_overview or f"Core syllabus module for {code}.",
        learning_objectives="Master core concepts and analytical frameworks."
    )
    db_session.add(mod)

    audit = AuditLog(
        actor_id=g.current_user.id,
        actor_name=g.current_user.name,
        actor_role=g.current_user.role,
        event_type="course_created",
        target_entity="Course",
        target_id=course.id,
        course_id=course.id,
        change_after=json.dumps({"code": code, "title": title}),
        justification=f"Created new academic course {code}: {title}"
    )
    db_session.add(audit)
    db_session.commit()

    d = course.to_dict()
    d["modules"] = [m.to_dict() for m in course.modules]
    d["timetables"] = []
    return jsonify({
        "success": True,
        "message": f"Course {code} created successfully",
        "course": d
    }), 201


@session_bp.route("/courses/<int:course_id>/modules", methods=["GET"])
@require_auth
def get_course_modules(course_id):
    modules = db_session.query(SyllabusModule).filter(
        SyllabusModule.course_id == course_id
    ).order_by(SyllabusModule.module_number.asc()).all()
    return jsonify({
        "success": True,
        "modules": [m.to_dict() for m in modules]
    })


@session_bp.route("/courses/<int:course_id>/modules", methods=["POST"])
@require_roles("Dean", "Professor")
def create_course_module(course_id):
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"success": False, "message": "Module title is required"}), 400

    existing_count = db_session.query(SyllabusModule).filter(SyllabusModule.course_id == course_id).count()
    module_number = int(data.get("module_number") or (existing_count + 1))
    description = (data.get("description") or "").strip()
    learning_objectives = (data.get("learning_objectives") or "").strip()

    mod = SyllabusModule(
        course_id=course_id,
        module_number=module_number,
        title=title,
        description=description,
        learning_objectives=learning_objectives
    )
    db_session.add(mod)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Module {module_number} added to {course.code}",
        "module": mod.to_dict()
    }), 201

@session_bp.route("", methods=["GET"])
@require_module("lifecycle")
def get_sessions():
    course_id = request.args.get("course_id", type=int)
    status_filter = request.args.get("status")
    
    query = db_session.query(LectureSession)
    user = g.current_user
    if user.role in ("Student", "Teaching Assistant"):
        enrolled_course_ids = [
            e.course_id for e in db_session.query(CourseEnrollment).filter(
                CourseEnrollment.user_id == user.id,
                CourseEnrollment.status == "active"
            ).all()
        ]
        if not enrolled_course_ids:
            return jsonify({"success": True, "count": 0, "sessions": []})
        query = query.filter(LectureSession.course_id.in_(enrolled_course_ids))

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
@require_module("lifecycle")
def get_session_detail(session_id):
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    user = g.current_user
    if user.role in ("Student", "Teaching Assistant"):
        enr = db_session.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == session.course_id,
            CourseEnrollment.user_id == user.id,
            CourseEnrollment.status == "active"
        ).first()
        if not enr:
            return jsonify({"success": False, "message": "Access Denied: Not enrolled in this course"}), 403

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
@require_roles("Dean", "Professor")
def schedule_session():
    """Module 1: Schedule Lecture Session mapped to syllabus modules"""
    data = request.get_json(silent=True) or {}
    course_id = data.get("course_id")
    title = (data.get("title") or "").strip()
    session_type = data.get("session_type", "Lecture")
    module_id = data.get("module_id")
    scheduled_start_str = data.get("scheduled_start")
    scheduled_end_str = data.get("scheduled_end")
    created_by_id = g.current_user.id
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

    if scheduled_end <= scheduled_start:
        return jsonify({"success": False, "message": "Scheduled end time must be after scheduled start time"}), 400

    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    resolved_module_id = None
    if module_id:
        module = db_session.query(SyllabusModule).filter(SyllabusModule.id == module_id).first()
        if not module:
            return jsonify({"success": False, "message": "Syllabus module not found"}), 404
        resolved_module_id = module.id

    actor = db_session.query(User).filter(User.id == created_by_id).first()
    if not actor:
        actor = db_session.query(User).filter(User.id == course.primary_instructor_id).first()
        created_by_id = actor.id if actor else created_by_id

    # Generate guaranteed-unique room code e.g. GATE-CS401-4921
    clean_code = course.code.replace(" ", "")
    room_code = None
    for _ in range(10):
        code_suffix = f"{int(datetime.datetime.utcnow().timestamp()) % 10000:04d}-{secrets.randbelow(900) + 100}"
        candidate = f"GATE-{clean_code}-{code_suffix}"
        if not db_session.query(LectureSession).filter(LectureSession.virtual_room_code == candidate).first():
            room_code = candidate
            break
    if not room_code:
        room_code = f"GATE-{clean_code}-{secrets.token_hex(4).upper()}"

    new_session = LectureSession(
        course_id=course_id,
        module_id=resolved_module_id,
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
@require_roles("Dean", "Professor")
def configure_room_security(session_id):
    """Module 1: Configure Academic Room Security"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    actor_id = g.current_user.id
    if isinstance(data.get("security_config"), dict):
        security_config = data["security_config"]
    elif isinstance(data.get("room_security_config"), dict):
        security_config = data["room_security_config"]
    else:
        existing_cfg = {}
        if session.room_security_config:
            try:
                existing_cfg = json.loads(session.room_security_config)
            except Exception:
                existing_cfg = {}
        security_config = {
            **existing_cfg,
            **{k: data[k] for k in ("restrict_to_enrolled", "require_institutional_email", "grace_period_mins", "lock_gate") if k in data},
        }

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
@require_roles("Dean", "Professor")
def start_session(session_id):
    """Module 1: Start Session - Launches virtual lecture room"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    if session.status == "cancelled":
        return jsonify({"success": False, "message": "Cannot start a cancelled session"}), 400

    now = datetime.datetime.utcnow()
    session.status = "in_progress"
    session.actual_start = now
    db_session.commit()

    actor = g.current_user
    audit = AuditLog(
        actor_id=actor.id,
        actor_name=actor.name,
        actor_role=actor.role,
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
@require_roles("Dean", "Professor")
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
            attended_mins = max(0.0, (now - att.first_join_time).total_seconds() / 60.0)
            att.total_duration_minutes = round(attended_mins, 1)
            coverage = min(100.0, (attended_mins / total_session_duration_mins) * 100.0)
            att.lecture_coverage_pct = round(coverage, 1)
            if att.lecture_coverage_pct >= 75.0 and not att.is_late:
                att.automated_status = "present"
            elif att.is_late:
                att.automated_status = "late"
            else:
                att.automated_status = "partial"
            att.registrar_compliance_flag = (att.lecture_coverage_pct >= 75.0) or (att.verified_status == "excused")

    db_session.commit()

    actor = g.current_user
    audit = AuditLog(
        actor_id=actor.id,
        actor_name=actor.name,
        actor_role=actor.role,
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
@require_roles("Dean", "Professor")
def assign_co_host(session_id):
    """Module 1: Assign Guest Lecturers/TAs as co-hosts"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    host_role = data.get("host_role", "teaching_assistant")

    if not user_id:
        return jsonify({"success": False, "message": "user_id is required"}), 400

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
@require_roles("Dean", "Professor")
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
@require_roles("Dean", "Professor")
def archive_recording(session_id):
    """Module 1: Archive Recorded Session linked to course module"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
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
@require_roles("Dean", "Professor")
def set_recurring_timetable(course_id):
    """Module 1: Set Recurring Timetable (e.g. MWF blocks) and optionally batch schedule sessions"""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    data = request.get_json(silent=True) or {}
    day_of_week = (data.get("day_of_week") or "").strip() # e.g. "Monday"
    start_time = (data.get("start_time") or "").strip()   # "10:00"
    end_time = (data.get("end_time") or "").strip()       # "11:30"
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
@require_module("lifecycle")
def get_course_timetables(course_id):
    timetables = db_session.query(RecurringTimetable).filter(
        RecurringTimetable.course_id == course_id,
        RecurringTimetable.is_active == True
    ).all()
    return jsonify({
        "success": True,
        "timetables": [t.to_dict() for t in timetables]
    })


@session_bp.route("/recurring-timetables/<int:timetable_id>", methods=["DELETE"])
@require_roles("Dean", "Professor")
def delete_recurring_timetable(timetable_id):
    tt = db_session.query(RecurringTimetable).filter(RecurringTimetable.id == timetable_id).first()
    if not tt:
        return jsonify({"success": False, "message": "Timetable block not found"}), 404
    db_session.delete(tt)
    db_session.commit()
    return jsonify({"success": True, "message": "Recurring timetable block removed"})


@session_bp.route("/courses/<int:course_id>/generate-from-timetable", methods=["POST"])
@require_roles("Dean", "Professor")
def generate_sessions_from_timetable(course_id):
    """Project active recurring timetable blocks into upcoming scheduled lecture sessions."""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    timetables = db_session.query(RecurringTimetable).filter(
        RecurringTimetable.course_id == course_id,
        RecurringTimetable.is_active == True
    ).all()
    if not timetables:
        return jsonify({"success": False, "message": "No active recurring timetable blocks for this course"}), 400

    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2,
        "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6
    }

    now = datetime.datetime.utcnow()
    first_module = course.modules[0] if course.modules else None
    existing_count = db_session.query(LectureSession).filter(LectureSession.course_id == course_id).count()
    created_sessions = []

    for idx, tt in enumerate(timetables, start=1):
        target_wd = weekday_map.get((tt.day_of_week or "").strip().lower(), 0)
        days_ahead = (target_wd - now.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        next_date = (now + datetime.timedelta(days=days_ahead)).date()

        try:
            sh, sm = [int(x) for x in tt.start_time.split(":")[:2]]
            eh, em = [int(x) for x in tt.end_time.split(":")[:2]]
        except Exception:
            sh, sm, eh, em = 10, 0, 11, 30

        sched_start = datetime.datetime.combine(next_date, datetime.time(sh, sm))
        sched_end = datetime.datetime.combine(next_date, datetime.time(eh, em))
        if sched_end <= sched_start:
            sched_end = sched_start + datetime.timedelta(minutes=90)

        clean_code = course.code.replace(" ", "")
        room_code = f"GATE-{clean_code}-{secrets.token_hex(3).upper()}"
        sess_num = existing_count + idx
        new_sess = LectureSession(
            course_id=course_id,
            module_id=first_module.id if first_module else None,
            title=f"Session {sess_num:02d}: {course.code} {tt.day_of_week} Block ({tt.room_or_gate})",
            session_type="Lecture",
            scheduled_start=sched_start,
            scheduled_end=sched_end,
            status="scheduled",
            virtual_room_code=room_code,
            room_security_config=json.dumps({
                "restrict_to_enrolled": course.room_security_level == "enrolled_only",
                "require_institutional_email": True,
                "grace_period_mins": 10
            }),
            created_by_id=g.current_user.id
        )
        db_session.add(new_sess)
        created_sessions.append(new_sess)

    db_session.commit()
    return jsonify({
        "success": True,
        "message": f"Projected {len(created_sessions)} upcoming lecture sessions from recurring timetable.",
        "sessions": [s.to_dict() for s in created_sessions]
    }), 201


@session_bp.route("/<int:session_id>", methods=["DELETE"])
@require_roles("Dean", "Professor")
def delete_session(session_id):
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404
    title = session.title
    course_id = session.course_id
    db_session.delete(session)
    audit = AuditLog(
        actor_id=g.current_user.id,
        actor_name=g.current_user.name,
        actor_role=g.current_user.role,
        event_type="session_deleted",
        target_entity="LectureSession",
        target_id=session_id,
        course_id=course_id,
        justification=f"Removed scheduled session '{title}'."
    )
    db_session.add(audit)
    db_session.commit()
    return jsonify({"success": True, "message": f"Session '{title}' removed"})
