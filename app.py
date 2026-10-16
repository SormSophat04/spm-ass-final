import os
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
from config import Config, UPLOAD_DIR
from database import init_db, db_session

# Import routes
from routes.auth_routes import auth_bp
from routes.session_routes import session_bp
from routes.attendance_routes import attendance_bp
from routes.leave_routes import leave_bp
from routes.notes_routes import notes_bp
from routes.quiz_routes import quiz_bp
from routes.roles_routes import roles_bp
from routes.audit_routes import audit_bp
from routes.export_routes import export_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Enable CORS for Next.js frontend
    CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(session_bp)
    app.register_blueprint(attendance_bp)
    app.register_blueprint(leave_bp)
    app.register_blueprint(notes_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(roles_bp)
    app.register_blueprint(audit_bp)
    app.register_blueprint(export_bp)

    @app.teardown_appcontext
    def shutdown_session(exception=None):
        db_session.remove()

    @app.route("/api/health", methods=["GET"])
    def health():
        return jsonify({
            "status": "healthy",
            "service": "Academic Lecture & Institutional Seminar Coordinator API",
            "version": "2.4.0",
            "database": "Active (SQLite/PostgreSQL compatible)"
        })

    @app.route("/api/stats", methods=["GET"])
    def institutional_stats():
        from models import User, Course, LectureSession, AttendanceRecord, LeaveRequest, LiveQuiz, AuditLog
        return jsonify({
            "total_users": db_session.query(User).count(),
            "total_courses": db_session.query(Course).count(),
            "total_sessions": db_session.query(LectureSession).count(),
            "total_attendance_records": db_session.query(AttendanceRecord).count(),
            "total_leave_requests": db_session.query(LeaveRequest).count(),
            "total_quizzes": db_session.query(LiveQuiz).count(),
            "total_audit_events": db_session.query(AuditLog).count()
        })

    @app.route("/uploads/<path:filename>")
    def download_file(filename):
        return send_from_directory(UPLOAD_DIR, filename)

    return app

if __name__ == "__main__":
    init_db()
    app = create_app()
    port = int(os.getenv("PORT", 5000))
    print(f"Starting Academic Lecture Coordinator API on port {port}...")
    app.run(host="127.0.0.1", port=port, debug=True)
