# utils.py
import markdown
import bleach
import sys
from datetime import datetime, timezone
from flask import session, current_app, abort
from database import query_db
from urllib.parse import quote_plus
import json
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

def role_required(allowed_roles):
    """
    A decorator to restrict access to routes based on user roles.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'role' not in session or session['role'] not in allowed_roles:
                abort(403)  # Forbidden
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def humanize_time(dt_str):
    if not dt_str: return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return dt_str
    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta.days > 0: return f"{delta.days}d ago"
    if delta.seconds >= 3600: return f"{delta.seconds // 3600}h ago"
    if delta.seconds >= 60: return f"{delta.seconds // 60}m ago"
    return "Just now"

def format_date_usa(date_str):
    """Formats an ISO date string to MM/DD/YYYY format."""
    if not date_str or date_str in ["N/A", "Month to Month", "Invalid Start Date"]:
        return date_str
    try:
        date_obj = datetime.fromisoformat(date_str.split('T')[0])
        return date_obj.strftime('%m/%d/%Y')
    except (ValueError, TypeError):
        return date_str

def filesizeformat(value, binary=False):
    """Formats a file size."""
    if value is None:
        return '0 Bytes'
    return '{:.1f} {}'.format(value / 1024, 'KiB') if value < 1024*1024 else '{:.1f} {}'.format(value / (1024*1024), 'MiB')

def to_markdown(text):
    """Converts a string of text to markdown and sanitizes it."""
    if not text:
        return ""
    allowed_tags = ['p', 'b', 'i', 'strong', 'em', 'br', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'code', 'a', 'blockquote']
    allowed_attrs = {'a': ['href', 'title']}
    html = markdown.markdown(text, extensions=['fenced_code', 'tables'])
    clean_html = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)
    return clean_html

def from_json(json_string):
    """Parses a JSON string into a Python object."""
    if not json_string:
        return None
    try:
        return json.loads(json_string)
    except (json.JSONDecodeError, TypeError):
        return None

def urlencode(text):
    """URL-encodes a string for use in URLs."""
    return quote_plus(text)

def register_template_filters(app):
    app.template_filter('humanize')(humanize_time)
    app.template_filter('usa_date')(format_date_usa)
    app.template_filter('filesizeformat')(filesizeformat)
    app.template_filter('markdown')(to_markdown)
    app.template_filter('urlencode')(urlencode)
    app.template_filter('fromjson')(from_json)

def inject_custom_links():
    if current_app.config.get('DB_PASSWORD') and 'user_id' in session:
        try:
            links = query_db("SELECT * FROM custom_links ORDER BY link_order")
            return dict(custom_links=links)
        except Exception as e:
            print(f"Error fetching custom links for sidebar: {e}", file=sys.stderr)
            return dict(custom_links=[])
    return dict(custom_links=[])
