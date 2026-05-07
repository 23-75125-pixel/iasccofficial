import csv
import io
import os
import sqlite3
from datetime import datetime
from functools import wraps
from pathlib import Path

import click
from flask import (
    Flask,
    Response,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from database import close_db, get_db, init_db
from face_engine import FaceEngine, FaceEngineError, FaceEngineUnavailable
from time_utils import now as timezone_now


BASE_DIR = Path(__file__).resolve().parent
ALLOWED_COURSES = ("BSIT-NT 3201", "BSIT-NT 3202")
STUDENT_ID_PREFIX = "STU"


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "attendance.sqlite3"),
        DEFAULT_ADMIN_EMAIL=os.getenv("DEFAULT_ADMIN_EMAIL", "admin@example.com"),
        DEFAULT_ADMIN_PASSWORD=os.getenv("DEFAULT_ADMIN_PASSWORD", "Admin@12345"),
        DEFAULT_ADMIN_ENABLED=_is_truthy(os.getenv("DEFAULT_ADMIN_ENABLED", "1")),
        FACE_MATCH_THRESHOLD=float(os.getenv("FACE_MATCH_THRESHOLD", "88")),
        SECRET_KEY=os.getenv("SECRET_KEY") or _load_secret_key(Path(app.instance_path) / "secret_key"),
    )
    if config:
        app.config.update(config)

    app.teardown_appcontext(close_db)
    init_db(app)
    _ensure_default_admin(app)
    face_engine = FaceEngine(
        app.instance_path,
        threshold=app.config["FACE_MATCH_THRESHOLD"],
    )

    def has_admin():
        row = get_db().execute("SELECT id FROM admins LIMIT 1").fetchone()
        return row is not None

    def login_required(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "admin_id" not in session:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "message": "Authentication required."}), 401
                return redirect(url_for("login", next=request.path))
            return view(*args, **kwargs)

        return wrapped

    @app.context_processor
    def inject_context():
        return {
            "has_admin": has_admin,
            "current_year": _now().year,
            "default_admin_email": app.config["DEFAULT_ADMIN_EMAIL"],
            "default_admin_password": app.config["DEFAULT_ADMIN_PASSWORD"],
            "allowed_courses": ALLOWED_COURSES,
            "static_version": _static_version(),
        }

    @app.get("/")
    def index():
        if not has_admin():
            return redirect(url_for("setup"))
        if "admin_id" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "status": "healthy"})

    @app.get("/readyz")
    def readyz():
        get_db().execute("SELECT 1").fetchone()
        return jsonify({"ok": True, "status": "ready"})

    @app.route("/setup", methods=["GET", "POST"])
    def setup():
        if has_admin():
            return redirect(url_for("login"))

        error = None
        if request.method == "POST":
            email = _clean_text(request.form.get("email")).lower()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not email or "@" not in email:
                error = "Enter a valid admin email address."
            elif len(password) < 8:
                error = "Password must be at least 8 characters."
            elif password != confirm_password:
                error = "Passwords do not match."
            else:
                now = _now().isoformat(timespec="seconds")
                db = get_db()
                db.execute(
                    "INSERT INTO admins (email, password_hash, created_at) VALUES (?, ?, ?)",
                    (email, generate_password_hash(password), now),
                )
                db.commit()
                return redirect(url_for("login"))

        return render_template("setup.html", error=error)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not has_admin():
            return redirect(url_for("setup"))

        if request.method == "POST":
            payload = request.get_json(silent=True) or request.form
            email = _clean_text(payload.get("email")).lower()
            password = payload.get("password", "")
            admin = get_db().execute(
                "SELECT id, email, password_hash FROM admins WHERE email = ?",
                (email,),
            ).fetchone()

            if admin and check_password_hash(admin["password_hash"], password):
                session.clear()
                session["admin_id"] = admin["id"]
                session["admin_email"] = admin["email"]
                if request.is_json:
                    return jsonify({"ok": True, "redirect": url_for("dashboard")})
                return redirect(url_for("dashboard"))

            message = "Invalid email or password."
            if request.is_json:
                return jsonify({"ok": False, "message": message}), 401
            return render_template("login.html", error=message), 401

        if "admin_id" in session:
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.get("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", active_page="dashboard")

    @app.get("/attendance")
    @login_required
    def attendance():
        return render_template("attendance.html", active_page="attendance")

    @app.get("/register")
    @login_required
    def register():
        return render_template("register.html", active_page="register")

    @app.get("/records")
    @login_required
    def records():
        return render_template("records.html", active_page="records")

    @app.get("/api/system")
    @login_required
    def api_system():
        return jsonify({"ok": True, "face_engine": face_engine.status()})

    @app.get("/api/dashboard")
    @login_required
    def api_dashboard():
        today = _now().date().isoformat()
        selected_date = _clean_date(request.args.get("date")) or today
        db = get_db()
        total_students = db.execute(
            "SELECT COUNT(*) AS count FROM students WHERE is_active = 1"
        ).fetchone()["count"]
        attendance_count = db.execute(
            """
            SELECT COUNT(*) AS count
            FROM attendance_logs
            WHERE attendance_date = ? AND status = 'Present'
            """,
            (selected_date,),
        ).fetchone()["count"]
        attendance_for_date = _attendance_query(date=selected_date, limit=8)

        system_status = face_engine.status()
        return jsonify(
            {
                "ok": True,
                "stats": {
                    "total_students": total_students,
                    "attendance_today": attendance_count,
                    "attendance_date": selected_date,
                    "system_status": "Ready" if system_status["available"] else "Needs setup",
                    "model_trained": system_status["model_trained"],
                },
                "recent_activity": attendance_for_date,
            }
        )

    @app.get("/api/students")
    @login_required
    def api_students():
        rows = get_db().execute(
            """
            SELECT s.id, s.student_number, s.full_name, s.course, s.is_active,
                   COUNT(fs.id) AS sample_count, s.created_at
            FROM students s
            LEFT JOIN face_samples fs ON fs.student_id = s.id
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """
        ).fetchall()
        return jsonify({"ok": True, "students": [dict(row) for row in rows]})

    @app.get("/api/students/next-id")
    @login_required
    def api_next_student_id():
        return jsonify({"ok": True, "student_id": _next_student_number(get_db())})

    @app.post("/api/students")
    @login_required
    def api_create_student():
        payload = request.get_json(silent=True) or {}
        full_name = _clean_text(payload.get("full_name"))
        course = _clean_text(payload.get("course")).upper()
        face_images = payload.get("face_images") or []

        if len(full_name) < 2:
            return _json_error("Full name is required.", 400)
        if course not in ALLOWED_COURSES:
            return _json_error("Choose BSIT-NT 3201 or BSIT-NT 3202.", 400)
        if not isinstance(face_images, list) or len(face_images) < 3:
            return _json_error("Capture at least 3 face samples before saving.", 400)
        if len(face_images) > 12:
            return _json_error("Save up to 12 face samples per registration.", 400)

        db = get_db()
        student_number = _next_student_number(db)
        duplicate = db.execute(
            "SELECT id FROM students WHERE student_number = ?",
            (student_number,),
        ).fetchone()
        if duplicate:
            return _json_error("A generated Student ID already exists. Reload and try again.", 409)

        try:
            prepared_faces = face_engine.prepare_registration_faces(face_images)
        except FaceEngineUnavailable as exc:
            return _json_error(str(exc), 503)
        except FaceEngineError as exc:
            return _json_error(str(exc), 400)

        saved_paths = []
        try:
            now = _now().isoformat(timespec="seconds")
            cursor = db.execute(
                """
                INSERT INTO students (student_number, full_name, course, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (student_number, full_name, course, now, now),
            )
            student_db_id = cursor.lastrowid

            for face in prepared_faces:
                relative_path = face_engine.save_face_sample(student_number, face)
                saved_paths.append(relative_path)
                db.execute(
                    """
                    INSERT INTO face_samples (student_id, image_path, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (student_db_id, relative_path, now),
                )

            training_rows = db.execute(
                """
                SELECT fs.student_id, fs.image_path
                FROM face_samples fs
                JOIN students s ON s.id = fs.student_id
                WHERE s.is_active = 1
                """
            ).fetchall()
            training_status = face_engine.train(training_rows)
            db.commit()
        except (sqlite3.Error, FaceEngineError) as exc:
            db.rollback()
            for relative_path in saved_paths:
                face_engine.delete_relative_file(relative_path)
            return _json_error(f"Student could not be saved: {exc}", 500)

        return jsonify(
            {
                "ok": True,
                "message": "Student registered and recognition model updated.",
                "student": {
                    "id": student_db_id,
                    "student_id": student_number,
                    "full_name": full_name,
                    "course": course,
                    "sample_count": len(saved_paths),
                },
                "training": training_status,
            }
        ), 201

    @app.patch("/api/students/<int:student_id>")
    @login_required
    def api_update_student(student_id):
        payload = request.get_json(silent=True) or {}
        full_name = _clean_text(payload.get("full_name"))
        course = _clean_text(payload.get("course")).upper()

        if len(full_name) < 2:
            return _json_error("Full name is required.", 400)
        if course not in ALLOWED_COURSES:
            return _json_error("Choose BSIT-NT 3201 or BSIT-NT 3202.", 400)

        db = get_db()
        existing = db.execute(
            "SELECT id FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        if existing is None:
            return _json_error("Student was not found.", 404)

        try:
            db.execute(
                """
                UPDATE students
                SET full_name = ?, course = ?, updated_at = ?
                WHERE id = ?
                """,
                (full_name, course, _now().isoformat(timespec="seconds"), student_id),
            )
            db.commit()
        except sqlite3.Error as exc:
            db.rollback()
            return _json_error(f"Student could not be updated: {exc}", 500)

        return jsonify({"ok": True, "message": "Student updated."})

    @app.delete("/api/students/<int:student_id>")
    @login_required
    def api_delete_student(student_id):
        db = get_db()
        student = db.execute(
            "SELECT id, student_number FROM students WHERE id = ?",
            (student_id,),
        ).fetchone()
        if student is None:
            return _json_error("Student was not found.", 404)

        sample_paths = [
            row["image_path"]
            for row in db.execute(
                "SELECT image_path FROM face_samples WHERE student_id = ?",
                (student_id,),
            ).fetchall()
        ]
        snapshot_paths = [
            row["snapshot_path"]
            for row in db.execute(
                """
                SELECT snapshot_path
                FROM attendance_logs
                WHERE student_id = ? AND snapshot_path IS NOT NULL
                """,
                (student_id,),
            ).fetchall()
        ]

        try:
            db.execute("DELETE FROM students WHERE id = ?", (student_id,))
            training_rows = db.execute(
                """
                SELECT fs.student_id, fs.image_path
                FROM face_samples fs
                JOIN students s ON s.id = fs.student_id
                WHERE s.is_active = 1
                """
            ).fetchall()
            training_status = face_engine.train(training_rows)
            db.commit()
        except (sqlite3.Error, FaceEngineError) as exc:
            db.rollback()
            return _json_error(f"Student could not be deleted: {exc}", 500)

        for relative_path in sample_paths + snapshot_paths:
            face_engine.delete_relative_file(relative_path)

        return jsonify(
            {
                "ok": True,
                "message": "Student deleted and recognition model updated.",
                "training": training_status,
            }
        )

    @app.post("/api/attendance/recognize")
    @login_required
    def api_attendance_recognize():
        payload = request.get_json(silent=True) or {}
        image_data = payload.get("image")
        if not image_data:
            return _json_error("Camera image is required.", 400)

        try:
            result = face_engine.recognize(image_data)
        except FaceEngineUnavailable as exc:
            return _json_error(str(exc), 503)
        except FaceEngineError as exc:
            return _json_error(str(exc), 400)

        if not result["matched"]:
            return jsonify(
                {
                    "ok": True,
                    "matched": False,
                    "detection": _detection_payload(result),
                    "status": "Unknown",
                    "confidence": result["confidence"],
                    "threshold": result["threshold"],
                    "message": "Face not recognized.",
                }
            )

        db = get_db()
        student = db.execute(
            """
            SELECT id, student_number, full_name, course
            FROM students
            WHERE id = ? AND is_active = 1
            """,
            (result["student_id"],),
        ).fetchone()
        if student is None:
            return _json_error("Matched student is inactive or missing. Rebuild the model.", 409)

        now = _now()
        attendance_date = now.date().isoformat()
        existing = db.execute(
            """
            SELECT id, attendance_time, recorded_at, confidence
            FROM attendance_logs
            WHERE student_id = ? AND attendance_date = ? AND status = 'Present'
            """,
            (student["id"], attendance_date),
        ).fetchone()

        if existing:
            return _attendance_response(
                result,
                student,
                existing,
                attendance_date,
                "Already marked",
                "Attendance was already recorded today.",
            )

        snapshot_path = None
        try:
            snapshot_path = face_engine.save_attendance_snapshot(
                student["student_number"],
                image_data,
                now,
            )
            cursor = db.execute(
                """
                INSERT INTO attendance_logs
                    (student_id, recorded_at, attendance_date, attendance_time, status, confidence, snapshot_path)
                VALUES (?, ?, ?, ?, 'Present', ?, ?)
                """,
                (
                    student["id"],
                    now.isoformat(timespec="seconds"),
                    attendance_date,
                    now.strftime("%I:%M:%S %p"),
                    result["confidence"],
                    snapshot_path,
                ),
            )
            db.commit()
        except sqlite3.IntegrityError:
            db.rollback()
            face_engine.delete_relative_file(snapshot_path)
            existing = db.execute(
                """
                SELECT id, attendance_time, recorded_at, confidence
                FROM attendance_logs
                WHERE student_id = ? AND attendance_date = ? AND status = 'Present'
                """,
                (student["id"], attendance_date),
            ).fetchone()
            if existing:
                return _attendance_response(
                    result,
                    student,
                    existing,
                    attendance_date,
                    "Already marked",
                    "Attendance was already recorded today.",
                )
            return _json_error("Attendance was recorded by another request. Try again.", 409)
        except (sqlite3.Error, FaceEngineError) as exc:
            db.rollback()
            face_engine.delete_relative_file(snapshot_path)
            return _json_error(f"Attendance could not be saved: {exc}", 500)

        return _attendance_response(
            result,
            student,
            {
                "id": cursor.lastrowid,
                "attendance_time": now.strftime("%I:%M:%S %p"),
                "recorded_at": now.isoformat(timespec="seconds"),
                "confidence": result["confidence"],
            },
            attendance_date,
            "Present",
            "Attendance recorded.",
        )

    @app.get("/api/records")
    @login_required
    def api_records():
        search = _clean_text(request.args.get("search"))
        date = _clean_date(request.args.get("date"))
        return jsonify({"ok": True, "records": _attendance_query(search=search, date=date)})

    @app.get("/api/records/export.csv")
    @login_required
    def api_records_export():
        search = _clean_text(request.args.get("search"))
        date = _clean_date(request.args.get("date"))
        records = _attendance_query(search=search, date=date)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Name", "Student ID", "Course", "Date", "Time", "Status", "Confidence"])
        for record in records:
            writer.writerow(
                [
                    record["name"],
                    record["student_id"],
                    record["course"],
                    record["date"],
                    record["time"],
                    record["status"],
                    record["confidence"],
                ]
            )
        filename = f"attendance-records-{_now().date().isoformat()}.csv"
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.cli.command("create-admin")
    @click.option("--email", prompt=True, help="Admin email address.")
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Admin password. Must be at least 8 characters.",
    )
    def create_admin_command(email, password):
        email = _clean_text(email).lower()
        password = str(password or "")

        if not email or "@" not in email:
            raise click.ClickException("Enter a valid admin email address.")
        if len(password) < 8:
            raise click.ClickException("Password must be at least 8 characters.")

        db = get_db()
        existing = db.execute(
            "SELECT id FROM admins WHERE email = ?",
            (email,),
        ).fetchone()
        if existing:
            raise click.ClickException(f"Admin already exists: {email}")

        db.execute(
            "INSERT INTO admins (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), _now().isoformat(timespec="seconds")),
        )
        db.commit()
        click.echo(f"Admin created: {email}")

    @app.cli.command("retrain-model")
    def retrain_model_command():
        rows = get_db().execute(
            """
            SELECT fs.student_id, fs.image_path
            FROM face_samples fs
            JOIN students s ON s.id = fs.student_id
            WHERE s.is_active = 1
            """
        ).fetchall()
        try:
            status = face_engine.train(rows)
        except FaceEngineError as exc:
            raise click.ClickException(str(exc)) from exc

        click.echo(
            "Recognition model updated: "
            f"{status['sample_count']} saved samples, "
            f"{status.get('augmented_sample_count', status['sample_count'])} training samples, "
            f"{status['student_count']} students, "
            f"threshold {status.get('threshold', app.config['FACE_MATCH_THRESHOLD'])}."
        )

    def _attendance_query(search="", date=None, limit=None):
        db = get_db()
        params = []
        filters = []
        if search:
            filters.append(
                """
                LOWER(
                    s.full_name || ' ' || s.student_number || ' ' ||
                    s.course || ' ' || a.attendance_date || ' ' || a.status
                ) LIKE ?
                """
            )
            params.append(f"%{search.lower()}%")
        if date:
            filters.append("a.attendance_date = ?")
            params.append(date)

        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        limit_clause = ""
        if limit:
            limit_clause = "LIMIT ?"
            params.append(limit)

        rows = db.execute(
            f"""
            SELECT a.id, s.full_name AS name, s.student_number AS student_id,
                   s.course, a.attendance_date AS date, a.attendance_time AS time,
                   a.status, a.confidence, a.recorded_at
            FROM attendance_logs a
            JOIN students s ON s.id = a.student_id
            {where}
            ORDER BY a.recorded_at DESC
            {limit_clause}
            """,
            params,
        ).fetchall()
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "student_id": row["student_id"],
                "course": row["course"],
                "date": row["date"],
                "time": row["time"],
                "status": row["status"],
                "confidence": round(float(row["confidence"]), 2),
                "recorded_at": row["recorded_at"],
            }
            for row in rows
        ]

    def _json_error(message, status):
        return jsonify({"ok": False, "message": message}), status

    return app


def _load_secret_key(path):
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    secret = os.urandom(32).hex()
    path.write_text(secret, encoding="utf-8")
    return secret


def _ensure_default_admin(app):
    if not app.config["DEFAULT_ADMIN_ENABLED"]:
        return

    email = _clean_text(app.config["DEFAULT_ADMIN_EMAIL"]).lower()
    password = str(app.config["DEFAULT_ADMIN_PASSWORD"] or "")
    if not email or "@" not in email:
        raise RuntimeError("DEFAULT_ADMIN_EMAIL must be a valid email address.")
    if len(password) < 8:
        raise RuntimeError("DEFAULT_ADMIN_PASSWORD must be at least 8 characters.")

    with app.app_context():
        db = get_db()
        existing_default_admin = db.execute(
            "SELECT id FROM admins WHERE email = ?",
            (email,),
        ).fetchone()
        if existing_default_admin:
            return

        db.execute(
            "INSERT INTO admins (email, password_hash, created_at) VALUES (?, ?, ?)",
            (email, generate_password_hash(password), _now().isoformat(timespec="seconds")),
        )
        db.commit()


def _is_truthy(value):
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _clean_text(value):
    return " ".join(str(value or "").strip().split())


def _clean_date(value):
    value = _clean_text(value)
    if not value:
        return ""
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return ""
    return value


def _now():
    return timezone_now()


def _static_version():
    app_version = _clean_text(os.getenv("APP_VERSION"))
    if app_version:
        return app_version

    newest_mtime = 0
    for relative_path in ("static/css/styles.css", "static/js/script.js"):
        path = BASE_DIR / relative_path
        if path.exists():
            newest_mtime = max(newest_mtime, int(path.stat().st_mtime))
    return str(newest_mtime or int(_now().timestamp()))


def _next_student_number(db):
    next_index = 1
    prefix = f"{STUDENT_ID_PREFIX}-"
    rows = db.execute("SELECT student_number FROM students").fetchall()
    for row in rows:
        value = str(row["student_number"] or "").upper()
        if not value.startswith(prefix):
            continue
        suffix = value[len(prefix) :]
        if suffix.isdigit():
            next_index = max(next_index, int(suffix) + 1)
    return f"{STUDENT_ID_PREFIX}-{next_index:04d}"


def _student_payload(row):
    return {
        "id": row["id"],
        "student_id": row["student_number"],
        "full_name": row["full_name"],
        "course": row["course"],
    }


def _attendance_response(result, student, attendance, attendance_date, status, message):
    return jsonify(
        {
            "ok": True,
            "matched": True,
            "detection": _detection_payload(result),
            "status": status,
            "student": _student_payload(student),
            "attendance": {
                "id": attendance["id"],
                "date": attendance_date,
                "time": attendance["attendance_time"],
                "recorded_at": attendance["recorded_at"],
                "confidence": round(float(attendance["confidence"]), 2),
            },
            "message": message,
        }
    )


def _detection_payload(result):
    return {
        "box": result.get("box"),
        "image_size": result.get("image_size"),
        "backend": result.get("detection_backend"),
    }


app = create_app()


if __name__ == "__main__":
    app.run(debug=True)
