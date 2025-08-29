# hamnertime/integodash/integodash-fda17dde7f19ded546de5dbffc8ee99ff55ec5f3/database.py
import os
from flask import g, session, request, current_app
from datetime import datetime, timezone
import json

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

DATABASE = 'brainhair.db'

# --- Default Widget Layouts ---
# This dictionary serves as the fallback for any user who has not saved their own layout.
default_widget_layouts = {
    "client_details": [
        {"w": 12, "h": 1, "id": "billing-period-selector-widget", "x": 0, "y": 0},
        {"w": 6, "h": 4, "id": "client-details-widget", "x": 0, "y": 1},
        {"w": 6, "h": 4, "id": "client-features-widget", "x": 6, "y": 1},
        {"w": 6, "h": 2, "id": "locations-widget", "x": 0, "y": 5},
        {"w": 6, "h": 5, "id": "billing-receipt-widget", "x": 6, "y": 5},
        {"w": 6, "h": 3, "id": "contract-details-widget", "x": 0, "y": 7},
        {"w": 6, "h": 4, "id": "notes-widget", "x": 0, "y": 10},
        {"w": 6, "h": 4, "id": "attachments-widget", "x": 6, "y": 10},
        {"w": 12, "h": 3, "id": "tracked-assets-widget", "x": 0, "y": 14},
        {"w": 12, "h": 3, "id": "ticket-breakdown-widget", "x": 0, "y": 17}
    ],
    "client_settings": [
        {"w": 6, "h": 5, "id": "client-details-widget", "x": 0, "y": 0},
        {"x": 6, "w": 6, "h": 5, "id": "contract-details-widget", "y": 0},
        {"y": 5, "w": 12, "h": 7, "id": "billing-overrides-widget", "x": 0},
        {"y": 12, "w": 12, "h": 4, "id": "feature-overrides-widget", "x": 0},
        {"y": 16, "w": 12, "h": 4, "id": "custom-line-items-widget", "x": 0},
        {"x": 0, "y": 20, "w": 6, "h": 4, "id": "add-manual-user-widget"},
        {"y": 20, "w": 6, "h": 4, "id": "add-manual-asset-widget", "x": 6},
        {"y": 24, "w": 12, "h": 3, "id": "user-overrides-widget", "x": 0},
        {"y": 27, "w": 12, "h": 4, "id": "asset-overrides-widget", "x": 0}
    ],
    "clients": [
        {"x": 0, "y": 0, "w": 12, "h": 8, "id": "clients-table-widget"},
        {"w": 12, "h": 2, "id": "export-all-widget", "x": 0, "y": 8}
    ],
    "settings": [
        {"w": 12, "h": 2, "id": "import-export-widget", "x": 0, "y": 0},
        {"x": 0, "w": 12, "h": 4, "id": "scheduler-widget", "y": 2},
        {"y": 6, "w": 12, "h": 7, "id": "users-auditing-widget", "x": 0},
        {"y": 13, "w": 12, "h": 3, "id": "custom-links-widget", "x": 0},
        {"y": 16, "w": 12, "h": 8, "id": "billing-plans-widget", "x": 0},
        {"x": 0, "y": 24, "w": 12, "h": 8, "id": "feature-options-widget"}
    ]
}


def get_db_connection(password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(DATABASE, timeout=10)
    con.execute(f"PRAGMA key = '{password}';")
    con.row_factory = sqlite3.Row
    return con

def get_db():
    """Opens a new database connection if there is none yet for the current application context."""
    if not hasattr(g, '_database'):
        password = current_app.config.get('DB_PASSWORD')
        if not password:
            raise ValueError("Database password not found in app config.")
        try:
            g._database = get_db_connection(password)
            g._database.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1;")
        except sqlite3.DatabaseError:
            g._database = None
            raise ValueError("Invalid master password.")
    return g._database

def close_connection(exception):
    """Closes the database again at the end of the request."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    """Queries the database and returns a list of dictionaries."""
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    if one:
        return rv[0] if rv else None
    return rv

def log_and_execute(query, args=()):
    """Logs and executes a database write operation."""
    db = get_db()
    user_id = session.get('user_id')
    timestamp = datetime.now(timezone.utc).isoformat()

    action = query.strip().split()[0].upper()
    table_name = ''
    if action == 'INSERT':
        table_name = query.strip().split()[2]
    elif action == 'UPDATE':
        table_name = query.strip().split()[1]
    elif action == 'DELETE':
        table_name = query.strip().split()[2]

    record_id = None
    details = f"Query: {query}, Args: {str(args)}"

    try:
        cur = db.execute(query, args)
        db.execute(
            "INSERT INTO audit_log (user_id, timestamp, action, table_name, record_id, details) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, timestamp, action, table_name, record_id, details)
        )
        db.commit()
        return cur
    except Exception as e:
        db.rollback()
        raise e

def log_read_action(action, details=""):
    """Logs a non-modifying action, like a download or export."""
    db = get_db()
    user_id = session.get('user_id')
    timestamp = datetime.now(timezone.utc).isoformat()

    db.execute(
        "INSERT INTO audit_log (user_id, timestamp, action, table_name, details) VALUES (?, ?, ?, ?, ?)",
        (user_id, timestamp, action, 'N/A', details)
    )
    db.commit()

def log_page_view(response):
    """Logs a page view."""
    if 'user_id' in session and request.endpoint not in ['static']:
        db = get_db()
        user_id = session.get('user_id')
        timestamp = datetime.now(timezone.utc).isoformat()
        details = f"Path: {request.path}, Method: {request.method}, Status: {response.status_code}"
        db.execute(
            "INSERT INTO audit_log (user_id, timestamp, action, table_name, details) VALUES (?, ?, ?, ?, ?)",
            (user_id, timestamp, 'PAGE_VIEW', 'N/A', details)
        )
        db.commit()

def get_user_widget_layout(user_id, page_name):
    """
    Fetches the widget layout for a specific user and page.
    If no layout is found for the user, it returns the default layout.
    """
    layout_data = query_db(
        "SELECT layout FROM user_widget_layouts WHERE user_id = ? AND page_name = ?",
        [user_id, page_name],
        one=True
    )
    if layout_data and layout_data['layout']:
        return json.loads(layout_data['layout'])

    # If no user-specific layout is found, return the default for that page
    return default_widget_layouts.get(page_name)


def save_user_widget_layout(user_id, page_name, layout):
    """Saves or updates the widget layout for a specific user and page."""
    layout_json = json.dumps(layout)
    log_and_execute(
        """
        INSERT INTO user_widget_layouts (user_id, page_name, layout)
        VALUES (?, ?, ?)
        ON CONFLICT(user_id, page_name) DO UPDATE SET
            layout = excluded.layout
        """,
        (user_id, page_name, layout_json)
    )

def delete_user_widget_layout(user_id, page_name):
    """Deletes the saved widget layout for a specific user and page."""
    log_and_execute(
        "DELETE FROM user_widget_layouts WHERE user_id = ? AND page_name = ?",
        (user_id, page_name)
    )

def init_app_db(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_connection)
