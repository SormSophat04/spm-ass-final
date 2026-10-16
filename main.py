import os
from fastapi import FastAPI
from fastapi.middleware.wsgi import WSGIMiddleware
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app import create_app
from database import init_db, db_session
from models import User
from seed import seed_database

# Ensure database tables exist
init_db()

# Auto-seed if running on an empty database (e.g. initial cloud deployment)
try:
    if db_session.query(User).count() == 0:
        print("[FastAPI Cloud] Fresh database detected. Seeding initial institutional dataset...")
        seed_database()
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

@app.api_route("/api/seed", methods=["GET", "POST"])
def manual_seed():
    """Manual seed trigger for cloud instances."""
    try:
        seed_database()
        return {"success": True, "message": "Database successfully seeded with academic dataset!"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# Mount the Flask application for all other routes (/api/*, /uploads/*, etc.)
app.mount("/", WSGIMiddleware(flask_app))

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 5000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
