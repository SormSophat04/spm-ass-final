import datetime
import json
from database import db_session, init_db, engine, Base
from models import (
    User, Course, SyllabusModule, CourseEnrollment, TAPermissionScope,
    RecurringTimetable, LectureSession, SessionCoHost, AttendanceRecord,
    SessionEntranceLog, LeaveRequest, LectureMOM, LectureMOMEdit,
    LectureAttachment, LiveQuiz, QuizResponse, AuditLog
)

def seed_database():
    print("Re-creating database tables...")
    Base.metadata.drop_all(bind=engine)
    init_db()

    now = datetime.datetime.utcnow()
    yesterday = now - datetime.timedelta(days=1)
    two_days_ago = now - datetime.timedelta(days=2)
    tomorrow = now + datetime.timedelta(days=1)
    next_week = now + datetime.timedelta(days=7)

    # 1. Users across all Academic Roles
    users_data = [
        # Dean
        User(institutional_id="ADM-2026-001", name="Dr. Eleanor Vance", email="e.vance@university.edu", role="Dean", department="Faculty of Science & Technology"),
        # Professors
        User(institutional_id="FAC-2026-010", name="Prof. Alan Turing-Ward", email="a.turing@university.edu", role="Professor", department="Computer Science & Engineering"),
        User(institutional_id="FAC-2026-012", name="Prof. Clara Richter", email="c.richter@university.edu", role="Professor", department="Computer Science & Engineering"),
        User(institutional_id="FAC-2026-015", name="Prof. Marcus Brody", email="m.brody@university.edu", role="Professor", department="Electrical & Systems Engineering"),
        # Teaching Assistants
        User(institutional_id="TA-2026-041", name="Alex Chen", email="alex.chen@university.edu", role="Teaching Assistant", department="Computer Science & Engineering"),
        User(institutional_id="TA-2026-042", name="Priya Sharma", email="priya.sharma@university.edu", role="Teaching Assistant", department="Computer Science & Engineering"),
        # Students
        User(institutional_id="STU-2026-101", name="Jordan Miller", email="jordan.miller@student.university.edu", role="Student", department="Computer Science & Engineering"),
        User(institutional_id="STU-2026-102", name="Maya Lin", email="maya.lin@student.university.edu", role="Student", department="Computer Science & Engineering"),
        User(institutional_id="STU-2026-103", name="Liam O'Connor", email="liam.oconnor@student.university.edu", role="Student", department="Computer Science & Engineering"),
        User(institutional_id="STU-2026-104", name="Sophia Patel", email="sophia.patel@student.university.edu", role="Student", department="Computer Science & Engineering"),
        User(institutional_id="STU-2026-105", name="Lucas Meyer", email="lucas.meyer@student.university.edu", role="Student", department="Computer Science & Engineering"),
        User(institutional_id="STU-2026-106", name="Emma Watson-Lee", email="emma.wl@student.university.edu", role="Student", department="Computer Science & Engineering"),
        # Auditor
        User(institutional_id="AUD-2026-090", name="David Kim", email="david.kim@partner.university.edu", role="Auditor", department="Institutional Quality Assurance"),
    ]

    for u in users_data:
        db_session.add(u)
    db_session.commit()

    dean = users_data[0]
    prof_alan = users_data[1]
    prof_clara = users_data[2]
    ta_alex = users_data[4]
    ta_priya = users_data[5]
    students = users_data[6:12]
    auditor = users_data[12]

    # 2. Courses
    course_cs401 = Course(
        code="CS-401",
        title="Distributed Systems & Cloud Consensus Protocols",
        department="Computer Science & Engineering",
        term="Fall 2026",
        credits=4,
        primary_instructor_id=prof_alan.id,
        room_security_level="enrolled_only",
        syllabus_overview="Comprehensive study of distributed synchronization, Paxos, Raft consensus, Byzantine fault tolerance, and eventual consistency in high-availability cloud platforms."
    )
    course_ai502 = Course(
        code="AI-502",
        title="Advanced Neural Architectures & Foundation Models",
        department="Computer Science & Engineering",
        term="Fall 2026",
        credits=4,
        primary_instructor_id=prof_clara.id,
        room_security_level="verified_institutional_email",
        syllabus_overview="Theoretical foundations and empirical scaling laws of multi-head attention, mixture of experts, diffusion dynamics, and reinforcement learning with human feedback."
    )
    db_session.add_all([course_cs401, course_ai502])
    db_session.commit()

    # 3. Syllabus Modules
    modules_cs401 = [
        SyllabusModule(course_id=course_cs401.id, module_number=1, title="Foundations of Asynchronous Systems & Logical Clocks", description="Lamport timestamps, Vector clocks, and Partial ordering of events in distributed networks.", learning_objectives="Compute vector clock causality; prove consistency boundaries in non-synchronized networks."),
        SyllabusModule(course_id=course_cs401.id, module_number=2, title="Leader Election & Consensus: Paxos to Raft", description="State machine replication, quorum slices, leader election terms, and log compaction.", learning_objectives="Implement two-phase commit and Raft heartbeats; prove safety invariants under network partitions."),
        SyllabusModule(course_id=course_cs401.id, module_number=3, title="Byzantine Fault Tolerance & Distributed Ledger Verification", description="PBFT algorithm, cryptographic signatures, threshold quorums, and Sybil resistance.", learning_objectives="Analyze 3f+1 quorum thresholds under adversarial conditions.")
    ]
    modules_ai502 = [
        SyllabusModule(course_id=course_ai502.id, module_number=1, title="Attention Mechanisms & Transformer Backbones", description="Self-attention, Rotary Position Embeddings (RoPE), FlashAttention, and KV caching.", learning_objectives="Derive matrix formulations for scaled dot-product attention."),
        SyllabusModule(course_id=course_ai502.id, module_number=2, title="Mixture of Experts & Sparse Parameter Scaling", description="Top-k routing, expert capacity factors, and load balancing loss functions.", learning_objectives="Calculate parameter FLOP efficiency in MoE architectures.")
    ]
    db_session.add_all(modules_cs401 + modules_ai502)
    db_session.commit()

    # 4. Course Enrollments
    enrollments = []
    # CS401 enrollments
    enrollments.append(CourseEnrollment(course_id=course_cs401.id, user_id=prof_alan.id, role_scope="co_instructor", status="active"))
    enrollments.append(CourseEnrollment(course_id=course_cs401.id, user_id=ta_alex.id, role_scope="ta", status="active"))
    enrollments.append(CourseEnrollment(course_id=course_cs401.id, user_id=auditor.id, role_scope="auditor", status="active"))
    for s in students:
        enrollments.append(CourseEnrollment(course_id=course_cs401.id, user_id=s.id, role_scope="student", status="active"))
    
    # AI502 enrollments
    enrollments.append(CourseEnrollment(course_id=course_ai502.id, user_id=prof_clara.id, role_scope="co_instructor", status="active"))
    enrollments.append(CourseEnrollment(course_id=course_ai502.id, user_id=ta_priya.id, role_scope="ta", status="active"))
    for s in students[:4]:
        enrollments.append(CourseEnrollment(course_id=course_ai502.id, user_id=s.id, role_scope="student", status="active"))

    db_session.add_all(enrollments)
    db_session.commit()

    # 5. TA Permission Scopes
    ta_scope_cs401 = TAPermissionScope(
        course_id=course_cs401.id,
        ta_id=ta_alex.id,
        can_take_attendance=True,
        can_coedit_notes=True,
        can_launch_polls=True,
        can_publish_grades=False # Restricted as per Module 6
    )
    ta_scope_ai502 = TAPermissionScope(
        course_id=course_ai502.id,
        ta_id=ta_priya.id,
        can_take_attendance=True,
        can_coedit_notes=True,
        can_launch_polls=True,
        can_publish_grades=False
    )
    db_session.add_all([ta_scope_cs401, ta_scope_ai502])
    db_session.commit()

    # 6. Recurring Timetables
    tt_cs401_1 = RecurringTimetable(course_id=course_cs401.id, day_of_week="Monday", start_time="10:00", end_time="11:30", room_or_gate="Auditorium 302 & Virtual Gate Alpha")
    tt_cs401_2 = RecurringTimetable(course_id=course_cs401.id, day_of_week="Wednesday", start_time="10:00", end_time="11:30", room_or_gate="Auditorium 302 & Virtual Gate Alpha")
    tt_cs401_3 = RecurringTimetable(course_id=course_cs401.id, day_of_week="Friday", start_time="10:00", end_time="11:30", room_or_gate="Auditorium 302 & Virtual Gate Alpha")
    
    tt_ai502_1 = RecurringTimetable(course_id=course_ai502.id, day_of_week="Tuesday", start_time="14:00", end_time="16:00", room_or_gate="Seminar Hall 101 & Virtual Gate Beta")
    tt_ai502_2 = RecurringTimetable(course_id=course_ai502.id, day_of_week="Thursday", start_time="14:00", end_time="16:00", room_or_gate="Seminar Hall 101 & Virtual Gate Beta")
    db_session.add_all([tt_cs401_1, tt_cs401_2, tt_cs401_3, tt_ai502_1, tt_ai502_2])
    db_session.commit()

    # 7. Lecture Sessions
    # Session 1: Past completed session for CS401
    s1_start = two_days_ago.replace(hour=10, minute=0, second=0, microsecond=0)
    s1_end = two_days_ago.replace(hour=11, minute=30, second=0, microsecond=0)
    session_past = LectureSession(
        course_id=course_cs401.id,
        module_id=modules_cs401[0].id,
        title="Session 01: Asynchronous Timestamps & Logical Ordering Invariants",
        session_type="Lecture",
        scheduled_start=s1_start,
        scheduled_end=s1_end,
        actual_start=s1_start + datetime.timedelta(minutes=1),
        actual_end=s1_end - datetime.timedelta(minutes=2),
        status="completed",
        virtual_room_code="GATE-CS401-01",
        room_security_config=json.dumps({"restrict_to_enrolled": True, "require_institutional_email": True, "grace_period_mins": 10}),
        recording_url="https://media.university.edu/archives/2026/cs401_lec01.mp4",
        recording_status="archived",
        recording_duration_mins=87,
        recording_notes="High-definition capture with automated transcription and slide synchronization.",
        created_by_id=prof_alan.id
    )

    # Session 2: Currently Live / In-Progress session for CS401
    s2_start = now - datetime.timedelta(minutes=35)
    s2_end = now + datetime.timedelta(minutes=55)
    session_live = LectureSession(
        course_id=course_cs401.id,
        module_id=modules_cs401[1].id,
        title="Session 02: Raft Consensus Invariants, Quorum Slices & Leader Election",
        session_type="Lecture",
        scheduled_start=s2_start,
        scheduled_end=s2_end,
        actual_start=s2_start,
        actual_end=None,
        status="in_progress",
        virtual_room_code="GATE-CS401-02",
        room_security_config=json.dumps({"restrict_to_enrolled": True, "require_institutional_email": True, "grace_period_mins": 10}),
        recording_url=None,
        recording_status="none",
        recording_duration_mins=0,
        recording_notes="Live recording actively buffering to university media storage.",
        created_by_id=prof_alan.id
    )

    # Session 3: Upcoming scheduled session for CS401
    s3_start = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    s3_end = tomorrow.replace(hour=11, minute=30, second=0, microsecond=0)
    session_upcoming = LectureSession(
        course_id=course_cs401.id,
        module_id=modules_cs401[2].id,
        title="Session 03: Practical Byzantine Fault Tolerance (PBFT) & Cryptographic Quorums",
        session_type="Lecture",
        scheduled_start=s3_start,
        scheduled_end=s3_end,
        actual_start=None,
        actual_end=None,
        status="scheduled",
        virtual_room_code="GATE-CS401-03",
        room_security_config=json.dumps({"restrict_to_enrolled": True, "require_institutional_email": True, "grace_period_mins": 10}),
        created_by_id=prof_alan.id
    )

    # Session 4: AI502 Seminar Session
    s4_start = next_week.replace(hour=14, minute=0, second=0, microsecond=0)
    s4_end = next_week.replace(hour=16, minute=0, second=0, microsecond=0)
    session_ai_seminar = LectureSession(
        course_id=course_ai502.id,
        module_id=modules_ai502[0].id,
        title="Institutional Seminar: Attention Optimization, FlashAttention-3 & Linear Attention",
        session_type="Seminar",
        scheduled_start=s4_start,
        scheduled_end=s4_end,
        actual_start=None,
        actual_end=None,
        status="scheduled",
        virtual_room_code="GATE-AI502-01",
        room_security_config=json.dumps({"restrict_to_enrolled": False, "require_institutional_email": True, "grace_period_mins": 15}),
        created_by_id=prof_clara.id
    )

    db_session.add_all([session_past, session_live, session_upcoming, session_ai_seminar])
    db_session.commit()

    # 8. Session Co-Hosts
    cohost_1 = SessionCoHost(session_id=session_live.id, user_id=ta_alex.id, host_role="teaching_assistant")
    cohost_2 = SessionCoHost(session_id=session_live.id, user_id=users_data[3].id, host_role="guest_lecturer") # Prof Marcus Brody as guest scholar
    db_session.add_all([cohost_1, cohost_2])
    db_session.commit()

    # 9. Attendance Records for Completed Session (Session 1)
    # Student 0 (Jordan): on-time, full attendance
    att_1 = AttendanceRecord(
        session_id=session_past.id,
        student_id=students[0].id,
        first_join_time=s1_start + datetime.timedelta(minutes=2),
        last_exit_time=s1_end - datetime.timedelta(minutes=1),
        total_duration_minutes=87.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=96.7,
        automated_status="present",
        verified_status="present",
        registrar_compliance_flag=True
    )
    # Student 1 (Maya): late arrival (entered 18 mins after start > 10 min grace period)
    att_2 = AttendanceRecord(
        session_id=session_past.id,
        student_id=students[1].id,
        first_join_time=s1_start + datetime.timedelta(minutes=18),
        last_exit_time=s1_end,
        total_duration_minutes=72.0,
        is_late=True,
        late_minutes=18.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=80.0,
        automated_status="late",
        verified_status="late",
        registrar_compliance_flag=True
    )
    # Student 2 (Liam): early disconnection (disconnected 25 mins early)
    att_3 = AttendanceRecord(
        session_id=session_past.id,
        student_id=students[2].id,
        first_join_time=s1_start + datetime.timedelta(minutes=1),
        last_exit_time=s1_end - datetime.timedelta(minutes=25),
        total_duration_minutes=64.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=True,
        early_exit_minutes=25.0,
        lecture_coverage_pct=71.1,
        automated_status="partial",
        verified_status="partial",
        registrar_compliance_flag=False
    )
    # Student 3 (Sophia): Excused absence with medical leave override
    att_4 = AttendanceRecord(
        session_id=session_past.id,
        student_id=students[3].id,
        first_join_time=None,
        last_exit_time=None,
        total_duration_minutes=0.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=0.0,
        automated_status="absent",
        verified_status="excused",
        verified_by_id=prof_alan.id,
        verification_reason="Validated official clinic medical certificate for acute bronchitis (DOC-MED-4482).",
        verified_at=yesterday,
        registrar_compliance_flag=True
    )
    # Student 4 (Lucas): unexcused absence
    att_5 = AttendanceRecord(
        session_id=session_past.id,
        student_id=students[4].id,
        first_join_time=None,
        last_exit_time=None,
        total_duration_minutes=0.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=0.0,
        automated_status="absent",
        verified_status="absent",
        registrar_compliance_flag=False
    )
    # Student 5 (Emma): on-time, full attendance
    att_6 = AttendanceRecord(
        session_id=session_past.id,
        student_id=students[5].id,
        first_join_time=s1_start,
        last_exit_time=s1_end,
        total_duration_minutes=90.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=100.0,
        automated_status="present",
        verified_status="present",
        registrar_compliance_flag=True
    )
    db_session.add_all([att_1, att_2, att_3, att_4, att_5, att_6])

    # 10. Live Session Attendance (Session 2 in progress)
    live_att_1 = AttendanceRecord(
        session_id=session_live.id,
        student_id=students[0].id,
        first_join_time=s2_start + datetime.timedelta(minutes=1),
        last_exit_time=None,
        total_duration_minutes=34.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=100.0,
        automated_status="present",
        verified_status="pending",
        registrar_compliance_flag=True
    )
    live_att_2 = AttendanceRecord(
        session_id=session_live.id,
        student_id=students[1].id,
        first_join_time=s2_start + datetime.timedelta(minutes=3),
        last_exit_time=None,
        total_duration_minutes=32.0,
        is_late=False,
        late_minutes=0.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=95.0,
        automated_status="present",
        verified_status="pending",
        registrar_compliance_flag=True
    )
    live_att_3 = AttendanceRecord(
        session_id=session_live.id,
        student_id=students[2].id,
        first_join_time=s2_start + datetime.timedelta(minutes=14),
        last_exit_time=None,
        total_duration_minutes=21.0,
        is_late=True,
        late_minutes=14.0,
        is_early_exit=False,
        early_exit_minutes=0.0,
        lecture_coverage_pct=61.8,
        automated_status="late",
        verified_status="pending",
        registrar_compliance_flag=True
    )
    db_session.add_all([live_att_1, live_att_2, live_att_3])
    db_session.commit()

    # 11. Session Entrance Logs (Module 7 & Module 2 tracking)
    entrance_logs = [
        SessionEntranceLog(session_id=session_live.id, user_id=students[0].id, event_type="joined", timestamp=s2_start + datetime.timedelta(minutes=1), ip_address="192.168.10.15", user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128.0", details="Passed institutional gate check."),
        SessionEntranceLog(session_id=session_live.id, user_id=students[1].id, event_type="joined", timestamp=s2_start + datetime.timedelta(minutes=3), ip_address="192.168.10.22", user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)", details="Institutional Single-Sign-On verified."),
        SessionEntranceLog(session_id=session_live.id, user_id=students[2].id, event_type="gate_attempt", timestamp=s2_start + datetime.timedelta(minutes=13), ip_address="192.168.12.80", details="Gate authentication request."),
        SessionEntranceLog(session_id=session_live.id, user_id=students[2].id, event_type="joined", timestamp=s2_start + datetime.timedelta(minutes=14), ip_address="192.168.12.80", details="Entered virtual classroom; flagged as Late (+14m)."),
        SessionEntranceLog(session_id=session_past.id, user_id=students[2].id, event_type="disconnected", timestamp=s1_end - datetime.timedelta(minutes=25), ip_address="192.168.12.80", disconnection_reason="network_timeout", details="TCP connection dropped abruptly before dismissal.")
    ]
    db_session.add_all(entrance_logs)
    db_session.commit()

    # 12. Leave Requests & Note Proxy Pairing (Module 3)
    leave_req_1 = LeaveRequest(
        student_id=students[3].id, # Sophia
        course_id=course_cs401.id,
        session_id=session_past.id,
        category="medical",
        start_date=s1_start,
        end_date=s1_end,
        reason="Acute upper respiratory infection and medical bedrest prescribed by University Health Service.",
        document_filename="Medical_Certificate_DrLau_UHS_4482.pdf",
        document_url="/uploads/Medical_Certificate_DrLau_UHS_4482.pdf",
        document_type="application/pdf",
        status="approved",
        reviewed_by_id=prof_alan.id,
        review_comment="Official UHS certificate confirmed. Attendance verified as excused; note proxy assigned.",
        reviewed_at=yesterday,
        note_proxy_id=students[0].id, # Jordan assigned as note proxy
        proxy_notes_delivered=True
    )

    leave_req_2 = LeaveRequest(
        student_id=students[4].id, # Lucas
        course_id=course_cs401.id,
        session_id=session_upcoming.id,
        category="university_competition",
        start_date=tomorrow,
        end_date=tomorrow + datetime.timedelta(days=2),
        reason="Representing University Varsity Debate Team at National Invitational Championship in Chicago.",
        document_filename="Athletics_Debate_Dean_Sanction_Letter.pdf",
        document_url="/uploads/Athletics_Debate_Dean_Sanction_Letter.pdf",
        document_type="application/pdf",
        status="pending",
        reviewed_by_id=None,
        note_proxy_id=students[1].id, # Maya proposed as note proxy
        proxy_notes_delivered=False
    )
    db_session.add_all([leave_req_1, leave_req_2])
    db_session.commit()

    # 13. Lecture MOM & Structured Study Notes (Module 4)
    mom_past = LectureMOM(
        session_id=session_past.id,
        title="Official MOM: Module 1 - Asynchronous Systems & Causality Invariants",
        topic_summary="Systematic proof of Lamport's happens-before relation (->). We analyzed how partial orderings resolve non-deterministic message delivery in network models with unbounded latency. Evaluated vector clock algorithms where each node i maintains vector V_i.",
        formulas_and_theorems="1. Lamport Invariant: If a -> b, then C(a) < C(b).\n2. Vector Clock Update Rule: On send(m): V_i[i] = V_i[i] + 1; On receive(m, V_m): V_i[k] = max(V_i[k], V_m[k]) for all k, then V_i[i] = V_i[i] + 1.\n3. Quorum Intersection Property: Q_1 ∩ Q_2 ≠ ∅ for any quorums of size > N/2.",
        key_takeaways="• Clock synchronization via physical clocks (NTP) cannot guarantee strict event ordering in safety-critical distributed algorithms.\n• Vector clocks require O(N) storage where N is process count, prompting modern systems to use hybrid logical clocks (HLC).\n• Consistency models establish the contract between concurrent writes and read visibility.",
        ta_supplementary_notes="TA Alex Chen Note: Please review Homework 1 Problem 3 regarding the transitive reduction of vector clock posets. Office hours held Thursdays 2-4 PM in Turing Lab 204.",
        status="locked", # Sealed upon conclusion of module
        version=2,
        created_by_id=prof_alan.id,
        last_edited_by_id=ta_alex.id,
        published_at=two_days_ago + datetime.timedelta(hours=4),
        locked_at=yesterday,
        locked_by_id=prof_alan.id
    )

    mom_live = LectureMOM(
        session_id=session_live.id,
        title="Draft MOM: Module 2 - Raft Consensus & Log Replication",
        topic_summary="Analyzing leader election in Raft. Discussion on randomized election timeouts [150ms, 300ms] to avoid split votes. Deconstructed how candidate requests votes with RequestVote RPC.",
        formulas_and_theorems="Leader Election Condition: votes >= floor(N/2) + 1.\nLog Matching Property: If two logs contain an entry with the same index and term, then the logs are identical in all entries up through the given index.",
        key_takeaways="• Raft decomposes consensus into Leader Election, Log Replication, and Safety Invariants.\n• Only candidates with up-to-date logs can receive majority quorum approvals.",
        ta_supplementary_notes="Live co-editing by TA Alex: Adding diagrams of split-vote resolution scenarios.",
        status="draft",
        version=1,
        created_by_id=prof_alan.id,
        last_edited_by_id=ta_alex.id
    )
    db_session.add_all([mom_past, mom_live])
    db_session.commit()

    # MOM Edits history
    edit_1 = LectureMOMEdit(mom_id=mom_past.id, editor_id=prof_alan.id, editor_role="Professor", change_summary="Drafted initial lecture minutes and Lamport Invariant proofs.")
    edit_2 = LectureMOMEdit(mom_id=mom_past.id, editor_id=ta_alex.id, editor_role="Teaching Assistant", change_summary="Added TA supplementary notes on HW1 vector clock posets.")
    edit_3 = LectureMOMEdit(mom_id=mom_past.id, editor_id=prof_alan.id, editor_role="Professor", change_summary="Published official syllabus MOM and sealed lock against edits.")
    db_session.add_all([edit_1, edit_2, edit_3])

    # Slide Attachments
    att_slide_1 = LectureAttachment(
        session_id=session_past.id,
        mom_id=mom_past.id,
        file_name="CS401_Lec01_Logical_Clocks_Vector_Posets.pdf",
        file_url="https://courseware.university.edu/cs401/slides/CS401_Lec01.pdf",
        file_type="application/pdf",
        file_size_kb=3420,
        uploaded_by_id=prof_alan.id
    )
    att_slide_2 = LectureAttachment(
        session_id=session_live.id,
        mom_id=mom_live.id,
        file_name="CS401_Lec02_Raft_Consensus_State_Machine.pdf",
        file_url="https://courseware.university.edu/cs401/slides/CS401_Lec02.pdf",
        file_type="application/pdf",
        file_size_kb=4810,
        uploaded_by_id=prof_alan.id
    )
    db_session.add_all([att_slide_1, att_slide_2])
    db_session.commit()

    # 14. Live In-Class Quizzes & Concept Polls (Module 5)
    # Quiz 1: Completed Quiz on Session 1
    q1_questions = [
        {
            "id": 1,
            "question": "In a distributed system, if event A causally precedes event B (A -> B), what is strictly guaranteed by Lamport timestamps C?",
            "options": [
                "C(A) < C(B)",
                "C(A) > C(B)",
                "C(A) == C(B)",
                "No ordering can be inferred without physical GPS synchrony"
            ],
            "correct_answer": "C(A) < C(B)",
            "explanation": "The Clock Condition dictates that if A -> B, then C(A) must be strictly less than C(B). The converse is not necessarily true.",
            "points": 5
        },
        {
            "id": 2,
            "question": "True or False: Vector Clocks can detect whether two events are concurrent without requiring total physical clock synchrony.",
            "options": ["True", "False"],
            "correct_answer": "True",
            "explanation": "If neither V(A) <= V(B) nor V(B) <= V(A), events A and B are definitively concurrent (A || B).",
            "points": 5
        }
    ]
    quiz_past = LiveQuiz(
        session_id=session_past.id,
        title="Check-in Quiz 01: Logical Clocks & Concurrent Event Detection",
        prompt_type="multiple_choice",
        status="closed",
        questions_json=json.dumps(q1_questions),
        time_limit_seconds=90,
        launched_at=s1_start + datetime.timedelta(minutes=45),
        closed_at=s1_start + datetime.timedelta(minutes=47),
        total_points=10,
        created_by_id=prof_alan.id
    )
    db_session.add(quiz_past)
    db_session.commit()

    # Quiz 1 Responses
    resp_1 = QuizResponse(quiz_id=quiz_past.id, student_id=students[0].id, answers_json=json.dumps({"1": "C(A) < C(B)", "2": "True"}), latency_ms=1120, score=10.0, max_score=10.0, percentage=100.0, is_passed=True, gradebook_exported=True)
    resp_2 = QuizResponse(quiz_id=quiz_past.id, student_id=students[1].id, answers_json=json.dumps({"1": "C(A) < C(B)", "2": "False"}), latency_ms=2340, score=5.0, max_score=10.0, percentage=50.0, is_passed=False, gradebook_exported=True)
    resp_3 = QuizResponse(quiz_id=quiz_past.id, student_id=students[2].id, answers_json=json.dumps({"1": "C(A) < C(B)", "2": "True"}), latency_ms=1890, score=10.0, max_score=10.0, percentage=100.0, is_passed=True, gradebook_exported=True)
    resp_6 = QuizResponse(quiz_id=quiz_past.id, student_id=students[5].id, answers_json=json.dumps({"1": "C(A) < C(B)", "2": "True"}), latency_ms=980, score=10.0, max_score=10.0, percentage=100.0, is_passed=True, gradebook_exported=True)
    db_session.add_all([resp_1, resp_2, resp_3, resp_6])

    # Quiz 2: Active / Live Quiz on Session 2 (In-Class Concept Check)
    q2_questions = [
        {
            "id": 1,
            "question": "What is the primary architectural purpose of utilizing randomized election timeouts in the Raft consensus protocol?",
            "options": [
                "To prevent split-vote deadlocks where multiple candidates split the quorum equally",
                "To reduce cryptographic hashing overhead across peer nodes",
                "To force client RPC requests to wait for disk log flushes",
                "To ensure Byzantine nodes are permanently ejected from the ring"
            ],
            "correct_answer": "To prevent split-vote deadlocks where multiple candidates split the quorum equally",
            "explanation": "Randomizing election timeouts between e.g. 150-300ms ensures that one candidate usually times out before others, successfully gathering majority votes without collision.",
            "points": 5
        },
        {
            "id": 2,
            "question": "In a 5-node Raft cluster, what is the minimum quorum of servers required to elect a leader and commit a log entry?",
            "options": ["2 nodes", "3 nodes", "4 nodes", "5 nodes (unanimous)"],
            "correct_answer": "3 nodes",
            "explanation": "Majority quorum is defined as floor(N/2) + 1. For N=5, floor(5/2) + 1 = 3 nodes.",
            "points": 5
        }
    ]
    quiz_live = LiveQuiz(
        session_id=session_live.id,
        title="Live Concept Poll: Raft Leader Election & Quorum Safety Invariants",
        prompt_type="multiple_choice",
        status="launched",
        questions_json=json.dumps(q2_questions),
        time_limit_seconds=60,
        launched_at=now - datetime.timedelta(seconds=25),
        closed_at=None,
        total_points=10,
        created_by_id=prof_alan.id
    )
    db_session.add(quiz_live)
    db_session.commit()

    # 15. Activity Log & Audit Trail (Module 7)
    audit_entries = [
        AuditLog(
            actor_id=prof_alan.id,
            actor_name=prof_alan.name,
            actor_role="Professor",
            event_type="attendance_override",
            target_entity="AttendanceRecord",
            target_id=att_4.id,
            course_id=course_cs401.id,
            change_before=json.dumps({"automated_status": "absent", "verified_status": "pending"}),
            change_after=json.dumps({"verified_status": "excused", "justification": "Doctor certificate validated"}),
            justification="Student submitted accredited University Health Service medical note (DOC-MED-4482) for bronchitis.",
            ip_address="192.168.1.101"
        ),
        AuditLog(
            actor_id=prof_alan.id,
            actor_name=prof_alan.name,
            actor_role="Professor",
            event_type="note_locked",
            target_entity="LectureMOM",
            target_id=mom_past.id,
            course_id=course_cs401.id,
            change_before=json.dumps({"status": "published"}),
            change_after=json.dumps({"status": "locked"}),
            justification="Module 1 syllabus period concluded. MOM sealed against further TA or student modifications.",
            ip_address="192.168.1.101"
        ),
        AuditLog(
            actor_id=dean.id,
            actor_name=dean.name,
            actor_role="Dean",
            event_type="role_permission_update",
            target_entity="TAPermissionScope",
            target_id=ta_scope_cs401.id,
            course_id=course_cs401.id,
            change_before=json.dumps({"can_publish_grades": False}),
            change_after=json.dumps({"can_publish_grades": False}),
            justification="Institutional policy enforcement: Grade publishing restricted exclusively to primary faculty.",
            ip_address="192.168.0.5"
        ),
        AuditLog(
            actor_id=prof_alan.id,
            actor_name=prof_alan.name,
            actor_role="Professor",
            event_type="quiz_gradebook_export",
            target_entity="LiveQuiz",
            target_id=quiz_past.id,
            course_id=course_cs401.id,
            change_before="{}",
            change_after=json.dumps({"status": "closed", "exported_count": 4}),
            justification="Synchronized Check-in Quiz 01 scores to Registrar Gradebook database.",
            ip_address="192.168.1.101"
        )
    ]
    db_session.add_all(audit_entries)
    db_session.commit()

    print("Institutional Database successfully seeded!")
    print(f"Users created: {len(users_data)}")
    print(f"Courses: 2 ({course_cs401.code}, {course_ai502.code})")
    print(f"Sessions: 4 (1 completed, 1 in-progress, 2 scheduled)")
    print("MOM Notes, Attendance Records, Quizzes, Leaves, and Audit Logs primed.")

if __name__ == "__main__":
    seed_database()
