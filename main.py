# main.py
import os
import sys
from datetime import datetime, timezone, timedelta
from flask import Flask, session, redirect, url_for, request, current_app, flash
from apscheduler.schedulers.background import BackgroundScheduler
from threading import Lock

# Local module imports
from database import init_app_db, log_page_view, query_db
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
    # Set a default session lifetime, will be updated dynamically
    app.permanent_session_lifetime = timedelta(hours=3)


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
        # Make session permanent so its lifetime is controlled by app.permanent_session_lifetime
        # and it will be refreshed on each request.
        session.permanent = True

        # Allow access to login and static files without authentication
        if request.endpoint and (request.endpoint.startswith('static') or request.endpoint in ['auth.login']):
            return

        if not current_app.config.get('DB_PASSWORD'):
            return redirect(url_for('auth.login'))

        # Check if user is logged in first
        if 'user_id' not in session and request.endpoint != 'auth.select_user':
             return redirect(url_for('auth.select_user'))

        # If a user is logged in, perform session checks
        if 'user_id' in session:
            # Dynamically set session lifetime from DB
            timeout_setting = query_db("SELECT value FROM app_settings WHERE key = 'session_timeout_minutes'", one=True)
            timeout_minutes = int(timeout_setting['value']) if timeout_setting and timeout_setting['value'] else 180
            app.permanent_session_lifetime = timedelta(minutes=timeout_minutes)

            # Check for session timeout based on last activity
            if 'last_activity' in session:
                try:
                    # Session stores datetime as an ISO string, so we parse it back
                    last_activity_time = datetime.fromisoformat(session['last_activity'])
                    time_since_activity = datetime.now(timezone.utc) - last_activity_time

                    if time_since_activity > timedelta(minutes=timeout_minutes):
                        user_id_to_logout = session.get('user_id')
                        with sessions_lock:
                            if user_id_to_logout in active_sessions:
                                del active_sessions[user_id_to_logout]
                        session.clear()
                        flash('You have been automatically logged out due to inactivity.', 'info')
                        return redirect(url_for('auth.select_user'))

                    # If the session is valid, update the activity time to now. This resets the timer.
                    session['last_activity'] = datetime.now(timezone.utc).isoformat()

                except (ValueError, TypeError):
                    # If parsing fails for any reason, the session is corrupt. Log out.
                    session.clear()
                    flash('Invalid session. Please select your user again.', 'info')
                    return redirect(url_for('auth.select_user'))
            else:
                # If there's no last_activity, it's an old or invalid session, so log them out
                session.clear()
                flash('Your session has expired. Please select your user again.', 'info')
                return redirect(url_for('auth.select_user'))

            # If session is valid, update last seen time for the "who is online" view
            with sessions_lock:
                if session['user_id'] in active_sessions:
                    active_sessions[session['user_id']]['last_seen'] = datetime.now(timezone.utc)


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

    print("--- Starting Flask Web Server ---")
    try:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
    finally:
        if scheduler.running:
            print("--- Shutting down scheduler ---")
            scheduler.shutdown()

