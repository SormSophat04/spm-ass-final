import datetime
import json
from flask import Blueprint, request, jsonify
from database import db_session
from models import (
    LeaveRequest, AttendanceRecord, Course, LectureSession,
    User, CourseEnrollment, AuditLog
)

leave_bp = Blueprint("leaves", __name__, url_prefix="/api/leaves")

@leave_bp.route("", methods=["GET"])
def get_leave_requests():
    student_id = request.args.get("student_id", type=int)
    course_id = request.args.get("course_id", type=int)
    status = request.args.get("status")

    query = db_session.query(LeaveRequest)
    if student_id:
        query = query.filter(LeaveRequest.student_id == student_id)
    if course_id:
        query = query.filter(LeaveRequest.course_id == course_id)
    if status:
        query = query.filter(LeaveRequest.status == status)

    requests_list = query.order_by(LeaveRequest.created_at.desc()).all()
    return jsonify({
        "success": True,
        "count": len(requests_list),
        "leaves": [r.to_dict() for r in requests_list]
    })

@leave_bp.route("", methods=["POST"])
def submit_leave_request():
    """Module 3: Submit Leave Request with category tags and official documentation"""
    data = request.get_json() or {}
    student_id = data.get("student_id")
    course_id = data.get("course_id")
    session_id = data.get("session_id")
    category = data.get("category", "medical") # medical, university_competition, academic_conference, bereavement, emergency
    start_date_str = data.get("start_date")
    end_date_str = data.get("end_date")
    reason = data.get("reason", "").strip()
    document_filename = data.get("document_filename")
    document_url = data.get("document_url", "/uploads/sample_medical_doc.pdf")
    document_type = data.get("document_type", "application/pdf")
    note_proxy_id = data.get("note_proxy_id")

    if not student_id or not course_id or not start_date_str or not end_date_str or not reason:
        return jsonify({"success": False, "message": "Missing required leave submission fields"}), 400

    try:
        start_date = datetime.datetime.fromisoformat(start_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
        end_date = datetime.datetime.fromisoformat(end_date_str.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception as e:
        return jsonify({"success": False, "message": f"Invalid date format: {str(e)}"}), 400

    new_leave = LeaveRequest(
        student_id=student_id,
        course_id=course_id,
        session_id=session_id if session_id else None,
        category=category,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        document_filename=document_filename or "Official_Document_Attachment.pdf",
        document_url=document_url,
        document_type=document_type,
        status="pending",
        note_proxy_id=note_proxy_id if note_proxy_id else None,
        proxy_notes_delivered=False
    )
    db_session.add(new_leave)
    db_session.commit()

    student = db_session.query(User).filter(User.id == student_id).first()
    course = db_session.query(Course).filter(Course.id == course_id).first()

    audit = AuditLog(
        actor_id=student_id,
        actor_name=student.name if student else "Student",
        actor_role="Student",
        event_type="leave_request_submitted",
        target_entity="LeaveRequest",
        target_id=new_leave.id,
        course_id=course_id,
        change_after=json.dumps({"category": category, "reason": reason}),
        justification=f"Student submitted excused absence request under category '{category}'."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Excused leave request successfully routed for academic validation",
        "leave": new_leave.to_dict()
    }), 201

@leave_bp.route("/<int:leave_id>/review", methods=["PUT"])
def review_leave_request(leave_id):
    """Module 3: Approve/Reject Absence & Automatically reconcile attendance to excused"""
    data = request.get_json() or {}
    status = data.get("status") # "approved" or "rejected"
    review_comment = data.get("review_comment", "").strip()
    reviewer_id = data.get("reviewer_id", 2) # Faculty / Advisor ID

    if status not in ["approved", "rejected"]:
        return jsonify({"success": False, "message": "Status must be 'approved' or 'rejected'"}), 400

    leave = db_session.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        return jsonify({"success": False, "message": "Leave request not found"}), 404

    reviewer = db_session.query(User).filter(User.id == reviewer_id).first()
    now = datetime.datetime.utcnow()

    leave.status = status
    leave.reviewed_by_id = reviewer_id
    leave.review_comment = review_comment
    leave.reviewed_at = now

    # If approved, reconcile attendance record for the associated session or sessions in the date window
    if status == "approved":
        target_sessions = []
        if leave.session_id:
            s = db_session.query(LectureSession).filter(LectureSession.id == leave.session_id).first()
            if s:
                target_sessions.append(s)
        else:
            # All sessions in course falling within the start_date and end_date window
            target_sessions = db_session.query(LectureSession).filter(
                LectureSession.course_id == leave.course_id,
                LectureSession.scheduled_start >= leave.start_date,
                LectureSession.scheduled_start <= leave.end_date
            ).all()

        for s in target_sessions:
            att = db_session.query(AttendanceRecord).filter(
                AttendanceRecord.session_id == s.id,
                AttendanceRecord.student_id == leave.student_id
            ).first()

            if not att:
                att = AttendanceRecord(
                    session_id=s.id,
                    student_id=leave.student_id,
                    total_duration_minutes=0.0,
                    automated_status="absent",
                    verified_status="excused",
                    verified_by_id=reviewer_id,
                    verification_reason=f"Approved leave ({leave.category}): {review_comment or 'Validated credentials'}",
                    verified_at=now,
                    registrar_compliance_flag=True
                )
                db_session.add(att)
            else:
                att.verified_status = "excused"
                att.verified_by_id = reviewer_id
                att.verification_reason = f"Approved leave ({leave.category}): {review_comment or 'Validated credentials'}"
                att.verified_at = now
                att.registrar_compliance_flag = True

    # Audit Trail
    audit = AuditLog(
        actor_id=reviewer_id,
        actor_name=reviewer.name if reviewer else "Faculty Reviewer",
        actor_role=reviewer.role if reviewer else "Professor",
        event_type="leave_request_reviewed",
        target_entity="LeaveRequest",
        target_id=leave.id,
        course_id=leave.course_id,
        change_before=json.dumps({"status": "pending"}),
        change_after=json.dumps({"status": status, "comment": review_comment}),
        justification=f"Formal validation: leave request {status.upper()} with justification."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Absence request has been {status}",
        "leave": leave.to_dict()
    })

@leave_bp.route("/<int:leave_id>/assign-proxy", methods=["POST"])
def assign_note_proxy(leave_id):
    """Module 3: Assign Note Proxy - Pairs absent students with designated note-takers"""
    data = request.get_json() or {}
    note_proxy_id = data.get("note_proxy_id")

    if not note_proxy_id:
        return jsonify({"success": False, "message": "note_proxy_id is required"}), 400

    leave = db_session.query(LeaveRequest).filter(LeaveRequest.id == leave_id).first()
    if not leave:
        return jsonify({"success": False, "message": "Leave request not found"}), 404

    proxy_user = db_session.query(User).filter(User.id == note_proxy_id).first()
    if not proxy_user:
        return jsonify({"success": False, "message": "Proxy student not found"}), 404

    leave.note_proxy_id = note_proxy_id
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Note proxy successfully assigned to peer {proxy_user.name}",
        "leave": leave.to_dict()
    })

@leave_bp.route("/student/<int:student_id>/history", methods=["GET"])
def get_student_leave_history(student_id):
    """Module 3: View Student Leave History & Displays cumulative absence records with threshold warnings"""
    student = db_session.query(User).filter(User.id == student_id).first()
    if not student:
        return jsonify({"success": False, "message": "Student not found"}), 404

    leaves = db_session.query(LeaveRequest).filter(
        LeaveRequest.student_id == student_id
    ).order_by(LeaveRequest.created_at.desc()).all()

    # Get attendance statistics across all enrolled courses
    attendances = db_session.query(AttendanceRecord).filter(
        AttendanceRecord.student_id == student_id
    ).all()

    unexcused_count = 0
    excused_count = 0
    present_count = 0
    late_count = 0

    for a in attendances:
        status = a.verified_status if a.verified_status not in ["pending", None] else a.automated_status
        if status in ["present", "override_approved"]:
            present_count += 1
        elif status == "late":
            late_count += 1
        elif status == "excused":
            excused_count += 1
        else:
            unexcused_count += 1

    total_sessions_recorded = len(attendances)
    absence_rate_pct = round(((unexcused_count + excused_count) / max(1, total_sessions_recorded)) * 100, 1)

    threshold_warning = False
    warning_message = "Absence rate within normal institutional parameters."
    if unexcused_count >= 3:
        threshold_warning = True
        warning_message = f"CRITICAL TRUANCY WARNING: Student has accrued {unexcused_count} unexcused absences. Exceeds institutional threshold (>= 3 absences). Subject to academic registrar review."
    elif unexcused_count == 2:
        warning_message = "ADVISORY WARNING: Student has 2 unexcused absences. One more absence will trigger mandatory dean review."

    return jsonify({
        "success": True,
        "student": student.to_dict(),
        "summary": {
            "total_records": total_sessions_recorded,
            "present_count": present_count,
            "late_count": late_count,
            "excused_count": excused_count,
            "unexcused_count": unexcused_count,
            "absence_rate_pct": absence_rate_pct,
            "threshold_warning": threshold_warning,
            "warning_message": warning_message
        },
        "leave_requests": [l.to_dict() for l in leaves]
    })
