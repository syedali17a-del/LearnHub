import re
import os
import sqlite3

os.chdir(os.path.dirname(os.path.abspath(__file__)))
if os.path.exists('lms.db'):
    os.remove('lms.db')

from app import app

failures = 0

def check(desc, condition):
    global failures
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {desc}")
    if not condition:
        failures += 1

def get_csrf(client, url):
    resp = client.get(url)
    match = re.search(r'name="csrf_token" value="([^"]+)"', resp.get_data(as_text=True))
    assert match, f"No CSRF token found on {url} (status {resp.status_code})"
    return match.group(1)

client = app.test_client()

# ---------------- Public pages ----------------
check("GET / -> 200", client.get('/').status_code == 200)
check("GET /welcome -> 200", client.get('/welcome').status_code == 200)
check("GET /courses -> 200", client.get('/courses').status_code == 200)
check("GET /courses/1 -> 200", client.get('/courses/1').status_code == 200)
check("GET /courses/9999 -> 404", client.get('/courses/9999').status_code == 404)

# ---------------- CSRF protection ----------------
r = client.post('/login', data={'email': 'x@x.com', 'password': 'x'})
check("POST without csrf_token -> 400", r.status_code == 400)

# ---------------- Register ----------------
token = get_csrf(client, '/register')
r = client.post('/register', data={
    'username': 'Test Student', 'email': 'student@test.com',
    'password': 'password123', 'confirm_password': 'password123',
    'csrf_token': token,
}, follow_redirects=True)
check("Register -> 200", r.status_code == 200)

token = get_csrf(client, '/register')
r = client.post('/register', data={
    'username': 'Test Student', 'email': 'student@test.com',
    'password': 'password123', 'confirm_password': 'password123',
    'csrf_token': token,
}, follow_redirects=True)
check("Duplicate email handled gracefully (200, not 500)", r.status_code == 200)
check("Duplicate email shows friendly message", b'already exists' in r.data)

# ---------------- Login ----------------
token = get_csrf(client, '/login')
r = client.post('/login', data={
    'email': 'student@test.com', 'password': 'password123', 'csrf_token': token,
}, follow_redirects=True)
check("Login -> 200", r.status_code == 200)

check("GET /dashboard -> 200", client.get('/dashboard').status_code == 200)

# ---------------- Enroll ----------------
token = get_csrf(client, '/courses/1')
r = client.post('/courses/1/enroll', data={'csrf_token': token}, follow_redirects=True)
check("Enroll -> 200", r.status_code == 200)

check("GET /materials -> 200", client.get('/materials').status_code == 200)
r = client.get('/quiz/1', follow_redirects=True)
check("GET /quiz/1 -> routes to Level 1 (200)", r.status_code == 200 and b'Level 1' in r.data)

# ---------------- Take quiz: clear all 3 levels with perfect scores ----------------
conn = sqlite3.connect('lms.db')
conn.row_factory = sqlite3.Row

def submit_level(level):
    qs = conn.execute("SELECT * FROM quizzes WHERE course_id=1 AND level=?", (level,)).fetchall()
    token = get_csrf(client, f'/quiz/1/{level}')
    form_data = {'csrf_token': token}
    for q in qs:
        form_data[f'q{q["id"]}'] = q['answer']
    return client.post(f'/quiz/1/{level}/submit', data=form_data, follow_redirects=True)

r = submit_level(1)
check("Submit Level 1 (15/15) -> 200", r.status_code == 200)
check("Level 1 pass shows 15/15", b'15/15' in r.data)
check("Level 2 unlocked after passing Level 1", b'Start Level 2' in r.data)

r = submit_level(2)
check("Submit Level 2 (15/15) -> 200", r.status_code == 200)
check("Level 3 unlocked after passing Level 2", b'Start Level 3' in r.data)

r = submit_level(3)
check("Submit Level 3 (15/15) -> 200", r.status_code == 200)
check("Course marked complete after Level 3", b'certificate is ready' in r.data.lower() or b'Get Your Certificate' in r.data)
conn.close()

check("GET /scores -> 200", client.get('/scores').status_code == 200)
check("GET /profile -> 200", client.get('/profile').status_code == 200)
check("GET /settings -> 200", client.get('/settings').status_code == 200)

# ---------------- Change password ----------------
token = get_csrf(client, '/settings')
r = client.post('/settings/password', data={
    'current_password': 'password123', 'new_password': 'newpass456',
    'confirm_password': 'newpass456', 'csrf_token': token,
}, follow_redirects=True)
check("Update password -> 200", r.status_code == 200)
check("Password update success message shown", b'updated successfully' in r.data)

check("GET /progress -> 200", client.get('/progress').status_code == 200)
check("GET /leaderboard -> 200", client.get('/leaderboard').status_code == 200)
check("GET /announcements -> 200", client.get('/announcements').status_code == 200)
check("GET /certificates -> 200", client.get('/certificates').status_code == 200)
r = client.get('/certificate/1')
check("GET /certificate/1 (all 3 levels passed) -> 200", r.status_code == 200)
check("Certificate shows overall score", b'Overall Score' in r.data)
check("Certificate shows time taken", b'Time to Complete' in r.data)

# ---------------- Logout / protected routes ----------------
r = client.get('/logout', follow_redirects=True)
check("Logout -> 200", r.status_code == 200)
r = client.get('/dashboard', follow_redirects=True)
check("Dashboard after logout redirects to login", b'Welcome Back' in r.data)

# =====================================================================
# ADMIN FLOW
# =====================================================================
admin_client = app.test_client()

token = get_csrf(admin_client, '/admin/login')
r = admin_client.post('/admin/login', data={
    'email': 'admin@learnhub.com', 'password': 'admin123', 'csrf_token': token,
}, follow_redirects=True)
check("Admin login -> 200", r.status_code == 200)
check("GET /admin -> 200", admin_client.get('/admin').status_code == 200)
check("GET /admin/courses -> 200", admin_client.get('/admin/courses').status_code == 200)

token = get_csrf(admin_client, '/admin/courses')
r = admin_client.post('/admin/courses/add', data={
    'course_name': 'Temporary Test Course', 'description': 'desc',
    'duration': '1 week', 'instructor': 'Tester', 'csrf_token': token,
}, follow_redirects=True)
check("Admin add course -> 200", r.status_code == 200)
check("New course appears in list", b'Temporary Test Course' in r.data)

conn = sqlite3.connect('lms.db')
conn.row_factory = sqlite3.Row
new_course = conn.execute("SELECT * FROM courses WHERE course_name='Temporary Test Course'").fetchone()
conn.close()
new_course_id = new_course['id']

check("Admin edit course form loads -> 200",
      admin_client.get(f'/admin/courses?edit={new_course_id}').status_code == 200)

token = get_csrf(admin_client, f'/admin/courses?edit={new_course_id}')
r = admin_client.post(f'/admin/courses/{new_course_id}/edit', data={
    'course_name': 'Temporary Test Course Updated', 'description': 'desc2',
    'duration': '2 weeks', 'instructor': 'Tester2', 'csrf_token': token,
}, follow_redirects=True)
check("Admin update course -> 200", r.status_code == 200)
check("Updated name appears", b'Temporary Test Course Updated' in r.data)

token = get_csrf(admin_client, '/admin/courses')
r = admin_client.post(f'/admin/courses/{new_course_id}/delete', data={'csrf_token': token}, follow_redirects=True)
check("Admin delete course -> 200", r.status_code == 200)

r = admin_client.get('/admin/students')
check("GET /admin/students -> 200", r.status_code == 200)
check("Test student appears in admin list", b'student@test.com' in r.data)

check("GET /admin/materials -> 200", admin_client.get('/admin/materials').status_code == 200)

token = get_csrf(admin_client, '/admin/materials')
r = admin_client.post('/admin/materials/add', data={
    'course_id': '1', 'title': 'Intro Slides', 'material_type': 'link',
    'value': 'https://example.com/slides.pdf', 'csrf_token': token,
}, follow_redirects=True)
check("Admin add material -> 200", r.status_code == 200)
check("Material appears", b'Intro Slides' in r.data)

check("GET /admin/quizzes -> 200", admin_client.get('/admin/quizzes').status_code == 200)

token = get_csrf(admin_client, '/admin/quizzes')
r = admin_client.post('/admin/quizzes/add', data={
    'course_id': '1', 'question': 'Test question?',
    'option1': 'A', 'option2': 'B', 'option3': 'C', 'option4': 'D',
    'correct_option': '2', 'csrf_token': token,
}, follow_redirects=True)
check("Admin add quiz -> 200", r.status_code == 200)
check("Quiz question appears", b'Test question?' in r.data)

check("GET /admin/scores -> 200", admin_client.get('/admin/scores').status_code == 200)
check("GET /admin/announcements -> 200", admin_client.get('/admin/announcements').status_code == 200)

token = get_csrf(admin_client, '/admin/announcements')
r = admin_client.post('/admin/announcements/add', data={
    'message': 'Welcome to the new semester!', 'csrf_token': token,
}, follow_redirects=True)
check("Admin add announcement -> 200", r.status_code == 200)
check("Announcement appears in admin list", b'Welcome to the new semester' in r.data)

# ---------------- Student sees the announcement ----------------
token = get_csrf(client, '/login')
r = client.post('/login', data={'email': 'student@test.com', 'password': 'newpass456', 'csrf_token': token},
                 follow_redirects=True)
check("Re-login with updated password works", r.status_code == 200)

check("Dashboard shows announcement", b'Welcome to the new semester' in client.get('/dashboard').data)
check("Announcements page shows it", b'Welcome to the new semester' in client.get('/announcements').data)

# ---------------- Access control ----------------
r = client.get('/admin', follow_redirects=True)
check("Student cannot access /admin", b'Admin Login' in r.data)

anon_client = app.test_client()
r = anon_client.get('/dashboard', follow_redirects=True)
check("Anonymous redirected from dashboard", b'Welcome Back' in r.data)
r = anon_client.get('/admin', follow_redirects=True)
check("Anonymous redirected from admin", b'Admin Login' in r.data)
check("Unknown route -> 404", anon_client.get('/nope-not-a-route').status_code == 404)

print("\n" + "=" * 50)
print(f"TOTAL FAILURES: {failures}")
print("=" * 50)
