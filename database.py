
import sqlite3
from pathlib import Path
from math import radians, sin, cos, asin, sqrt

DB_PATH = Path(__file__).with_name("cityfix.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    db = get_db()
    try:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'citizen'
        );

        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            ward TEXT NOT NULL,
            location TEXT NOT NULL,
            latitude REAL,
            longitude REAL,
            status TEXT NOT NULL DEFAULT 'Reported',
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(created_by) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            issue_id INTEGER NOT NULL,
            UNIQUE(user_id, issue_id),
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(issue_id) REFERENCES issues(id)
        );
        """)
        db.commit()
    finally:
        db.close()


def create_user(name, email, password, role="citizen"):
    db = get_db()
    try:
        cursor = db.execute(
            """INSERT INTO users (name, email, password, role)
               VALUES (?, ?, ?, ?)""",
            (name, email, password, role)
        )
        db.commit()
        return cursor.lastrowid
    finally:
        db.close()


def find_user(email):
    db = get_db()
    try:
        return db.execute(
            "SELECT * FROM users WHERE email = ?", (email,)
        ).fetchone()
    finally:
        db.close()


def create_issue(title, category, description, ward, location,
                 latitude, longitude, user_id):
    db = get_db()
    try:
        cursor = db.execute("""
            INSERT INTO issues
            (title, category, description, ward, location,
             latitude, longitude, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (title, category, description, ward, location,
              latitude, longitude, user_id))
        db.commit()
        return cursor.lastrowid
    finally:
        db.close()


def get_issues():
    db = get_db()
    try:
        return db.execute("""
            SELECT issues.*,
            users.name AS reporter,
            (SELECT COUNT(*) FROM votes
             WHERE votes.issue_id = issues.id) AS upvotes
            FROM issues
            LEFT JOIN users ON issues.created_by = users.id
            ORDER BY issues.created_at DESC
        """).fetchall()
    finally:
        db.close()


def get_issue(issue_id):
    db = get_db()
    try:
        return db.execute("""
            SELECT issues.*,
            users.name AS reporter,
            (SELECT COUNT(*) FROM votes
             WHERE votes.issue_id = issues.id) AS upvotes
            FROM issues
            LEFT JOIN users ON issues.created_by = users.id
            WHERE issues.id = ?
        """, (issue_id,)).fetchone()
    finally:
        db.close()


def add_vote(user_id, issue_id):
    db = get_db()
    try:
        cursor = db.execute("""
            INSERT OR IGNORE INTO votes (user_id, issue_id)
            VALUES (?, ?)
        """, (user_id, issue_id))
        db.commit()
        return cursor.rowcount == 1
    finally:
        db.close()


def find_duplicate(category, ward, location,
                   latitude=None, longitude=None):
    db = get_db()
    try:
        candidates = db.execute("""
            SELECT * FROM issues
            WHERE LOWER(category) = LOWER(?)
            AND LOWER(ward) = LOWER(?)
            AND status != 'Resolved'
        """, (category, ward)).fetchall()
    finally:
        db.close()

    for issue in candidates:
        if (latitude is not None and longitude is not None
                and issue["latitude"] is not None
                and issue["longitude"] is not None):

            lat1, lon1 = radians(latitude), radians(longitude)
            lat2 = radians(issue["latitude"])
            lon2 = radians(issue["longitude"])

            dlat = lat2 - lat1
            dlon = lon2 - lon1

            a = (sin(dlat / 2)**2
                 + cos(lat1) * cos(lat2) * sin(dlon / 2)**2)

            distance = 6371000 * 2 * asin(sqrt(a))

            if distance <= 100:
                return issue

        elif issue["location"].strip().casefold() == location.strip().casefold():
            return issue

    return None


def update_status(issue_id, new_status):
    transitions = {
        "Reported": ["In Progress"],
        "In Progress": ["Resolved"],
        "Resolved": []
    }

    db = get_db()
    try:
        issue = db.execute(
            "SELECT status FROM issues WHERE id = ?", (issue_id,)
        ).fetchone()

        if not issue:
            return False

        if new_status not in transitions.get(issue["status"], []):
            return False

        db.execute(
            "UPDATE issues SET status = ? WHERE id = ?",
            (new_status, issue_id)
        )
        db.commit()
        return True
    finally:
        db.close()


def get_statistics():
    db = get_db()
    try:
        total = db.execute(
            "SELECT COUNT(*) FROM issues"
        ).fetchone()[0]

        reported = db.execute(
            "SELECT COUNT(*) FROM issues WHERE status='Reported'"
        ).fetchone()[0]

        progress = db.execute(
            "SELECT COUNT(*) FROM issues WHERE status='In Progress'"
        ).fetchone()[0]

        resolved = db.execute(
            "SELECT COUNT(*) FROM issues WHERE status='Resolved'"
        ).fetchone()[0]

        wards = db.execute("""
            SELECT ward, COUNT(*) AS count
            FROM issues GROUP BY ward
        """).fetchall()

        categories = db.execute("""
            SELECT category, COUNT(*) AS count
            FROM issues GROUP BY category
        """).fetchall()

        return {
            "total": total,
            "reported": reported,
            "progress": progress,
            "resolved": resolved,
            "wards": wards,
            "categories": categories
        }
    finally:
        db.close()


# Update an existing user's password
def update_password(email, new_password):
    db = get_db()
    try:
        cursor = db.execute(
            "UPDATE users SET password = ? WHERE email = ?",
            (new_password, email)
        )
        db.commit()
        return cursor.rowcount == 1
    finally:
        db.close()
