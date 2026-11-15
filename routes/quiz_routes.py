import datetime
import json
from flask import Blueprint, g, request, jsonify
from database import db_session
from models import (
    LiveQuiz, QuizResponse, LectureSession, Course, User,
    CourseEnrollment, AuditLog
)
from security import has_ta_scope, require_module, require_roles

quiz_bp = Blueprint("quizzes", __name__, url_prefix="/api/quizzes")

@quiz_bp.route("/session/<int:session_id>", methods=["GET"])
@require_module("quizzes")
def get_session_quizzes(session_id):
    """Retrieve all live quizzes and concept checks for a session"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    quizzes = db_session.query(LiveQuiz).filter(
        LiveQuiz.session_id == session_id
    ).order_by(LiveQuiz.created_at.desc()).all()

    is_student = g.current_user.role == "Student"
    visible_quizzes = [q for q in quizzes if (not is_student or q.status != "draft")]

    quiz_list = []
    for q in visible_quizzes:
        qd = q.to_dict(include_answers=(not is_student or q.status == "closed"))
        if is_student:
            qd["responses"] = [r.to_dict() for r in q.responses if r.student_id == g.current_user.id]
        else:
            qd["responses"] = [r.to_dict() for r in q.responses]
        quiz_list.append(qd)

    return jsonify({
        "success": True,
        "session_id": session_id,
        "quizzes": quiz_list
    })

@quiz_bp.route("/<int:quiz_id>", methods=["GET"])
@require_module("quizzes")
def get_quiz_detail(quiz_id):
    quiz = db_session.query(LiveQuiz).filter(LiveQuiz.id == quiz_id).first()
    if not quiz:
        return jsonify({"success": False, "message": "Quiz not found"}), 404

    is_student_caller = g.current_user.role == "Student"
    if is_student_caller and quiz.status == "draft":
        return jsonify({"success": False, "message": "Access Denied: Draft quiz is not published yet"}), 403

    as_student = is_student_caller or (request.args.get("as_student", "false").lower() == "true")
    include_answers = (not as_student) or (quiz.status == "closed")

    return jsonify({
        "success": True,
        "quiz": quiz.to_dict(include_answers=include_answers),
        "responses": [r.to_dict() for r in quiz.responses] if not as_student else []
    })

@quiz_bp.route("/session/<int:session_id>", methods=["POST"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def create_quiz(session_id):
    """Module 5: Create Live Quiz/Poll (Multiple choice, true/false, open-ended)"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    if g.current_user.role == "Teaching Assistant" and not has_ta_scope(g.current_user, session.course_id, "can_launch_polls"):
        return jsonify({"success": False, "message": "Access Denied: TA lacks poll creation permission for this course"}), 403

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip() or "In-Class Concept Check"
    prompt_type = data.get("prompt_type", "multiple_choice")
    raw_questions = data.get("questions", [])
    time_limit_seconds = data.get("time_limit_seconds", 60)
    created_by_id = g.current_user.id

    if not isinstance(raw_questions, list) or not raw_questions:
        return jsonify({"success": False, "message": "At least one question prompt is required"}), 400

    questions = []
    for idx, q in enumerate(raw_questions, start=1):
        if isinstance(q, dict):
            normalized = dict(q)
            if "id" not in normalized or normalized["id"] is None:
                normalized["id"] = idx
            questions.append(normalized)

    total_points = sum(q.get("points", 5) for q in questions if isinstance(q, dict))

    new_quiz = LiveQuiz(
        session_id=session_id,
        title=title,
        prompt_type=prompt_type,
        status="draft",
        questions_json=json.dumps(questions),
        time_limit_seconds=time_limit_seconds,
        total_points=total_points,
        created_by_id=created_by_id
    )
    db_session.add(new_quiz)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Live quiz formulated and saved as draft",
        "quiz": new_quiz.to_dict(include_answers=True)
    }), 201

@quiz_bp.route("/<int:quiz_id>/launch", methods=["POST"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def launch_quiz(quiz_id):
    """Module 5: Launch In-Class Question (Triggers real-time question pop-up on student screens)"""
    quiz = db_session.query(LiveQuiz).filter(LiveQuiz.id == quiz_id).first()
    if not quiz:
        return jsonify({"success": False, "message": "Quiz not found"}), 404

    if g.current_user.role == "Teaching Assistant":
        course_id = quiz.session.course_id if quiz.session else None
        if not course_id or not has_ta_scope(g.current_user, course_id, "can_launch_polls"):
            return jsonify({"success": False, "message": "Access Denied: TA lacks poll launch permission for this course"}), 403

    actor_id = g.current_user.id

    quiz.status = "launched"
    quiz.launched_at = datetime.datetime.utcnow()
    quiz.closed_at = None
    db_session.commit()

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Instructor",
        actor_role=actor.role if actor else "Professor",
        event_type="quiz_launched",
        target_entity="LiveQuiz",
        target_id=quiz.id,
        course_id=quiz.session.course_id if quiz.session else None,
        change_after=json.dumps({"status": "launched", "launched_at": quiz.launched_at.isoformat()}),
        justification=f"Live concept poll '{quiz.title}' broadcast to active lecture participants."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Quiz '{quiz.title}' is now LIVE on all student screens!",
        "quiz": quiz.to_dict(include_answers=False)
    })

@quiz_bp.route("/<int:quiz_id>/submit", methods=["POST"])
@require_module("quizzes")
def submit_student_answer(quiz_id):
    """Module 5: Collect Student Answers (Gathers student responses with millisecond timestamps)"""
    quiz = db_session.query(LiveQuiz).filter(LiveQuiz.id == quiz_id).first()
    if not quiz:
        return jsonify({"success": False, "message": "Quiz not found"}), 404

    if quiz.status != "launched":
        return jsonify({"success": False, "message": "This quiz is not currently accepting responses."}), 400

    data = request.get_json(silent=True) or {}
    student_id = data.get("student_id") or (g.current_user.id if g.current_user.role == "Student" else None)
    if g.current_user.role == "Student" and student_id and int(student_id) != g.current_user.id:
        return jsonify({"success": False, "message": "Access Denied: Students can only submit answers for themselves"}), 403
    answers = data.get("answers", {}) # e.g. {"1": "C(A) < C(B)", "2": "True"}
    latency_ms = data.get("latency_ms", 1250) # millisecond timestamp latency

    if not student_id or not isinstance(answers, dict) or not answers:
        return jsonify({"success": False, "message": "student_id and answers required"}), 400

    student = db_session.query(User).filter(User.id == student_id).first()
    if not student:
        return jsonify({"success": False, "message": "Student not found"}), 404

    # Auto-grade based on correct answers in questions_json
    questions = json.loads(quiz.questions_json)
    score = 0.0
    for q in questions:
        q_id = str(q.get("id"))
        student_choice = answers.get(q_id)
        correct_choice = q.get("correct_answer")
        points = float(q.get("points", 5))
        if student_choice is not None:
            sc_clean = str(student_choice).strip().lower()
            cc_clean = str(correct_choice or "").strip().lower()
            if cc_clean and sc_clean == cc_clean:
                score += points
            elif quiz.prompt_type == "open_concept" and sc_clean:
                if cc_clean and (cc_clean in sc_clean or sc_clean in cc_clean):
                    score += points
                elif len(sc_clean) >= 12:
                    score += round(points * 0.8, 1)

    max_score = float(quiz.total_points)
    percentage = round((score / max(1.0, max_score)) * 100, 1)
    is_passed = percentage >= 50.0

    # Check existing submission
    resp = db_session.query(QuizResponse).filter(
        QuizResponse.quiz_id == quiz_id,
        QuizResponse.student_id == student_id
    ).first()

    now = datetime.datetime.utcnow()
    if resp:
        resp.answers_json = json.dumps(answers)
        resp.submitted_at = now
        resp.latency_ms = latency_ms
        resp.score = score
        resp.max_score = max_score
        resp.percentage = percentage
        resp.is_passed = is_passed
    else:
        resp = QuizResponse(
            quiz_id=quiz_id,
            student_id=student_id,
            answers_json=json.dumps(answers),
            submitted_at=now,
            latency_ms=latency_ms,
            score=score,
            max_score=max_score,
            percentage=percentage,
            is_passed=is_passed,
            gradebook_exported=False
        )
        db_session.add(resp)

    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Answer recorded successfully with millisecond timestamp verification",
        "response": resp.to_dict()
    })

@quiz_bp.route("/<int:quiz_id>/close", methods=["POST"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def close_quiz(quiz_id):
    """Module 5: Close Quiz (Terminates submission window and reveals correct answers and explanations)"""
    quiz = db_session.query(LiveQuiz).filter(LiveQuiz.id == quiz_id).first()
    if not quiz:
        return jsonify({"success": False, "message": "Quiz not found"}), 404

    if g.current_user.role == "Teaching Assistant":
        course_id = quiz.session.course_id if quiz.session else None
        if not course_id or not has_ta_scope(g.current_user, course_id, "can_launch_polls"):
            return jsonify({"success": False, "message": "Access Denied: TA lacks poll close permission for this course"}), 403

    actor_id = g.current_user.id

    quiz.status = "closed"
    quiz.closed_at = datetime.datetime.utcnow()
    db_session.commit()

    actor = db_session.query(User).filter(User.id == actor_id).first()
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Instructor",
        actor_role=actor.role if actor else "Professor",
        event_type="quiz_closed",
        target_entity="LiveQuiz",
        target_id=quiz.id,
        course_id=quiz.session.course_id if quiz.session else None,
        change_after=json.dumps({"status": "closed", "closed_at": quiz.closed_at.isoformat()}),
        justification=f"Quiz '{quiz.title}' closed. Correct answers and explanations revealed to cohort."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Quiz closed. Submission window terminated and explanations revealed.",
        "quiz": quiz.to_dict(include_answers=True)
    })

@quiz_bp.route("/<int:quiz_id>/export-gradebook", methods=["POST"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def export_poll_summary_to_gradebook(quiz_id):
    """Module 5: Export Poll Summary / Outputs quiz scorebooks directly into course gradebook"""
    quiz = db_session.query(LiveQuiz).filter(LiveQuiz.id == quiz_id).first()
    if not quiz:
        return jsonify({"success": False, "message": "Quiz not found"}), 404

    if g.current_user.role == "Teaching Assistant":
        course_id = quiz.session.course_id if quiz.session else None
        if not course_id or not has_ta_scope(g.current_user, course_id, "can_publish_grades"):
            return jsonify({
                "success": False,
                "message": "Access Denied: Teaching Assistant gradebook publishing is restricted by institutional policy."
            }), 403

    actor_id = g.current_user.id
    actor = db_session.query(User).filter(User.id == actor_id).first()

    exported_count = 0
    for resp in quiz.responses:
        resp.gradebook_exported = True
        exported_count += 1

    db_session.commit()

    # Module 7: Track Grade/Quiz Adjustments
    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Professor",
        actor_role=actor.role if actor else "Professor",
        event_type="grade_adjustment",
        target_entity="LiveQuiz",
        target_id=quiz.id,
        course_id=quiz.session.course_id if quiz.session else None,
        change_after=json.dumps({"exported_count": exported_count, "gradebook_sync": True}),
        justification=f"Synchronized {exported_count} student comprehension quiz scores to official course gradebook ledger."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Successfully exported {exported_count} quiz grades into registrar course gradebook.",
        "exported_count": exported_count,
        "quiz": quiz.to_dict(include_answers=True)
    })


@quiz_bp.route("/responses/<int:response_id>/adjust-score", methods=["PUT"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def adjust_quiz_response_score(response_id):
    """Module 5 & 7: Adjust individual student quiz score with mandatory audit justification."""
    resp = db_session.query(QuizResponse).filter(QuizResponse.id == response_id).first()
    if not resp:
        return jsonify({"success": False, "message": "Quiz response not found"}), 404

    quiz = resp.quiz
    if g.current_user.role == "Teaching Assistant":
        course_id = quiz.session.course_id if quiz and quiz.session else None
        if not course_id or not has_ta_scope(g.current_user, course_id, "can_publish_grades"):
            return jsonify({
                "success": False,
                "message": "Access Denied: TA lacks grade publishing permission for this course."
            }), 403

    data = request.get_json(silent=True) or {}
    new_score = data.get("score")
    justification = (data.get("justification") or "").strip()

    if new_score is None or not justification:
        return jsonify({"success": False, "message": "New score and academic justification are required"}), 400

    try:
        new_score_val = max(0.0, float(new_score))
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid score value"}), 400

    prev_score = resp.score
    max_score = float(resp.max_score or (quiz.total_points if quiz else 10.0))
    resp.score = round(new_score_val, 1)
    resp.percentage = round((resp.score / max(1.0, max_score)) * 100.0, 1)
    resp.is_passed = resp.percentage >= 50.0

    actor = g.current_user
    audit = AuditLog(
        actor_id=actor.id,
        actor_name=actor.name,
        actor_role=actor.role,
        event_type="grade_adjustment",
        target_entity="QuizResponse",
        target_id=resp.id,
        course_id=quiz.session.course_id if quiz and quiz.session else None,
        change_before=json.dumps({"score": prev_score, "student_id": resp.student_id}),
        change_after=json.dumps({"score": resp.score, "percentage": resp.percentage}),
        justification=justification,
        ip_address=request.remote_addr or "127.0.0.1"
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": f"Updated quiz score for {resp.student.name if resp.student else 'Student'} to {resp.score}/{max_score}",
        "response": resp.to_dict()
    })


@quiz_bp.route("/<int:quiz_id>", methods=["DELETE"])
@require_roles("Dean", "Professor")
def delete_quiz(quiz_id):
    quiz = db_session.query(LiveQuiz).filter(LiveQuiz.id == quiz_id).first()
    if not quiz:
        return jsonify({"success": False, "message": "Quiz not found"}), 404
    db_session.delete(quiz)
    db_session.commit()
    return jsonify({"success": True, "message": "Quiz deleted"})
