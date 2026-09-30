import sqlite3
from config import Config
from seed_data import SAMPLE_COURSES, SAMPLE_MATERIALS, SAMPLE_QUIZZES

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    profile_picture TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_name TEXT NOT NULL UNIQUE,
    description TEXT DEFAULT '',
    duration TEXT DEFAULT '',
    instructor TEXT DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS enrollments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    enrolled_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, course_id)
);

-- difficulty: 'easy' | 'medium' | 'hard' — one material of each per course
CREATE TABLE IF NOT EXISTS materials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    material_type TEXT NOT NULL DEFAULT 'link',
    value TEXT NOT NULL,
    difficulty TEXT NOT NULL DEFAULT 'easy',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- level: 1 (Beginner), 2 (Intermediate), 3 (Advanced) — 15 questions each
CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    level INTEGER NOT NULL DEFAULT 1,
    question TEXT NOT NULL,
    option1 TEXT NOT NULL,
    option2 TEXT NOT NULL,
    option3 TEXT NOT NULL,
    option4 TEXT NOT NULL,
    answer TEXT NOT NULL
);

-- One row per quiz attempt, kept for history/leaderboard/admin visibility.
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    level INTEGER NOT NULL DEFAULT 1,
    score REAL NOT NULL,
    taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tracks pass/fail + best raw score (out of 15) per student, per course, per
-- level. This is what gates access to the next level and what determines
-- when a course (and its certificate) is complete (level 3 passed).
CREATE TABLE IF NOT EXISTS level_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    level INTEGER NOT NULL,
    best_score INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    passed_at TIMESTAMP,
    UNIQUE(user_id, course_id, level)
);

CREATE TABLE IF NOT EXISTS announcements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


def get_connection():
    """Return a new SQLite connection with foreign keys enabled and
    rows accessible by column name (row['email']) instead of fragile
    positional indexing (row[3])."""
    conn = sqlite3.connect(Config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_existing_tables(conn):
    """Adds new columns to tables that may already exist from an older
    version of the database, so upgrading in place doesn't require
    deleting lms.db. Safe to run every startup — each ALTER is skipped
    if the column is already present."""
    cur = conn.cursor()

    def column_exists(table, column):
        cols = [row["name"] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]
        return column in cols

    if not column_exists("materials", "difficulty"):
        cur.execute("ALTER TABLE materials ADD COLUMN difficulty TEXT NOT NULL DEFAULT 'easy'")

    if not column_exists("quizzes", "level"):
        cur.execute("ALTER TABLE quizzes ADD COLUMN level INTEGER NOT NULL DEFAULT 1")

    if not column_exists("scores", "level"):
        cur.execute("ALTER TABLE scores ADD COLUMN level INTEGER NOT NULL DEFAULT 1")

    conn.commit()


def init_db(seed=True):
    conn = get_connection()
    cur = conn.cursor()
    cur.executescript(SCHEMA)
    conn.commit()

    _migrate_existing_tables(conn)

    if seed:
        cur.execute("SELECT COUNT(*) FROM courses")
        if cur.fetchone()[0] == 0:
            for name, desc, duration, instructor in SAMPLE_COURSES:
                cur.execute(
                    "INSERT INTO courses (course_name, description, duration, instructor) "
                    "VALUES (?, ?, ?, ?)",
                    (name, desc, duration, instructor),
                )
            conn.commit()

            cur.execute("SELECT id, course_name FROM courses")
            course_ids = {row["course_name"]: row["id"] for row in cur.fetchall()}

            for course_name, materials in SAMPLE_MATERIALS.items():
                course_id = course_ids.get(course_name)
                if not course_id:
                    continue
                for title, url, difficulty in materials:
                    cur.execute(
                        """INSERT INTO materials (course_id, title, material_type, value, difficulty)
                           VALUES (?, ?, 'link', ?, ?)""",
                        (course_id, title, url, difficulty),
                    )
            conn.commit()

            for course_name, levels in SAMPLE_QUIZZES.items():
                course_id = course_ids.get(course_name)
                if not course_id:
                    continue
                for level, questions in levels.items():
                    for question, opt1, opt2, opt3, opt4, correct_index in questions:
                        options = [opt1, opt2, opt3, opt4]
                        answer = options[correct_index - 1]
                        cur.execute(
                            """INSERT INTO quizzes
                               (course_id, level, question, option1, option2, option3, option4, answer)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            (course_id, level, question, opt1, opt2, opt3, opt4, answer),
                        )
            conn.commit()

    conn.close()


if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", Config.DB_PATH)
