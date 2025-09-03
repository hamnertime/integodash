# routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from database import query_db, get_db_connection, log_and_execute
from threading import Lock
from datetime import datetime, timezone, timedelta
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint('auth', __name__)

active_sessions = {}
sessions_lock = Lock()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    from main import scheduler # Import here to avoid circular dependency at module level
    if request.method == 'POST':
        password_attempt = request.form.get('password')
        try:
            # Test the password by trying to connect
            with get_db_connection(password_attempt) as con:
                 # Start scheduler only if it's not already running
                if not scheduler.running:
                    print("--- First successful login. Starting background scheduler. ---")
                    jobs = con.execute("SELECT id, script_path, interval_minutes FROM scheduler_jobs WHERE enabled = 1").fetchall()
                    for job in jobs:
                        from scheduler import run_job
                        # Use replace_existing=True to avoid errors on app restart in debug mode
                        scheduler.add_job(run_job, 'interval', minutes=job['interval_minutes'], args=[job['id'], job['script_path'], password_attempt], id=str(job['id']), replace_existing=True, next_run_time=datetime.now() + timedelta(seconds=10))
                    scheduler.start()

            current_app.config['DB_PASSWORD'] = password_attempt
            flash('Database unlocked successfully!', 'success')
            return redirect(url_for('auth.select_user'))
        except (ValueError, Exception):
            flash("Login failed: Invalid master password.", 'error')
    return render_template('login.html')

@auth_bp.route('/select_user', methods=['GET', 'POST'])
def select_user():
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        user = query_db("SELECT * FROM app_users WHERE id = ?", [user_id], one=True)
        if user and user['password_hash'] and check_password_hash(user['password_hash'], password):
            now = datetime.now(timezone.utc)
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['login_time'] = now.isoformat() # Store as string immediately
            session['last_activity'] = now.isoformat() # Set initial activity time

            with sessions_lock:
                active_sessions[user['id']] = {
                    'username': user['username'],
                    'login_time': now, # Keep as datetime object for in-memory display
                    'last_seen': now
                }

            if user['force_password_reset']:
                flash('You must reset your password before continuing.', 'info')
                return redirect(url_for('auth.reset_password'))

            return redirect(url_for('clients.billing_dashboard'))
        else:
            flash("Invalid user or password.", 'error')

    users = query_db("SELECT * FROM app_users ORDER BY username")
    return render_template('user_selection.html', users=users)

@auth_bp.route('/reset_password', methods=['GET', 'POST'])
def reset_password():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if new_password != confirm_password:
            flash('Passwords do not match.', 'error')
        else:
            password_hash = generate_password_hash(new_password)
            log_and_execute("UPDATE app_users SET password_hash = ?, force_password_reset = 0 WHERE id = ?",
                          (password_hash, session['user_id']))
            flash('Password updated successfully. You can now use the dashboard.', 'success')
            return redirect(url_for('clients.billing_dashboard'))

    return render_template('reset_password.html')


@auth_bp.route('/logout')
def logout():
    user_id = session.get('user_id')
    with sessions_lock:
        if user_id in active_sessions:
            del active_sessions[user_id]

    session.clear() # This removes user_id, username, role, login_time, and last_activity
    flash("You have been logged out.", "success")
    return redirect(url_for('auth.select_user'))

