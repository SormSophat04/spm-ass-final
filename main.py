import os
from fastapi import FastAPI, Request
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app import create_app
from database import db_session
from seed import ensure_seeded, seed_database
from security import SESSION_COOKIE_NAME, resolve_user_from_token

# Ensure database tables exist and auto-seed if running on an empty database
try:
    ensure_seeded()
except Exception as e:
    print(f"[FastAPI Cloud] Note during DB check/seeding: {e}")

# Create underlying Flask API
flask_app = create_app()

# Initialize FastAPI application for FastAPI Cloud
app = FastAPI(
    title="Academic Lecture & Institutional Seminar Coordinator API",
    version="2.4.0",
    description="Backend API mounted for FastAPI Cloud & production cloud deployment",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Enable CORS for FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {
        "status": "online",
        "service": "Academic Lecture & Institutional Seminar Coordinator API",
        "platform": "FastAPI Cloud",
        "version": "2.4.0",
        "docs": "/docs",
        "health": "/api/health"
    }

@app.get("/health")
def health_status():
    return {
        "status": "healthy",
        "platform": "FastAPI Cloud"
    }

@app.post("/api/seed")
def manual_seed(request: Request):
    """Protected seed trigger restricted to authenticated Dean accounts."""
    try:
        auth_header = request.headers.get("authorization", "").strip()
        token = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else request.cookies.get(SESSION_COOKIE_NAME)
        user = resolve_user_from_token(token)
        if not user:
            return JSONResponse(status_code=401, content={"success": False, "message": "Authentication required."})
        if user.role != "Dean":
            return JSONResponse(status_code=403, content={"success": False, "message": "Access Denied: Dean role required."})

        seed_database()
        return {"success": True, "message": "Database successfully seeded with academic dataset!"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    finally:
        db_session.remove()

# Mount the Flask application for all other routes (/api/*, /uploads/*, etc.)
app.mount("/", WSGIMiddleware(flask_app))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_excludes=["data/*", "exports/*", "uploads/*", "*.db", "*.db-journal", "*.sqlite*"]
    )
