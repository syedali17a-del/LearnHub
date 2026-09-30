import re
import io
import os
import sqlite3

os.chdir(os.path.dirname(os.path.abspath(__file__)))
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
admin_client = app.test_client()

# Log in the existing student from round 1, and admin
token = get_csrf(client, '/login')
client.post('/login', data={'email': 'student@test.com', 'password': 'newpass456', 'csrf_token': token},
            follow_redirects=True)

token = get_csrf(admin_client, '/admin/login')
admin_client.post('/admin/login', data={'email': 'admin@learnhub.com', 'password': 'admin123', 'csrf_token': token},
                   follow_redirects=True)

# ---------------- Failing a quiz + certificate gating ----------------
# Course 2 (Full-Stack Web Development) - enroll then answer Level 1 all wrong
token = get_csrf(client, '/settings')
client.post('/courses/2/enroll', data={'csrf_token': token}, follow_redirects=True)

conn = sqlite3.connect('lms.db')
conn.row_factory = sqlite3.Row
qs = conn.execute("SELECT * FROM quizzes WHERE course_id=2 AND level=1").fetchall()
conn.close()

token = get_csrf(client, '/quiz/2/1')
form_data = {'csrf_token': token}
for q in qs:
    wrong = next(o for o in [q['option1'], q['option2'], q['option3'], q['option4']] if o != q['answer'])
    form_data[f'q{q["id"]}'] = wrong

r = client.post('/quiz/2/1/submit', data=form_data, follow_redirects=True)
check("Submit all-wrong Level 1 quiz -> 200", r.status_code == 200)
check("Shows 0/15 score", b'0/15' in r.data)
check("Failing shows retry, not next-level, CTA", b'Retake Level 1' in r.data)

r = client.get('/certificate/2', follow_redirects=True)
check("Certificate blocked (level 1 not passed) -> redirects to list", b'Certificates' in r.data)
check("Flash explains why", b'complete all 3 levels' in r.data.lower())

# ---------------- Double enrollment ----------------
token = get_csrf(client, '/settings')
r = client.post('/courses/1/enroll', data={'csrf_token': token}, follow_redirects=True)
check("Re-enrolling in same course -> 200 (no crash)", r.status_code == 200)
check("Shows already-enrolled message", b'already enrolled' in r.data)

# ---------------- Wrong current password on settings ----------------
token = get_csrf(client, '/settings')
r = client.post('/settings/password', data={
    'current_password': 'totally-wrong', 'new_password': 'whatever123',
    'confirm_password': 'whatever123', 'csrf_token': token,
}, follow_redirects=True)
check("Wrong current password rejected -> 200", r.status_code == 200)
check("Shows incorrect-password message", b'incorrect' in r.data.lower())

# password should NOT have changed - verify old (newpass456) still works
token = get_csrf(client, '/login')
r = client.post('/login', data={'email': 'student@test.com', 'password': 'newpass456', 'csrf_token': token},
                 follow_redirects=True)
check("Original password still works after rejected change", b'Dashboard' in r.data or client.get('/dashboard').status_code == 200)

# ---------------- File upload: profile picture ----------------
token = get_csrf(client, '/settings')
fake_image = (io.BytesIO(b'\x89PNG\r\n\x1a\nfakepngbytes'), 'avatar.png')
r = client.post('/settings/picture', data={'photo': fake_image, 'csrf_token': token},
                 content_type='multipart/form-data', follow_redirects=True)
check("Profile picture upload -> 200", r.status_code == 200)
check("Upload success message shown", b'Profile picture updated' in r.data)

uploaded_files = os.listdir('profile_pictures')
check("File actually saved to profile_pictures/", any(f.endswith('avatar.png') for f in uploaded_files))

r = client.get('/profile')
check("Profile page now shows uploaded image", b'<img' in r.data and b'profile_pictures' in r.data)

# reject disallowed extension
token = get_csrf(client, '/settings')
fake_exe = (io.BytesIO(b'not an image'), 'malware.exe')
r = client.post('/settings/picture', data={'photo': fake_exe, 'csrf_token': token},
                 content_type='multipart/form-data', follow_redirects=True)
check("Disallowed file extension rejected -> 200", r.status_code == 200)
check("Shows rejection message", b'PNG, JPG' in r.data)

# ---------------- File upload: admin PDF material ----------------
token = get_csrf(admin_client, '/admin/materials')
fake_pdf = (io.BytesIO(b'%PDF-1.4 fake pdf content'), 'syllabus.pdf')
r = admin_client.post('/admin/materials/add', data={
    'course_id': '1', 'title': 'Course Syllabus', 'material_type': 'pdf',
    'file': fake_pdf, 'csrf_token': token,
}, content_type='multipart/form-data', follow_redirects=True)
check("Admin PDF upload -> 200", r.status_code == 200)
check("PDF material appears", b'Course Syllabus' in r.data)

uploaded = os.listdir('uploads')
check("PDF actually saved to uploads/", any(f.endswith('syllabus.pdf') for f in uploaded))

r = client.get('/materials')
check("Student sees the PDF material with Open link", b'Course Syllabus' in r.data)

# ---------------- Cascade delete ----------------
token = get_csrf(admin_client, '/admin/courses')
admin_client.post('/admin/courses/add', data={
    'course_name': 'Cascade Test Course', 'description': '', 'duration': '', 'instructor': '',
    'csrf_token': token,
}, follow_redirects=True)

conn = sqlite3.connect('lms.db')
conn.row_factory = sqlite3.Row
cascade_course = conn.execute("SELECT * FROM courses WHERE course_name='Cascade Test Course'").fetchone()
cascade_id = cascade_course['id']
conn.close()

token = get_csrf(admin_client, '/admin/quizzes')
admin_client.post('/admin/quizzes/add', data={
    'course_id': str(cascade_id), 'question': 'Cascade question?',
    'option1': 'A', 'option2': 'B', 'option3': 'C', 'option4': 'D',
    'correct_option': '1', 'csrf_token': token,
}, follow_redirects=True)

conn = sqlite3.connect('lms.db')
before_count = conn.execute("SELECT COUNT(*) FROM quizzes WHERE course_id=?", (cascade_id,)).fetchone()[0]
conn.close()
check("Quiz question exists before delete", before_count == 1)

token = get_csrf(admin_client, '/admin/courses')
admin_client.post(f'/admin/courses/{cascade_id}/delete', data={'csrf_token': token}, follow_redirects=True)

conn = sqlite3.connect('lms.db')
after_count = conn.execute("SELECT COUNT(*) FROM quizzes WHERE course_id=?", (cascade_id,)).fetchone()[0]
course_gone = conn.execute("SELECT COUNT(*) FROM courses WHERE id=?", (cascade_id,)).fetchone()[0]
conn.close()
check("Quiz cascade-deleted with course", after_count == 0)
check("Course itself deleted", course_gone == 0)

# ---------------- Error pages render correctly ----------------
r = client.get('/nonexistent-page-xyz')
check("404 page renders (has content, not blank)", len(r.data) > 200)
check("404 page has helpful message", b'exist' in r.data.lower() or b'moved' in r.data.lower())

print("\n" + "=" * 50)
print(f"TOTAL FAILURES: {failures}")
print("=" * 50)
