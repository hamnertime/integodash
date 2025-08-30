# main.py
import os
import sys
from datetime import datetime, timezone, timedelta
from flask import Flask, session, redirect, url_for, request, current_app
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Lock

# Local module imports
from database import init_app_db, log_page_view
from scheduler import run_job
from routes.auth import auth_bp, active_sessions, sessions_lock
from routes.clients import clients_bp
from routes.assets import assets_bp
from routes.contacts import contacts_bp
from routes.settings import settings_bp
from utils import register_template_filters, inject_custom_links

def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.secret_key = 'a_permanent_secret_key_for_production'
    app.config['DB_PASSWORD'] = None
    app.config['UPLOAD_FOLDER'] = 'uploads'

    # Initialize database
    init_app_db(app)

    # Register utilities
    register_template_filters(app)
    app.context_processor(inject_custom_links)

    # Register blueprints with correct URL prefixes
    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp) # Handles root '/' and '/client/*'
    app.register_blueprint(assets_bp, url_prefix='/assets')
    app.register_blueprint(contacts_bp, url_prefix='/contacts')
    app.register_blueprint(settings_bp) # Handles '/settings' and other utility routes

    @app.before_request
    def before_request_tasks():
        session.permanent = False
        if 'user_id' in session:
            with sessions_lock:
                if session['user_id'] in active_sessions:
                    active_sessions[session['user_id']]['last_seen'] = datetime.now(timezone.utc)

        # Allow access to login and static files without authentication
        if request.endpoint and (request.endpoint.startswith('static') or request.endpoint in ['auth.login']):
            return

        if not current_app.config.get('DB_PASSWORD'):
            return redirect(url_for('auth.login'))

        if 'user_id' not in session and request.endpoint != 'auth.select_user':
            return redirect(url_for('auth.select_user'))

    @app.after_request
    def after_request_tasks(response):
        if current_app.config.get('DB_PASSWORD') and 'user_id' in session:
            try:
                # List of endpoints that perform partial page updates via fetch
                exempt_endpoints = [
                    'clients.get_clients_partial', 'clients.get_notes_partial', 'clients.get_attachments_partial',
                    'assets.get_assets_partial', 'contacts.get_contacts_partial',
                    'settings.save_layout', 'settings.get_log'
                ]
                if request.endpoint and request.endpoint not in exempt_endpoints:
                    log_page_view(response)
            except Exception as e:
                print(f"Failed to log page view: {e}", file=sys.stderr)
        return response

    return app

def cleanup_inactive_sessions():
    """Removes users from active_sessions if they haven't been seen recently."""
    now = datetime.now(timezone.utc)
    inactive_threshold = timedelta(minutes=2)
    with sessions_lock:
        inactive_users = [
            user_id for user_id, data in active_sessions.items()
            if now - data.get('last_seen', data['login_time']) > inactive_threshold
        ]
        for user_id in inactive_users:
            print(f"--- Cleaning up inactive session for user ID: {user_id} ---")
            del active_sessions[user_id]

app = create_app()
scheduler = BackgroundScheduler()

if __name__ == '__main__':
    DATABASE = 'brainhair.db'
    UPLOAD_FOLDER = 'uploads'
    STATIC_JS_FOLDER = 'static/js'

    if not os.path.exists(DATABASE):
        print(f"Database not found. Run 'python init_db.py' first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    if not os.path.exists(STATIC_JS_FOLDER):
        os.makedirs(STATIC_JS_FOLDER)

    with app.app_context():
        scheduler.add_job(cleanup_inactive_sessions, 'interval', minutes=1, id='cleanup_sessions')

    print("--- Starting Flask Web Server ---")
    try:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
    finally:
        if scheduler.running:
            print("--- Shutting down scheduler ---")
            scheduler.shutdown()
