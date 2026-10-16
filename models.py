import datetime
import json
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float, DateTime, ForeignKey, Index
)
from sqlalchemy.orm import relationship
from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    institutional_id = Column(String(64), unique=True, nullable=False, index=True) # e.g. STU-2026-101, FAC-304
    name = Column(String(128), nullable=False)
    email = Column(String(128), unique=True, nullable=False, index=True)
    role = Column(String(32), nullable=False, default="Student") # Dean, Professor, Teaching Assistant, Student, Auditor
    department = Column(String(128), default="Computer Science & Engineering")
    avatar_url = Column(String(256), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    taught_courses = relationship("Course", back_populates="primary_instructor", foreign_keys="Course.primary_instructor_id")
    enrollments = relationship("CourseEnrollment", back_populates="user", cascade="all, delete-orphan")
    attendance_records = relationship("AttendanceRecord", back_populates="student", foreign_keys="AttendanceRecord.student_id")
    leave_requests = relationship("LeaveRequest", back_populates="student", foreign_keys="LeaveRequest.student_id")
    proxied_leaves = relationship("LeaveRequest", back_populates="note_proxy", foreign_keys="LeaveRequest.note_proxy_id")
    quiz_responses = relationship("QuizResponse", back_populates="student")

    def to_dict(self):
        return {
            "id": self.id,
            "institutional_id": self.institutional_id,
            "name": self.name,
            "email": self.email,
            "role": self.role,
            "department": self.department,
            "avatar_url": self.avatar_url,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True)
    code = Column(String(32), unique=True, nullable=False, index=True) # e.g. "CS-401"
    title = Column(String(256), nullable=False)
    department = Column(String(128), default="Computer Science & Engineering")
    term = Column(String(64), default="Fall 2026")
    credits = Column(Integer, default=4)
    primary_instructor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    syllabus_overview = Column(Text, nullable=True)
    room_security_level = Column(String(64), default="enrolled_only") # enrolled_only, verified_institutional_email, open_auditor
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    primary_instructor = relationship("User", back_populates="taught_courses", foreign_keys=[primary_instructor_id])
    modules = relationship("SyllabusModule", back_populates="course", cascade="all, delete-orphan", order_by="SyllabusModule.module_number")
    sessions = relationship("LectureSession", back_populates="course", cascade="all, delete-orphan")
    enrollments = relationship("CourseEnrollment", back_populates="course", cascade="all, delete-orphan")
    ta_scopes = relationship("TAPermissionScope", back_populates="course", cascade="all, delete-orphan")
    recurring_timetables = relationship("RecurringTimetable", back_populates="course", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "code": self.code,
            "title": self.title,
            "department": self.department,
            "term": self.term,
            "credits": self.credits,
            "primary_instructor_id": self.primary_instructor_id,
            "primary_instructor_name": self.primary_instructor.name if self.primary_instructor else None,
            "room_security_level": self.room_security_level,
            "syllabus_overview": self.syllabus_overview,
            "modules_count": len(self.modules) if self.modules else 0,
            "active_students_count": len([e for e in self.enrollments if e.status == "active" and e.role_scope == "student"]),
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class SyllabusModule(Base):
    __tablename__ = "syllabus_modules"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    module_number = Column(Integer, nullable=False)
    title = Column(String(256), nullable=False)
    description = Column(Text, nullable=True)
    learning_objectives = Column(Text, nullable=True)

    # Relationships
    course = relationship("Course", back_populates="modules")
    sessions = relationship("LectureSession", back_populates="syllabus_module")

    def to_dict(self):
        return {
            "id": self.id,
            "course_id": self.course_id,
            "module_number": self.module_number,
            "title": self.title,
            "description": self.description,
            "learning_objectives": self.learning_objectives
        }


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role_scope = Column(String(32), default="student") # student, ta, auditor, co_instructor
    status = Column(String(32), default="active") # active, dropped, completed, revoked
    enrolled_at = Column(DateTime, default=datetime.datetime.utcnow)
    revoked_at = Column(DateTime, nullable=True)
    revocation_reason = Column(String(256), nullable=True)

    # Relationships
    course = relationship("Course", back_populates="enrollments")
    user = relationship("User", back_populates="enrollments")

    def to_dict(self):
        return {
            "id": self.id,
            "course_id": self.course_id,
            "course_code": self.course.code if self.course else None,
            "course_title": self.course.title if self.course else None,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "institutional_id": self.user.institutional_id if self.user else None,
            "user_email": self.user.email if self.user else None,
            "role_scope": self.role_scope,
            "status": self.status,
            "enrolled_at": self.enrolled_at.isoformat() if self.enrolled_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
            "revocation_reason": self.revocation_reason
        }


class TAPermissionScope(Base):
    __tablename__ = "ta_permission_scopes"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    ta_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    can_take_attendance = Column(Boolean, default=True)
    can_coedit_notes = Column(Boolean, default=True)
    can_launch_polls = Column(Boolean, default=True)
    can_publish_grades = Column(Boolean, default=False) # Restricted by default as per Module 6 specs
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    course = relationship("Course", back_populates="ta_scopes")
    ta = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "course_id": self.course_id,
            "course_code": self.course.code if self.course else None,
            "ta_id": self.ta_id,
            "ta_name": self.ta.name if self.ta else None,
            "ta_email": self.ta.email if self.ta else None,
            "can_take_attendance": self.can_take_attendance,
            "can_coedit_notes": self.can_coedit_notes,
            "can_launch_polls": self.can_launch_polls,
            "can_publish_grades": self.can_publish_grades,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None
        }


class RecurringTimetable(Base):
    __tablename__ = "recurring_timetables"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    day_of_week = Column(String(32), nullable=False) # e.g. "Monday", "Wednesday", "Friday"
    start_time = Column(String(16), nullable=False) # "10:00"
    end_time = Column(String(16), nullable=False)   # "11:30"
    room_or_gate = Column(String(128), default="Auditorium Hall B & Virtual Gate")
    term_start = Column(DateTime, nullable=True)
    term_end = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True)

    # Relationships
    course = relationship("Course", back_populates="recurring_timetables")

    def to_dict(self):
        return {
            "id": self.id,
            "course_id": self.course_id,
            "course_code": self.course.code if self.course else None,
            "day_of_week": self.day_of_week,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "room_or_gate": self.room_or_gate,
            "is_active": self.is_active
        }


class LectureSession(Base):
    __tablename__ = "lecture_sessions"

    id = Column(Integer, primary_key=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    module_id = Column(Integer, ForeignKey("syllabus_modules.id"), nullable=True)
    title = Column(String(256), nullable=False)
    session_type = Column(String(64), default="Lecture") # Lecture, Seminar, Colloquium, Lab
    scheduled_start = Column(DateTime, nullable=False)
    scheduled_end = Column(DateTime, nullable=False)
    actual_start = Column(DateTime, nullable=True)
    actual_end = Column(DateTime, nullable=True)
    status = Column(String(32), default="scheduled") # scheduled, in_progress, completed, cancelled
    
    # Virtual Gate & Security
    virtual_room_code = Column(String(64), unique=True, nullable=False) # e.g. "GATE-CS401-09"
    room_security_config = Column(Text, default='{"restrict_to_enrolled": true, "require_institutional_email": true, "grace_period_mins": 10}')
    
    # Recording Archive
    recording_url = Column(String(512), nullable=True)
    recording_status = Column(String(32), default="none") # none, processing, archived
    recording_duration_mins = Column(Integer, default=0)
    recording_notes = Column(Text, nullable=True)

    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    course = relationship("Course", back_populates="sessions")
    syllabus_module = relationship("SyllabusModule", back_populates="sessions")
    created_by = relationship("User", foreign_keys=[created_by_id])
    co_hosts = relationship("SessionCoHost", back_populates="session", cascade="all, delete-orphan")
    attendance_records = relationship("AttendanceRecord", back_populates="session", cascade="all, delete-orphan")
    notes = relationship("LectureMOM", back_populates="session", cascade="all, delete-orphan", uselist=False)
    quizzes = relationship("LiveQuiz", back_populates="session", cascade="all, delete-orphan")
    entrance_logs = relationship("SessionEntranceLog", back_populates="session", cascade="all, delete-orphan")
    attachments = relationship("LectureAttachment", back_populates="session", cascade="all, delete-orphan")

    def to_dict(self):
        sec_cfg = {}
        if self.room_security_config:
            try:
                sec_cfg = json.loads(self.room_security_config)
            except Exception:
                sec_cfg = {}

        return {
            "id": self.id,
            "course_id": self.course_id,
            "course_code": self.course.code if self.course else None,
            "course_title": self.course.title if self.course else None,
            "module_id": self.module_id,
            "module_title": self.syllabus_module.title if self.syllabus_module else None,
            "module_number": self.syllabus_module.module_number if self.syllabus_module else None,
            "title": self.title,
            "session_type": self.session_type,
            "scheduled_start": self.scheduled_start.isoformat() if self.scheduled_start else None,
            "scheduled_end": self.scheduled_end.isoformat() if self.scheduled_end else None,
            "actual_start": self.actual_start.isoformat() if self.actual_start else None,
            "actual_end": self.actual_end.isoformat() if self.actual_end else None,
            "status": self.status,
            "virtual_room_code": self.virtual_room_code,
            "room_security_config": sec_cfg,
            "recording_url": self.recording_url,
            "recording_status": self.recording_status,
            "recording_duration_mins": self.recording_duration_mins,
            "recording_notes": self.recording_notes,
            "created_by_id": self.created_by_id,
            "created_by_name": self.created_by.name if self.created_by else None,
            "co_hosts": [ch.to_dict() for ch in self.co_hosts],
            "attendance_count": len(self.attendance_records) if self.attendance_records else 0,
            "has_mom": bool(self.notes),
            "mom_status": self.notes.status if self.notes else None,
            "quizzes_count": len(self.quizzes) if self.quizzes else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class SessionCoHost(Base):
    __tablename__ = "session_co_hosts"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    host_role = Column(String(64), default="teaching_assistant") # teaching_assistant, guest_lecturer, co_instructor
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    session = relationship("LectureSession", back_populates="co_hosts")
    user = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "user_email": self.user.email if self.user else None,
            "host_role": self.host_role,
            "assigned_at": self.assigned_at.isoformat() if self.assigned_at else None
        }


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Timing and coverage metrics
    first_join_time = Column(DateTime, nullable=True)
    last_exit_time = Column(DateTime, nullable=True)
    total_duration_minutes = Column(Float, default=0.0)
    
    # Flags computed automatically
    is_late = Column(Boolean, default=False)
    late_minutes = Column(Float, default=0.0)
    is_early_exit = Column(Boolean, default=False)
    early_exit_minutes = Column(Float, default=0.0)
    lecture_coverage_pct = Column(Float, default=0.0) # e.g. 92.5%
    
    # Automated vs Verified
    automated_status = Column(String(32), default="absent") # present, late, partial, absent
    verified_status = Column(String(32), default="pending")  # present, late, excused, absent, override_approved
    verified_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    verification_reason = Column(Text, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    
    # Compliance check
    registrar_compliance_flag = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    session = relationship("LectureSession", back_populates="attendance_records")
    student = relationship("User", back_populates="attendance_records", foreign_keys=[student_id])
    verified_by = relationship("User", foreign_keys=[verified_by_id])

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "session_title": self.session.title if self.session else None,
            "course_id": self.session.course_id if self.session else None,
            "course_code": self.session.course.code if self.session and self.session.course else None,
            "student_id": self.student_id,
            "student_name": self.student.name if self.student else None,
            "institutional_id": self.student.institutional_id if self.student else None,
            "student_email": self.student.email if self.student else None,
            "first_join_time": self.first_join_time.isoformat() if self.first_join_time else None,
            "last_exit_time": self.last_exit_time.isoformat() if self.last_exit_time else None,
            "total_duration_minutes": round(self.total_duration_minutes, 1),
            "is_late": self.is_late,
            "late_minutes": round(self.late_minutes, 1),
            "is_early_exit": self.is_early_exit,
            "early_exit_minutes": round(self.early_exit_minutes, 1),
            "lecture_coverage_pct": round(self.lecture_coverage_pct, 1),
            "automated_status": self.automated_status,
            "verified_status": self.verified_status,
            "verified_by_name": self.verified_by.name if self.verified_by else None,
            "verification_reason": self.verification_reason,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "registrar_compliance_flag": self.registrar_compliance_flag
        }


class SessionEntranceLog(Base):
    __tablename__ = "session_entrance_logs"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    event_type = Column(String(64), nullable=False) # gate_attempt, joined, heartbeat, disconnected, reconnected, gate_rejected
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    ip_address = Column(String(64), default="127.0.0.1")
    user_agent = Column(String(256), nullable=True)
    disconnection_reason = Column(String(128), nullable=True) # normal_logout, network_timeout, browser_closed, kicked
    details = Column(Text, nullable=True)

    # Relationships
    session = relationship("LectureSession", back_populates="entrance_logs")
    user = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_name": self.user.name if self.user else None,
            "institutional_id": self.user.institutional_id if self.user else None,
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "disconnection_reason": self.disconnection_reason,
            "details": self.details
        }


class LeaveRequest(Base):
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=True)
    
    category = Column(String(64), nullable=False) # medical, university_competition, academic_conference, bereavement, personal_emergency
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    reason = Column(Text, nullable=False)
    
    # Official attachments
    document_filename = Column(String(256), nullable=True)
    document_url = Column(String(512), nullable=True)
    document_type = Column(String(64), nullable=True)
    
    # Approval workflow
    status = Column(String(32), default="pending") # pending, approved, rejected
    reviewed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    review_comment = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    
    # Note Proxy pairing
    note_proxy_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    proxy_notes_delivered = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    student = relationship("User", back_populates="leave_requests", foreign_keys=[student_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    note_proxy = relationship("User", back_populates="proxied_leaves", foreign_keys=[note_proxy_id])
    course = relationship("Course")
    session = relationship("LectureSession")

    def to_dict(self):
        return {
            "id": self.id,
            "student_id": self.student_id,
            "student_name": self.student.name if self.student else None,
            "institutional_id": self.student.institutional_id if self.student else None,
            "course_id": self.course_id,
            "course_code": self.course.code if self.course else None,
            "course_title": self.course.title if self.course else None,
            "session_id": self.session_id,
            "session_title": self.session.title if self.session else None,
            "category": self.category,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "reason": self.reason,
            "document_filename": self.document_filename,
            "document_url": self.document_url,
            "document_type": self.document_type,
            "status": self.status,
            "reviewed_by_id": self.reviewed_by_id,
            "reviewed_by_name": self.reviewed_by.name if self.reviewed_by else None,
            "review_comment": self.review_comment,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "note_proxy_id": self.note_proxy_id,
            "note_proxy_name": self.note_proxy.name if self.note_proxy else None,
            "proxy_notes_delivered": self.proxy_notes_delivered,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class LectureMOM(Base):
    __tablename__ = "lecture_moms"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), unique=True, nullable=False)
    title = Column(String(256), nullable=False)
    topic_summary = Column(Text, nullable=False)
    formulas_and_theorems = Column(Text, nullable=True)
    key_takeaways = Column(Text, nullable=True)
    ta_supplementary_notes = Column(Text, nullable=True) # Co-edited by TAs
    
    # Lifecycle
    status = Column(String(32), default="draft") # draft, published, locked
    version = Column(Integer, default=1)
    
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    last_edited_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    published_at = Column(DateTime, nullable=True)
    locked_at = Column(DateTime, nullable=True)
    locked_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    # Relationships
    session = relationship("LectureSession", back_populates="notes")
    created_by = relationship("User", foreign_keys=[created_by_id])
    last_edited_by = relationship("User", foreign_keys=[last_edited_by_id])
    locked_by = relationship("User", foreign_keys=[locked_by_id])
    attachments = relationship("LectureAttachment", back_populates="mom", cascade="all, delete-orphan")
    edits = relationship("LectureMOMEdit", back_populates="mom", cascade="all, delete-orphan", order_by="desc(LectureMOMEdit.timestamp)")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "session_title": self.session.title if self.session else None,
            "course_id": self.session.course_id if self.session else None,
            "course_code": self.session.course.code if self.session and self.session.course else None,
            "course_title": self.session.course.title if self.session and self.session.course else None,
            "module_number": self.session.syllabus_module.module_number if self.session and self.session.syllabus_module else None,
            "module_title": self.session.syllabus_module.title if self.session and self.session.syllabus_module else None,
            "title": self.title,
            "topic_summary": self.topic_summary,
            "formulas_and_theorems": self.formulas_and_theorems,
            "key_takeaways": self.key_takeaways,
            "ta_supplementary_notes": self.ta_supplementary_notes,
            "status": self.status,
            "version": self.version,
            "created_by_name": self.created_by.name if self.created_by else None,
            "last_edited_by_name": self.last_edited_by.name if self.last_edited_by else None,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            "locked_by_name": self.locked_by.name if self.locked_by else None,
            "attachments": [att.to_dict() for att in self.attachments],
            "edits": [e.to_dict() for e in self.edits[:5]],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None
        }


class LectureMOMEdit(Base):
    __tablename__ = "lecture_mom_edits"

    id = Column(Integer, primary_key=True)
    mom_id = Column(Integer, ForeignKey("lecture_moms.id"), nullable=False)
    editor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    editor_role = Column(String(64), nullable=True)
    change_summary = Column(String(256), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    mom = relationship("LectureMOM", back_populates="edits")
    editor = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "mom_id": self.mom_id,
            "editor_name": self.editor.name if self.editor else "Academic Staff",
            "editor_role": self.editor_role or (self.editor.role if self.editor else None),
            "change_summary": self.change_summary,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None
        }


class LectureAttachment(Base):
    __tablename__ = "lecture_attachments"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    mom_id = Column(Integer, ForeignKey("lecture_moms.id"), nullable=True)
    file_name = Column(String(256), nullable=False)
    file_url = Column(String(512), nullable=False)
    file_type = Column(String(64), default="application/pdf")
    file_size_kb = Column(Integer, default=512)
    uploaded_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    session = relationship("LectureSession", back_populates="attachments")
    mom = relationship("LectureMOM", back_populates="attachments")
    uploaded_by = relationship("User")

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "mom_id": self.mom_id,
            "file_name": self.file_name,
            "file_url": self.file_url,
            "file_type": self.file_type,
            "file_size_kb": self.file_size_kb,
            "uploaded_by_name": self.uploaded_by.name if self.uploaded_by else None,
            "uploaded_at": self.uploaded_at.isoformat() if self.uploaded_at else None
        }


class LiveQuiz(Base):
    __tablename__ = "live_quizzes"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("lecture_sessions.id"), nullable=False)
    title = Column(String(256), nullable=False)
    prompt_type = Column(String(64), default="multiple_choice") # multiple_choice, true_false, open_concept
    status = Column(String(32), default="draft") # draft, launched, closed
    
    # JSON array of question objects:
    # [{"id": 1, "question": "...", "options": ["A", "B", "C", "D"], "correct_answer": "B", "explanation": "...", "points": 10}]
    questions_json = Column(Text, nullable=False)
    
    time_limit_seconds = Column(Integer, default=60)
    launched_at = Column(DateTime, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    total_points = Column(Integer, default=10)
    
    created_by_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    session = relationship("LectureSession", back_populates="quizzes")
    created_by = relationship("User")
    responses = relationship("QuizResponse", back_populates="quiz", cascade="all, delete-orphan")

    def to_dict(self, include_answers=False):
        parsed_questions = []
        if self.questions_json:
            try:
                raw_q = json.loads(self.questions_json)
                for q in raw_q:
                    q_copy = dict(q)
                    if not include_answers and self.status == "launched":
                        # Hide correct answers from active in-flight student screen
                        q_copy.pop("correct_answer", None)
                        q_copy.pop("explanation", None)
                    parsed_questions.append(q_copy)
            except Exception:
                parsed_questions = []

        # Calculate cohort mastery stats if closed
        cohort_stats = {}
        if self.responses:
            scores = [r.score for r in self.responses]
            total_students = len(self.responses)
            avg_score = sum(scores) / total_students if total_students > 0 else 0
            passed_count = len([r for r in self.responses if r.is_passed])
            cohort_stats = {
                "total_responses": total_students,
                "average_score": round(avg_score, 2),
                "average_pct": round((avg_score / self.total_points) * 100, 1) if self.total_points > 0 else 0,
                "pass_rate_pct": round((passed_count / total_students) * 100, 1) if total_students > 0 else 0,
                "highest_score": max(scores) if scores else 0,
                "lowest_score": min(scores) if scores else 0
            }

        return {
            "id": self.id,
            "session_id": self.session_id,
            "session_title": self.session.title if self.session else None,
            "course_id": self.session.course_id if self.session else None,
            "course_code": self.session.course.code if self.session and self.session.course else None,
            "title": self.title,
            "prompt_type": self.prompt_type,
            "status": self.status,
            "questions": parsed_questions,
            "time_limit_seconds": self.time_limit_seconds,
            "launched_at": self.launched_at.isoformat() if self.launched_at else None,
            "closed_at": self.closed_at.isoformat() if self.closed_at else None,
            "total_points": self.total_points,
            "created_by_name": self.created_by.name if self.created_by else None,
            "cohort_stats": cohort_stats,
            "responses_count": len(self.responses) if self.responses else 0,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class QuizResponse(Base):
    __tablename__ = "quiz_responses"

    id = Column(Integer, primary_key=True)
    quiz_id = Column(Integer, ForeignKey("live_quizzes.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    answers_json = Column(Text, nullable=False) # e.g. {"1": "B", "2": "True"}
    submitted_at = Column(DateTime, default=datetime.datetime.utcnow)
    latency_ms = Column(Integer, default=1240) # Millisecond timestamp latency
    score = Column(Float, default=0.0)
    max_score = Column(Float, default=10.0)
    percentage = Column(Float, default=0.0)
    is_passed = Column(Boolean, default=False)
    gradebook_exported = Column(Boolean, default=False)

    # Relationships
    quiz = relationship("LiveQuiz", back_populates="responses")
    student = relationship("User", back_populates="quiz_responses")

    def to_dict(self):
        ans = {}
        if self.answers_json:
            try:
                ans = json.loads(self.answers_json)
            except Exception:
                ans = {}

        return {
            "id": self.id,
            "quiz_id": self.quiz_id,
            "student_id": self.student_id,
            "student_name": self.student.name if self.student else None,
            "institutional_id": self.student.institutional_id if self.student else None,
            "answers": ans,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "latency_ms": self.latency_ms,
            "score": round(self.score, 1),
            "max_score": round(self.max_score, 1),
            "percentage": round(self.percentage, 1),
            "is_passed": self.is_passed,
            "gradebook_exported": self.gradebook_exported
        }


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_name = Column(String(128), nullable=False)
    actor_role = Column(String(64), nullable=False)
    
    event_type = Column(String(64), nullable=False, index=True) # attendance_override, grade_adjustment, role_change, note_locked, session_gate_security, access_revoked, etc.
    target_entity = Column(String(64), nullable=False) # AttendanceRecord, QuizResponse, CourseEnrollment, LectureMOM, LectureSession
    target_id = Column(Integer, nullable=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    
    change_before = Column(Text, nullable=True)
    change_after = Column(Text, nullable=True)
    justification = Column(Text, nullable=True)
    ip_address = Column(String(64), default="127.0.0.1")

    # Relationships
    actor = relationship("User", foreign_keys=[actor_id])
    course = relationship("Course", foreign_keys=[course_id])

    def to_dict(self):
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "actor_id": self.actor_id,
            "actor_name": self.actor_name,
            "actor_role": self.actor_role,
            "event_type": self.event_type,
            "target_entity": self.target_entity,
            "target_id": self.target_id,
            "course_id": self.course_id,
            "course_code": self.course.code if self.course else None,
            "change_before": self.change_before,
            "change_after": self.change_after,
            "justification": self.justification,
            "ip_address": self.ip_address
        }
