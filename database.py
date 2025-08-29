# hamnertime/integodash/integodash-fda17dde7f19ded546de5dbffc8ee99ff55ec5f3/database.py
import os
from flask import g, session, request, current_app
from datetime import datetime, timezone

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

DATABASE = 'brainhair.db'

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

def init_app_db(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_connection)
