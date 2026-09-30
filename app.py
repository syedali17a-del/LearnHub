import os
import sqlite3
import secrets
import random
from functools import wraps
from datetime import datetime

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, send_from_directory, abort, g
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

from config import Config
from database import get_connection, init_db

app = Flask(__name__)
app.config.from_object(Config)

os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
os.makedirs(Config.PROFILE_PICTURE_FOLDER, exist_ok=True)

init_db()

if Config.ADMIN_PASSWORD == "admin123":
    print("WARNING: Admin is still using the default password. "
          "Set ADMIN_EMAIL and ADMIN_PASSWORD environment variables before deploying.")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def get_db():
    if "db" not in g:
        g.db = get_connection()
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.context_processor
def inject_current_user():
    """Makes `current_user` available in every template without each
    route needing to fetch and pass it manually."""
    if session.get("user_id"):
        db = get_db()
        user = db.execute(
            "SELECT id, username, email, profile_picture FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
        return {"current_user": user}
    return {"current_user": None}


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("email"):
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin"):
            flash("Please log in as an admin to continue.", "warning")
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)
    return wrapped


# ---------------------------------------------------------------------------
# CSRF protection (lightweight, no extra dependency)
# ---------------------------------------------------------------------------

def _generate_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(16)
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = _generate_csrf_token


@app.before_request
def csrf_protect():
    if request.method == "POST":
        token = session.get("_csrf_token")
        form_token = request.form.get("csrf_token")
        if not token or not form_token or not secrets.compare_digest(token, form_token):
            abort(400, description="Your form session expired. Please go back and try again.")


# ---------------------------------------------------------------------------
# File upload helpers
# ---------------------------------------------------------------------------

def allowed_file(filename, allowed_extensions):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in allowed_extensions


def save_upload(file_storage, folder, allowed_extensions):
    filename = secure_filename(file_storage.filename)
    if not filename or not allowed_file(filename, allowed_extensions):
        return None
    unique_name = f"{secrets.token_hex(8)}_{filename}"
    file_storage.save(os.path.join(folder, unique_name))
    return unique_name


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def get_passed_levels(user_id, course_id):
    """Set of level numbers (1-3) this user has passed for a course."""
    db = get_db()
    rows = db.execute(
        "SELECT level FROM level_progress WHERE user_id = ? AND course_id = ? AND passed = 1",
        (user_id, course_id),
    ).fetchall()
    return {row["level"] for row in rows}


def get_next_unlocked_level(user_id, course_id):
    """The level (1-3) the student should attempt next, or None if all
    three levels are already passed (course complete)."""
    passed = get_passed_levels(user_id, course_id)
    for level in (1, 2, 3):
        if level not in passed:
            return level
    return None


def is_level_unlocked(user_id, course_id, level):
    """A level is reachable if it's level 1, or the level before it has
    already been passed (retaking an already-passed level is allowed)."""
    if level == 1:
        return True
    return (level - 1) in get_passed_levels(user_id, course_id)


def get_course_completion_percent(user_id):
    """{course_id: percent} where percent = (levels passed / 3) * 100,
    used for dashboard/progress bars."""
    db = get_db()
    rows = db.execute(
        "SELECT course_id, COUNT(*) AS passed_count FROM level_progress "
        "WHERE user_id = ? AND passed = 1 GROUP BY course_id",
        (user_id,),
    ).fetchall()
    return {row["course_id"]: round((row["passed_count"] / Config.TOTAL_LEVELS) * 100) for row in rows}


def get_course_level_progress(user_id, course_id):
    """Full per-level detail for one course, used on the progress and
    course-details pages: [{level, label, unlocked, passed, best_score,
    pass_score, attempts}, ...]"""
    db = get_db()
    rows = {
        row["level"]: row for row in db.execute(
            "SELECT * FROM level_progress WHERE user_id = ? AND course_id = ?",
            (user_id, course_id),
        ).fetchall()
    }
    result = []
    for level in (1, 2, 3):
        row = rows.get(level)
        result.append({
            "level": level,
            "label": Config.LEVEL_LABELS[level],
            "unlocked": is_level_unlocked(user_id, course_id, level),
            "passed": bool(row["passed"]) if row else False,
            "best_score": row["best_score"] if row else 0,
            "attempts": row["attempts"] if row else 0,
            "pass_score": Config.LEVEL_PASS_SCORES[level],
        })
    return result


def is_course_complete(user_id, course_id):
    return 3 in get_passed_levels(user_id, course_id)


def format_duration(seconds):
    """Turns a second count into a friendly string like '2 days, 3 hours'
    for the certificate's 'time taken' field."""
    seconds = max(int(seconds), 0)
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes and not days:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if not parts:
        parts.append("under a minute")
    return ", ".join(parts)


def get_enrolled_courses(user_id):
    db = get_db()
    return db.execute(
        """
        SELECT c.* FROM courses c
        INNER JOIN enrollments e ON e.course_id = c.id
        WHERE e.user_id = ?
        ORDER BY e.enrolled_at DESC
        """,
        (user_id,),
    ).fetchall()


def is_enrolled(user_id, course_id):
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM enrollments WHERE user_id = ? AND course_id = ?",
        (user_id, course_id),
    ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("splash.html")


@app.route("/welcome")
def welcome():
    return render_template("welcome.html")


@app.route("/courses")
def courses():
    db = get_db()
    course_rows = db.execute("SELECT * FROM courses ORDER BY course_name").fetchall()

    enrolled_ids = set()
    if session.get("user_id"):
        enrolled_ids = {
            row["course_id"] for row in db.execute(
                "SELECT course_id FROM enrollments WHERE user_id = ?",
                (session["user_id"],),
            ).fetchall()
        }

    return render_template("courses.html", courses=course_rows, enrolled_ids=enrolled_ids)


@app.route("/courses/<int:course_id>")
def course_details(course_id):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    material_count = db.execute(
        "SELECT COUNT(*) AS c FROM materials WHERE course_id = ?", (course_id,)
    ).fetchone()["c"]

    quiz_count = db.execute(
        "SELECT COUNT(*) AS c FROM quizzes WHERE course_id = ?", (course_id,)
    ).fetchone()["c"]

    enrolled = False
    level_progress = None
    if session.get("user_id"):
        enrolled = is_enrolled(session["user_id"], course_id)
        if enrolled:
            level_progress = get_course_level_progress(session["user_id"], course_id)

    return render_template(
        "course_details.html",
        course=course,
        material_count=material_count,
        quiz_count=quiz_count,
        enrolled=enrolled,
        level_progress=level_progress,
        course_complete=is_course_complete(session["user_id"], course_id) if enrolled else False,
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    confirm_password = request.form.get("confirm_password", "")

    if not username or not email or not password:
        flash("Please fill in all fields.", "danger")
        return redirect(url_for("register"))

    if len(password) < 6:
        flash("Password must be at least 6 characters long.", "danger")
        return redirect(url_for("register"))

    if password != confirm_password:
        flash("Passwords do not match.", "danger")
        return redirect(url_for("register"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
            (username, email, generate_password_hash(password)),
        )
        db.commit()
    except sqlite3.IntegrityError:
        flash("An account with that email already exists. Try logging in instead.", "danger")
        return redirect(url_for("register"))

    flash("Account created! You can log in now.", "success")
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

    if user and check_password_hash(user["password"], password):
        session.permanent = True
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["email"] = user["email"]
        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(url_for("dashboard"))

    flash("Invalid email or password.", "danger")
    return redirect(url_for("login"))


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    session.pop("email", None)
    flash("You have been logged out.", "success")
    return redirect(url_for("welcome"))


# ---------------------------------------------------------------------------
# Student routes
# ---------------------------------------------------------------------------

@app.route("/courses/<int:course_id>/enroll", methods=["POST"])
@login_required
def enroll(course_id):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    if is_enrolled(session["user_id"], course_id):
        flash(f"You're already enrolled in {course['course_name']}.", "info")
    else:
        db.execute(
            "INSERT INTO enrollments (user_id, course_id) VALUES (?, ?)",
            (session["user_id"], course_id),
        )
        db.commit()
        flash(f"Enrolled in {course['course_name']}! Happy learning.", "success")

    return redirect(url_for("course_details", course_id=course_id))


@app.route("/dashboard")
@login_required
def dashboard():
    courses_enrolled = get_enrolled_courses(session["user_id"])
    progress = get_course_completion_percent(session["user_id"])

    db = get_db()
    announcement = db.execute(
        "SELECT * FROM announcements ORDER BY id DESC LIMIT 1"
    ).fetchone()

    overall_progress = 0
    if courses_enrolled:
        total = sum(progress.get(c["id"], 0) for c in courses_enrolled)
        overall_progress = round(total / len(courses_enrolled))

    return render_template(
        "dashboard.html",
        courses=courses_enrolled,
        progress=progress,
        overall_progress=overall_progress,
        announcement=announcement,
    )


@app.route("/materials")
@login_required
def materials():
    db = get_db()
    rows = db.execute(
        """
        SELECT m.*, c.course_name FROM materials m
        INNER JOIN courses c ON c.id = m.course_id
        INNER JOIN enrollments e ON e.course_id = m.course_id
        WHERE e.user_id = ?
        ORDER BY c.course_name,
                 CASE m.difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
        """,
        (session["user_id"],),
    ).fetchall()

    grouped = {}
    for row in rows:
        course_group = grouped.setdefault(row["course_name"], {"easy": [], "medium": [], "hard": []})
        course_group.setdefault(row["difficulty"], []).append(row)

    return render_template("materials.html", grouped=grouped)


@app.route("/quiz/<int:course_id>")
@login_required
def quiz_start(course_id):
    """Convenience entry point: sends the student to whichever level
    they should currently be attempting, or to the certificate flow
    if every level is already passed."""
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    if not is_enrolled(session["user_id"], course_id):
        flash("Enroll in this course before taking its quiz.", "warning")
        return redirect(url_for("course_details", course_id=course_id))

    next_level = get_next_unlocked_level(session["user_id"], course_id)
    if next_level is None:
        flash("You've already completed every level of this course! 🎉", "success")
        return redirect(url_for("certificate", course_id=course_id))

    return redirect(url_for("quiz", course_id=course_id, level=next_level))


@app.route("/quiz/<int:course_id>/<int:level>")
@login_required
def quiz(course_id, level):
    if level not in (1, 2, 3):
        abort(404)

    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    if not is_enrolled(session["user_id"], course_id):
        flash("Enroll in this course before taking its quiz.", "warning")
        return redirect(url_for("course_details", course_id=course_id))

    if not is_level_unlocked(session["user_id"], course_id, level):
        flash(f"Pass Level {level - 1} first to unlock this level.", "warning")
        return redirect(url_for("quiz_start", course_id=course_id))

    quizzes = db.execute(
        "SELECT * FROM quizzes WHERE course_id = ? AND level = ?", (course_id, level)
    ).fetchall()

    # Shuffle question order and each question's option order every time
    # the quiz is loaded, so no two attempts look identical. Grading later
    # compares the submitted option *text* to the stored answer text, so
    # shuffling here never affects correctness.
    shuffled_questions = list(quizzes)
    random.shuffle(shuffled_questions)
    display_questions = []
    for q in shuffled_questions:
        options = [q["option1"], q["option2"], q["option3"], q["option4"]]
        random.shuffle(options)
        display_questions.append({"id": q["id"], "question": q["question"], "options": options})

    progress = get_course_level_progress(session["user_id"], course_id)

    return render_template(
        "quiz.html",
        course=course,
        level=level,
        level_label=Config.LEVEL_LABELS[level],
        pass_score=Config.LEVEL_PASS_SCORES[level],
        total_questions=Config.QUESTIONS_PER_LEVEL,
        questions=display_questions,
        level_progress=progress,
    )


@app.route("/quiz/<int:course_id>/<int:level>/submit", methods=["POST"])
@login_required
def submit_quiz(course_id, level):
    if level not in (1, 2, 3):
        abort(404)

    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course:
        abort(404)

    if not is_level_unlocked(session["user_id"], course_id, level):
        flash("Pass the previous level first.", "warning")
        return redirect(url_for("quiz_start", course_id=course_id))

    quizzes = db.execute(
        "SELECT id, answer FROM quizzes WHERE course_id = ? AND level = ?", (course_id, level)
    ).fetchall()

    total = len(quizzes)
    correct = 0
    for q in quizzes:
        user_answer = request.form.get(f"q{q['id']}")
        if user_answer is not None and user_answer == q["answer"]:
            correct += 1

    percentage = round((correct / total) * 100, 2) if total else 0
    pass_score = Config.LEVEL_PASS_SCORES[level]
    passed = correct >= pass_score

    db.execute(
        "INSERT INTO scores (user_id, course_id, level, score) VALUES (?, ?, ?, ?)",
        (session["user_id"], course_id, level, percentage),
    )
    db.execute(
        """
        INSERT INTO level_progress (user_id, course_id, level, best_score, attempts, passed, passed_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(user_id, course_id, level) DO UPDATE SET
            best_score = MAX(best_score, excluded.best_score),
            attempts = attempts + 1,
            passed = MAX(passed, excluded.passed),
            passed_at = CASE WHEN passed = 0 AND excluded.passed = 1
                             THEN excluded.passed_at ELSE passed_at END
        """,
        (session["user_id"], course_id, level, correct, int(passed),
         datetime.now() if passed else None),
    )
    db.commit()

    is_final_level = level == Config.TOTAL_LEVELS
    session["last_quiz_result"] = {
        "course_id": course_id,
        "level": level,
        "correct": correct,
        "total": total,
        "percentage": percentage,
        "passed": passed,
        "pass_score": pass_score,
        "next_level": level + 1 if passed and not is_final_level else None,
        "course_complete": bool(passed and is_final_level),
    }
    return redirect(url_for("quiz_result", course_id=course_id, level=level))


@app.route("/quiz/<int:course_id>/<int:level>/result")
@login_required
def quiz_result(course_id, level):
    result = session.pop("last_quiz_result", None)
    if not result or result.get("course_id") != course_id or result.get("level") != level:
        flash("Take the quiz first to see a result.", "info")
        return redirect(url_for("quiz_start", course_id=course_id))

    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()

    return render_template(
        "quiz_result.html",
        course=course,
        level=level,
        level_label=Config.LEVEL_LABELS[level],
        score=result["correct"],
        total_questions=result["total"],
        percentage=result["percentage"],
        passed=result["passed"],
        pass_score=result["pass_score"],
        next_level=result["next_level"],
        course_complete=result["course_complete"],
    )


@app.route("/scores")
@login_required
def scores():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.score, s.taken_at, s.level, c.course_name
        FROM scores s INNER JOIN courses c ON c.id = s.course_id
        WHERE s.user_id = ? ORDER BY s.taken_at DESC
        """,
        (session["user_id"],),
    ).fetchall()

    quizzes_completed = len(rows)
    average_score = round(sum(r["score"] for r in rows) / quizzes_completed, 2) if quizzes_completed else 0
    highest_score = max((r["score"] for r in rows), default=0)
    latest_score = rows[0]["score"] if rows else 0

    return render_template(
        "scores.html", rows=rows, average_score=average_score,
        highest_score=highest_score, latest_score=latest_score,
        quizzes_completed=quizzes_completed,
    )


@app.route("/profile")
@login_required
def profile():
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    if not user:
        abort(404)
    enrolled_count = db.execute(
        "SELECT COUNT(*) AS c FROM enrollments WHERE user_id = ?", (session["user_id"],)
    ).fetchone()["c"]
    return render_template("profile.html", user=user, enrolled_count=enrolled_count)


@app.route("/settings")
@login_required
def settings():
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
    return render_template("settings.html", user=user)


@app.route("/settings/password", methods=["POST"])
@login_required
def update_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")

    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()

    if not user or not check_password_hash(user["password"], current_password):
        flash("Your current password is incorrect.", "danger")
    elif len(new_password) < 6:
        flash("New password must be at least 6 characters long.", "danger")
    elif new_password != confirm_password:
        flash("New passwords do not match.", "danger")
    else:
        db.execute(
            "UPDATE users SET password = ? WHERE id = ?",
            (generate_password_hash(new_password), session["user_id"]),
        )
        db.commit()
        flash("Password updated successfully.", "success")

    return redirect(url_for("settings"))


@app.route("/settings/picture", methods=["POST"])
@login_required
def update_profile_picture():
    file = request.files.get("photo")

    if not file or file.filename == "":
        flash("Choose an image to upload.", "danger")
        return redirect(url_for("settings"))

    saved_name = save_upload(file, Config.PROFILE_PICTURE_FOLDER, Config.ALLOWED_IMAGE_EXTENSIONS)
    if not saved_name:
        flash("Please upload a PNG, JPG, or WEBP image.", "danger")
        return redirect(url_for("settings"))

    db = get_db()
    db.execute("UPDATE users SET profile_picture = ? WHERE id = ?", (saved_name, session["user_id"]))
    db.commit()
    flash("Profile picture updated.", "success")
    return redirect(url_for("settings"))


@app.route("/progress")
@login_required
def progress():
    courses_enrolled = get_enrolled_courses(session["user_id"])
    course_levels = {
        c["id"]: get_course_level_progress(session["user_id"], c["id"])
        for c in courses_enrolled
    }
    completion = get_course_completion_percent(session["user_id"])
    return render_template(
        "progress.html", courses=courses_enrolled,
        course_levels=course_levels, progress=completion,
    )


@app.route("/leaderboard")
@login_required
def leaderboard():
    db = get_db()
    rows = db.execute(
        """
        SELECT u.username,
               COUNT(DISTINCT CASE WHEN lp.level = 3 AND lp.passed = 1 THEN lp.course_id END) AS courses_completed,
               COALESCE(ROUND(AVG(lp.best_score) * 100.0 / 15, 1), 0) AS avg_score
        FROM users u
        LEFT JOIN level_progress lp ON lp.user_id = u.id
        GROUP BY u.id
        HAVING COUNT(lp.id) > 0
        ORDER BY courses_completed DESC, avg_score DESC
        LIMIT 10
        """
    ).fetchall()
    return render_template("leaderboard.html", rows=rows)


@app.route("/announcements")
@login_required
def announcements():
    db = get_db()
    rows = db.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    return render_template("announcements.html", rows=rows)


@app.route("/certificates")
@login_required
def certificates():
    db = get_db()
    completed = db.execute(
        """
        SELECT DISTINCT c.id, c.course_name
        FROM level_progress lp
        INNER JOIN courses c ON c.id = lp.course_id
        WHERE lp.user_id = ? AND lp.level = 3 AND lp.passed = 1
        ORDER BY c.course_name
        """,
        (session["user_id"],),
    ).fetchall()
    return render_template("certificates.html", rows=completed)


@app.route("/certificate/<int:course_id>")
@login_required
def certificate(course_id):
    db = get_db()
    course = db.execute("SELECT * FROM courses WHERE id = ?", (course_id,)).fetchone()
    if not course or not is_course_complete(session["user_id"], course_id):
        flash("Complete all 3 levels of this course to unlock its certificate.", "info")
        return redirect(url_for("certificates"))

    levels = get_course_level_progress(session["user_id"], course_id)
    total_possible = Config.QUESTIONS_PER_LEVEL * Config.TOTAL_LEVELS
    total_scored = sum(lv["best_score"] for lv in levels)
    overall_score_percent = round((total_scored / total_possible) * 100)

    enrollment = db.execute(
        "SELECT enrolled_at FROM enrollments WHERE user_id = ? AND course_id = ?",
        (session["user_id"], course_id),
    ).fetchone()
    level3_row = db.execute(
        "SELECT passed_at FROM level_progress WHERE user_id = ? AND course_id = ? AND level = 3",
        (session["user_id"], course_id),
    ).fetchone()

    time_taken = "—"
    if enrollment and level3_row and enrollment["enrolled_at"] and level3_row["passed_at"]:
        started = datetime.strptime(str(enrollment["enrolled_at"]), "%Y-%m-%d %H:%M:%S")
        finished = datetime.strptime(str(level3_row["passed_at"]).split(".")[0], "%Y-%m-%d %H:%M:%S")
        time_taken = format_duration((finished - started).total_seconds())

    return render_template(
        "certificate.html",
        course=course,
        username=session["username"],
        overall_score_percent=overall_score_percent,
        total_scored=total_scored,
        total_possible=total_possible,
        time_taken=time_taken,
        date=datetime.now().strftime("%B %d, %Y"),
    )


# ---------------------------------------------------------------------------
# File serving
# ---------------------------------------------------------------------------

@app.route("/uploads/<path:filename>")
@login_required
def uploaded_file(filename):
    return send_from_directory(Config.UPLOAD_FOLDER, filename)


@app.route("/profile_pictures/<path:filename>")
@login_required
def profile_picture_file(filename):
    return send_from_directory(Config.PROFILE_PICTURE_FOLDER, filename)


# ---------------------------------------------------------------------------
# Admin routes
# ---------------------------------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "GET":
        return render_template("admin/admin_login.html")

    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")

    valid_email = secrets.compare_digest(email, Config.ADMIN_EMAIL.lower())
    valid_password = secrets.compare_digest(password, Config.ADMIN_PASSWORD)

    if valid_email and valid_password:
        session.permanent = True
        session["admin"] = True
        flash("Welcome back, admin.", "success")
        return redirect(url_for("admin_dashboard"))

    flash("Invalid admin credentials.", "danger")
    return redirect(url_for("admin_login"))


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    flash("Admin logged out.", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = {
        "students": db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"],
        "courses": db.execute("SELECT COUNT(*) AS c FROM courses").fetchone()["c"],
        "quizzes": db.execute("SELECT COUNT(*) AS c FROM quizzes").fetchone()["c"],
        "enrollments": db.execute("SELECT COUNT(*) AS c FROM enrollments").fetchone()["c"],
    }
    return render_template("admin/admin_dashboard.html", stats=stats)


@app.route("/admin/courses")
@admin_required
def admin_courses():
    db = get_db()
    rows = db.execute("SELECT * FROM courses ORDER BY course_name").fetchall()
    edit_id = request.args.get("edit", type=int)
    edit_course = db.execute("SELECT * FROM courses WHERE id = ?", (edit_id,)).fetchone() if edit_id else None
    return render_template("admin/admin_courses.html", courses=rows, edit_course=edit_course)


@app.route("/admin/courses/add", methods=["POST"])
@admin_required
def admin_course_add():
    name = request.form.get("course_name", "").strip()
    description = request.form.get("description", "").strip()
    duration = request.form.get("duration", "").strip()
    instructor = request.form.get("instructor", "").strip()

    if not name:
        flash("Course name is required.", "danger")
        return redirect(url_for("admin_courses"))

    db = get_db()
    try:
        db.execute(
            "INSERT INTO courses (course_name, description, duration, instructor) VALUES (?, ?, ?, ?)",
            (name, description, duration, instructor),
        )
        db.commit()
        flash(f"Course '{name}' added.", "success")
    except sqlite3.IntegrityError:
        flash("A course with that name already exists.", "danger")

    return redirect(url_for("admin_courses"))


@app.route("/admin/courses/<int:course_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_course_edit(course_id):
    if request.method == "GET":
        return redirect(url_for("admin_courses", edit=course_id))

    name = request.form.get("course_name", "").strip()
    description = request.form.get("description", "").strip()
    duration = request.form.get("duration", "").strip()
    instructor = request.form.get("instructor", "").strip()

    if not name:
        flash("Course name is required.", "danger")
        return redirect(url_for("admin_courses", edit=course_id))

    db = get_db()
    try:
        db.execute(
            "UPDATE courses SET course_name=?, description=?, duration=?, instructor=? WHERE id=?",
            (name, description, duration, instructor, course_id),
        )
        db.commit()
        flash("Course updated.", "success")
    except sqlite3.IntegrityError:
        flash("Another course already uses that name.", "danger")

    return redirect(url_for("admin_courses"))


@app.route("/admin/courses/<int:course_id>/delete", methods=["POST"])
@admin_required
def admin_course_delete(course_id):
    db = get_db()
    db.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    db.commit()
    flash("Course deleted.", "success")
    return redirect(url_for("admin_courses"))


@app.route("/admin/students")
@admin_required
def admin_students():
    db = get_db()
    rows = db.execute(
        """
        SELECT u.*, COUNT(e.id) AS enrolled_count
        FROM users u LEFT JOIN enrollments e ON e.user_id = u.id
        GROUP BY u.id ORDER BY u.created_at DESC
        """
    ).fetchall()
    return render_template("admin/admin_students.html", students=rows)


@app.route("/admin/students/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_student_delete(user_id):
    db = get_db()
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))
    db.commit()
    flash("Student removed.", "success")
    return redirect(url_for("admin_students"))


@app.route("/admin/materials")
@admin_required
def admin_materials():
    db = get_db()
    rows = db.execute(
        """
        SELECT m.*, c.course_name FROM materials m
        INNER JOIN courses c ON c.id = m.course_id
        ORDER BY c.course_name, CASE m.difficulty WHEN 'easy' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END
        """
    ).fetchall()
    course_rows = db.execute("SELECT * FROM courses ORDER BY course_name").fetchall()
    return render_template("admin/admin_materials.html", materials=rows, course_list=course_rows)


@app.route("/admin/materials/add", methods=["POST"])
@admin_required
def admin_material_add():
    course_id = request.form.get("course_id", type=int)
    title = request.form.get("title", "").strip()
    material_type = request.form.get("material_type", "link")
    difficulty = request.form.get("difficulty", "easy")
    if difficulty not in ("easy", "medium", "hard"):
        difficulty = "easy"
    link_value = request.form.get("value", "").strip()
    file = request.files.get("file")

    if not course_id or not title:
        flash("Course and title are required.", "danger")
        return redirect(url_for("admin_materials"))

    if material_type == "pdf" and file and file.filename:
        saved_name = save_upload(file, Config.UPLOAD_FOLDER, Config.ALLOWED_MATERIAL_EXTENSIONS)
        if not saved_name:
            flash("Please upload a PDF file.", "danger")
            return redirect(url_for("admin_materials"))
        value = saved_name
    elif material_type == "link" and link_value:
        value = link_value
    else:
        flash("Provide a link or upload a PDF.", "danger")
        return redirect(url_for("admin_materials"))

    db = get_db()
    db.execute(
        "INSERT INTO materials (course_id, title, material_type, value, difficulty) VALUES (?, ?, ?, ?, ?)",
        (course_id, title, material_type, value, difficulty),
    )
    db.commit()
    flash("Material added.", "success")
    return redirect(url_for("admin_materials"))


@app.route("/admin/materials/<int:material_id>/delete", methods=["POST"])
@admin_required
def admin_material_delete(material_id):
    db = get_db()
    db.execute("DELETE FROM materials WHERE id = ?", (material_id,))
    db.commit()
    flash("Material removed.", "success")
    return redirect(url_for("admin_materials"))


@app.route("/admin/quizzes")
@admin_required
def admin_quizzes():
    db = get_db()
    course_list = db.execute("SELECT * FROM courses ORDER BY course_name").fetchall()

    filter_course_id = request.args.get("course_id", type=int)
    filter_level = request.args.get("level", type=int)
    if not filter_course_id and course_list:
        filter_course_id = course_list[0]["id"]
    if filter_level not in (1, 2, 3):
        filter_level = 1

    rows = db.execute(
        """
        SELECT q.*, c.course_name FROM quizzes q
        INNER JOIN courses c ON c.id = q.course_id
        WHERE q.course_id = ? AND q.level = ?
        ORDER BY q.id
        """,
        (filter_course_id, filter_level),
    ).fetchall()

    edit_id = request.args.get("edit", type=int)
    edit_quiz = db.execute("SELECT * FROM quizzes WHERE id = ?", (edit_id,)).fetchone() if edit_id else None
    return render_template(
        "admin/admin_quizzes.html", quizzes=rows, course_list=course_list, edit_quiz=edit_quiz,
        filter_course_id=filter_course_id, filter_level=filter_level, level_labels=Config.LEVEL_LABELS,
    )


def _quiz_form_values(form):
    course_id = form.get("course_id", type=int)
    level = form.get("level", type=int) or 1
    question = form.get("question", "").strip()
    options = [
        form.get("option1", "").strip(), form.get("option2", "").strip(),
        form.get("option3", "").strip(), form.get("option4", "").strip(),
    ]
    correct_index = form.get("correct_option", type=int) or 1
    return course_id, level, question, options, correct_index


@app.route("/admin/quizzes/add", methods=["POST"])
@admin_required
def admin_quiz_add():
    course_id, level, question, options, correct_index = _quiz_form_values(request.form)

    if not course_id or not question or not all(options):
        flash("Fill in the course, question, and all four options.", "danger")
        return redirect(url_for("admin_quizzes"))

    answer = options[correct_index - 1]
    db = get_db()
    db.execute(
        """INSERT INTO quizzes (course_id, level, question, option1, option2, option3, option4, answer)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (course_id, level, question, *options, answer),
    )
    db.commit()
    flash("Quiz question added.", "success")
    return redirect(url_for("admin_quizzes", course_id=course_id, level=level))


@app.route("/admin/quizzes/<int:quiz_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_quiz_edit(quiz_id):
    if request.method == "GET":
        return redirect(url_for("admin_quizzes", edit=quiz_id))

    course_id, level, question, options, correct_index = _quiz_form_values(request.form)

    if not course_id or not question or not all(options):
        flash("Fill in the course, question, and all four options.", "danger")
        return redirect(url_for("admin_quizzes", edit=quiz_id))

    answer = options[correct_index - 1]
    db = get_db()
    db.execute(
        """UPDATE quizzes SET course_id=?, level=?, question=?, option1=?, option2=?,
           option3=?, option4=?, answer=? WHERE id=?""",
        (course_id, level, question, *options, answer, quiz_id),
    )
    db.commit()
    flash("Quiz question updated.", "success")
    return redirect(url_for("admin_quizzes", course_id=course_id, level=level))


@app.route("/admin/quizzes/<int:quiz_id>/delete", methods=["POST"])
@admin_required
def admin_quiz_delete(quiz_id):
    db = get_db()
    db.execute("DELETE FROM quizzes WHERE id = ?", (quiz_id,))
    db.commit()
    flash("Quiz question deleted.", "success")
    return redirect(url_for("admin_quizzes"))


@app.route("/admin/scores")
@admin_required
def admin_scores():
    db = get_db()
    rows = db.execute(
        """
        SELECT u.username, u.email, c.course_name, s.level, s.score, s.taken_at
        FROM scores s
        INNER JOIN users u ON u.id = s.user_id
        INNER JOIN courses c ON c.id = s.course_id
        ORDER BY s.taken_at DESC
        """
    ).fetchall()
    return render_template("admin/admin_scores.html", rows=rows)


@app.route("/admin/announcements")
@admin_required
def admin_announcements():
    db = get_db()
    rows = db.execute("SELECT * FROM announcements ORDER BY id DESC").fetchall()
    return render_template("admin/admin_announcements.html", rows=rows)


@app.route("/admin/announcements/add", methods=["POST"])
@admin_required
def admin_announcement_add():
    message = request.form.get("message", "").strip()
    if not message:
        flash("Announcement message can't be empty.", "danger")
        return redirect(url_for("admin_announcements"))

    db = get_db()
    db.execute("INSERT INTO announcements (message) VALUES (?)", (message,))
    db.commit()
    flash("Announcement posted.", "success")
    return redirect(url_for("admin_announcements"))


@app.route("/admin/announcements/<int:announcement_id>/delete", methods=["POST"])
@admin_required
def admin_announcement_delete(announcement_id):
    db = get_db()
    db.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
    db.commit()
    flash("Announcement removed.", "success")
    return redirect(url_for("admin_announcements"))


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
def bad_request(e):
    return render_template("errors/error.html", code=400, title="Something went wrong",
                            message=getattr(e, "description", "Please try that again.")), 400


@app.errorhandler(404)
def not_found(e):
    return render_template("errors/error.html", code=404, title="Page not found",
                            message="That page doesn't exist or may have moved."), 404


@app.errorhandler(413)
def too_large(e):
    return render_template("errors/error.html", code=413, title="File too large",
                            message="Please upload a file smaller than 10 MB."), 413


@app.errorhandler(500)
def server_error(e):
    return render_template("errors/error.html", code=500, title="Something broke on our end",
                            message="Please try again in a moment."), 500


if __name__ == "__main__":
    app.run(debug=True)
