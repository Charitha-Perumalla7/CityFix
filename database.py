import os
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cityfix.db")

# Exact 10 Citizen Categories mapped cleanly to 5 Municipal Departments
CATEGORY_DEPARTMENT_MAP = {
    "Roads & Potholes": "Roads & Infrastructure Dept",
    "Footpaths & Accessibility": "Roads & Infrastructure Dept",
    "Traffic & Road Safety": "Roads & Infrastructure Dept",
    "Waste Management": "Sanitation & Solid Waste Dept",
    "Public Toilets & Sanitation": "Sanitation & Solid Waste Dept",
    "Street Lighting": "Street Lighting & Electrical Dept",
    "Water Supply": "Water & Drainage Engineering Dept",
    "Drainage & Sewage": "Water & Drainage Engineering Dept",
    "Parks & Public Spaces": "Parks & Animal Welfare Dept",
    "Stray Animal Concerns": "Parks & Animal Welfare Dept",
}

VALID_CATEGORIES = list(CATEGORY_DEPARTMENT_MAP.keys())
VALID_DEPARTMENTS = sorted(list(set(CATEGORY_DEPARTMENT_MAP.values())))
VALID_STATUSES = ["Reported", "Assigned", "In Progress", "Resolved", "Reopened"]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('citizen', 'main_authority', 'dept_authority')),
        department TEXT,
        active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS complaints (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        department TEXT NOT NULL,
        location TEXT NOT NULL,
        description TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Reported',
        reporter_id INTEGER NOT NULL,
        reporter_name TEXT NOT NULL,
        is_anonymous INTEGER NOT NULL DEFAULT 0,
        before_photo TEXT NOT NULL,
        after_photo TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (reporter_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS complaint_timeline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        complaint_id TEXT NOT NULL,
        status TEXT NOT NULL,
        note TEXT NOT NULL,
        actor TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        complaint_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(user_id, complaint_id),
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY (complaint_id) REFERENCES complaints(id) ON DELETE CASCADE
    );
    """)

    existing_users = cur.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if existing_users == 0:
        now = datetime.now().strftime("%Y-%m-%d %I:%M %p")
        demo_users = [
            ("Ananya Sharma", "citizen@cityfix.gov", generate_password_hash("citizen123"), "citizen", None, 1, now),
            ("Rohan Verma", "rohan@cityfix.gov", generate_password_hash("citizen123"), "citizen", None, 1, now),
            ("Commissioner Arvind Rao", "admin@cityfix.gov", generate_password_hash("admin123"), "main_authority", None, 1, now),
            ("Priya Nair (Roads)", "roads@cityfix.gov", generate_password_hash("dept123"), "dept_authority", "Roads & Infrastructure Dept", 1, now),
            ("Vikram Das (Sanitation)", "sanitation@cityfix.gov", generate_password_hash("dept123"), "dept_authority", "Sanitation & Solid Waste Dept", 1, now),
            ("Meera Iyer (Lighting)", "lighting@cityfix.gov", generate_password_hash("dept123"), "dept_authority", "Street Lighting & Electrical Dept", 1, now),
            ("Karthik Shenoy (Water)", "water@cityfix.gov", generate_password_hash("dept123"), "dept_authority", "Water & Drainage Engineering Dept", 1, now),
            ("Sneha Kulkarni (Parks)", "parks@cityfix.gov", generate_password_hash("dept123"), "dept_authority", "Parks & Animal Welfare Dept", 1, now),
        ]
        cur.executemany(
            "INSERT INTO users (name, email, password_hash, role, department, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            demo_users
        )

        before_road = "https://images.unsplash.com/photo-1515162816999-a0c47dc192f7?auto=format&fit=crop&w=800&q=80"
        before_light = "https://images.unsplash.com/photo-1513836279014-a89f7a76ae86?auto=format&fit=crop&w=800&q=80"
        before_waste = "https://images.unsplash.com/photo-1532996122724-e3c354a0b15b?auto=format&fit=crop&w=800&q=80"
        after_waste = "https://images.unsplash.com/photo-1506744038136-46273834b3fb?auto=format&fit=crop&w=800&q=80"

        seed_complaints = [
            (
                "CF-1042",
                "Damaged Roadway & Drainage Grate on Oak Avenue",
                "Roads & Potholes",
                "Roads & Infrastructure Dept",
                "Sector 4, Oak Avenue",
                "Large crater pothole next to the storm grate causing two-wheeler skids and water pooling during evening traffic.",
                "In Progress",
                1,
                "Ananya Sharma",
                0,
                before_road,
                None,
                "2026-11-16 09:30 AM",
                "2026-11-18 02:15 PM",
            ),
            (
                "CF-1043",
                "Three Consecutive Streetlights Out Near Metro Footbridge",
                "Street Lighting",
                "Street Lighting & Electrical Dept",
                "Indiranagar 100ft Cross",
                "Pole numbers EL-14, EL-15, and EL-16 have been completely dark for 4 nights, creating safety hazards for pedestrians.",
                "Assigned",
                2,
                "Rohan Verma",
                1,
                before_light,
                None,
                "2026-11-17 07:45 PM",
                "2026-11-18 10:00 AM",
            ),
            (
                "CF-1044",
                "Overflowing Garbage Compactor Outside Market Gate",
                "Waste Management",
                "Sanitation & Solid Waste Dept",
                "Greenview Market North Gate",
                "Commercial wet waste spilled onto the footpath blocking pedestrian walkway and attracting stray cattle.",
                "Resolved",
                1,
                "Ananya Sharma",
                0,
                before_waste,
                after_waste,
                "2026-11-14 08:10 AM",
                "2026-11-16 04:40 PM",
            ),
        ]
        cur.executemany("""
            INSERT INTO complaints (
                id, title, category, department, location, description, status,
                reporter_id, reporter_name, is_anonymous, before_photo, after_photo,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, seed_complaints)

        timeline_rows = [
            ("CF-1042", "Reported", "Complaint logged via CityFix Citizen Portal.", "Ananya Sharma", "2026-11-16 09:30 AM"),
            ("CF-1042", "Assigned", "Auto-routed and verified by Main Authority.", "Commissioner Arvind Rao", "2026-11-16 11:15 AM"),
            ("CF-1042", "In Progress", "Asphalt patching crew & drainage team dispatched to Oak Avenue.", "Priya Nair (Roads)", "2026-11-18 02:15 PM"),
            ("CF-1043", "Reported", "Anonymous complaint logged with geo-tagged night photo.", "Anonymous Citizen", "2026-11-17 07:45 PM"),
            ("CF-1043", "Assigned", "Assigned to Electrical Maintenance Division.", "Commissioner Arvind Rao", "2026-11-18 10:00 AM"),
            ("CF-1044", "Reported", "Complaint logged by verified citizen.", "Ananya Sharma", "2026-11-14 08:10 AM"),
            ("CF-1044", "Assigned", "Routed to Sanitation & Solid Waste Dept.", "Commissioner Arvind Rao", "2026-11-14 09:00 AM"),
            ("CF-1044", "In Progress", "Compactor truck and sanitation crew deployed.", "Vikram Das (Sanitation)", "2026-11-15 01:20 PM"),
            ("CF-1044", "Resolved", "Waste cleared, area bleached, and After verification photo uploaded.", "Vikram Das (Sanitation)", "2026-11-16 04:40 PM"),
        ]
        cur.executemany(
            "INSERT INTO complaint_timeline (complaint_id, status, note, actor, timestamp) VALUES (?, ?, ?, ?, ?)",
            timeline_rows
        )

        cur.executemany(
            "INSERT INTO votes (user_id, complaint_id, created_at) VALUES (?, ?, ?)",
            [(1, "CF-1042", now), (2, "CF-1042", now), (1, "CF-1043", now)]
        )

    conn.commit()
    conn.close()