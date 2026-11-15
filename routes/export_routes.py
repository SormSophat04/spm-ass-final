import csv
import io
from flask import Blueprint, request, jsonify, Response
from database import db_session
from models import AuditLog, Course, LectureSession, AttendanceRecord, CourseEnrollment
from security import require_roles

export_bp = Blueprint("export", __name__, url_prefix="/api/export")

@export_bp.route("/courses/<int:course_id>/attendance-csv", methods=["GET"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def export_course_attendance_csv(course_id):
    """Module 2 & 7: Produces university registrar compliance CSV attendance sheet"""
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

    output = io.StringIO()
    writer = csv.writer(output)

    # Headers
    header = ["Student ID", "Full Name", "Institutional Email"]
    for s in sessions:
        header.append(f"{s.title[:20]} ({s.scheduled_start.strftime('%m/%d')})")
    header.extend(["Total Hours Attended", "Unexcused Absences", "Registrar Status"])
    writer.writerow(header)

    # Rows
    for enr in enrollments:
        student = enr.user
        if not student:
            continue

        row = [student.institutional_id, student.name, student.email]
        total_mins = 0.0
        unexcused = 0

        for s in sessions:
            att = db_session.query(AttendanceRecord).filter(
                AttendanceRecord.session_id == s.id,
                AttendanceRecord.student_id == student.id
            ).first()

            if att:
                status = att.verified_status if att.verified_status not in ["pending", None] else (att.automated_status or "absent")
                mins = att.total_duration_minutes or 0.0
                row.append(f"{status.upper()} ({round(mins)}m)")
                total_mins += mins
                if status == "absent":
                    unexcused += 1
            else:
                row.append("ABSENT (0m)")
                unexcused += 1

        total_hrs = round(total_mins / 60.0, 1)
        compliance = "COMPLIANT" if unexcused < 3 else "TRUANCY_FLAGGED"
        row.extend([str(total_hrs), str(unexcused), compliance])
        writer.writerow(row)

    csv_data = output.getvalue()
    filename = f"Registrar_Attendance_{course.code.replace(' ', '_')}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@export_bp.route("/audit-csv", methods=["GET"])
@require_roles("Dean", "Professor", "Auditor")
def export_audit_trail_csv():
    """Module 7: Export immutable academic integrity audit trail to CSV."""
    course_id = request.args.get("course_id", type=int)
    event_type = request.args.get("event_type")

    query = db_session.query(AuditLog)
    if course_id:
        query = query.filter(AuditLog.course_id == course_id)
    if event_type:
        query = query.filter(AuditLog.event_type == event_type)

    logs = query.order_by(AuditLog.timestamp.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Audit ID", "Timestamp (UTC)", "Actor Name", "Actor Role", "Event Type", "Course Code", "Target Entity", "Target ID", "Justification", "IP Address"])

    for l in logs:
        writer.writerow([
            l.id,
            l.timestamp.isoformat() if l.timestamp else "",
            l.actor_name,
            l.actor_role,
            l.event_type,
            l.course.code if l.course else "GLOBAL",
            l.target_entity,
            l.target_id or "",
            l.justification or "",
            l.ip_address or "127.0.0.1"
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=Institutional_Audit_Trail.csv"}
    )
