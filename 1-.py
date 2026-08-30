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
    "SK": "sk1234",
    "User_4": "pass1234",
}

# -----------------------------------------------------------------------------
# 1. DATABASE LAYER (SQLite Persistence with Multi-User Support)
# -----------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in locals() else os.getcwd()
DB_PATH = os.path.join(SCRIPT_DIR, "study_tracker.db")

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

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
    streak = (stats["streak_count"] if stats and stats["streak_count"] else 0)
    return streak, total_minutes, today_minutes

def get_gang_leaderboard():
    """Fetches study stats across all authorized users for friendly comparison."""
    conn = get_db_connection()
    leaderboard = []
    for u in AUTHORIZED_USERS.keys():
        stats = conn.execute("SELECT streak_count FROM user_stats WHERE username = ?", (u,)).fetchone()
        logs = conn.execute("SELECT SUM(duration_minutes) as total_min FROM study_logs WHERE username = ?", (u,)).fetchone()
        streak = stats["streak_count"] if stats and stats["streak_count"] else 0
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
        ["Dashboard", "Subject Master Plans", "Focus Timer (Pomodoro)", "Analytics & Badges", "Export Plans"],
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
        </div>
        """, unsafe_allow_html=True)
    with m2:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">⏱️ Today's Focus</div>
            <div class="metric-value">{today_min} <span style="font-size: 1rem;">Mins</span></div>
        </div>
        """, unsafe_allow_html=True)
    with m3:
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">📚 Total Study Time</div>
            <div class="metric-value">{round(total_min / 60, 1)} <span style="font-size: 1rem;">Hours</span></div>
        </div>
        """, unsafe_allow_html=True)
    with m4:
        subjects = get_subjects(current_user)
        st.markdown(f"""
        <div class="glass-card">
            <div class="metric-title">🎯 Master Subjects</div>
            <div class="metric-value">{len(subjects)}</div>
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
                            st.rerun()
                
                # Delete Chapter
                if st.button(f"🗑️ Delete Chapter '{chap['name']}'", key=f"del_chap_{chap_id}"):
                    conn = get_db_connection()
                    conn.execute("DELETE FROM chapters WHERE id = ?", (chap_id,))
                    conn.commit()
                    conn.close()
                    st.rerun()

        # Delete Subject
        st.markdown("---")
        if st.button("⚠️ Delete This Entire Subject Master Plan", key=f"del_sub_{active_sub['id']}"):
            conn = get_db_connection()
            conn.execute("DELETE FROM subjects WHERE id = ?", (active_sub["id"],))
            conn.commit()
            conn.close()
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
            sel_sub = st.selectbox("Active Subject", subjects, format_func=lambda s: s["name"])
            chaps = get_chapters(sel_sub["id"])
            all_tasks = []
            for ch in chaps:
                all_tasks.extend(get_tasks(ch["id"]))
            
            sel_task = None
            if all_tasks:
                sel_task = st.selectbox("Target Task (Optional)", [None] + all_tasks,
                                        format_func=lambda t: t["title"] if t else "General Study Session")
            
            # Timer durations
            duration_preset = st.radio("Focus Duration", [25, 50, 15, 5], horizontal=True, format_func=lambda x: f"{x} Mins")
            
            mins = st.session_state.timer_seconds // 60
            secs = st.session_state.timer_seconds % 60
            
            st.markdown(f"""
            <div class="glass-card" style="text-align: center; padding: 2.5rem;">
                <h1 style="font-size: 4.5rem; letter-spacing: 2px; font-variant-numeric: tabular-nums;">
                    {mins:02d}:{secs:02d}
                </h1>
                <p style="color: #94A3B8;">Focus Mode Active • Logged to {current_user}</p>
            </div>
            """, unsafe_allow_html=True)
            
            btn_c1, btn_c2, btn_c3 = st.columns(3)
            with btn_c1:
                if st.button("▶️ Start Session", use_container_width=True):
                    st.session_state.timer_running = True
                    st.session_state.timer_seconds = duration_preset * 60
                    st.session_state.timer_total_duration = duration_preset * 60
                    st.rerun()
            with btn_c2:
                if st.button("⏸️ Pause", use_container_width=True):
                    st.session_state.timer_running = False
            with btn_c3:
                if st.button("⏹️ Log & Finish", use_container_width=True):
                    st.session_state.timer_running = False
                    elapsed_min = max(1, (st.session_state.timer_total_duration - st.session_state.timer_seconds) // 60)
                    log_study_time(sel_sub["id"], sel_task["id"] if sel_task else None, elapsed_min, current_user)
                    st.success(f"Logged {elapsed_min} minutes of focus for {current_user}!")
                    st.session_state.timer_seconds = duration_preset * 60
                    st.rerun()

        with c2:
            st.markdown("### 💡 Focus Tips")
            st.markdown("""
            <div class="glass-card">
                <ul>
                    <li><b>Single Tasking:</b> Focus strictly on your selected checklist item.</li>
                    <li><b>Hydrate:</b> Keep a water bottle within arm's reach.</li>
                    <li><b>Short Breaks:</b> Take a 5-minute break after each 25-minute sprint.</li>
                </ul>
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
    
    streak, total_min, _ = get_streak_and_analytics(current_user)
    hours = round(total_min / 60, 1)
    user_subjects = get_subjects(current_user)
    
    # Personal Badges System
    st.markdown(f"### 🎖️ Your Achievements ({current_user})")
    badges = [
        {"name": "Seedling Scholar", "desc": "Started your first study plan", "unlocked": total_min > 0, "icon": "🌱"},
        {"name": "Consistency Champion", "desc": "Reached a 3-day study streak", "unlocked": streak >= 3, "icon": "🔥"},
        {"name": "Centurion", "desc": "Logged over 10 hours of focus time", "unlocked": hours >= 10, "icon": "🛡️"},
        {"name": "Master Architect", "desc": "Created 3 or more Subject Master Plans", "unlocked": len(user_subjects) >= 3, "icon": "🏛️"}
    ]
    
    b_cols = st.columns(4)
    for idx, b in enumerate(badges):
        with b_cols[idx]:
            opacity = "1.0" if b["unlocked"] else "0.35"
            status_text = "Unlocked ✅" if b["unlocked"] else "Locked 🔒"
            st.markdown(f"""
            <div class="glass-card" style="text-align: center; opacity: {opacity};">
                <div style="font-size: 2.5rem; margin-bottom: 8px;">{b['icon']}</div>
                <strong>{b['name']}</strong>
                <p style="font-size: 0.8rem; color: #94A3B8; margin-top: 4px;">{b['desc']}</p>
                <span style="font-size: 0.75rem; font-weight: 600;">{status_text}</span>
            </div>
            """, unsafe_allow_html=True)

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
