# Kinevox Academy Institute — Backend API

A complete REST API for the Kinevox Academy Management System, built with
**Python + Flask + SQLite**. No external database server required — the DB
file is created automatically on first run.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. (Optional) copy and edit environment config
cp .env.example .env

# 3. Run the server
python app.py
```

Server starts at **http://localhost:5000**

Default admin credentials (same as the frontend):
| Field    | Value        |
|----------|--------------|
| Username | `admin`      |
| Password | `Kinevox123` |

---

## Authentication

All `/api/*` routes (except `/api/health` and `/api/auth/login`) require a
**Bearer token** in the `Authorization` header.

```
Authorization: Bearer <token>
```

Tokens are valid for **8 hours** (configurable via `JWT_EXPIRY_HOURS`).

---

## API Reference

### Auth  `/api/auth`

| Method | Endpoint                  | Description              |
|--------|---------------------------|--------------------------|
| POST   | `/login`                  | Login, receive JWT token |
| POST   | `/logout`                 | Logout (stateless)       |
| GET    | `/me`                     | Current user info        |
| POST   | `/change-password`        | Change admin password    |

**Login request:**
```json
POST /api/auth/login
{ "username": "admin", "password": "Kinevox123" }
```

**Login response:**
```json
{
  "success": true,
  "data": {
    "token": "eyJ...",
    "user": { "id": 1, "username": "admin", "role": "admin" }
  }
}
```

---

### Employees  `/api/employees`

| Method | Endpoint                                | Description                        |
|--------|-----------------------------------------|------------------------------------|
| GET    | `/`                                     | List all employees                 |
| POST   | `/`                                     | Create employee                    |
| GET    | `/<id>`                                 | Get single employee                |
| PUT    | `/<id>`                                 | Update employee                    |
| DELETE | `/<id>`                                 | Delete employee                    |
| GET    | `/<id>/attendance?month=YYYY-MM`        | Monthly attendance summary         |
| POST   | `/<id>/attendance`                      | Upsert monthly attendance summary  |
| GET    | `/<id>/attendance/log?month=YYYY-MM`    | Daily attendance log               |
| POST   | `/<id>/attendance/log`                  | Log a daily attendance entry       |
| GET    | `/<id>/schedule`                        | Get schedule                       |
| PUT    | `/<id>/schedule`                        | Update schedule                    |
| GET    | `/<id>/salary-history`                  | Past salary slip records           |

**Query params for GET `/`:** `search`, `status`, `dept`

**Create/Update employee body:**
```json
{
  "name": "Arjun Sharma",
  "role": "Senior Developer & Trainer",
  "dept": "Programming",
  "email": "arjun@kinevoxacademy.in",
  "phone": "9876543210",
  "doj": "2023-01-15",
  "salary": 45000,
  "bonus": 5000,
  "credits": 120,
  "schedule": "Mon-Fri 9AM-5PM",
  "status": "active",
  "courses": ["Web Development", "React Basics"]
}
```

**Daily attendance log body:**
```json
{
  "date": "2024-05-20",
  "status": "present",
  "note": "On time"
}
```
Status values: `present` | `absent` | `late` | `off`

---

### Students  `/api/students`

| Method | Endpoint                       | Description                     |
|--------|--------------------------------|---------------------------------|
| GET    | `/`                            | List students (with filters)    |
| POST   | `/`                            | Create student                  |
| GET    | `/completed`                   | Completed students only         |
| GET    | `/<id>`                        | Get single student              |
| PUT    | `/<id>`                        | Update student                  |
| DELETE | `/<id>`                        | Delete student                  |
| PUT    | `/<id>/progress`               | Update progress percentage      |
| POST   | `/<id>/complete`               | Mark as completed (100%)        |
| GET    | `/<id>/certificate`            | Get/issue certificate record    |

**Query params for GET `/`:**
`search`, `status`, `course`, `trainer_id`, `institution`,
`min_pct`, `max_pct`, `enroll_date`,
`sort_by` (`name` | `name_desc` | `doj` | `doj_desc` | `percentage` | `percentage_desc`)

**Create student body:**
```json
{
  "name": "Rahul Verma",
  "email": "rahul@gmail.com",
  "phone": "8765432109",
  "dob": "2005-06-12",
  "institution": "DPS School",
  "course": "Web Development",
  "assigned_to": "EMP001",
  "enroll_date": "2024-01-10",
  "progress": 0,
  "status": "active"
}
```

**Certificate response:**
```json
{
  "cert_no": "KVI-STU001-2026",
  "student_name": "Rahul Verma",
  "course": "Web Development",
  "issued_on": "2026-05-30"
}
```

---

### Courses  `/api/courses`

| Method | Endpoint                     | Description                  |
|--------|------------------------------|------------------------------|
| GET    | `/`                          | List courses                 |
| POST   | `/`                          | Create course                |
| GET    | `/<id>`                      | Get single course            |
| PUT    | `/<id>`                      | Update course                |
| DELETE | `/<id>`                      | Delete course                |
| PUT    | `/<id>/enrollment`           | Update enrollment count      |

**Query params for GET `/`:** `search`, `status`, `category`

**Create course body:**
```json
{
  "name": "Web Development",
  "category": "Programming",
  "duration": "3 months",
  "fee": 8000,
  "seats": 15,
  "assigned_to": "EMP001",
  "description": "HTML, CSS, JavaScript, React.",
  "status": "active"
}
```

**Enrollment update body:**
```json
{ "enrolled": 10 }
// OR use delta (relative):
{ "delta": 1 }
```

---

### Payroll  `/api/payroll`

| Method | Endpoint                   | Description                         |
|--------|----------------------------|-------------------------------------|
| GET    | `/summary`                 | All employees with payroll breakdown|
| GET    | `/<emp_id>/slip`           | Calculate salary slip (not saved)   |
| POST   | `/<emp_id>/slip`           | Generate & persist salary slip      |
| GET    | `/<emp_id>/id-card`        | ID card data for an employee        |
| GET    | `/slips`                   | All issued salary slips             |

**Query params for GET `/<emp_id>/slip`:** `month` (1-12), `year`

**Salary slip response includes:**
```json
{
  "emp_name": "Arjun Sharma",
  "month_label": "May 2026",
  "basic": 45000,
  "bonus": 5000,
  "gross": 50000,
  "pf": 5400,
  "tax": 2500,
  "net": 42100,
  "working_days": 22,
  "total_days": 25
}
```

**Payroll formula:**
- Gross = Basic + Bonus
- PF = Basic × 12%
- Tax = Gross × 5%
- Net = Gross − PF − Tax

---

### Reports  `/api/reports`

| Method | Endpoint          | Description                              |
|--------|-------------------|------------------------------------------|
| GET    | `/dashboard`      | Top-level KPIs + recent data             |
| GET    | `/revenue`        | Revenue per course                       |
| GET    | `/students`       | Student distributions & progress buckets |
| GET    | `/attendance`     | Attendance overview (all employees)      |
| GET    | `/courses`        | Course performance metrics               |
| GET    | `/employees`      | Employee stats by dept/status            |
| GET    | `/full`           | All reports combined in one call         |

---

### File Uploads  `/api/uploads`

| Method | Endpoint                              | Description               |
|--------|---------------------------------------|---------------------------|
| POST   | `/employee/<id>/photo`                | Upload employee photo     |
| DELETE | `/employee/<id>/photo`                | Remove employee photo     |
| POST   | `/student/<id>/photo`                 | Upload student photo      |
| DELETE | `/student/<id>/photo`                 | Remove student photo      |
| POST   | `/employee/<id>/document`             | Upload employee document  |

**Photo upload:** `multipart/form-data`, field name `file`

**Document upload:** `multipart/form-data`, field `file` + `doc_type` (`resume` | `sign` | `id_doc`)

Uploaded files are served at `/uploads/<path>`.

---

## Response Format

All endpoints return a consistent JSON envelope:

**Success:**
```json
{
  "success": true,
  "message": "...",
  "data": { ... }
}
```

**Error:**
```json
{
  "success": false,
  "error": "Human-readable error message"
}
```

HTTP status codes follow REST conventions:
`200 OK`, `201 Created`, `400 Bad Request`, `401 Unauthorized`, `404 Not Found`, `500 Server Error`

---

## Project Structure

```
kinevox-backend/
├── app.py                  # App factory & entry point
├── requirements.txt
├── .env.example
├── kinevox.db              # SQLite DB (auto-created on first run)
├── uploads/                # Uploaded files (auto-created)
│   ├── employees/
│   └── students/
├── db/
│   └── database.py         # Schema, seed data, get_db()
├── middleware/
│   └── auth.py             # JWT generation & require_auth decorator
├── routes/
│   ├── auth.py             # /api/auth/*
│   ├── employees.py        # /api/employees/*
│   ├── students.py         # /api/students/*
│   ├── courses.py          # /api/courses/*
│   ├── payroll.py          # /api/payroll/*
│   ├── reports.py          # /api/reports/*
│   └── uploads.py          # /api/uploads/*
└── utils/
    └── helpers.py          # Response builders, ID gen, payroll calc
```

---

## Connecting the Frontend

In the frontend HTML file, replace the in-memory arrays with `fetch()` calls
to this API. Example for loading employees:

```javascript
const BASE = 'http://localhost:5000/api';
const token = localStorage.getItem('kinevox_token');

async function loadEmployees() {
  const res = await fetch(`${BASE}/employees`, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  const { data } = await res.json();
  employees = data;   // replaces the in-memory array
  renderEmployees();
}
```

Login flow:
```javascript
async function doLogin() {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });
  const { data } = await res.json();
  if (data?.token) {
    localStorage.setItem('kinevox_token', data.token);
  }
}
```

---

## Environment Variables

| Variable           | Default                           | Description               |
|--------------------|-----------------------------------|---------------------------|
| `SECRET_KEY`       | `kinevox-super-secret-key-2024`   | JWT signing key           |
| `JWT_EXPIRY_HOURS` | `8`                               | Token validity in hours   |
| `PORT`             | `5000`                            | HTTP port                 |
| `DEBUG`            | `true`                            | Flask debug mode          |

---

## Production Notes

1. Change `SECRET_KEY` to a long random string (32+ chars).
2. Set `DEBUG=false`.
3. Use a WSGI server like **Gunicorn**: `gunicorn -w 4 app:app`
4. Put Nginx in front for HTTPS termination.
5. Back up `kinevox.db` regularly (it's a single file).
