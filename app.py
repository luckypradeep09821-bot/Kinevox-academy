"""
Kinevox Academy Institute — Backend API
========================================
A complete REST API for the Kinevox Academy Management System.

Features:
  - Serves the frontend at  GET /
  - JWT authentication
  - Employee CRUD + attendance + schedule
  - Student CRUD + progress + certificates
  - Course CRUD
  - Payroll calculations (salary slips)
  - Reports & analytics
  - Photo / file uploads
  - SQLite persistence

Run:
    python app.py
    Then open  http://localhost:5000

Default credentials:
    username: admin
    password: Kinevox123
"""

import os
from dotenv import load_dotenv
load_dotenv()   # loads .env locally; on Render, env vars are injected via dashboard

from flask import Flask, send_from_directory
from flask_cors import CORS

from db.database import init_db
from routes.auth      import auth_bp
from routes.employees import emp_bp
from routes.students  import stu_bp
from routes.courses   import crs_bp
from routes.payroll   import pay_bp
from routes.reports   import rep_bp
from routes.uploads   import upload_bp

# ── App factory ──────────────────────────────────────────────────────────────

def create_app():
    app = Flask(
        __name__,
        static_folder  = "uploads",
        static_url_path= "/uploads",
        template_folder= "templates",
    )
    app.config["SECRET_KEY"]         = os.getenv("SECRET_KEY", "kinevox-super-secret-key-2024")
    app.config["JWT_EXPIRY_HOURS"]   = int(os.getenv("JWT_EXPIRY_HOURS", 8))
    app.config["UPLOAD_FOLDER"]      = os.path.join(os.path.dirname(__file__), "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024   # 5 MB
    app.config["ALLOWED_EXTENSIONS"] = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    CORS(app, resources={r"/api/*": {"origins": "*"}})

    # Initialise database and seed demo data
    init_db(app)

    # ── Serve the frontend at root ────────────────────────────────────────
    @app.route("/")
    def serve_frontend():
        return send_from_directory(
            os.path.join(os.path.dirname(__file__), "templates"),
            "index.html"
        )

    # ── Health check ──────────────────────────────────────────────────────
    @app.route("/api/health")
    def health():
        return {"status": "ok", "app": "Kinevox Academy API", "version": "1.0.0"}

    # ── Register blueprints ───────────────────────────────────────────────
    app.register_blueprint(auth_bp,   url_prefix="/api/auth")
    app.register_blueprint(emp_bp,    url_prefix="/api/employees")
    app.register_blueprint(stu_bp,    url_prefix="/api/students")
    app.register_blueprint(crs_bp,    url_prefix="/api/courses")
    app.register_blueprint(pay_bp,    url_prefix="/api/payroll")
    app.register_blueprint(rep_bp,    url_prefix="/api/reports")
    app.register_blueprint(upload_bp, url_prefix="/api/uploads")

    return app


app = create_app()

if __name__ == "__main__":
    port  = int(os.getenv("PORT", 5000))
    debug = os.getenv("DEBUG", "true").lower() == "true"
    print(f"""
╔══════════════════════════════════════════════════════╗
║        Kinevox Academy Institute — Full Stack       ║
║                                                     ║
║  Open browser:  http://localhost:{port}               ║
║  API health:    http://localhost:{port}/api/health    ║
║  Login:         admin / Kinevox123                  ║
╚══════════════════════════════════════════════════════╝
""")
    app.run(host="0.0.0.0", port=port, debug=debug)
