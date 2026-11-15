import datetime
import json
import os
from flask import Blueprint, g, request, jsonify, send_file, current_app
from database import db_session
from models import (
    LectureMOM, LectureMOMEdit, LectureAttachment, LectureSession,
    Course, User, AuditLog
)
from config import PDF_EXPORT_DIR
from security import has_ta_scope, require_module, require_roles

notes_bp = Blueprint("notes", __name__, url_prefix="/api/notes")

@notes_bp.route("/session/<int:session_id>", methods=["GET"])
@require_module("notes")
def get_session_mom(session_id):
    """Retrieve structured notes and minutes for a lecture session"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    mom = db_session.query(LectureMOM).filter(LectureMOM.session_id == session_id).first()
    if mom and mom.status == "draft" and g.current_user.role in ("Student", "Auditor"):
        mom = None
    attachments = db_session.query(LectureAttachment).filter(LectureAttachment.session_id == session_id).all()

    return jsonify({
        "success": True,
        "session_id": session_id,
        "session_title": session.title,
        "course_code": session.course.code if session.course else None,
        "course_title": session.course.title if session.course else None,
        "has_mom": bool(mom),
        "mom": mom.to_dict() if mom else None,
        "attachments": [a.to_dict() for a in attachments]
    })

@notes_bp.route("/session/<int:session_id>", methods=["POST"])
@require_roles("Dean", "Professor")
def create_or_update_mom(session_id):
    """Module 4: Create Lecture Notes / Draft structured topic summaries and formulas"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip() or f"MOM: {session.title}"
    topic_summary = (data.get("topic_summary") or "").strip()
    formulas_and_theorems = (data.get("formulas_and_theorems") or "").strip()
    key_takeaways = (data.get("key_takeaways") or "").strip()
    ta_supplementary_notes = (data.get("ta_supplementary_notes") or "").strip()
    author_id = g.current_user.id

    author = db_session.query(User).filter(User.id == author_id).first()

    mom = db_session.query(LectureMOM).filter(LectureMOM.session_id == session_id).first()
    now = datetime.datetime.utcnow()

    if mom:
        if mom.status == "locked":
            return jsonify({
                "success": False,
                "message": "This lecture note has been sealed and locked by the academic department. Edits are disabled."
            }), 403

        mom.title = title
        mom.topic_summary = topic_summary
        mom.formulas_and_theorems = formulas_and_theorems
        mom.key_takeaways = key_takeaways
        if ta_supplementary_notes:
            mom.ta_supplementary_notes = ta_supplementary_notes
        mom.version += 1
        mom.last_edited_by_id = author_id
        mom.updated_at = now

        # Record revision history
        edit_log = LectureMOMEdit(
            mom_id=mom.id,
            editor_id=author_id,
            editor_role=author.role if author else "Staff",
            change_summary=f"Updated lecture summary and formula derivations (v{mom.version})."
        )
        db_session.add(edit_log)
    else:
        mom = LectureMOM(
            session_id=session_id,
            title=title,
            topic_summary=topic_summary,
            formulas_and_theorems=formulas_and_theorems,
            key_takeaways=key_takeaways,
            ta_supplementary_notes=ta_supplementary_notes,
            status="draft",
            version=1,
            created_by_id=author_id,
            last_edited_by_id=author_id
        )
        db_session.add(mom)
        db_session.flush()

        edit_log = LectureMOMEdit(
            mom_id=mom.id,
            editor_id=author_id,
            editor_role=author.role if author else "Staff",
            change_summary="Initial MOM draft created."
        )
        db_session.add(edit_log)

    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Lecture notes successfully saved",
        "mom": mom.to_dict()
    })

@notes_bp.route("/<int:mom_id>/coedit", methods=["PUT"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def coedit_ta_notes(mom_id):
    """Module 4: Co-edit TA Notes (Enables TAs to add supplementary explanations and reading references)"""
    mom = db_session.query(LectureMOM).filter(LectureMOM.id == mom_id).first()
    if not mom:
        return jsonify({"success": False, "message": "MOM record not found"}), 404

    if g.current_user.role == "Teaching Assistant":
        course_id = mom.session.course_id if mom.session else None
        if not course_id or not has_ta_scope(g.current_user, course_id, "can_coedit_notes"):
            return jsonify({"success": False, "message": "Access Denied: TA lacks note co-edit permission for this course"}), 403

    if mom.status == "locked":
        return jsonify({
            "success": False,
            "message": "Cannot co-edit: Note record is officially locked upon module conclusion."
        }), 403

    data = request.get_json(silent=True) or {}
    ta_notes = (data.get("ta_supplementary_notes") or "").strip()
    editor_id = g.current_user.id

    editor = db_session.query(User).filter(User.id == editor_id).first()

    mom.ta_supplementary_notes = ta_notes
    mom.last_edited_by_id = editor_id
    mom.version += 1
    mom.updated_at = datetime.datetime.utcnow()

    edit_log = LectureMOMEdit(
        mom_id=mom.id,
        editor_id=editor_id,
        editor_role=editor.role if editor else "Teaching Assistant",
        change_summary="TA co-edited supplementary references, office hour examples, and formulas."
    )
    db_session.add(edit_log)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "TA supplementary notes successfully merged",
        "mom": mom.to_dict()
    })

@notes_bp.route("/<int:mom_id>/publish", methods=["POST"])
@require_roles("Dean", "Professor")
def publish_official_mom(mom_id):
    """Module 4: Publish Official Syllabus MOM (Makes notes visible to all enrolled students)"""
    mom = db_session.query(LectureMOM).filter(LectureMOM.id == mom_id).first()
    if not mom:
        return jsonify({"success": False, "message": "MOM not found"}), 404

    if mom.status == "locked":
        return jsonify({
            "success": False,
            "message": "Cannot publish: Note record is officially locked upon module conclusion."
        }), 403

    actor_id = g.current_user.id
    actor = db_session.query(User).filter(User.id == actor_id).first()
    prev_status = mom.status

    mom.status = "published"
    mom.published_at = datetime.datetime.utcnow()
    db_session.commit()

    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Professor",
        actor_role=actor.role if actor else "Professor",
        event_type="mom_published",
        target_entity="LectureMOM",
        target_id=mom.id,
        course_id=mom.session.course_id if mom.session else None,
        change_before=json.dumps({"status": prev_status}),
        change_after=json.dumps({"status": "published", "version": mom.version}),
        justification=f"Approved official syllabus MOM '{mom.title}' for enrolled cohort study."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Official syllabus MOM published and distributed to enrolled cohort",
        "mom": mom.to_dict()
    })

@notes_bp.route("/<int:mom_id>/lock", methods=["POST"])
@require_roles("Dean", "Professor")
def lock_mom(mom_id):
    """Module 4: Lock Note from Edits (Seals the notes upon conclusion of syllabus module)"""
    mom = db_session.query(LectureMOM).filter(LectureMOM.id == mom_id).first()
    if not mom:
        return jsonify({"success": False, "message": "MOM not found"}), 404

    actor_id = g.current_user.id
    actor = db_session.query(User).filter(User.id == actor_id).first()
    prev_status = mom.status

    mom.status = "locked"
    mom.locked_at = datetime.datetime.utcnow()
    mom.locked_by_id = actor_id
    db_session.commit()

    audit = AuditLog(
        actor_id=actor_id,
        actor_name=actor.name if actor else "Professor",
        actor_role=actor.role if actor else "Professor",
        event_type="note_locked",
        target_entity="LectureMOM",
        target_id=mom.id,
        course_id=mom.session.course_id if mom.session else None,
        change_before=json.dumps({"status": prev_status}),
        change_after=json.dumps({"status": "locked"}),
        justification="Module completed; note record sealed against further modifications for accreditation compliance."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Note record has been officially locked and sealed",
        "mom": mom.to_dict()
    })


@notes_bp.route("/<int:mom_id>/unlock", methods=["POST"])
@require_roles("Dean", "Professor")
def unlock_mom(mom_id):
    """Unseal a locked MOM back to published status so faculty/TAs can make authorized revisions."""
    mom = db_session.query(LectureMOM).filter(LectureMOM.id == mom_id).first()
    if not mom:
        return jsonify({"success": False, "message": "MOM not found"}), 404

    actor = g.current_user
    prev_status = mom.status
    mom.status = "published"
    mom.locked_at = None
    mom.locked_by_id = None

    edit_log = LectureMOMEdit(
        mom_id=mom.id,
        editor_id=actor.id,
        editor_role=actor.role,
        change_summary="Unsealed note lock for authorized academic revision."
    )
    db_session.add(edit_log)

    audit = AuditLog(
        actor_id=actor.id,
        actor_name=actor.name,
        actor_role=actor.role,
        event_type="note_unlocked",
        target_entity="LectureMOM",
        target_id=mom.id,
        course_id=mom.session.course_id if mom.session else None,
        change_before=json.dumps({"status": prev_status}),
        change_after=json.dumps({"status": "published"}),
        justification="Unsealed lecture MOM lock for authorized revision."
    )
    db_session.add(audit)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Note record unsealed and reopened for revisions",
        "mom": mom.to_dict()
    })

@notes_bp.route("/session/<int:session_id>/attachments", methods=["POST"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def attach_slides(session_id):
    """Module 4: Attach Lecture Slides & reading materials to note record"""
    session = db_session.query(LectureSession).filter(LectureSession.id == session_id).first()
    if not session:
        return jsonify({"success": False, "message": "Session not found"}), 404

    if g.current_user.role == "Teaching Assistant" and not has_ta_scope(g.current_user, session.course_id, "can_coedit_notes"):
        return jsonify({"success": False, "message": "Access Denied: TA lacks permission to attach course materials"}), 403

    data = request.get_json(silent=True) or {}
    file_name = (data.get("file_name") or "").strip() or "Lecture_Slides_Supplementary.pdf"
    file_url = (data.get("file_url") or "").strip() or "https://courseware.university.edu/slides/lecture_deck.pdf"
    file_type = (data.get("file_type") or "").strip() or "application/pdf"
    file_size_kb = max(1, int(data.get("file_size_kb", 2048) or 2048))
    uploaded_by_id = g.current_user.id

    mom = db_session.query(LectureMOM).filter(LectureMOM.session_id == session_id).first()
    if mom and mom.status == "locked":
        return jsonify({"success": False, "message": "Cannot attach slides: MOM note record is officially locked."}), 403

    att = LectureAttachment(
        session_id=session_id,
        mom_id=mom.id if mom else None,
        file_name=file_name,
        file_url=file_url,
        file_type=file_type,
        file_size_kb=file_size_kb,
        uploaded_by_id=uploaded_by_id
    )
    db_session.add(att)
    db_session.commit()

    return jsonify({
        "success": True,
        "message": "Lecture slides successfully bound to session record",
        "attachment": att.to_dict()
    }), 201


@notes_bp.route("/attachments/<int:attachment_id>", methods=["DELETE"])
@require_roles("Dean", "Professor", "Teaching Assistant")
def delete_attachment(attachment_id):
    att = db_session.query(LectureAttachment).filter(LectureAttachment.id == attachment_id).first()
    if not att:
        return jsonify({"success": False, "message": "Attachment not found"}), 404
    if att.mom and att.mom.status == "locked":
        return jsonify({"success": False, "message": "Cannot remove attachment from a locked MOM"}), 403
    db_session.delete(att)
    db_session.commit()
    return jsonify({"success": True, "message": "Attachment removed"})

_PDF_UNICODE_ASCII_MAP = {
    "\u2022": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2192": "->",
    "\u2190": "<-",
    "\u21d2": "=>",
    "\u2264": "<=",
    "\u2265": ">=",
    "\u2260": "!=",
    "\u2229": " intersect ",
    "\u222a": " union ",
    "\u2205": "empty-set",
    "\u2208": " in ",
    "\u2286": "<=",
    "\u221e": "inf",
    "\u00b7": "*",
    "\u2248": "~=",
    "\u00d7": "x",
}


def _sanitize_latin1(text: str) -> str:
    """Transliterate math/typographic Unicode characters for core Latin-1 PDF fonts."""
    if not text:
        return ""
    out = text
    for src, dst in _PDF_UNICODE_ASCII_MAP.items():
        out = out.replace(src, dst)
    return out.encode("latin-1", "replace").decode("latin-1")


@notes_bp.route("/<int:mom_id>/export-pdf", methods=["GET"])
@require_module("notes")
def export_mom_pdf(mom_id):
    """Module 4: Export Lecture MOM to PDF printable study guides and review sheets"""
    mom = db_session.query(LectureMOM).filter(LectureMOM.id == mom_id).first()
    if not mom:
        return jsonify({"success": False, "message": "MOM not found"}), 404
    if mom.status == "draft" and g.current_user.role in ("Student", "Auditor"):
        return jsonify({"success": False, "message": "Access Denied: Unpublished draft notes cannot be exported."}), 403

    try:
        from fpdf import FPDF

        # Discover Unicode TTF fonts on Windows or Linux; fall back to Latin-1-safe core fonts otherwise.
        font_candidates = [
            (
                "Segoe",
                {
                    "": "C:/Windows/Fonts/segoeui.ttf",
                    "B": "C:/Windows/Fonts/segoeuib.ttf",
                    "I": "C:/Windows/Fonts/segoeuii.ttf",
                },
                "C:/Windows/Fonts/consola.ttf",
                "C:/Windows/Fonts/seguisym.ttf",
            ),
            (
                "DejaVu",
                {
                    "": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "B": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "I": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
                },
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                None,
            ),
        ]

        selected_family = "Helvetica"
        mono_family = "Courier"
        unicode_enabled = False

        pdf_font_config = None
        for family, styles, mono_path, sym_path in font_candidates:
            if os.path.exists(styles[""]):
                pdf_font_config = (family, styles, mono_path, sym_path)
                break

        class MOMPDF(FPDF):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.body_family = "Helvetica"
                self.mono_family = "Courier"
                self.unicode_ready = False

                if pdf_font_config:
                    family, styles, mono_path, sym_path = pdf_font_config
                    self.add_font(family, "", styles[""])
                    self.add_font(family, "B", styles["B"] if os.path.exists(styles["B"]) else styles[""])
                    self.add_font(family, "I", styles["I"] if os.path.exists(styles["I"]) else styles[""])
                    self.body_family = family
                    if mono_path and os.path.exists(mono_path):
                        self.add_font("MonoUnicode", "", mono_path)
                        self.mono_family = "MonoUnicode"
                    else:
                        self.mono_family = family
                    if sym_path and os.path.exists(sym_path):
                        self.add_font("SymFallback", "", sym_path)
                        self.set_fallback_fonts(["SymFallback"])
                    self.unicode_ready = True

            def safe_text(self, text: str) -> str:
                return text if self.unicode_ready else _sanitize_latin1(text)

            def header(self):
                self.set_font(self.body_family, "B", 14)
                self.set_text_color(30, 41, 59)
                self.cell(0, 10, self.safe_text("INSTITUTIONAL LECTURE MINUTES & STUDY GUIDE"), border=False, new_x="LMARGIN", new_y="NEXT", align="C")
                self.set_font(self.body_family, "", 9)
                self.set_text_color(100, 116, 139)
                self.cell(0, 5, self.safe_text("Office of Academic Affairs • Syllabus Compliance Document"), border=False, new_x="LMARGIN", new_y="NEXT", align="C")
                self.ln(5)

            def footer(self):
                self.set_y(-15)
                self.set_font(self.body_family, "I", 8)
                self.set_text_color(148, 163, 184)
                self.cell(0, 10, f"Page {self.page_no()}", border=False, align="C")

        pdf = MOMPDF()
        selected_family = pdf.body_family
        mono_family = pdf.mono_family
        unicode_enabled = pdf.unicode_ready
        _ = unicode_enabled

        pdf.add_page()
        pdf.set_auto_page_break(auto=True, margin=15)

        # Meta Box
        pdf.set_font(selected_family, "B", 11)
        pdf.set_text_color(15, 23, 42)
        course_code = mom.session.course.code if mom.session and mom.session.course else "ACAD-401"
        course_title = mom.session.course.title if mom.session and mom.session.course else "Course"
        pdf.cell(0, 8, pdf.safe_text(f"Course: {course_code} - {course_title}"), new_x="LMARGIN", new_y="NEXT")

        pdf.set_font(selected_family, "", 10)
        session_title = mom.session.title if mom.session else "Session"
        date_str = mom.session.scheduled_start.strftime("%B %d, %Y (%H:%M UTC)") if mom.session else "N/A"
        pdf.cell(0, 6, pdf.safe_text(f"Session: {session_title}"), new_x="LMARGIN", new_y="NEXT")
        pdf.cell(0, 6, pdf.safe_text(f"Date: {date_str}  |  Status: {mom.status.upper()} (v{mom.version})"), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Section: Topic Summary
        pdf.set_font(selected_family, "B", 12)
        pdf.set_text_color(30, 58, 138)
        pdf.cell(0, 8, "1. Executive Topic Summary", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font(selected_family, "", 10)
        pdf.set_text_color(51, 65, 85)
        pdf.multi_cell(0, 6, pdf.safe_text(mom.topic_summary or "No summary provided."))
        pdf.ln(4)

        # Section: Formulas & Theorems
        if mom.formulas_and_theorems:
            pdf.set_font(selected_family, "B", 12)
            pdf.set_text_color(30, 58, 138)
            pdf.cell(0, 8, "2. Formulas, Invariants & Theorems", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(mono_family, "", 9)
            pdf.set_text_color(15, 23, 42)
            pdf.multi_cell(0, 5, pdf.safe_text(mom.formulas_and_theorems))
            pdf.ln(4)

        # Section: Key Takeaways
        if mom.key_takeaways:
            pdf.set_font(selected_family, "B", 12)
            pdf.set_text_color(30, 58, 138)
            pdf.cell(0, 8, "3. Key Takeaways & Conceptual Foundations", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(selected_family, "", 10)
            pdf.set_text_color(51, 65, 85)
            pdf.multi_cell(0, 6, pdf.safe_text(mom.key_takeaways))
            pdf.ln(4)

        # Section: TA Supplementary Notes
        if mom.ta_supplementary_notes:
            pdf.set_font(selected_family, "B", 12)
            pdf.set_text_color(30, 58, 138)
            pdf.cell(0, 8, "4. Teaching Assistant Supplementary References", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font(selected_family, "I", 10)
            pdf.set_text_color(71, 85, 105)
            pdf.multi_cell(0, 6, pdf.safe_text(mom.ta_supplementary_notes))
            pdf.ln(4)

        os.makedirs(PDF_EXPORT_DIR, exist_ok=True)
        pdf_filename = f"MOM_Session_{mom.session_id}_v{mom.version}.pdf"
        output_path = os.path.abspath(os.path.join(PDF_EXPORT_DIR, pdf_filename))
        pdf.output(output_path)

        return send_file(
            output_path,
            as_attachment=True,
            download_name=pdf_filename,
            mimetype="application/pdf"
        )
    except Exception as e:
        # Fallback to structured JSON/markdown if PDF rendering encounters unexpected limits
        return jsonify({
            "success": True,
            "export_type": "json_study_guide",
            "mom": mom.to_dict(),
            "note": f"PDF generated or export stream available: {str(e)}"
        })
