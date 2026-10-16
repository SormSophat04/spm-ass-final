import datetime
import json
from flask import Blueprint, request, jsonify
from database import db_session
from models import (
    AttendanceRecord, LectureSession, Course, CourseEnrollment,
    User, SessionEntranceLog, AuditLog
)

attendance_bp = Blueprint("attendance", __name__, url_prefix="/api/attendance")

@attendance_bp.route("/session/<int:session_id>", methods=["GET"])
def get_session_attendance(session_id):
    """Retrieve full attendance sheet for a specific lecture session"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    # Enrolled students in course
    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == session.course_id,
        CourseEnrollment.status == "active",
        CourseEnrollment.role_scope == "student"
    ).all()

    existing_records = {
        r.student_id: r for r in db_session.query(AttendanceRecord).filter(
            AttendanceRecord.session_id == session_id
        ).all()
    }

    # Aggregate compliance summary
    records_output = []
    present_count = 0
    late_count = 0
    partial_count = 0
    absent_count = 0
    excused_count = 0

    for enr in enrollments:
        student = enr.user
        if not student:
            continue
        rec = existing_records.get(student.id)
        if rec:
            rec_dict = rec.to_dict()
            effective_status = rec.verified_status if rec.verified_status not in ["pending", None] else rec.automated_status
            if effective_status == "present":
                present_count += 1
            elif effective_status == "late":
                late_count += 1
            elif effective_status == "partial":
                partial_count += 1
            elif effective_status == "excused":
                excused_count += 1
            else:
                absent_count += 1
            records_output.append(rec_dict)
        else:
            # Student not joined yet
            absent_count += 1
            records_output.append({
                "id": None,
                "session_id": session.id,
                "student_id": student.id,
                "student_name": student.name,
                "institutional_id": student.institutional_id,
                "student_email": student.email,
                "first_join_time": None,
                "last_exit_time": None,
                "total_duration_minutes": 0.0,
                "is_late": False,
                "late_minutes": 0.0,
                "is_early_exit": False,
                "early_exit_minutes": 0.0,
                "lecture_coverage_pct": 0.0,
                "automated_status": "absent",
                "verified_status": "pending",
                "verification_reason": None,
                "registrar_compliance_flag": False
            })

    total_enrolled = len(enrollments)
    attendance_rate = round(((present_count + late_count) / max(1, total_enrolled)) * 100, 1)

    return jsonify({
        "success": True,
        "session_id": session.id,
        "session_title": session.title,
        "course_code": session.course.code if session.course else None,
        "status": session.status,
        "metrics": {
            "total_enrolled": total_enrolled,
            "present_count": present_count,
            "late_count": late_count,
            "partial_count": partial_count,
            "absent_count": absent_count,
            "excused_count": excused_count,
            "attendance_rate_pct": attendance_rate
        },
        "records": records_output
    })

@attendance_bp.route("/join-gate", methods=["POST"])
def join_lecture_gate():
    """Module 2: Auto-Track Connection Duration & Detect Late Arrivals at Virtual Room Gate"""
    data = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = data.get("student_id")
    ip_address = request.remote_addr or data.get("ip_address", "127.0.0.1")
    user_agent = request.headers.get("User-Agent", "Mozilla/5.0")

    if not session_id or not student_id:
        return jsonify({"success": False, "message": "session_id and student_id required"}), 400

    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    student = db_session.query(User).filter(User.id == student_id).first()

    if not session or not student:
        return jsonify({"success": False, "message": "Session or Student not found"}), 404

    # Gate Security Check (Module 1 & 2 integration)
    sec_cfg = {}
    if session.room_security_config:
        try:
            sec_cfg = json.loads(session.room_security_config)
        except Exception:
            pass

    # Restrict to enrolled
    if sec_cfg.get("restrict_to_enrolled", True):
        enrollment = db_session.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == session.course_id,
            CourseEnrollment.user_id == student_id,
            CourseEnrollment.status == "active"
        ).first()
        if not enrollment and student.role not in ["Dean", "Professor"]:
            # Gate Rejected
            log = SessionEntranceLog(
                session_id=session_id,
                user_id=student_id,
                event_type="gate_rejected",
                ip_address=ip_address,
                user_agent=user_agent,
                details="Access denied: Student ID is not enrolled in this course section."
            )
            db_session.add(log)
            db_session.commit()
            return jsonify({
                "success": False,
                "admitted": False,
                "message": "Gate Rejected: You are not enrolled in this course section."
            }), 403

    now = datetime.datetime.utcnow()

    # Calculate Late Arrival against session scheduled start or actual start
    grace_period_mins = sec_cfg.get("grace_period_mins", 10)
    session_start_ref = session.actual_start or session.scheduled_start
    elapsed_start_mins = (now - session_start_ref).total_seconds() / 60.0
    
    is_late = False
    late_minutes = 0.0
    if elapsed_start_mins > grace_period_mins:
        is_late = True
        late_minutes = elapsed_start_mins

    # Find or create AttendanceRecord
    rec = db_session.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.student_id == student_id
    ).first()

    if not rec:
        rec = AttendanceRecord(
            session_id=session_id,
            student_id=student_id,
            first_join_time=now,
            last_exit_time=None,
            total_duration_minutes=1.0,
            is_late=is_late,
            late_minutes=round(late_minutes, 1),
            is_early_exit=False,
            early_exit_minutes=0.0,
            lecture_coverage_pct=100.0 if not is_late else max(10.0, 100.0 - (late_minutes * 1.5)),
            automated_status="late" if is_late else "present",
            verified_status="pending",
            registrar_compliance_flag=not is_late
        )
        db_session.add(rec)
    else:
        # Re-joining
        if not rec.first_join_time:
            rec.first_join_time = now
            rec.is_late = is_late
            rec.late_minutes = round(late_minutes, 1)
            rec.automated_status = "late" if is_late else "present"
        rec.last_exit_time = None

    # Entrance log
    log = SessionEntranceLog(
        session_id=session_id,
        user_id=student_id,
        event_type="joined",
        ip_address=ip_address,
        user_agent=user_agent,
        details=f"Admitted via gate. Status: {'Late Arrival (+' + str(round(late_minutes)) + 'm)' if is_late else 'On-time entrance'}."
    )
    db_session.add(log)
    db_session.commit()

    return jsonify({
        "success": True,
        "admitted": True,
        "is_late": is_late,
        "late_minutes": round(late_minutes, 1),
        "record": rec.to_dict()
    })

@attendance_bp.route("/heartbeat", methods=["POST"])
def attendance_heartbeat():
    """Module 2: Auto-Track Connection Duration (updates connection duration periodically)"""
    data = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = data.get("student_id")
    increment_seconds = data.get("increment_seconds", 30)

    rec = db_session.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.student_id == student_id
    ).first()

    if rec:
        session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
        rec.total_duration_minutes = round(rec.total_duration_minutes + (increment_seconds / 60.0), 1)
        
        # Calculate coverage against scheduled duration
        if session:
            sched_mins = max(1.0, (session.scheduled_end - session.scheduled_start).total_seconds() / 60.0)
            rec.lecture_coverage_pct = min(100.0, round((rec.total_duration_minutes / sched_mins) * 100.0, 1))

        db_session.commit()
        return jsonify({"success": True, "total_duration_minutes": rec.total_duration_minutes, "coverage_pct": rec.lecture_coverage_pct})

    return jsonify({"success": False, "message": "Attendance record not found"}), 404

@attendance_bp.route("/leave-gate", methods=["POST"])
def leave_lecture_gate():
    """Module 2: Flag Early Disconnections when student drops off before lecture dismissal"""
    data = request.get_json() or {}
    session_id = data.get("session_id")
    student_id = data.get("student_id")
    reason = data.get("reason", "normal_disconnect")

    rec = db_session.query(AttendanceRecord).filter(
        AttendanceRecord.session_id == session_id,
        AttendanceRecord.student_id == student_id
    ).first()
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()

    if not rec or not session:
        return jsonify({"success": False, "message": "Record or session not found"}), 404

    now = datetime.datetime.utcnow()
    rec.last_exit_time = now

    # Check if early disconnection: left more than 10 mins before scheduled end
    target_end = session.actual_end or session.scheduled_end
    early_diff_mins = (target_end - now).total_seconds() / 60.0
    
    is_early_exit = False
    if early_diff_mins > 10.0 and session.status == "in_progress":
        is_early_exit = True
        rec.is_early_exit = True
        rec.early_exit_minutes = round(early_diff_mins, 1)
        if rec.lecture_coverage_pct < 75.0:
            rec.automated_status = "partial"

    # Log disconnection event
    log = SessionEntranceLog(
        session_id=session_id,
        user_id=student_id,
        event_type="disconnected",
        disconnection_reason=reason,
        details=f"Exit recorded. {'Early disconnect flagged (-' + str(round(early_diff_mins)) + 'm)' if is_early_exit else 'Normal exit.'}"
    )
    db_session.add(log)
    db_session.commit()

    return jsonify({
        "success": True,
        "is_early_exit": is_early_exit,
        "early_exit_minutes": round(early_diff_mins, 1) if is_early_exit else 0.0,
        "record": rec.to_dict()
    })

@attendance_bp.route("/override", methods=["PUT"])
def override_verified_status():
    """Module 2: Update Verified Status & Reconcile automated attendance with professor manual overrides"""
    data = request.get_json() or {}
    record_id = data.get("record_id")
    verified_status = data.get("verified_status") # present, late, partial, excused, absent, override_approved
    verification_reason = data.get("verification_reason", "").strip()
    actor_id = data.get("actor_id", 2)

    if not record_id or not verified_status:
        return jsonify({"success": False, "message": "record_id and verified_status required"}), 400

    if not verification_reason:
        return jsonify({"success": False, "message": "Academic justification log is required for attendance override."}), 400

    rec = db_session.query(AttendanceRecord).filter(AttendanceRecord.id == record_id).first()
    if not rec:
        return jsonify({"success": False, "message": "Attendance record not found"}), 404

    actor = db_session.query(User).filter(User.id == actor_id).first()
    prev_status = rec.verified_status or rec.automated_status

    rec.verified_status = verified_status
    rec.verified_by_id = actor_id
    rec.verification_reason = verification_reason
    rec.verified_at = datetime.datetime.utcnow()
    rec.registrar_compliance_flag = verified_status in ["present", "late", "excused", "override_approved"]

    # Module 7: Log Attendance Overrides with justification
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Professor",
        actor_role=actor.role if actor else "Professor",
        event_type="attendance_override",
        target_entity="AttendanceRecord",
        target_id=rec.id,
        course_id=rec.session.course_id if rec.session else None,
        change_before=json.dumps({"verified_status": prev_status}),
        change_after=json.dumps({"verified_status": verified_status, "justification": verification_reason}),
        justification=verification_reason,
        ip_address=request.remote_addr or "127.0.0.1"
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Attendance status successfully updated to {verified_status}",
        "record": rec.to_dict()
    })

@attendance_bp.route("/courses/<int:course_id>/roster-enroll", methods=["POST"])
def enroll_student_roster(course_id):
    """Module 2: Enroll Student Roster from campus Student Information System (SIS)"""
    data = request.get_json() or {}
    students_input = data.get("students", []) # list of dicts: [{institutional_id, name, email}]
    actor_id = data.get("actor_id", 1)

    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    enrolled_count = 0
    created_users = 0

    for s in students_input:
        inst_id = s.get("institutional_id", "").strip()
        name = s.get("name", "").strip()
        email = s.get("email", "").strip()

        if not inst_id or not name:
            continue

        user = db_session.query(User).filter(
            (User.institutional_id == inst_id) | (User.email == email)
        ).first()

        if not user:
            user = User(
                institutional_id=inst_id,
                name=name,
                email=email or f"{inst_id.lower()}@student.university.edu",
                role="Student",
                department=course.department
            )
            db_session.add(user)
            db_session.flush()
            created_users += 1

        # Check existing enrollment
        existing_enr = db_session.query(CourseEnrollment).filter(
            CourseEnrollment.course_id == course_id,
            CourseEnrollment.user_id == user.id
        ).first()

        if not existing_enr:
            new_enr = CourseEnrollment(
                course_id=course_id,
                user_id=user.id,
                role_scope="student",
                status="active"
            )
            db_session.add(new_enr)
            enrolled_count += 1

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Registrar",
        actor_role=actor.role if actor else "Dean",
        event_type="roster_enrollment",
        target_entity="CourseEnrollment",
        course_id=course_id,
        change_after=json.dumps({"enrolled_students": enrolled_count, "new_users": created_users}),
        justification=f"Imported student roster batch from SIS into course {course.code}."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Successfully enrolled {enrolled_count} students ({created_users} newly registered).",
        "enrolled_count": enrolled_count
    })

@attendance_bp.route("/courses/<int:course_id>/attendance-sheet", methods=["GET"])
def get_course_attendance_sheet(course_id):
    """Module 2: Generate Academic Attendance Sheet for university registrar compliance"""
    course = db_session.query(Course).filter(Course.id == course_id).first()
    if not course:
        return jsonify({"success": False, "message": "Course not found"}), 404

    sessions = db_session.query(LectureSession).filter(
        LectureSession.course_id == course_id
    ).order_by(LectureSession.scheduled_start).all()

    enrollments = db_session.query(CourseEnrollment).filter(
        CourseEnrollment.course_id == course_id,
        CourseEnrollment.status == "active",
        CourseEnrollment.role_scope == "student"
    ).all()

    matrix = []
    for enr in enrollments:
        student = enr.user
        if not student:
            continue

        student_row = {
            "student_id": student.id,
            "institutional_id": student.institutional_id,
            "name": student.name,
            "email": student.email,
            "total_attended_hours": 0.0,
            "sessions": {},
            "unexcused_absences": 0,
            "excused_absences": 0,
            "compliance_status": "Compliant"
        }

        total_sessions = len(sessions)
        attended_sessions = 0

        for sess in sessions:
            att = db_session.query(AttendanceRecord).filter(
                AttendanceRecord.session_id == sess.id,
                AttendanceRecord.student_id == student.id
            ).first()

            if att:
                eff = att.verified_status if att.verified_status not in ["pending", None] else att.automated_status
                duration_hrs = round(att.total_duration_minutes / 60.0, 2)
                student_row["total_attended_hours"] += duration_hrs
                student_row["sessions"][sess.id] = {
                    "status": eff,
                    "coverage_pct": att.lecture_coverage_pct,
                    "is_late": att.is_late,
                    "duration_minutes": att.total_duration_minutes
                }
                if eff in ["present", "late", "override_approved"]:
                    attended_sessions += 1
                elif eff == "excused":
                    student_row["excused_absences"] += 1
                else:
                    student_row["unexcused_absences"] += 1
            else:
                student_row["sessions"][sess.id] = {"status": "absent", "coverage_pct": 0.0}
                student_row["unexcused_absences"] += 1

        student_row["total_attended_hours"] = round(student_row["total_attended_hours"], 1)
        if student_row["unexcused_absences"] >= 3:
            student_row["compliance_status"] = "Truancy Warning (>= 3 absences)"
        elif student_row["unexcused_absences"] > 0:
            student_row["compliance_status"] = "Minor Deficiency"

        matrix.append(student_row)

    return jsonify({
        "success": True,
        "course_id": course.id,
        "course_code": course.code,
        "course_title": course.title,
        "sessions": [{"id": s.id, "title": s.title, "date": s.scheduled_start.strftime("%Y-%m-%d")} for s in sessions],
        "attendance_matrix": matrix
    })
