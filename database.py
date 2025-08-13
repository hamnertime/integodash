import os
from flask import g, session

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
        password = session.get('db_password')
        if not password:
            raise ValueError("Database password not found in session.")
        try:
            g._database = get_db_connection(password)
            # Test the connection with a simple query
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

def init_app_db(app):
    """Register database functions with the Flask app."""
    app.teardown_appcontext(close_connection)
