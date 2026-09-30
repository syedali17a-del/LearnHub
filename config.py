import os
from datetime import timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Config:
    # Set a real SECRET_KEY environment variable before deploying anywhere
    # public. This fallback is only safe for local development.
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-key-change-this-before-deploying")

    DB_PATH = os.path.join(BASE_DIR, "lms.db")

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    PROFILE_PICTURE_FOLDER = os.path.join(BASE_DIR, "profile_pictures")

    ALLOWED_MATERIAL_EXTENSIONS = {"pdf"}
    ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}

    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB upload limit

    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Admin sign-in. Override both via environment variables in production;
    # these defaults exist only so the app runs out of the box.
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@learnhub.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

    # Level-gated quiz system: 3 levels per course, 15 questions each.
    # Students must clear a level's pass score to unlock the next one.
    QUESTIONS_PER_LEVEL = 15
    LEVEL_PASS_SCORES = {1: 7, 2: 12, 3: 15}
    LEVEL_LABELS = {1: "Level 1 — Beginner", 2: "Level 2 — Intermediate", 3: "Level 3 — Advanced"}
    TOTAL_LEVELS = 3
