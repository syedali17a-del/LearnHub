# LearnHub — Learning Management System

A full-stack Flask LMS: students browse and enroll in courses, work through
per-course quizzes, track progress, and earn certificates. Admins manage
courses, students, materials, quizzes, and announcements from a protected
panel.

This is a rebuild of your original project — same core idea, same tech
stack (Flask + SQLite + Jinja), rebuilt with a consistent design system,
a normalized database, and the security gaps closed.

---

## Quick Start

```bash
pip install -r requirements.txt --break-system-packages   # Pydroid/Termux
# or just: pip install -r requirements.txt                # normal machine

python3 app.py
```

Open `http://127.0.0.1:5000`. The database (`lms.db`) is created and
seeded automatically on first run — 6 sample courses, each with 3
difficulty-tiered materials and a 3-level quiz (15 questions per level,
270 questions total), so there's something to click through immediately.

**Default admin login:** `admin@learnhub.com` / `admin123`
Change this before showing the app to anyone else (see Environment
Variables below). The app prints a warning to the console every time it
starts if you're still using the default.

---

## Environment Variables

None of these are required to run locally — the app has safe fallbacks —
but set them before deploying anywhere public:

| Variable         | Purpose                                  | Fallback                  |
|-------------------|-------------------------------------------|----------------------------|
| `SECRET_KEY`      | Signs session cookies                     | dev key (not safe to keep) |
| `ADMIN_EMAIL`     | Admin login email                         | admin@learnhub.com         |
| `ADMIN_PASSWORD`  | Admin login password                      | admin123                   |

On Linux/Mac/Termux: `export SECRET_KEY="something-long-and-random"`
On Pydroid, you can instead just edit the fallback values directly in
`config.py` before running.

---

## Project Structure

```
LearnHub/
├── app.py                     All routes, auth, CSRF, uploads
├── config.py                  Secrets, upload rules, admin credentials
├── database.py                Schema + sample seed data
├── requirements.txt
├── test_app_student_and_admin_flow.py   Automated tests (see Testing)
├── test_app_edge_cases.py
├── static/
│   ├── style.css               Design system (variables, components)
│   └── script.js                Nav highlighting, flash auto-dismiss, quiz counter, etc.
├── templates/
│   ├── base.html                Shared layout + conditional bottom nav
│   ├── _macros.html             Reusable: flash messages, CSRF field, progress ring
│   ├── (public + student pages)
│   ├── admin/                   Admin panel (all routes protected)
│   └── errors/                  Shared 400/404/413/500 page
├── uploads/                    PDF materials (git-ignored, folder kept via .gitkeep)
└── profile_pictures/           Uploaded avatars (git-ignored)
```

---

## What Changed From Your Original Version

**Security**
- Every `/admin/*` route now actually checks the admin session. In the
  original, only `/admin` itself was protected — `/view_users`,
  `/add_course`, `/delete_course` etc. had no check at all, so anyone who
  knew or guessed the URL could use them.
- Added CSRF protection on every form (a hidden token tied to your
  session, checked on every POST).
- File uploads now validate extension, use `secure_filename`, and get a
  random prefix so two people uploading `notes.pdf` can't overwrite each
  other. Upload size is capped at 10 MB.
- Admin credentials moved out of source code and into `config.py`
  (environment-variable overridable), compared with a constant-time check
  instead of `==`.
- Emails are normalized (lowercased/trimmed) and the `users` table has a
  real `UNIQUE` constraint, so duplicate accounts and the old
  "de-duplicate after the fact" cleanup queries are gone.

**Database**
- `courses` gained `description`, `duration`, and `instructor` columns —
  your original `course_details` route already read `course[2]`,
  `course[3]`, `course[4]` expecting these, but the schema never defined
  them.
- Everything now links by ID with foreign keys (`ON DELETE CASCADE`)
  instead of by course-name text — renaming a course no longer silently
  orphans its enrollments/materials/quizzes.
- **Quizzes are now scoped per-course** (per your answer when I asked) —
  `quizzes.course_id` links each question to one course, so a student
  taking "Python Fundamentals" only sees Python questions, not the whole
  question bank.
- `scores` now records which course a quiz result belongs to, which is
  what makes real per-course progress possible.

**Functionality that existed but wasn't reachable**
- Change-password and profile-picture upload had working routes in your
  original `app.py` but no page ever linked to them. Both now live on a
  proper `/settings` page.
- `/progress` was hardcoded sample text ("Python Mastery — 75%"). It now
  shows your actual enrolled courses with real progress rings, calculated
  from your latest quiz score per course.

**Everything that used to `return "<h1>...</h1>"`**
About 20 of your original routes returned raw HTML strings built with
f-strings (add course, view users, leaderboard, certificate, and so on).
These are now real templates using the same design system as the rest of
the app, and mutations (add/edit/delete) now redirect back to a proper
list page with a flash message instead of dead-ending on a confirmation
screen.

**Images**
The `static/Images/*.png` files in your upload were all present but
0 bytes, and the paths in `dashboard.html` didn't match the folder's
actual capitalization anyway. Rather than patch both problems, the
rebuild uses Bootstrap Icons (a font, loaded from the same CDN pattern
you were already using for Bootstrap) — nothing to go missing, crisp at
any size, no case-sensitivity risk if you ever deploy to a Linux host.

**Dropped**
`templates/index.html` was never linked to by any route (`/` renders
`splash.html`) — it looked like an earlier draft of the welcome page, so
it wasn't carried into the rebuild. `templates/navbar.html` was empty and
is also gone.

---

## Design System

Colors, spacing, radii, and shadows are defined once as CSS variables at
the top of `style.css` instead of repeated per-selector — your original
had `.dashboard-header`, `.avatar`, `.banner-card` and a few others
defined two or three times with different values each time. Headings use
Sora, body/UI text uses Inter (both loaded from Google Fonts), replacing
the default Segoe UI. The one deliberate signature element is the
circular progress ring (pure CSS `conic-gradient`, no images or JS
charting library) used on the dashboard and progress page — progress is
the actual point of an LMS, so it gets a real visual treatment instead of
a plain bar.

## Progress & Certificates — how they're calculated

There's no granular "which lesson did you open" tracking in this data
model, so **progress per course = your latest quiz score for that
course** (0% if you haven't taken it yet). A certificate unlocks once
your best score in a course reaches 50%. Both thresholds are simple
proxies, not a full content-completion engine — worth knowing if you
extend this later.

---

## Testing

Two scripts exercise the whole app using Flask's test client — no server
needs to be running:

```bash
python3 test_app_student_and_admin_flow.py   # register→enroll→quiz→admin CRUD, 57 checks
python3 test_app_edge_cases.py               # uploads, cascade deletes, failing scores, 25 checks
```

Both wipe and reseed the database when run, so use a copy of `lms.db` if
you want to keep data around.

---

## Possible Next Steps

- Pagination once you have many courses/students
- Flask-Migrate (or hand-written migrations) if you change the schema
  again after real users exist
- Email verification on registration
- Splitting `app.py` into Blueprints if it keeps growing — it's
  intentionally kept as one file for now to match how you've been
  editing this in Acode
