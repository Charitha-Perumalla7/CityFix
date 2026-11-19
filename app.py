import os
import uuid
from datetime import datetime
from functools import wraps
from flask import Flask, request, jsonify, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from database import (
    get_db,
    init_db,
    CATEGORY_DEPARTMENT_MAP,
    VALID_CATEGORIES,
    VALID_DEPARTMENTS,
    VALID_STATUSES,
)

app = Flask(__name__, static_folder=".", static_url_path="")
app.secret_key = os.environ.get("SECRET_KEY", "cityfix-municipal-secret-2026")


def current_user():
    uid = session.get("user_id")
    if not uid:
        return None
    conn = get_db()
    user = conn.execute(
        "SELECT id, name, email, role, department, active FROM users WHERE id = ?",
        (uid,),
    ).fetchone()
    conn.close()
    if not user or not user["active"]:
        session.clear()
        return None
    return dict(user)


def login_required(roles=None):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                return jsonify({"error": "Authentication required. Please sign in."}), 401
            if roles and user["role"] not in roles:
                return jsonify({"error": "Access denied for your account role."}), 403
            return fn(user, *args, **kwargs)
        return wrapper
    return decorator


def serialize_complaint(conn, row, user=None):
    c = dict(row)
    if c["is_anonymous"]:
        c["public_reporter"] = "Anonymous Citizen"
    else:
        c["public_reporter"] = c["reporter_name"]

    if c["is_anonymous"] and (not user or user["id"] != c["reporter_id"]):
        c["reporter_name"] = "Anonymous Citizen"

    vote_count = conn.execute(
        "SELECT COUNT(*) FROM votes WHERE complaint_id = ?", (c["id"],)
    ).fetchone()[0]
    c["votes"] = vote_count

    has_voted = False
    if user and user["role"] == "citizen":
        v = conn.execute(
            "SELECT 1 FROM votes WHERE user_id = ? AND complaint_id = ?",
            (user["id"], c["id"]),
        ).fetchone()
        has_voted = bool(v)
    c["has_voted"] = has_voted

    timeline = conn.execute(
        "SELECT status, note, actor, timestamp FROM complaint_timeline WHERE complaint_id = ? ORDER BY id ASC",
        (c["id"],),
    ).fetchall()
    c["timeline"] = [dict(t) for t in timeline]
    return c


@app.route("/")
def serve_index():
    return send_from_directory(".", "index.html")


@app.route("/api/meta", methods=["GET"])
def get_meta():
    return jsonify({
        "categories": VALID_CATEGORIES,
        "departments": VALID_DEPARTMENTS,
        "category_department_map": CATEGORY_DEPARTMENT_MAP,
        "statuses": VALID_STATUSES,
        "user": current_user(),
    })


# -------------------- AUTHENTICATION --------------------

@app.route("/api/auth/register", methods=["POST"])
def register_citizen():
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not name or not email or len(password) < 4:
        return jsonify({"error": "Name, valid email, and password (min 4 chars) are required."}), 400

    conn = get_db()
    exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if exists:
        conn.close()
        return jsonify({"error": "An account with this email already exists."}), 409

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    cur = conn.execute(
        "INSERT INTO users (name, email, password_hash, role, department, active, created_at) VALUES (?, ?, ?, 'citizen', NULL, 1, ?)",
        (name, email, generate_password_hash(password), now),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()

    session["user_id"] = user_id
    return jsonify({"user": current_user()}), 201


@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True)
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    portal = data.get("portal") or "citizen"

    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if not row or not check_password_hash(row["password_hash"], password):
        return jsonify({"error": "Invalid email or password."}), 401

    if not row["active"]:
        return jsonify({"error": "This account has been deactivated by the Main Authority."}), 403

    if portal == "citizen" and row["role"] != "citizen":
        return jsonify({"error": "Authority accounts must sign in through the Official Authority Portal."}), 403
    if portal == "authority" and row["role"] not in ("main_authority", "dept_authority"):
        return jsonify({"error": "Citizen accounts cannot access the Official Authority Portal."}), 403

    session["user_id"] = row["id"]
    return jsonify({"user": current_user()})


@app.route("/api/auth/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


# -------------------- COMPLAINTS & DUPLICATE CHECK --------------------

@app.route("/api/complaints", methods=["GET"])
def list_complaints():
    user = current_user()
    scope = request.args.get("scope", "public")
    conn = get_db()

    if scope == "authority":
        if not user or user["role"] not in ("main_authority", "dept_authority"):
            conn.close()
            return jsonify({"error": "Authority login required."}), 403
        if user["role"] == "dept_authority":
            rows = conn.execute(
                "SELECT * FROM complaints WHERE department = ? ORDER BY rowid DESC",
                (user["department"],),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM complaints ORDER BY rowid DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM complaints ORDER BY rowid DESC").fetchall()

    items = [serialize_complaint(conn, r, user) for r in rows]
    conn.close()
    return jsonify({"complaints": items})


@app.route("/api/complaints/duplicates", methods=["GET"])
def check_duplicates():
    category = (request.args.get("category") or "").strip()
    location = (request.args.get("location") or "").strip().lower()
    title = (request.args.get("title") or "").strip().lower()

    if not category:
        return jsonify({"duplicates": []})

    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM complaints WHERE category = ? AND status != 'Resolved' ORDER BY rowid DESC",
        (category,),
    ).fetchall()

    matches = []
    for r in rows:
        loc_match = location and (location in r["location"].lower() or r["location"].lower() in location)
        title_words = [w for w in title.split() if len(w) > 3]
        word_match = any(w in r["title"].lower() or w in r["location"].lower() for w in title_words)
        if loc_match or word_match or (not location and not title):
            matches.append(serialize_complaint(conn, r, current_user()))

    conn.close()
    return jsonify({"duplicates": matches[:3]})


@app.route("/api/complaints", methods=["POST"])
@login_required(roles=["citizen"])
def create_complaint(user):
    data = request.get_json(force=True)
    title = (data.get("title") or "").strip()
    category = (data.get("category") or "").strip()
    location = (data.get("location") or "").strip()
    description = (data.get("description") or "").strip()
    is_anonymous = 1 if data.get("is_anonymous") else 0
    before_photo = (data.get("before_photo") or "").strip()

    if not title or category not in CATEGORY_DEPARTMENT_MAP or not location or not description:
        return jsonify({"error": "Title, valid category, location, and description are required."}), 400

    if not before_photo:
        return jsonify({"error": "A 'Before' evidence photo is required to submit a civic complaint."}), 400

    department = CATEGORY_DEPARTMENT_MAP[category]
    cid = f"CF-{uuid.uuid4().hex[:4].upper()}"
    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    public_actor = "Anonymous Citizen" if is_anonymous else user["name"]

    conn = get_db()
    conn.execute("""
        INSERT INTO complaints (
            id, title, category, department, location, description, status,
            reporter_id, reporter_name, is_anonymous, before_photo, after_photo,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'Reported', ?, ?, ?, ?, NULL, ?, ?)
    """, (
        cid, title, category, department, location, description,
        user["id"], user["name"], is_anonymous, before_photo, now, now
    ))

    conn.execute(
        "INSERT INTO complaint_timeline (complaint_id, status, note, actor, timestamp) VALUES (?, 'Reported', ?, ?, ?)",
        (cid, f"Complaint submitted and auto-routed to {department}.", public_actor, now),
    )
    conn.commit()

    row = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    complaint = serialize_complaint(conn, row, user)
    conn.close()
    return jsonify({"complaint": complaint}), 201


@app.route("/api/complaints/<cid>/vote", methods=["POST"])
@login_required(roles=["citizen"])
def toggle_vote(user, cid):
    conn = get_db()
    comp = conn.execute("SELECT id FROM complaints WHERE id = ?", (cid,)).fetchone()
    if not comp:
        conn.close()
        return jsonify({"error": "Complaint not found."}), 404

    existing = conn.execute(
        "SELECT id FROM votes WHERE user_id = ? AND complaint_id = ?",
        (user["id"], cid),
    ).fetchone()

    if existing:
        conn.execute("DELETE FROM votes WHERE id = ?", (existing["id"],))
    else:
        now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        conn.execute(
            "INSERT INTO votes (user_id, complaint_id, created_at) VALUES (?, ?, ?)",
            (user["id"], cid, now),
        )
    conn.commit()

    row = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    complaint = serialize_complaint(conn, row, user)
    conn.close()
    return jsonify({"complaint": complaint})


@app.route("/api/complaints/<cid>/reopen", methods=["POST"])
@login_required(roles=["citizen"])
def reopen_complaint(user, cid):
    data = request.get_json(force=True)
    reason = (data.get("reason") or "").strip()
    if len(reason) < 5:
        return jsonify({"error": "Please provide a clear reason (at least 5 characters) to reopen this complaint."}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Complaint not found."}), 404

    if row["reporter_id"] != user["id"]:
        conn.close()
        return jsonify({"error": "Only the original citizen who reported this issue can reopen it."}), 403

    if row["status"] != "Resolved":
        conn.close()
        return jsonify({"error": "Only Resolved complaints can be reopened."}), 400

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    actor = "Anonymous Citizen" if row["is_anonymous"] else user["name"]

    conn.execute(
        "UPDATE complaints SET status = 'Reopened', after_photo = NULL, updated_at = ? WHERE id = ?",
        (now, cid),
    )
    conn.execute(
        "INSERT INTO complaint_timeline (complaint_id, status, note, actor, timestamp) VALUES (?, 'Reopened', ?, ?, ?)",
        (cid, f"Reopened by citizen: {reason}", actor, now),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    complaint = serialize_complaint(conn, updated, user)
    conn.close()
    return jsonify({"complaint": complaint})


# -------------------- AUTHORITY ACTIONS --------------------

@app.route("/api/complaints/<cid>/assign", methods=["POST"])
@login_required(roles=["main_authority"])
def assign_department(user, cid):
    data = request.get_json(force=True)
    department = (data.get("department") or "").strip()
    note = (data.get("note") or "").strip()

    if department not in VALID_DEPARTMENTS:
        return jsonify({"error": "Invalid municipal department selected."}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Complaint not found."}), 404

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    new_status = "Assigned" if row["status"] in ("Reported", "Reopened") else row["status"]
    audit_note = note or f"Assigned to {department} by Main Authority."

    conn.execute(
        "UPDATE complaints SET department = ?, status = ?, updated_at = ? WHERE id = ?",
        (department, new_status, now, cid),
    )
    conn.execute(
        "INSERT INTO complaint_timeline (complaint_id, status, note, actor, timestamp) VALUES (?, ?, ?, ?, ?)",
        (cid, new_status, audit_note, user["name"], now),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    complaint = serialize_complaint(conn, updated, user)
    conn.close()
    return jsonify({"complaint": complaint})


@app.route("/api/complaints/<cid>/status", methods=["POST"])
@login_required(roles=["main_authority", "dept_authority"])
def update_status(user, cid):
    data = request.get_json(force=True)
    new_status = (data.get("status") or "").strip()
    note = (data.get("note") or "").strip()
    after_photo = (data.get("after_photo") or "").strip()

    if new_status not in VALID_STATUSES:
        return jsonify({"error": "Invalid complaint status."}), 400

    conn = get_db()
    row = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Complaint not found."}), 404

    if user["role"] == "dept_authority" and row["department"] != user["department"]:
        conn.close()
        return jsonify({"error": "Access denied: This ticket belongs to another department."}), 403

    if new_status == "Resolved" and not after_photo and not row["after_photo"]:
        conn.close()
        return jsonify({"error": "Mandatory 'After' resolution photo proof is required before marking Resolved."}), 400

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    final_after = after_photo if new_status == "Resolved" else (None if new_status == "Reopened" else row["after_photo"])
    audit_note = note or f"Status updated to {new_status}."

    conn.execute(
        "UPDATE complaints SET status = ?, after_photo = ?, updated_at = ? WHERE id = ?",
        (new_status, final_after, now, cid),
    )
    conn.execute(
        "INSERT INTO complaint_timeline (complaint_id, status, note, actor, timestamp) VALUES (?, ?, ?, ?, ?)",
        (cid, new_status, audit_note, user["name"], now),
    )
    conn.commit()

    updated = conn.execute("SELECT * FROM complaints WHERE id = ?", (cid,)).fetchone()
    complaint = serialize_complaint(conn, updated, user)
    conn.close()
    return jsonify({"complaint": complaint})


# -------------------- MAIN AUTHORITY ACCOUNT MANAGEMENT --------------------

@app.route("/api/authority/accounts", methods=["GET"])
@login_required(roles=["main_authority"])
def list_dept_accounts(user):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, email, role, department, active, created_at FROM users WHERE role = 'dept_authority' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return jsonify({"accounts": [dict(r) for r in rows]})


@app.route("/api/authority/accounts", methods=["POST"])
@login_required(roles=["main_authority"])
def create_dept_account(user):
    data = request.get_json(force=True)
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    department = (data.get("department") or "").strip()

    if not name or not email or len(password) < 4 or department not in VALID_DEPARTMENTS:
        return jsonify({"error": "Officer name, email, password (min 4 chars), and valid department are required."}), 400

    conn = get_db()
    exists = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if exists:
        conn.close()
        return jsonify({"error": "An account with this email already exists."}), 409

    now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
    conn.execute(
        "INSERT INTO users (name, email, password_hash, role, department, active, created_at) VALUES (?, ?, ?, 'dept_authority', ?, 1, ?)",
        (name, email, generate_password_hash(password), department, now),
    )
    conn.commit()
    conn.close()
    return jsonify({"ok": True}), 201


@app.route("/api/authority/accounts/<int:acc_id>/toggle", methods=["POST"])
@login_required(roles=["main_authority"])
def toggle_dept_account(user, acc_id):
    conn = get_db()
    row = conn.execute("SELECT id, active FROM users WHERE id = ? AND role = 'dept_authority'", (acc_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Department authority account not found."}), 404

    new_state = 0 if row["active"] else 1
    conn.execute("UPDATE users SET active = ? WHERE id = ?", (new_state, acc_id))
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "active": new_state})


@app.route("/api/authority/accounts/<int:acc_id>", methods=["DELETE"])
@login_required(roles=["main_authority"])
def delete_dept_account(user, acc_id):
    conn = get_db()
    conn.execute("DELETE FROM users WHERE id = ? AND role = 'dept_authority'", (acc_id,))
    conn.commit()
    conn.close()
    return jsonify({"ok": True})


if __name__ == "__main__":
    init_db()
    app.run(debug=True, port=5000)