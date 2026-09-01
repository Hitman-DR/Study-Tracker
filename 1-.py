"""
Liquid Glass Study Tracker & Planner
====================================
A modern, accessible, glassmorphism-styled hierarchical study tracker
built with Streamlit, Plotly, and SQLite persistence.

Architecture:
- Multi-User Auth: Predefined credentials in `AUTHORIZED_USERS`
- Hierarchical: User -> Subject -> Chapter Sub-plan -> Tasks / Checklists
- Storage: Local SQLite database (`study_tracker.db`) with user data isolation
- Theme: Liquid glass (backdrop-filter blur, frosted glass gradients, CSS tokens)
"""

import os
import streamlit as st
import sqlite3
import json
import time
from datetime import datetime, date
import plotly.graph_objects as go
import pandas as pd

AUTHORIZED_USERS = {
    "Deepak": "hitman_dr",
    "Ruba": "donruba_67",
    "User_3": "focus_now",
    "User_4": "pass1234",
}

import shutil

# -----------------------------------------------------------------------------
# 1. DATABASE LAYER (Persistent Multi-User Storage & Cloud Sync Engine)
# -----------------------------------------------------------------------------
def get_db_path():
    """Guarantees a permanent, resilient storage location across working directories and reboots."""
    # 1. Explicit environment variable override
    custom_path = os.environ.get("STUDY_TRACKER_DB_PATH")
    if custom_path:
        os.makedirs(os.path.dirname(os.path.abspath(custom_path)), exist_ok=True)
        return os.path.abspath(custom_path)
    
    # 2. Permanent user home directory: ~/.study_tracker/study_tracker.db
    user_home = os.path.expanduser("~")
    permanent_dir = os.path.join(user_home, ".study_tracker")
    os.makedirs(permanent_dir, exist_ok=True)
    permanent_db = os.path.join(permanent_dir, "study_tracker.db")
    
    # 3. Automatic migration from local script directory if found
    script_dir = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
    local_db = os.path.join(script_dir, "study_tracker.db")
    
    if os.path.exists(local_db) and os.path.abspath(local_db) != os.path.abspath(permanent_db):
        if not os.path.exists(permanent_db) or os.path.getsize(permanent_db) == 0:
            try:
                shutil.copy2(local_db, permanent_db)
            except Exception:
                pass
                
    return permanent_db

DB_PATH = get_db_path()

def get_db_connection():
    """Establishes an SQLite connection with PRAGMA foreign keys and WAL journal mode."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

def export_full_database_json():
    """Exports all tables, plans, tasks, user stats, and logs to a structured JSON dictionary."""
    conn = get_db_connection()
    export_payload = {
        "app": "StudyTracker Pro",
        "version": "2.0",
        "exported_at": datetime.now().isoformat(),
        "subjects": [dict(r) for r in conn.execute("SELECT * FROM subjects").fetchall()],
        "chapters": [dict(r) for r in conn.execute("SELECT * FROM chapters").fetchall()],
        "tasks": [dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()],
        "study_logs": [dict(r) for r in conn.execute("SELECT * FROM study_logs").fetchall()],
        "user_stats": [dict(r) for r in conn.execute("SELECT * FROM user_stats").fetchall()],
    }
    conn.close()
    return export_payload

def auto_save_backup():
    """Automatically writes a redundant JSON backup snapshot to disk upon any mutation."""
    try:
        data = export_full_database_json()
        backup_dir = os.path.dirname(DB_PATH)
        backup_file = os.path.join(backup_dir, "study_tracker_backup.json")
        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def import_full_database_json(json_data):
    """Safely restores/merges database from exported JSON payload without data corruption."""
    if isinstance(json_data, str):
        json_data = json.loads(json_data)
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Restore User Stats
    for stat in json_data.get("user_stats", []):
        cursor.execute("""
            INSERT INTO user_stats (username, streak_count, last_study_date)
            VALUES (?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                streak_count = excluded.streak_count,
                last_study_date = excluded.last_study_date
        """, (stat["username"], stat.get("streak_count", 0), stat.get("last_study_date")))

    # 2. Restore Subjects
    subject_id_map = {}
    for sub in json_data.get("subjects", []):
        old_id = sub["id"]
        existing = cursor.execute("SELECT id FROM subjects WHERE username = ? AND name = ?", (sub.get("username", "default"), sub["name"])).fetchone()
        if existing:
            subject_id_map[old_id] = existing["id"]
            cursor.execute("UPDATE subjects SET description = ?, color = ? WHERE id = ?", (sub.get("description"), sub.get("color", "#4F46E5"), existing["id"]))
        else:
            cursor.execute("INSERT INTO subjects (username, name, description, color, created_at) VALUES (?, ?, ?, ?, ?)",
                           (sub.get("username", "default"), sub["name"], sub.get("description"), sub.get("color", "#4F46E5"), sub.get("created_at", datetime.now().isoformat())))
            subject_id_map[old_id] = cursor.lastrowid

    # 3. Restore Chapters
    chapter_id_map = {}
    for chap in json_data.get("chapters", []):
        old_c_id = chap["id"]
        new_sub_id = subject_id_map.get(chap["subject_id"], chap["subject_id"])
        existing_c = cursor.execute("SELECT id FROM chapters WHERE subject_id = ? AND name = ?", (new_sub_id, chap["name"])).fetchone()
        if existing_c:
            chapter_id_map[old_c_id] = existing_c["id"]
            cursor.execute("UPDATE chapters SET description = ?, completed = ? WHERE id = ?", (chap.get("description"), chap.get("completed", 0), existing_c["id"]))
        else:
            cursor.execute("INSERT INTO chapters (subject_id, name, description, completed) VALUES (?, ?, ?, ?)",
                           (new_sub_id, chap["name"], chap.get("description"), chap.get("completed", 0)))
            chapter_id_map[old_c_id] = cursor.lastrowid

    # 4. Restore Tasks
    for t in json_data.get("tasks", []):
        new_c_id = chapter_id_map.get(t["chapter_id"], t["chapter_id"])
        existing_t = cursor.execute("SELECT id FROM tasks WHERE chapter_id = ? AND title = ?", (new_c_id, t["title"])).fetchone()
        if existing_t:
            cursor.execute("UPDATE tasks SET status = ?, priority = ?, due_date = ?, completed = ? WHERE id = ?",
                           (t.get("status", "not started"), t.get("priority", "Medium"), t.get("due_date"), t.get("completed", 0), existing_t["id"]))
        else:
            cursor.execute("INSERT INTO tasks (chapter_id, title, status, priority, due_date, completed) VALUES (?, ?, ?, ?, ?, ?)",
                           (new_c_id, t["title"], t.get("status", "not started"), t.get("priority", "Medium"), t.get("due_date"), t.get("completed", 0)))

    # 5. Restore Study Logs
    for log in json_data.get("study_logs", []):
        new_sub_id = subject_id_map.get(log.get("subject_id"), log.get("subject_id"))
        dup = cursor.execute("SELECT id FROM study_logs WHERE username = ? AND duration_minutes = ? AND log_date = ? AND timestamp = ?",
                             (log.get("username", "default"), log["duration_minutes"], log["log_date"], log.get("timestamp"))).fetchone()
        if not dup:
            cursor.execute("INSERT INTO study_logs (username, subject_id, task_id, duration_minutes, log_date, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                           (log.get("username", "default"), new_sub_id, log.get("task_id"), log["duration_minutes"], log["log_date"], log.get("timestamp", datetime.now().isoformat())))

    conn.commit()
    conn.close()
    auto_save_backup()

def init_db():
    """Initializes the database schema and performs automated schema migrations."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Subjects (scoped by username)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subjects (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT DEFAULT 'default',
        name TEXT NOT NULL,
        description TEXT,
        color TEXT DEFAULT '#4F46E5',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # Chapters (Sub-plans)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chapters (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        description TEXT,
        completed INTEGER DEFAULT 0,
        FOREIGN KEY (subject_id) REFERENCES subjects (id) ON DELETE CASCADE
    )
    """)
    
    # Tasks (Checklist Items)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chapter_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'not started',
        priority TEXT DEFAULT 'Medium',
        due_date DATE,
        completed INTEGER DEFAULT 0,
        FOREIGN KEY (chapter_id) REFERENCES chapters (id) ON DELETE CASCADE
    )
    """)
    
    # Study Logs (scoped by username)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS study_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT DEFAULT 'default',
        subject_id INTEGER,
        task_id INTEGER,
        duration_minutes INTEGER NOT NULL,
        log_date DATE NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE SET NULL,
        FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
    )
    """)
    
    # User Profile / Stats (keyed by username)
    # Check for legacy user_stats schema migration
    cursor.execute("PRAGMA table_info(user_stats)")
    stat_cols = [row["name"] for row in cursor.fetchall()]
    if stat_cols and "username" not in stat_cols:
        cursor.execute("DROP TABLE user_stats")
        
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_stats (
        username TEXT PRIMARY KEY,
        streak_count INTEGER DEFAULT 0,
        last_study_date DATE
    )
    """)
    
    # Check for migrations if subjects/study_logs existed prior
    cursor.execute("PRAGMA table_info(subjects)")
    sub_cols = [row["name"] for row in cursor.fetchall()]
    if "username" not in sub_cols:
        cursor.execute("ALTER TABLE subjects ADD COLUMN username TEXT DEFAULT 'default'")
        
    cursor.execute("PRAGMA table_info(study_logs)")
    log_cols = [row["name"] for row in cursor.fetchall()]
    if "username" not in log_cols:
        cursor.execute("ALTER TABLE study_logs ADD COLUMN username TEXT DEFAULT 'default'")
    
    # Ensure all authorized users exist in user_stats
    for u in AUTHORIZED_USERS.keys():
        cursor.execute("INSERT OR IGNORE INTO user_stats (username, streak_count) VALUES (?, 0)", (u,))
    
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# 2. STATE MANAGEMENT & SESSION CONTROLLER
# -----------------------------------------------------------------------------
def init_session_state():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "username" not in st.session_state:
        st.session_state.username = None
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "dark"
    if "high_contrast" not in st.session_state:
        st.session_state.high_contrast = False
    if "timer_running" not in st.session_state:
        st.session_state.timer_running = False
    if "timer_seconds" not in st.session_state:
        st.session_state.timer_seconds = 25 * 60
    if "timer_total_duration" not in st.session_state:
        st.session_state.timer_total_duration = 25 * 60
    if "timer_end_time" not in st.session_state:
        st.session_state.timer_end_time = None
    if "timer_mode" not in st.session_state:
        st.session_state.timer_mode = "Focus"
    if "timer_preset" not in st.session_state:
        st.session_state.timer_preset = 25
    if "history" not in st.session_state:
        st.session_state.history = []  # For undo action logging

init_session_state()

# -----------------------------------------------------------------------------
# 3. LIQUID GLASS CSS & ACCESSIBILITY INJECTION
# -----------------------------------------------------------------------------
def inject_custom_css():
    is_dark = st.session_state.theme_mode == "dark"
    is_contrast = st.session_state.high_contrast

    # Theme CSS Variables
    if is_contrast:
        bg_gradient = "linear-gradient(135deg, #000000 0%, #121212 100%)"
        card_bg = "rgba(20, 20, 20, 0.95)"
        card_border = "2px solid #FFFFFF"
        text_primary = "#FFFFFF"
        text_secondary = "#E2E8F0"
        accent_glow = "rgba(255, 255, 255, 0.2)"
    elif is_dark:
        bg_gradient = "radial-gradient(ellipse at 20% 20%, #1e1b4b 0%, #0f172a 50%, #020617 100%)"
        card_bg = "rgba(30, 41, 59, 0.55)"
        card_border = "1px solid rgba(255, 255, 255, 0.12)"
        text_primary = "#F8FAFC"
        text_secondary = "#94A3B8"
        accent_glow = "0 8px 32px 0 rgba(0, 0, 0, 0.37)"
    else:  # Light Mode
        bg_gradient = "radial-gradient(ellipse at 20% 20%, #e0e7ff 0%, #f8fafc 50%, #e2e8f0 100%)"
        card_bg = "rgba(255, 255, 255, 0.65)"
        card_border = "1px solid rgba(255, 255, 255, 0.6)"
        text_primary = "#0F172A"
        text_secondary = "#475569"
        accent_glow = "0 8px 32px 0 rgba(31, 38, 135, 0.1)"

    glass_css = f"""
    <style>
    /* App Canvas styling */
    .stApp {{
        background: {bg_gradient};
        background-attachment: fixed;
        color: {text_primary};
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    }}

    /* Liquid Glass Containers */
    .glass-card {{
        background: {card_bg};
        backdrop-filter: blur(14px);
        -webkit-backdrop-filter: blur(14px);
        border: {card_border};
        border-radius: 16px;
        padding: 1.25rem;
        box-shadow: {accent_glow};
        margin-bottom: 1rem;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .glass-card:hover {{
        transform: translateY(-2px);
    }}

    /* Metrics & Badges */
    .metric-title {{
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        color: {text_secondary};
        font-weight: 600;
        margin-bottom: 4px;
    }}
    .metric-value {{
        font-size: 1.8rem;
        font-weight: 700;
        color: {text_primary};
    }}

    /* Badges */
    .badge-pill {{
        display: inline-block;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.75rem;
        font-weight: 600;
        backdrop-filter: blur(6px);
        margin-right: 6px;
    }}
    .priority-High {{ background: rgba(239, 68, 68, 0.25); color: #FCA5A5; border: 1px solid rgba(239, 68, 68, 0.4); }}
    .priority-Medium {{ background: rgba(245, 158, 11, 0.25); color: #FCD34D; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .priority-Low {{ background: rgba(16, 185, 129, 0.25); color: #6EE7B7; border: 1px solid rgba(16, 185, 129, 0.4); }}

    /* Status indicators */
    .status-completed {{ color: #10B981; font-weight: 600; }}
    .status-in-progress {{ color: #3B82F6; font-weight: 600; }}
    .status-not-started {{ color: {text_secondary}; font-weight: 500; }}

    /* Achievement Tier Borders & Glows */
    .tier-Bronze {{ border: 1.5px solid #CD7F32 !important; box-shadow: 0 0 12px rgba(205, 127, 50, 0.25) !important; }}
    .tier-Silver {{ border: 1.5px solid #94A3B8 !important; box-shadow: 0 0 12px rgba(148, 163, 184, 0.25) !important; }}
    .tier-Gold {{ border: 1.5px solid #F59E0B !important; box-shadow: 0 0 15px rgba(245, 158, 11, 0.35) !important; }}
    .tier-Platinum {{ border: 1.5px solid #06B6D4 !important; box-shadow: 0 0 18px rgba(6, 182, 212, 0.4) !important; }}
    .tier-Legendary {{ border: 1.5px solid #EC4899 !important; box-shadow: 0 0 22px rgba(236, 72, 153, 0.5) !important; }}

    /* Active Timer Card Glow */
    .timer-active-card {{
        border: 2px solid #6366F1 !important;
        box-shadow: 0 0 35px rgba(99, 102, 241, 0.45) !important;
    }}

    /* Accessible Focus outlines */
    button:focus, input:focus, select:focus {{
        outline: 2px solid #6366F1 !important;
        outline-offset: 2px !important;
    }}

    /* Streamlit widget container adjustments */
    div[data-testid="stExpander"] {{
        background: {card_bg};
        border-radius: 12px;
        border: {card_border};
        backdrop-filter: blur(10px);
    }}
    </style>
    """
    st.markdown(glass_css, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 4. BUSINESS LOGIC & DATA ACCESS HELPERS (Multi-User Scoped)
# -----------------------------------------------------------------------------
def get_subjects(username=None):
    if not username:
        username = st.session_state.get("username", "default")
    conn = get_db_connection()
    subs = conn.execute("SELECT * FROM subjects WHERE username = ? ORDER BY name ASC", (username,)).fetchall()
    conn.close()
    return [dict(s) for s in subs]

def get_chapters(subject_id):
    conn = get_db_connection()
    chaps = conn.execute("SELECT * FROM chapters WHERE subject_id = ? ORDER BY id ASC", (subject_id,)).fetchall()
    conn.close()
    return [dict(c) for c in chaps]

def get_tasks(chapter_id):
    conn = get_db_connection()
    tasks = conn.execute("SELECT * FROM tasks WHERE chapter_id = ? ORDER BY id ASC", (chapter_id,)).fetchall()
    conn.close()
    return [dict(t) for t in tasks]

def calculate_chapter_progress(chapter_id):
    tasks = get_tasks(chapter_id)
    if not tasks:
        # Check if chapter itself is marked completed
        conn = get_db_connection()
        chap = conn.execute("SELECT completed FROM chapters WHERE id = ?", (chapter_id,)).fetchone()
        conn.close()
        return 100.0 if (chap and chap["completed"] == 1) else 0.0
    completed = sum(1 for t in tasks if t["completed"] == 1)
    return round((completed / len(tasks)) * 100, 1)

def calculate_subject_progress(subject_id):
    chapters = get_chapters(subject_id)
    if not chapters:
        return 0.0
    percentages = [calculate_chapter_progress(c["id"]) for c in chapters]
    return round(sum(percentages) / len(percentages), 1)

def log_study_time(subject_id, task_id, duration_minutes, username=None):
    if not username:
        username = st.session_state.get("username", "default")
    conn = get_db_connection()
    today = date.today().isoformat()
    conn.execute(
        "INSERT INTO study_logs (username, subject_id, task_id, duration_minutes, log_date) VALUES (?, ?, ?, ?, ?)",
        (username, subject_id, task_id, duration_minutes, today)
    )
    
    # Update Streak for this specific user
    stats = conn.execute("SELECT * FROM user_stats WHERE username = ?", (username,)).fetchone()
    if not stats:
        conn.execute("INSERT INTO user_stats (username, streak_count, last_study_date) VALUES (?, 1, ?)", (username, today))
    else:
        last_date = stats["last_study_date"]
        streak = stats["streak_count"] or 0
        if last_date != today:
            if last_date:
                last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
                delta = (date.today() - last_dt).days
                if delta == 1:
                    streak += 1
                elif delta > 1:
                    streak = 1
            else:
                streak = 1
            conn.execute("UPDATE user_stats SET streak_count = ?, last_study_date = ? WHERE username = ?", (streak, today, username))
    
    conn.commit()
    conn.close()
    auto_save_backup()

def get_streak_and_analytics(username=None):
    if not username:
        username = st.session_state.get("username", "default")
    conn = get_db_connection()
    stats = conn.execute("SELECT * FROM user_stats WHERE username = ?", (username,)).fetchone()
    logs = conn.execute("SELECT SUM(duration_minutes) as total_min FROM study_logs WHERE username = ?", (username,)).fetchone()
    today_logs = conn.execute(
        "SELECT SUM(duration_minutes) as today_min FROM study_logs WHERE username = ? AND log_date = ?", 
        (username, date.today().isoformat())
    ).fetchone()
    conn.close()
    
    total_minutes = (logs["total_min"] if logs and logs["total_min"] else 0)
    today_minutes = (today_logs["today_min"] if today_logs and today_logs["today_min"] else 0)
    
    streak = 0
    if stats and stats["streak_count"]:
        last_date = stats["last_study_date"]
        if last_date:
            last_dt = datetime.strptime(last_date, "%Y-%m-%d").date()
            delta = (date.today() - last_dt).days
            if delta <= 1:
                streak = stats["streak_count"]
            else:
                streak = 0
        else:
            streak = stats["streak_count"]
            
    return streak, total_minutes, today_minutes

def get_gang_leaderboard():
    """Fetches study stats across all authorized users for friendly comparison."""
    conn = get_db_connection()
    leaderboard = []
    today = date.today()
    for u in AUTHORIZED_USERS.keys():
        stats = conn.execute("SELECT streak_count, last_study_date FROM user_stats WHERE username = ?", (u,)).fetchone()
        logs = conn.execute("SELECT SUM(duration_minutes) as total_min FROM study_logs WHERE username = ?", (u,)).fetchone()
        streak = 0
        if stats and stats["streak_count"]:
            if stats["last_study_date"]:
                last_dt = datetime.strptime(stats["last_study_date"], "%Y-%m-%d").date()
                if (today - last_dt).days <= 1:
                    streak = stats["streak_count"]
            else:
                streak = stats["streak_count"]
                
        total_min = logs["total_min"] if logs and logs["total_min"] else 0
        leaderboard.append({
            "username": u,
            "streak": streak,
            "total_hours": round(total_min / 60, 1),
            "total_min": total_min
        })
    conn.close()
    leaderboard.sort(key=lambda x: (x["total_min"], x["streak"]), reverse=True)
    return leaderboard

def record_history_action(action_type, table, record_id, previous_state):
    """Simple undo log tracking."""
    st.session_state.history.append({
        "type": action_type,
        "table": table,
        "id": record_id,
        "state": previous_state,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })

def get_user_achievement_stats(username=None):
    """Aggregates all multi-dimensional study progress data for achievements."""
    if not username:
        username = st.session_state.get("username", "default")
    conn = get_db_connection()
    
    # Study logs stats
    logs = conn.execute(
        "SELECT SUM(duration_minutes) as total_min, COUNT(*) as session_count, MAX(duration_minutes) as max_session FROM study_logs WHERE username = ?", 
        (username,)
    ).fetchone()
    total_min = logs["total_min"] or 0
    session_count = logs["session_count"] or 0
    max_session = logs["max_session"] or 0
    
    # Today's logs
    today_str = date.today().isoformat()
    today_logs = conn.execute(
        "SELECT SUM(duration_minutes) as today_min, COUNT(*) as today_sessions FROM study_logs WHERE username = ? AND log_date = ?", 
        (username, today_str)
    ).fetchone()
    today_min = today_logs["today_min"] or 0
    today_sessions = today_logs["today_sessions"] or 0
    
    # User streak
    stats = conn.execute("SELECT streak_count FROM user_stats WHERE username = ?", (username,)).fetchone()
    streak = stats["streak_count"] if stats and stats["streak_count"] else 0
    
    # Subjects
    subs = conn.execute("SELECT id FROM subjects WHERE username = ?", (username,)).fetchall()
    subject_ids = [s["id"] for s in subs]
    subject_count = len(subject_ids)
    
    chapter_count = 0
    completed_chapters = 0
    task_count = 0
    completed_tasks = 0
    high_priority_completed = 0
    
    if subject_ids:
        placeholders = ','.join('?' * len(subject_ids))
        chapters = conn.execute(
            f"SELECT id, completed FROM chapters WHERE subject_id IN ({placeholders})", 
            subject_ids
        ).fetchall()
        chapter_count = len(chapters)
        completed_chapters = sum(1 for c in chapters if c["completed"] == 1)
        chapter_ids = [c["id"] for c in chapters]
        
        if chapter_ids:
            c_placeholders = ','.join('?' * len(chapter_ids))
            tasks = conn.execute(
                f"SELECT id, completed, priority FROM tasks WHERE chapter_id IN ({c_placeholders})", 
                chapter_ids
            ).fetchall()
            task_count = len(tasks)
            completed_tasks = sum(1 for t in tasks if t["completed"] == 1)
            high_priority_completed = sum(1 for t in tasks if t["completed"] == 1 and str(t["priority"]).lower() == 'high')
            
    conn.close()
    
    return {
        "total_min": total_min,
        "hours": round(total_min / 60, 1),
        "session_count": session_count,
        "max_session": max_session,
        "today_min": today_min,
        "today_sessions": today_sessions,
        "streak": streak,
        "subject_count": subject_count,
        "chapter_count": chapter_count,
        "completed_chapters": completed_chapters,
        "task_count": task_count,
        "completed_tasks": completed_tasks,
        "high_priority_completed": high_priority_completed
    }

def get_all_badges(stats):
    """Generates the full suite of 26 achievements with live progress, tiers, and XP."""
    total_min = stats["total_min"]
    hours = stats["hours"]
    session_count = stats["session_count"]
    max_session = stats["max_session"]
    today_min = stats["today_min"]
    today_sessions = stats["today_sessions"]
    streak = stats["streak"]
    subject_count = stats["subject_count"]
    completed_chapters = stats["completed_chapters"]
    completed_tasks = stats["completed_tasks"]
    high_priority_completed = stats["high_priority_completed"]
    
    badge_defs = [
        # --- FOCUS TIME & SESSIONS ---
        {
            "id": "first_step",
            "name": "First Steps",
            "category": "⏱️ Focus Time",
            "tier": "Bronze",
            "xp": 50,
            "desc": "Log your first Pomodoro focus session",
            "icon": "🌱",
            "current": session_count,
            "target": 1,
            "unit": "session",
            "unlocked": session_count >= 1,
        },
        {
            "id": "hour_of_power",
            "name": "Hour of Power",
            "category": "⏱️ Focus Time",
            "tier": "Bronze",
            "xp": 50,
            "desc": "Log at least 1 total hour of focus time",
            "icon": "⏳",
            "current": hours,
            "target": 1.0,
            "unit": "hrs",
            "unlocked": hours >= 1.0,
        },
        {
            "id": "5_hour_club",
            "name": "5-Hour Club",
            "category": "⏱️ Focus Time",
            "tier": "Silver",
            "xp": 100,
            "desc": "Accumulate 5 hours of logged study time",
            "icon": "🔋",
            "current": hours,
            "target": 5.0,
            "unit": "hrs",
            "unlocked": hours >= 5.0,
        },
        {
            "id": "centurion_focus",
            "name": "Centurion Focus",
            "category": "⏱️ Focus Time",
            "tier": "Silver",
            "xp": 150,
            "desc": "Log 10 total hours of focus time",
            "icon": "🛡️",
            "current": hours,
            "target": 10.0,
            "unit": "hrs",
            "unlocked": hours >= 10.0,
        },
        {
            "id": "25_hour_dedication",
            "name": "25-Hour Dedication",
            "category": "⏱️ Focus Time",
            "tier": "Gold",
            "xp": 250,
            "desc": "Reach 25 total hours of deep study time",
            "icon": "🌟",
            "current": hours,
            "target": 25.0,
            "unit": "hrs",
            "unlocked": hours >= 25.0,
        },
        {
            "id": "50_hour_scholar",
            "name": "Half-Century Scholar",
            "category": "⏱️ Focus Time",
            "tier": "Platinum",
            "xp": 500,
            "desc": "Reach 50 total hours of deep focus",
            "icon": "👑",
            "current": hours,
            "target": 50.0,
            "unit": "hrs",
            "unlocked": hours >= 50.0,
        },
        {
            "id": "100_hour_grandmaster",
            "name": "Century Grandmaster",
            "category": "⏱️ Focus Time",
            "tier": "Legendary",
            "xp": 1000,
            "desc": "Achieve a monumental 100 hours of focus",
            "icon": "🌌",
            "current": hours,
            "target": 100.0,
            "unit": "hrs",
            "unlocked": hours >= 100.0,
        },

        # --- STREAKS & CONSISTENCY ---
        {
            "id": "consistency_spark",
            "name": "Consistency Spark",
            "category": "🔥 Streaks",
            "tier": "Bronze",
            "xp": 50,
            "desc": "Reach a 3-day consecutive study streak",
            "icon": "🔥",
            "current": streak,
            "target": 3,
            "unit": "days",
            "unlocked": streak >= 3,
        },
        {
            "id": "weekly_warrior",
            "name": "Weekly Warrior",
            "category": "🔥 Streaks",
            "tier": "Silver",
            "xp": 100,
            "desc": "Maintain an uninterrupted 7-day study streak",
            "icon": "⚡",
            "current": streak,
            "target": 7,
            "unit": "days",
            "unlocked": streak >= 7,
        },
        {
            "id": "fortnight_focus",
            "name": "Fortnight of Focus",
            "category": "🔥 Streaks",
            "tier": "Gold",
            "xp": 250,
            "desc": "Maintain an uninterrupted 14-day study streak",
            "icon": "🚀",
            "current": streak,
            "target": 14,
            "unit": "days",
            "unlocked": streak >= 14,
        },
        {
            "id": "iron_discipline",
            "name": "Iron Discipline",
            "category": "🔥 Streaks",
            "tier": "Platinum",
            "xp": 500,
            "desc": "Reach an extraordinary 30-day study streak",
            "icon": "💎",
            "current": streak,
            "target": 30,
            "unit": "days",
            "unlocked": streak >= 30,
        },
        {
            "id": "unbreakable_will",
            "name": "Unbreakable Will",
            "category": "🔥 Streaks",
            "tier": "Legendary",
            "xp": 1000,
            "desc": "Reach a legendary 60-day study streak",
            "icon": "🌋",
            "current": streak,
            "target": 60,
            "unit": "days",
            "unlocked": streak >= 60,
        },

        # --- TASKS & CHECKLISTS ---
        {
            "id": "first_checkmark",
            "name": "First Checkmark",
            "category": "📝 Tasks",
            "tier": "Bronze",
            "xp": 50,
            "desc": "Complete your first checklist task",
            "icon": "✔️",
            "current": completed_tasks,
            "target": 1,
            "unit": "tasks",
            "unlocked": completed_tasks >= 1,
        },
        {
            "id": "task_slayer",
            "name": "Task Slayer",
            "category": "📝 Tasks",
            "tier": "Silver",
            "xp": 100,
            "desc": "Check off 10 completed checklist tasks",
            "icon": "⚔️",
            "current": completed_tasks,
            "target": 10,
            "unit": "tasks",
            "unlocked": completed_tasks >= 10,
        },
        {
            "id": "priority_hunter",
            "name": "Priority Hunter",
            "category": "📝 Tasks",
            "tier": "Silver",
            "xp": 100,
            "desc": "Complete 5 High-Priority tasks",
            "icon": "🚨",
            "current": high_priority_completed,
            "target": 5,
            "unit": "tasks",
            "unlocked": high_priority_completed >= 5,
        },
        {
            "id": "task_terminator",
            "name": "Task Terminator",
            "category": "📝 Tasks",
            "tier": "Gold",
            "xp": 250,
            "desc": "Complete 25 tasks across your study plans",
            "icon": "💥",
            "current": completed_tasks,
            "target": 25,
            "unit": "tasks",
            "unlocked": completed_tasks >= 25,
        },
        {
            "id": "task_titan",
            "name": "Task Titan",
            "category": "📝 Tasks",
            "tier": "Platinum",
            "xp": 500,
            "desc": "Complete 50 tasks across your study plans",
            "icon": "🎯",
            "current": completed_tasks,
            "target": 50,
            "unit": "tasks",
            "unlocked": completed_tasks >= 50,
        },
        {
            "id": "century_finisher",
            "name": "Century Finisher",
            "category": "📝 Tasks",
            "tier": "Legendary",
            "xp": 1000,
            "desc": "Complete 100 checklist tasks",
            "icon": "💫",
            "current": completed_tasks,
            "target": 100,
            "unit": "tasks",
            "unlocked": completed_tasks >= 100,
        },

        # --- ARCHITECTURE & PLANNING ---
        {
            "id": "blueprint_beginner",
            "name": "Blueprint Beginner",
            "category": "🏛️ Architecture",
            "tier": "Bronze",
            "xp": 50,
            "desc": "Create your first Subject Master Plan",
            "icon": "📐",
            "current": subject_count,
            "target": 1,
            "unit": "subjects",
            "unlocked": subject_count >= 1,
        },
        {
            "id": "master_architect",
            "name": "Master Architect",
            "category": "🏛️ Architecture",
            "tier": "Silver",
            "xp": 100,
            "desc": "Create 3 or more Subject Master Plans",
            "icon": "🏛️",
            "current": subject_count,
            "target": 3,
            "unit": "subjects",
            "unlocked": subject_count >= 3,
        },
        {
            "id": "polymath",
            "name": "Polymath",
            "category": "🏛️ Architecture",
            "tier": "Gold",
            "xp": 250,
            "desc": "Create 5 or more Subject Master Plans",
            "icon": "🌐",
            "current": subject_count,
            "target": 5,
            "unit": "subjects",
            "unlocked": subject_count >= 5,
        },
        {
            "id": "chapter_conqueror",
            "name": "Chapter Conqueror",
            "category": "🏛️ Architecture",
            "tier": "Silver",
            "xp": 100,
            "desc": "Complete at least 3 entire chapter sub-plans",
            "icon": "📑",
            "current": completed_chapters,
            "target": 3,
            "unit": "chapters",
            "unlocked": completed_chapters >= 3,
        },
        {
            "id": "curriculum_champion",
            "name": "Curriculum Champion",
            "category": "🏛️ Architecture",
            "tier": "Gold",
            "xp": 250,
            "desc": "Complete 10 chapter sub-plans",
            "icon": "🏆",
            "current": completed_chapters,
            "target": 10,
            "unit": "chapters",
            "unlocked": completed_chapters >= 10,
        },

        # --- SESSION FEATS & MILESTONES ---
        {
            "id": "deep_diver",
            "name": "Deep Work Diver",
            "category": "⚡ Feats",
            "tier": "Silver",
            "xp": 100,
            "desc": "Complete a single focus session of 50+ minutes",
            "icon": "🌊",
            "current": max_session,
            "target": 50,
            "unit": "mins",
            "unlocked": max_session >= 50,
        },
        {
            "id": "daily_marathoner",
            "name": "Daily Marathoner",
            "category": "⚡ Feats",
            "tier": "Gold",
            "xp": 250,
            "desc": "Focus for 2+ hours (120 mins) in a single day",
            "icon": "🏃",
            "current": today_min,
            "target": 120,
            "unit": "mins",
            "unlocked": today_min >= 120,
        },
        {
            "id": "sprint_machine",
            "name": "Sprint Machine",
            "category": "⚡ Feats",
            "tier": "Silver",
            "xp": 100,
            "desc": "Complete 5 focus sessions in a single day",
            "icon": "⚡",
            "current": today_sessions,
            "target": 5,
            "unit": "sessions",
            "unlocked": today_sessions >= 5,
        },
    ]
    return badge_defs

def calculate_user_level(total_xp):
    """Calculates user level, title, icon, and progress toward next level."""
    levels = [
        (0, "Novice Scholar", "🌱"),
        (150, "Focus Apprentice", "⚡"),
        (350, "Consistent Learner", "📖"),
        (650, "Academic Knight", "🛡️"),
        (1050, "Master Strategist", "⚔️"),
        (1600, "Grand Archon", "🏛️"),
        (2300, "Titan of Focus", "🔥"),
        (3200, "Study Legend", "👑"),
        (4500, "Immortal Grandmaster", "🌌")
    ]
    current_title = levels[0][1]
    current_icon = levels[0][2]
    current_level = 1
    next_xp = levels[1][0]
    prev_xp = 0
    
    for idx, (req_xp, title, icon) in enumerate(levels):
        if total_xp >= req_xp:
            current_level = idx + 1
            current_title = title
            current_icon = icon
            prev_xp = req_xp
            next_xp = levels[idx + 1][0] if idx + 1 < len(levels) else None
            
    return {
        "level": current_level,
        "title": current_title,
        "icon": current_icon,
        "current_xp": total_xp,
        "prev_xp": prev_xp,
        "next_xp": next_xp,
    }

# -----------------------------------------------------------------------------
# 5. VISUALIZATION COMPONENTS (Plotly Glass Donuts & Progress Rings)
# -----------------------------------------------------------------------------
def render_progress_ring(percentage, title="Completion", color="#6366F1"):
    fig = go.Figure(go.Pie(
        values=[percentage, max(0, 100 - percentage)],
        hole=0.75,
        sort=False,
        direction='clockwise',
        textinfo='none',
        marker=dict(colors=[color, 'rgba(150, 150, 150, 0.15)']),
        hoverinfo='skip'
    ))
    fig.update_layout(
        showlegend=False,
        margin=dict(t=0, b=0, l=0, r=0),
        height=140,
        width=140,
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        annotations=[dict(
            text=f"<b>{percentage:.0f}%</b>",
            x=0.5, y=0.5,
            font=dict(size=20, color='white' if st.session_state.theme_mode == 'dark' else '#0F172A'),
            showarrow=False
        )]
    )
    return fig

# -----------------------------------------------------------------------------
# 6. APPLICATION CONFIG & AUTHENTICATION GATEWAY
# -----------------------------------------------------------------------------
st.set_page_config(page_title="StudyTracker Pro", page_icon="⚡", layout="wide")
inject_custom_css()

def render_login():
    """Renders a sleek liquid glass login gateway."""
    col1, col2, col3 = st.columns([1, 1.8, 1])
    with col2:
        st.markdown("""
        <div class="glass-card" style="text-align: center; margin-top: 3rem; margin-bottom: 1.5rem; padding: 2rem;">
            <div style="font-size: 3.5rem; margin-bottom: 0.5rem;">⚡</div>
            <h2 style="margin: 0; font-weight: 700; letter-spacing: -0.5px;">StudyTracker Pro</h2>
            <p style="color: #94A3B8; margin-top: 0.4rem; font-size: 0.95rem;">Gang Study & Focus Portal</p>
        </div>
        """, unsafe_allow_html=True)
        
        with st.form("login_form"):
            st.markdown("#### 🔐 Member Login")
            user_input = st.selectbox("Select Your Name", list(AUTHORIZED_USERS.keys()), key="login_user")
            pwd_input = st.text_input("Password", type="password", placeholder="Enter your password", key="login_pwd")
            login_btn = st.form_submit_button("🚀 Enter Study Room", use_container_width=True)
            
            if login_btn:
                if user_input in AUTHORIZED_USERS and AUTHORIZED_USERS[user_input] == pwd_input:
                    st.session_state.authenticated = True
                    st.session_state.username = user_input
                    st.success(f"Welcome, {user_input}! Entering study workspace...")
                    st.rerun()
                else:
                    st.error("❌ Incorrect password. Please try again.")
        
        st.markdown("""
        <div style="text-align: center; margin-top: 1.5rem; color: #94A3B8; font-size: 0.85rem;">
            🔒 Multi-Device Protected Access • All your study logs & master plans are saved independently.
        </div>
        """, unsafe_allow_html=True)

# Guard the app behind authentication
if not st.session_state.authenticated:
    render_login()
    st.stop()

# -----------------------------------------------------------------------------
# 7. AUTHENTICATED APP LAYOUT & SIDEBAR
# -----------------------------------------------------------------------------
current_user = st.session_state.username

with st.sidebar:
    st.markdown("### ⚡ StudyTracker Pro")
    
    # User Profile Badge
    st.markdown(f"""
    <div style="background: rgba(99, 102, 241, 0.15); border: 1px solid rgba(99, 102, 241, 0.35); border-radius: 12px; padding: 0.75rem 1rem; margin-bottom: 0.75rem;">
        <span style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94A3B8;">Active Member</span><br/>
        <strong style="font-size: 1.15rem; color: #818CF8;">👤 {current_user}</strong>
    </div>
    """, unsafe_allow_html=True)
    
    if st.button("🚪 Logout", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.username = None
        st.rerun()
        
    st.markdown("---")
    
    # Theme & Accessibility toggles
    with st.expander("🎨 Display & Accessibility", expanded=False):
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            theme_choice = st.selectbox("Theme", ["dark", "light"], index=0 if st.session_state.theme_mode == "dark" else 1)
            if theme_choice != st.session_state.theme_mode:
                st.session_state.theme_mode = theme_choice
                st.rerun()
        with col_t2:
            contrast_choice = st.toggle("High Contrast", value=st.session_state.high_contrast)
            if contrast_choice != st.session_state.high_contrast:
                st.session_state.high_contrast = contrast_choice
                st.rerun()

    # Main Navigation
    nav_option = st.radio(
        "Navigation",
        ["Dashboard", "Subject Master Plans", "Focus Timer (Pomodoro)", "Analytics & Badges", "Export Plans", "💾 Backup & Cloud Sync"],
        label_visibility="collapsed"
    )

    st.markdown("---")
    
    # Quick Add Item widget
    with st.expander("⚡ Quick Add Task", expanded=False):
        subjects = get_subjects(current_user)
        if subjects:
            q_sub = st.selectbox("Subject", subjects, format_func=lambda s: s["name"], key="q_sub")
            chaps = get_chapters(q_sub["id"])
            if chaps:
                q_chap = st.selectbox("Chapter", chaps, format_func=lambda c: c["name"], key="q_chap")
                q_title = st.text_input("Task Title", key="q_title")
                q_priority = st.selectbox("Priority", ["Low", "Medium", "High"], index=1, key="q_priority")
                q_due = st.date_input("Due Date", value=date.today(), key="q_due")
                if st.button("Add Task", use_container_width=True):
                    if q_title.strip():
                        conn = get_db_connection()
                        conn.execute(
                            "INSERT INTO tasks (chapter_id, title, priority, due_date) VALUES (?, ?, ?, ?)",
                            (q_chap["id"], q_title.strip(), q_priority, q_due.isoformat())
                        )
                        conn.commit()
                        conn.close()
                        auto_save_backup()
                        st.success("Task added!")
                        st.rerun()
            else:
                st.info("Add a chapter to this subject first.")
        else:
            st.info("Add a subject first to use Quick Add.")

    # Undo Manager
    if st.session_state.history:
        st.markdown("---")
        last_action = st.session_state.history[-1]
        st.caption(f"Last Action: {last_action['type']} ({last_action['timestamp']})")
        if st.button("↺ Undo Last Change", use_container_width=True):
            action = st.session_state.history.pop()
            conn = get_db_connection()
            if action["type"] == "toggle_task":
                conn.execute("UPDATE tasks SET completed = ?, status = ? WHERE id = ?",
                             (action["state"]["completed"], action["state"]["status"], action["id"]))
            elif action["type"] == "delete_task":
                conn.execute(
                    "INSERT INTO tasks (id, chapter_id, title, status, priority, due_date, completed) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (action["id"], action["state"]["chapter_id"], action["state"]["title"],
                     action["state"]["status"], action["state"]["priority"], action["state"]["due_date"], action["state"]["completed"])
                )
            conn.commit()
            conn.close()
            auto_save_backup()
            st.success("Reverted!")
            st.rerun()

# -----------------------------------------------------------------------------
# 8. ROUTE: DASHBOARD OVERVIEW
# -----------------------------------------------------------------------------
if nav_option == "Dashboard":
    streak, total_min, today_min = get_streak_and_analytics(current_user)
    
    # Metric Ribbon
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">🔥 Daily Streak</div>
            <div class="metric-value">{streak} <span style="font-size: 1rem;">Days</span></div>
            <div style="font-size: 0.72rem; color: #94A3B8; margin-top: 4px;">Active consecutive study days</div>
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">⏱️ Today's Focus</div>
            <div class="metric-value">{today_min} <span style="font-size: 1rem;">Mins</span></div>
            <div style="font-size: 0.72rem; color: #94A3B8; margin-top: 4px;">Daily focus session counter</div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">📚 Lifetime Focus Time</div>
            <div class="metric-value">{round(total_min / 60, 1)} <span style="font-size: 1rem;">Hours</span></div>
            <div style="font-size: 0.72rem; color: #94A3B8; margin-top: 4px;">Permanent total study hours</div>
        </div>
        """, unsafe_allow_html=True)
    with m4:
        subjects = get_subjects(current_user)
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">🎯 Master Subjects</div>
            <div class="metric-value">{len(subjects)}</div>
            <div style="font-size: 0.72rem; color: #94A3B8; margin-top: 4px;">Saved active study plans</div>
        </div>
        """, unsafe_allow_html=True)

    # Search & Filter
    st.markdown("### 🔍 Quick Search & Task Lookup")
    search_q = st.text_input("Search tasks across your subjects & chapters...", placeholder="Type to search...", label_visibility="collapsed")
    
    if search_q.strip():
        conn = get_db_connection()
        results = conn.execute("""
            SELECT t.id, t.title, t.completed, t.priority, t.due_date, c.name as chapter_name, s.name as subject_name
            FROM tasks t
            JOIN chapters c ON t.chapter_id = c.id
            JOIN subjects s ON c.subject_id = s.id
            WHERE s.username = ? AND t.title LIKE ?
        """, (current_user, f"%{search_q}%")).fetchall()
        conn.close()

        if results:
            for r in results:
                st.markdown(f"""
                <div class="glass-card" style="padding: 0.75rem 1.25rem;">
                    <strong>{'✅' if r['completed'] else '⭕'} {r['title']}</strong> 
                    <span class="badge-pill priority-{r['priority']}">{r['priority']}</span>
                    <span style="color: #94A3B8; font-size: 0.85rem;">{r['subject_name']} → {r['chapter_name']} | Due: {r['due_date']}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("No matching tasks found.")

    st.markdown("### 📊 Subject Progress Overview")
    if not subjects:
        st.info("No study subjects created yet. Navigate to 'Subject Master Plans' to create your first master plan.")
    else:
        for sub in subjects:
            prog = calculate_subject_progress(sub["id"])
            chapters = get_chapters(sub["id"])
            
            c_left, c_right = st.columns([4, 1])
            with c_left:
                st.markdown(f"#### 📖 {sub['name']}")
                if sub['description']:
                    st.caption(sub['description'])
                st.progress(prog / 100)
                st.caption(f"{len(chapters)} Chapters • {prog}% Completed")
            with c_right:
                st.plotly_chart(render_progress_ring(prog, color=sub["color"]), use_container_width=True, key=f"ring_{sub['id']}")
            st.markdown("---")

# -----------------------------------------------------------------------------
# 9. ROUTE: SUBJECT MASTER PLANS (Hierarchical: Subject -> Chapter -> Task)
# -----------------------------------------------------------------------------
elif nav_option == "Subject Master Plans":
    st.markdown("## 📚 Subject Master Plans")
    
    # Action Ribbon
    col_s1, col_s2 = st.columns([3, 1])
    with col_s2:
        with st.expander("➕ Add New Subject"):
            with st.form("new_subject_form"):
                new_sub_name = st.text_input("Subject Name", placeholder="e.g. Organic Chemistry")
                new_sub_desc = st.text_area("Description / Goals")
                new_sub_color = st.color_picker("Theme Color", value="#4F46E5")
                submitted = st.form_submit_button("Create Master Plan")
                if submitted and new_sub_name.strip():
                    conn = get_db_connection()
                    conn.execute("INSERT INTO subjects (username, name, description, color) VALUES (?, ?, ?, ?)",
                                 (current_user, new_sub_name.strip(), new_sub_desc, new_sub_color))
                    conn.commit()
                    conn.close()
                    auto_save_backup()
                    st.success("Created!")
                    st.rerun()

    subjects = get_subjects(current_user)
    if not subjects:
        st.info("Start by adding your first subject plan using the form above.")
    else:
        # Subject Selector
        subject_names = {s["name"]: s for s in subjects}
        active_sub_name = st.selectbox("Select Subject Plan", list(subject_names.keys()))
        active_sub = subject_names[active_sub_name]
        
        # Subject Card Details
        st.markdown(f"""
        <div class="glass-card" style="border-left: 6px solid {active_sub['color']};">
            <h2>{active_sub['name']}</h2>
            <p style="color: #94A3B8;">{active_sub['description'] or 'No description provided.'}</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Chapter Sub-plans Section
        st.markdown("### 📑 Chapter Sub-plans & Checklists")
        chapters = get_chapters(active_sub["id"])
        
        # Add Chapter Form
        with st.expander("➕ Add Chapter Sub-plan"):
            with st.form("new_chap_form"):
                c_name = st.text_input("Chapter Title", placeholder="e.g. Chapter 1: Chemical Kinetics")
                c_desc = st.text_input("Sub-plan Description / Target")
                c_sub = st.form_submit_button("Add Chapter")
                if c_sub and c_name.strip():
                    conn = get_db_connection()
                    conn.execute("INSERT INTO chapters (subject_id, name, description) VALUES (?, ?, ?)",
                                 (active_sub["id"], c_name.strip(), c_desc))
                    conn.commit()
                    conn.close()
                    auto_save_backup()
                    st.rerun()

        # Render Chapters Hierarchy
        for chap in chapters:
            chap_id = chap["id"]
            chap_prog = calculate_chapter_progress(chap_id)
            
            with st.expander(f"📁 {chap['name']} ({chap_prog}% Done)", expanded=True):
                if chap['description']:
                    st.caption(f"🎯 Goal: {chap['description']}")
                
                # Progress Bar
                st.progress(chap_prog / 100)
                
                # Checkable Chapter status (if no tasks)
                tasks = get_tasks(chap_id)
                col_c1, col_c2 = st.columns([4, 1])
                with col_c2:
                    chap_done = st.checkbox("Mark Chapter Completed", value=bool(chap["completed"]), key=f"chap_chk_{chap_id}")
                    if chap_done != bool(chap["completed"]):
                        conn = get_db_connection()
                        conn.execute("UPDATE chapters SET completed = ? WHERE id = ?", (1 if chap_done else 0, chap_id))
                        conn.commit()
                        conn.close()
                        auto_save_backup()
                        st.rerun()

                # Nested Tasks Checklist
                st.markdown("##### 📝 Checklist Tasks")
                for t in tasks:
                    t_id = t["id"]
                    t_col1, t_col2, t_col3, t_col4 = st.columns([0.5, 4, 2, 0.5])
                    
                    # Task completion toggle
                    with t_col1:
                        is_checked = st.checkbox("", value=bool(t["completed"]), key=f"task_chk_{t_id}", label_visibility="collapsed")
                        if is_checked != bool(t["completed"]):
                            conn = get_db_connection()
                            new_status = "completed" if is_checked else "not started"
                            record_history_action("toggle_task", "tasks", t_id, {"completed": t["completed"], "status": t["status"]})
                            conn.execute("UPDATE tasks SET completed = ?, status = ? WHERE id = ?", (1 if is_checked else 0, new_status, t_id))
                            conn.commit()
                            conn.close()
                            auto_save_backup()
                            st.rerun()
                    
                    with t_col2:
                        title_style = "text-decoration: line-through; opacity: 0.6;" if t["completed"] else ""
                        st.markdown(f"<span style='{title_style}'>{t['title']}</span>", unsafe_allow_html=True)
                    
                    with t_col3:
                        st.markdown(f"""
                        <span class="badge-pill priority-{t['priority']}">{t['priority']}</span>
                        <span style="font-size: 0.8rem; color: #94A3B8;">📅 {t['due_date'] or 'No date'}</span>
                        """, unsafe_allow_html=True)
                    
                    with t_col4:
                        if st.button("🗑️", key=f"del_t_{t_id}", help="Delete Task"):
                            conn = get_db_connection()
                            record_history_action("delete_task", "tasks", t_id, dict(t))
                            conn.execute("DELETE FROM tasks WHERE id = ?", (t_id,))
                            conn.commit()
                            conn.close()
                            auto_save_backup()
                            st.rerun()
                
                # Add task inline
                with st.form(f"add_task_inline_{chap_id}"):
                    st.caption("Add task to this chapter:")
                    tc1, tc2, tc3, tc4 = st.columns([3, 1.5, 1.5, 1])
                    with tc1:
                        nt_title = st.text_input("Task Title", placeholder="e.g. Read section 2.1", label_visibility="collapsed")
                    with tc2:
                        nt_pri = st.selectbox("Priority", ["Low", "Medium", "High"], index=1, label_visibility="collapsed")
                    with tc3:
                        nt_due = st.date_input("Due Date", value=date.today(), label_visibility="collapsed")
                    with tc4:
                        nt_submit = st.form_submit_button("➕ Add")
                        if nt_submit and nt_title.strip():
                            conn = get_db_connection()
                            conn.execute("INSERT INTO tasks (chapter_id, title, priority, due_date) VALUES (?, ?, ?, ?)",
                                         (chap_id, nt_title.strip(), nt_pri, nt_due.isoformat()))
                            conn.commit()
                            conn.close()
                            auto_save_backup()
                            st.rerun()
                
                # Delete Chapter
                if st.button(f"🗑️ Delete Chapter '{chap['name']}'", key=f"del_chap_{chap_id}"):
                    conn = get_db_connection()
                    conn.execute("DELETE FROM chapters WHERE id = ?", (chap_id,))
                    conn.commit()
                    conn.close()
                    auto_save_backup()
                    st.rerun()

        # Delete Subject with Safety Confirmation
        st.markdown("---")
        with st.expander("⚠️ Danger Zone: Delete Master Plan", expanded=False):
            st.warning(f"Deleting **'{active_sub['name']}'** will permanently remove the entire master plan, its chapters, and checklist tasks.")
            confirm_del = st.checkbox(f"Yes, permanently delete '{active_sub['name']}'", key=f"conf_del_{active_sub['id']}")
            if st.button("🗑️ Permanently Delete This Master Plan", disabled=not confirm_del, type="primary" if confirm_del else "secondary", key=f"del_sub_{active_sub['id']}"):
                conn = get_db_connection()
                conn.execute("DELETE FROM subjects WHERE id = ?", (active_sub["id"],))
                conn.commit()
                conn.close()
                auto_save_backup()
                st.success(f"Master plan '{active_sub['name']}' has been deleted.")
                st.rerun()

# -----------------------------------------------------------------------------
# 10. ROUTE: FOCUS POMODORO TIMER
# -----------------------------------------------------------------------------
elif nav_option == "Focus Timer (Pomodoro)":
    st.markdown("## ⏱️ Pomodoro Focus Session")
    
    subjects = get_subjects(current_user)
    if not subjects:
        st.info("Create a subject master plan to associate your study session.")
    else:
        c1, c2 = st.columns([2, 1])
        with c1:
            # Session Mode Selection
            mode_choice = st.radio(
                "Session Mode", 
                ["🎯 Focus Session", "☕ Short Break", "🌴 Long Break"], 
                horizontal=True,
                key="pomodoro_mode_radio"
            )
            
            is_break = "Break" in (mode_choice or "")
            session_type = "Short Break" if "Short" in (mode_choice or "") else ("Long Break" if "Long" in (mode_choice or "") else "Focus")

            # Active Subject and Target Task (for Focus mode)
            if not is_break:
                sel_sub = st.selectbox("Active Subject", subjects, format_func=lambda s: s["name"], key="pomo_sub")
                chaps = get_chapters(sel_sub["id"])
                all_tasks = []
                for ch in chaps:
                    all_tasks.extend(get_tasks(ch["id"]))
                
                sel_task = None
                if all_tasks:
                    sel_task = st.selectbox("Target Task (Optional)", [None] + all_tasks,
                                            format_func=lambda t: t["title"] if t else "General Study Session", key="pomo_task")
            else:
                sel_sub = subjects[0]
                sel_task = None

            # Duration Presets
            if session_type == "Focus":
                col_d1, col_d2 = st.columns([3, 2])
                with col_d1:
                    duration_choice = st.radio("Focus Duration", [25, 50, 15, "Custom"], horizontal=True, format_func=lambda x: f"{x} Mins" if isinstance(x, int) else "Custom", key="pomo_dur_radio")
                with col_d2:
                    if duration_choice == "Custom":
                        duration_preset = st.number_input("Custom Minutes", min_value=1, max_value=180, value=30, step=5, key="pomo_custom_dur")
                    else:
                        duration_preset = int(duration_choice)
            elif session_type == "Short Break":
                duration_preset = 5
                st.caption("☕ Short Break: 5 Minutes to stretch and rest your eyes.")
            else:
                duration_preset = 15
                st.caption("🌴 Long Break: 15 Minutes to recharge and hydrate.")

            # Sync duration when idle (not running and not paused)
            target_total_sec = duration_preset * 60
            is_paused = (not st.session_state.timer_running) and (st.session_state.timer_seconds < st.session_state.timer_total_duration) and (st.session_state.timer_seconds > 0)
            
            if not st.session_state.timer_running and not is_paused:
                if st.session_state.timer_total_duration != target_total_sec or st.session_state.timer_mode != session_type:
                    st.session_state.timer_total_duration = target_total_sec
                    st.session_state.timer_seconds = target_total_sec
                    st.session_state.timer_mode = session_type

            # UI Containers
            timer_display_placeholder = st.empty()
            prog_bar_placeholder = st.empty()
            
            # Initial calculation of time values
            current_sec = st.session_state.timer_seconds
            mins = current_sec // 60
            secs = current_sec % 60
            
            # Render Static Timer Display (before buttons)
            status_tag = "⚡ FOCUS ACTIVE" if st.session_state.timer_running else ("⏸️ SESSION PAUSED" if is_paused else "READY TO FOCUS")
            status_color = "#10B981" if st.session_state.timer_running else ("#F59E0B" if is_paused else "#6366F1")
            card_class = "glass-card timer-active-card" if st.session_state.timer_running else "glass-card"
            
            task_label = sel_task['title'] if (not is_break and sel_task) else (sel_sub['name'] if not is_break else "Break & Rest")
            
            timer_display_placeholder.markdown(f"""
            <div class="{card_class}" style="text-align: center; padding: 2.2rem;">
                <div style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.1em; color: {status_color}; margin-bottom: 0.5rem; font-weight: 700;">
                    {status_tag}
                </div>
                <h1 style="font-size: 4.8rem; letter-spacing: 2px; font-variant-numeric: tabular-nums; margin: 0; color: #F8FAFC;">
                    {mins:02d}:{secs:02d}
                </h1>
                <p style="color: #94A3B8; margin-top: 0.5rem; font-size: 0.95rem;">
                    Target: <b style="color: #E2E8F0;">{task_label}</b> • Logged to <b>{current_user}</b>
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            # Progress bar
            current_pct = max(0.0, min(1.0, 1.0 - (current_sec / max(1, st.session_state.timer_total_duration))))
            prog_bar_placeholder.progress(current_pct)

            # Timer Control Buttons
            btn_c1, btn_c2, btn_c3 = st.columns(3)
            
            if not st.session_state.timer_running:
                if is_paused:
                    with btn_c1:
                        if st.button("▶️ Resume Session", use_container_width=True, type="primary", key="btn_resume"):
                            st.session_state.timer_running = True
                            st.session_state.timer_end_time = time.time() + st.session_state.timer_seconds
                            st.rerun()
                    with btn_c2:
                        if st.button("⏹️ Log & Finish Early", use_container_width=True, key="btn_finish_early"):
                            st.session_state.timer_running = False
                            elapsed_sec = st.session_state.timer_total_duration - st.session_state.timer_seconds
                            elapsed_min = max(1, round(elapsed_sec / 60))
                            if not is_break:
                                log_study_time(sel_sub["id"], sel_task["id"] if sel_task else None, elapsed_min, current_user)
                                st.success(f"Logged {elapsed_min} minutes of focus for {current_user}!")
                                st.balloons()
                            st.session_state.timer_seconds = target_total_sec
                            st.session_state.timer_total_duration = target_total_sec
                            st.session_state.timer_end_time = None
                            st.rerun()
                    with btn_c3:
                        if st.button("🔄 Reset Timer", use_container_width=True, key="btn_reset_paused"):
                            st.session_state.timer_running = False
                            st.session_state.timer_seconds = target_total_sec
                            st.session_state.timer_total_duration = target_total_sec
                            st.session_state.timer_end_time = None
                            st.rerun()
                else:
                    with btn_c1:
                        if st.button("▶️ Start Session", use_container_width=True, type="primary", key="btn_start"):
                            st.session_state.timer_running = True
                            st.session_state.timer_total_duration = target_total_sec
                            st.session_state.timer_seconds = target_total_sec
                            st.session_state.timer_end_time = time.time() + target_total_sec
                            st.rerun()
                    with btn_c2:
                        if st.button("🔄 Reset", use_container_width=True, key="btn_reset_idle"):
                            st.session_state.timer_seconds = target_total_sec
                            st.session_state.timer_total_duration = target_total_sec
                            st.session_state.timer_end_time = None
                            st.rerun()
                    with btn_c3:
                        st.empty()
            else:
                with btn_c1:
                    if st.button("⏸️ Pause", use_container_width=True, key="btn_pause_running"):
                        st.session_state.timer_running = False
                        if st.session_state.timer_end_time:
                            st.session_state.timer_seconds = max(0, int(st.session_state.timer_end_time - time.time()))
                        st.session_state.timer_end_time = None
                        st.rerun()
                with btn_c2:
                    if st.button("⏹️ Log & Finish Early", use_container_width=True, key="btn_finish_running"):
                        st.session_state.timer_running = False
                        remaining = max(0, int(st.session_state.timer_end_time - time.time())) if st.session_state.timer_end_time else st.session_state.timer_seconds
                        elapsed_sec = st.session_state.timer_total_duration - remaining
                        elapsed_min = max(1, round(elapsed_sec / 60))
                        if not is_break:
                            log_study_time(sel_sub["id"], sel_task["id"] if sel_task else None, elapsed_min, current_user)
                            st.success(f"Logged {elapsed_min} minutes of focus for {current_user}!")
                            st.balloons()
                        st.session_state.timer_seconds = target_total_sec
                        st.session_state.timer_total_duration = target_total_sec
                        st.session_state.timer_end_time = None
                        st.rerun()
                with btn_c3:
                    if st.button("🔄 Reset", use_container_width=True, key="btn_reset_running"):
                        st.session_state.timer_running = False
                        st.session_state.timer_seconds = target_total_sec
                        st.session_state.timer_total_duration = target_total_sec
                        st.session_state.timer_end_time = None
                        st.rerun()

            # LIVE TICKING LOOP
            if st.session_state.timer_running:
                while st.session_state.timer_running:
                    now = time.time()
                    remaining = int(st.session_state.timer_end_time - now)
                    if remaining <= 0:
                        st.session_state.timer_running = False
                        st.session_state.timer_seconds = 0
                        if not is_break:
                            elapsed_min = max(1, round(st.session_state.timer_total_duration / 60))
                            log_study_time(sel_sub["id"], sel_task["id"] if sel_task else None, elapsed_min, current_user)
                            st.balloons()
                            st.toast(f"🎉 Pomodoro Complete! Logged {elapsed_min} mins to {current_user}!", icon="🏆")
                        else:
                            st.toast("☕ Break time is over! Ready for the next focus sprint?", icon="🔔")
                        st.session_state.timer_seconds = target_total_sec
                        st.session_state.timer_total_duration = target_total_sec
                        st.session_state.timer_end_time = None
                        time.sleep(1)
                        st.rerun()
                        break

                    st.session_state.timer_seconds = remaining
                    m = remaining // 60
                    s = remaining % 60
                    pct = max(0.0, min(1.0, 1.0 - (remaining / max(1, st.session_state.timer_total_duration))))

                    timer_display_placeholder.markdown(f"""
                    <div class="glass-card timer-active-card" style="text-align: center; padding: 2.2rem;">
                        <div style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.1em; color: #10B981; margin-bottom: 0.5rem; font-weight: 700;">
                            ⚡ {session_type.upper()} IN PROGRESS
                        </div>
                        <h1 style="font-size: 4.8rem; letter-spacing: 2px; font-variant-numeric: tabular-nums; margin: 0; color: #F8FAFC;">
                            {m:02d}:{s:02d}
                        </h1>
                        <p style="color: #94A3B8; margin-top: 0.5rem; font-size: 0.95rem;">
                            Target: <b style="color: #E2E8F0;">{task_label}</b> • Logged to <b>{current_user}</b>
                        </p>
                    </div>
                    """, unsafe_allow_html=True)
                    prog_bar_placeholder.progress(pct)
                    time.sleep(1)

        with c2:
            st.markdown("### 💡 Focus & Productivity Tips")
            st.markdown("""
            <div class="glass-card">
                <ul style="padding-left: 1.2rem; margin: 0; line-height: 1.6;">
                    <li><b>🎯 Single-Tasking:</b> Focus strictly on your selected checklist item.</li>
                    <li><b>💧 Stay Hydrated:</b> Keep a water bottle within reach during deep sprints.</li>
                    <li><b>☕ Interval Breaks:</b> Take a 5-minute breather after every 25 minutes.</li>
                    <li><b>📱 Zero Distractions:</b> Put your phone on Do Not Disturb mode.</li>
                </ul>
            </div>
            """, unsafe_allow_html=True)
            
            # Quick Stats widget
            st.markdown("### 📊 Session Summary")
            st_streak, st_total, st_today = get_streak_and_analytics(current_user)
            st.markdown(f"""
            <div class="glass-card" style="padding: 1rem 1.25rem;">
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span style="color: #94A3B8;">Today's Focus:</span>
                    <strong style="color: #818CF8;">{st_today} mins</strong>
                </div>
                <div style="display: flex; justify-content: space-between; margin-bottom: 8px;">
                    <span style="color: #94A3B8;">Total Hours:</span>
                    <strong style="color: #818CF8;">{round(st_total/60, 1)} hrs</strong>
                </div>
                <div style="display: flex; justify-content: space-between;">
                    <span style="color: #94A3B8;">Active Streak:</span>
                    <strong style="color: #F59E0B;">🔥 {st_streak} days</strong>
                </div>
            </div>
            """, unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# 11. ROUTE: ANALYTICS & MOTIVATIONAL BADGES
# -----------------------------------------------------------------------------
elif nav_option == "Analytics & Badges":
    st.markdown("## 🏆 Analytics & Achievement Badges")
    
    # Gang Leaderboard Ribbon
    st.markdown("### 👥 Gang Study Leaderboard")
    leaderboard = get_gang_leaderboard()
    l_cols = st.columns(len(leaderboard))
    for idx, member in enumerate(leaderboard):
        with l_cols[idx]:
            is_me = member["username"] == current_user
            highlight_border = "2px solid #6366F1" if is_me else "1px solid rgba(255, 255, 255, 0.12)"
            rank_badge = ["🥇", "🥈", "🥉", "🎖️"][idx] if idx < 4 else f"#{idx+1}"
            st.markdown(f"""
            <div class="glass-card" style="text-align: center; border: {highlight_border};">
                <div style="font-size: 1.6rem; margin-bottom: 2px;">{rank_badge}</div>
                <strong style="font-size: 1.05rem; color: {'#818CF8' if is_me else '#F8FAFC'};">{member['username']} {'(You)' if is_me else ''}</strong>
                <div style="margin-top: 6px; font-size: 0.85rem; color: #94A3B8;">🔥 Streak: <b>{member['streak']}d</b></div>
                <div style="font-size: 0.85rem; color: #94A3B8;">⏱️ Focus: <b>{member['total_hours']}h</b></div>
            </div>
            """, unsafe_allow_html=True)
            
    st.markdown("---")
    
    # User Gamification & Level Overview
    stats = get_user_achievement_stats(current_user)
    badges = get_all_badges(stats)
    unlocked_badges = [b for b in badges if b["unlocked"]]
    unlocked_count = len(unlocked_badges)
    total_xp = sum(b["xp"] for b in unlocked_badges)
    level_info = calculate_user_level(total_xp)
    
    # Hero Gamification Card
    next_xp_str = f"/ {level_info['next_xp']} XP" if level_info['next_xp'] else "(Max Level reached!)"
    if level_info['next_xp']:
        xp_progress = (total_xp - level_info['prev_xp']) / max(1, (level_info['next_xp'] - level_info['prev_xp']))
    else:
        xp_progress = 1.0
        
    st.markdown(f"""
    <div class="glass-card" style="border: 2px solid #6366F1; background: rgba(99, 102, 241, 0.12); padding: 1.5rem 2rem; margin-bottom: 1.5rem;">
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 1rem;">
            <div>
                <span style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em; color: #94A3B8;">Scholar Rank & Level</span>
                <div style="font-size: 1.8rem; font-weight: 700; color: #F8FAFC; margin-top: 4px;">
                    {level_info['icon']} Level {level_info['level']}: <span style="color: #818CF8;">{level_info['title']}</span>
                </div>
            </div>
            <div style="text-align: right;">
                <span style="font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.08em; color: #94A3B8;">Total Earned XP</span>
                <div style="font-size: 1.8rem; font-weight: 700; color: #F59E0B; margin-top: 4px;">
                    ✨ {total_xp:,} <span style="font-size: 1rem; color: #94A3B8;">XP</span>
                </div>
            </div>
        </div>
        <div style="margin-top: 1rem;">
            <div style="display: flex; justify-content: space-between; font-size: 0.8rem; color: #94A3B8; margin-bottom: 4px;">
                <span>Badges Unlocked: <b>{unlocked_count} / {len(badges)}</b> ({int((unlocked_count / len(badges)) * 100)}%)</span>
                <span>Level Progress: <b>{total_xp} {next_xp_str}</b></span>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.progress(max(0.0, min(1.0, xp_progress)))

    # Badges Filter and Category Controls
    st.markdown(f"### 🎖️ Achievement Badges Menu ({unlocked_count}/{len(badges)} Earned)")
    
    f_col1, f_col2 = st.columns([3, 2])
    with f_col1:
        cat_filter = st.selectbox(
            "Filter by Category", 
            ["All Categories", "⏱️ Focus Time", "🔥 Streaks", "📝 Tasks", "🏛️ Architecture", "⚡ Feats"],
            key="badge_cat_filter"
        )
    with f_col2:
        status_filter = st.selectbox(
            "Filter by Status", 
            ["All Badges", "Unlocked Only ✅", "Locked / In Progress 🔒"],
            key="badge_status_filter"
        )
        
    filtered_badges = badges
    if cat_filter != "All Categories":
        filtered_badges = [b for b in filtered_badges if b["category"] == cat_filter]
    if status_filter == "Unlocked Only ✅":
        filtered_badges = [b for b in filtered_badges if b["unlocked"]]
    elif status_filter == "Locked / In Progress 🔒":
        filtered_badges = [b for b in filtered_badges if not b["unlocked"]]
        
    # Render Badges in responsive 4-column grid
    if not filtered_badges:
        st.info("No badges match the selected filters.")
    else:
        # Tier icon helper
        tier_icons = {"Bronze": "🥉", "Silver": "🥈", "Gold": "🥇", "Platinum": "💎", "Legendary": "👑"}
        
        # Grid loop in batches of 4
        num_cols = 4
        for i in range(0, len(filtered_badges), num_cols):
            chunk = filtered_badges[i:i+num_cols]
            cols = st.columns(num_cols)
            for j, b in enumerate(chunk):
                with cols[j]:
                    tier_icon = tier_icons.get(b["tier"], "🎖️")
                    opacity = "1.0" if b["unlocked"] else "0.55"
                    tier_class = f"tier-{b['tier']}" if b["unlocked"] else ""
                    
                    # Progress calculation
                    prog_val = min(1.0, max(0.0, b["current"] / max(0.001, b["target"])))
                    prog_pct_int = int(prog_val * 100)
                    
                    cur_disp = f"{b['current']:.1f}" if isinstance(b['current'], float) else f"{b['current']}"
                    tgt_disp = f"{b['target']:.1f}" if isinstance(b['target'], float) else f"{b['target']}"
                    
                    if b["unlocked"]:
                        status_html = f"""
                        <div style="background: rgba(16, 185, 129, 0.2); color: #34D399; border: 1px solid rgba(16, 185, 129, 0.4); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 600; margin-top: 8px;">
                            ✅ Unlocked (+{b['xp']} XP)
                        </div>
                        """
                        prog_html = f"""
                        <div style="font-size: 0.75rem; color: #34D399; margin-top: 6px; font-weight: 600;">
                            Completed: {tgt_disp} {b['unit']}
                        </div>
                        """
                    else:
                        status_html = f"""
                        <div style="background: rgba(148, 163, 184, 0.12); color: #94A3B8; border: 1px solid rgba(148, 163, 184, 0.25); padding: 3px 8px; border-radius: 9999px; font-size: 0.72rem; font-weight: 600; margin-top: 8px;">
                            🔒 Locked ({b['xp']} XP)
                        </div>
                        """
                        prog_html = f"""
                        <div style="font-size: 0.72rem; color: #94A3B8; margin-top: 6px;">
                            Progress: <b>{cur_disp} / {tgt_disp} {b['unit']}</b> ({prog_pct_int}%)
                        </div>
                        <div style="background: rgba(255,255,255,0.08); border-radius: 9999px; height: 5px; width: 100%; margin-top: 4px; overflow: hidden;">
                            <div style="background: #6366F1; width: {prog_pct_int}%; height: 100%;"></div>
                        </div>
                        """
                    
                    st.markdown(f"""
                    <div class="glass-card {tier_class}" style="text-align: center; opacity: {opacity}; padding: 1.25rem 1rem; display: flex; flex-direction: column; justify-content: space-between; height: 100%;">
                        <div>
                            <div style="font-size: 2.3rem; margin-bottom: 4px;">{b['icon']}</div>
                            <strong style="font-size: 0.95rem; color: #F8FAFC;">{b['name']}</strong>
                            <div style="font-size: 0.72rem; color: #818CF8; margin-top: 2px; font-weight: 600;">
                                {tier_icon} {b['tier']} Tier • {b['category']}
                            </div>
                            <p style="font-size: 0.78rem; color: #94A3B8; margin-top: 6px; min-height: 2.4rem; line-height: 1.3;">
                                {b['desc']}
                            </p>
                        </div>
                        <div>
                            {prog_html}
                            {status_html}
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

    st.markdown("---")
    
    # Activity Chart
    st.markdown("### 📈 Your Recent Focus Activity")
    conn = get_db_connection()
    logs_df = pd.read_sql_query("""
        SELECT log_date, SUM(duration_minutes) as minutes 
        FROM study_logs 
        WHERE username = ?
        GROUP BY log_date 
        ORDER BY log_date DESC LIMIT 7
    """, conn, params=(current_user,))
    conn.close()

    if not logs_df.empty:
        fig = go.Figure(data=[
            go.Bar(
                x=logs_df["log_date"],
                y=logs_df["minutes"],
                marker_color='#6366F1',
                opacity=0.85
            )
        ])
        fig.update_layout(
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            font_color='#94A3B8',
            margin=dict(t=20, b=20, l=20, r=20),
            yaxis_title="Minutes Focused",
            xaxis_title="Date"
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Log your first Pomodoro session to see your personal focus analytics.")

# -----------------------------------------------------------------------------
# 12. ROUTE: EXPORT FUNCTIONALITY (Markdown / JSON)
# -----------------------------------------------------------------------------
elif nav_option == "Export Plans":
    st.markdown("## 📤 Export Study Plans")
    st.write(f"Export study plans, sub-plans, and checklists for **{current_user}** into structured Markdown or JSON format.")
    
    subjects = get_subjects(current_user)
    if subjects:
        export_data = []
        md_text = f"# 📚 Study Master Plan Summary ({current_user})\n*Generated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        
        for s in subjects:
            s_dict = {"subject": s["name"], "description": s["description"], "chapters": []}
            md_text += f"## 📖 Subject: {s['name']}\n{s['description']}\n\n"
            
            chapters = get_chapters(s["id"])
            for c in chapters:
                c_dict = {"chapter": c["name"], "completed": bool(c["completed"]), "tasks": []}
                md_text += f"### 📑 Chapter: {c['name']}\n"
                
                tasks = get_tasks(c["id"])
                for t in tasks:
                    status_box = "[x]" if t["completed"] else "[ ]"
                    md_text += f"- {status_box} **{t['title']}** (Priority: {t['priority']}, Due: {t['due_date']})\n"
                    c_dict["tasks"].append(dict(t))
                s_dict["chapters"].append(c_dict)
                md_text += "\n"
            export_data.append(s_dict)

        col_e1, col_e2 = st.columns(2)
        with col_e1:
            st.download_button(
                label="📄 Download Markdown Plan (.md)",
                data=md_text,
                file_name=f"study_master_plan_{current_user.lower()}.md",
                mime="text/markdown",
                use_container_width=True
            )
        with col_e2:
            st.download_button(
                label="📦 Download Full Data (.json)",
                data=json.dumps(export_data, indent=2),
                file_name=f"study_tracker_{current_user.lower()}.json",
                mime="application/json",
                use_container_width=True
            )
        
        with st.expander("Preview Markdown Output"):
            st.code(md_text, language="markdown")
    else:
        st.info("No study plans available to export.")

# -----------------------------------------------------------------------------
# 13. ROUTE: BACKUP, RESTORE & CLOUD PERSISTENCE
# -----------------------------------------------------------------------------
elif nav_option == "💾 Backup & Cloud Sync":
    st.markdown("## 💾 Data Backup, Restore & Multi-Device Sync")
    st.write("Ensure your master study plans, checklists, streaks, and focus records are 100% permanent and safeguarded across all devices.")

    # Storage Diagnostics Card
    conn = get_db_connection()
    total_subs = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
    total_chaps = conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0]
    total_tasks = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    total_logs = conn.execute("SELECT COUNT(*) FROM study_logs").fetchone()[0]
    conn.close()

    db_size_kb = round(os.path.getsize(DB_PATH) / 1024, 1) if os.path.exists(DB_PATH) else 0
    backup_file = os.path.join(os.path.dirname(DB_PATH), "study_tracker_backup.json")
    backup_time_str = datetime.fromtimestamp(os.path.getmtime(backup_file)).strftime("%Y-%m-%d %H:%M:%S") if os.path.exists(backup_file) else "None yet"

    st.markdown(f"""
    <div class="glass-card" style="border: 2px solid #6366F1; margin-bottom: 1.5rem;">
        <h4 style="margin: 0; color: #818CF8;">🛡️ Local Storage & Auto-Backup Status</h4>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 1rem; margin-top: 1rem;">
            <div>
                <span style="font-size: 0.8rem; color: #94A3B8;">Permanent DB Location:</span><br/>
                <code style="font-size: 0.75rem;">{DB_PATH}</code>
            </div>
            <div>
                <span style="font-size: 0.8rem; color: #94A3B8;">Database Size:</span><br/>
                <strong>{db_size_kb} KB</strong>
            </div>
            <div>
                <span style="font-size: 0.8rem; color: #94A3B8;">Auto-Backup File:</span><br/>
                <span style="color: #34D399; font-size: 0.85rem;">✅ Active ({backup_time_str})</span>
            </div>
            <div>
                <span style="font-size: 0.8rem; color: #94A3B8;">Saved Content:</span><br/>
                <strong>{total_subs} Subjects • {total_tasks} Tasks • {total_logs} Focus Logs</strong>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_b1, col_b2 = st.columns(2)

    with col_b1:
        st.markdown("### 📥 1-Click Full Backup")
        st.caption("Download a complete snapshot of all members' subjects, chapters, tasks, streaks, and focus history.")
        
        full_json = json.dumps(export_full_database_json(), indent=2)
        st.download_button(
            label="📦 Download Full Database Backup (.json)",
            data=full_json,
            file_name=f"study_tracker_full_backup_{date.today().isoformat()}.json",
            mime="application/json",
            use_container_width=True,
            type="primary"
        )
        
        if os.path.exists(DB_PATH):
            with open(DB_PATH, "rb") as fp:
                db_bytes = fp.read()
            st.download_button(
                label="🗄️ Download Raw SQLite File (.db)",
                data=db_bytes,
                file_name=f"study_tracker_{date.today().isoformat()}.db",
                mime="application/x-sqlite3",
                use_container_width=True
            )

    with col_b2:
        st.markdown("### 🔄 1-Click Restore / Import")
        st.caption("Upload any previous `.json` backup file to restore all master plans, checklists, and focus history.")
        
        uploaded_backup = st.file_uploader("Choose a backup .json file", type=["json"], key="restore_uploader")
        if uploaded_backup is not None:
            if st.button("🚀 Restore All Data From File", use_container_width=True, type="primary"):
                try:
                    content = uploaded_backup.getvalue().decode("utf-8")
                    import_full_database_json(content)
                    st.success("🎉 Database successfully restored and merged!")
                    st.balloons()
                    time.sleep(1)
                    st.rerun()
                except Exception as ex:
                    st.error(f"❌ Error restoring backup: {ex}")

    st.markdown("---")
    
    # Cloud Deployment & Multi-Device Sync Guide
    with st.expander("☁️ Why does progress get erased on Streamlit Community Cloud or across different devices?", expanded=True):
        st.markdown("""
        #### 🔍 Why does this happen?
        1. **Streamlit Community Cloud (or Render/Heroku) has Ephemeral Storage:**
           * When your app is hosted online for free, the cloud host runs it in a temporary container.
           * Every time the app sleeps after inactivity or restarts, the container is refreshed and local files (`.db`) are reset!
        2. **Multi-Device Separation:**
           * If you open the app on your phone and a friend opens it on their laptop, local SQLite databases cannot communicate over the internet unless connected to a shared cloud database.
        
        #### 💡 How to keep data 100% permanent forever:
        * **Option 1 (Local Usage - Fixed!):** When running locally with `streamlit run 1-.py`, your database is now permanently locked into your user home directory (`~/.study_tracker/study_tracker.db`) and auto-backed up to `study_tracker_backup.json`. It will **never** reset when started from different folders.
        * **Option 2 (Online Usage - 1-Click Restore):** Before closing your online session, download your backup `.json`. When you open the app next time, simply upload it under **1-Click Restore** to bring back all plans instantly!
        * **Option 3 (Permanent Cloud Database):** You can connect a free PostgreSQL cloud database (such as [Supabase](https://supabase.com) or [Neon](https://neon.tech)) in your Streamlit secrets (`secrets.toml`) for 24/7 cross-device syncing across all group members.
        """)