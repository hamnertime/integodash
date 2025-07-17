import os
import sys
import subprocess
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, g, request, redirect, url_for, flash, session, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from collections import defaultdict

# Use the sqlcipher3 library provided by the wheels package
try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)


# --- Configuration ---
DATABASE = 'brainhair.db'
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Initialize the scheduler, but DO NOT start it yet.
scheduler = BackgroundScheduler()

# --- Helper Function for Template ---
def humanize_time(dt_str):
    """Converts an ISO 8601 string to a human-readable relative time."""
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return dt_str

    now = datetime.now(timezone.utc)
    delta = now - dt

    if delta.days > 0:
        return f"{delta.days}d ago"
    elif delta.seconds >= 3600:
        return f"{delta.seconds // 3600}h ago"
    elif delta.seconds >= 60:
        return f"{delta.seconds // 60}m ago"
    else:
        return "Just now"

def days_old(dt_str):
    """Calculates how many days old a ticket is."""
    if not dt_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return ""

    now = datetime.now(timezone.utc)
    delta = now - dt
    if delta.days == 0:
        return "Today"
    elif delta.days == 1:
        return "1 day old"
    else:
        return f"{delta.days} days old"

# Add the helpers to the Jinja2 environment
app.jinja_env.filters['humanize'] = humanize_time
app.jinja_env.filters['days_old'] = days_old


# --- Database Functions ---
def get_db_connection(password):
    """Connects to the encrypted database with a provided password."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(DATABASE, timeout=10)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    con.row_factory = sqlite3.Row
    return con

def get_db():
    """Connects to the db for a web request, using the password from the session."""
    db = getattr(g, '_database', None)
    if db is None:
        session_password = session.get('db_password')
        if not session_password:
            raise ValueError("Database password not found in session.")

        try:
            db = g._database = get_db_connection(session_password)
            db.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1;")
        except sqlite3.DatabaseError:
            if hasattr(g, '_database') and g._database:
                g._database.close()
            g._database = None
            raise ValueError("Invalid master password.")

    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Scheduler Functions ---
def run_job(job_id, script_path, password):
    """The function executed by the scheduler for each background job."""
    print(f"[{datetime.now()}] SCHEDULER: Running job '{job_id}': {script_path}")
    log_output = ""
    status = "Failure"

    try:
        python_executable = sys.executable
        env = os.environ.copy()
        env['DB_MASTER_PASSWORD'] = password

        result = subprocess.run(
            [python_executable, script_path],
            capture_output=True, text=True, check=False, timeout=600,
            encoding='utf-8', errors='replace', env=env
        )

        log_output = f"--- STDOUT ---\n{result.stdout}\n\n--- STDERR ---\n{result.stderr}"
        if result.returncode == 0:
            status = "Success"

        print(f"--- LOG OUTPUT FOR JOB {job_id}: {script_path} ---")
        print(log_output)
        print(f"--- END LOG FOR JOB {job_id} ---")

        print(f"[{datetime.now()}] SCHEDULER: Finished job '{job_id}' with status: {status}")

    except Exception as e:
        log_output = f"Scheduler failed to run script: {e}"
        print(f"[{datetime.now()}] SCHEDULER: FATAL ERROR running job '{job_id}': {e}", file=sys.stderr)

    finally:
        try:
            con = get_db_connection(password)
            cur = con.cursor()
            cur.execute("""
                UPDATE scheduler_jobs
                SET last_run = ?, last_status = ?, last_run_log = ?
                WHERE id = ?
            """, (datetime.now().isoformat(timespec='seconds'), status, log_output, job_id))
            con.commit()
            con.close()
        except Exception as e:
            print(f"[{datetime.now()}] SCHEDULER: Failed to log job result to DB: {e}", file=sys.stderr)


# --- Web Application Routes ---
@app.before_request
def require_login():
    if 'db_password' not in session and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password_attempt = request.form.get('password')
        try:
            con = get_db_connection(password_attempt)
            if not scheduler.running:
                print("--- First successful login. Starting background scheduler. ---")
                try:
                    jobs = con.execute("SELECT id, script_path, interval_minutes FROM scheduler_jobs WHERE enabled = 1").fetchall()
                    for job in jobs:
                        scheduler.add_job(run_job, 'interval', minutes=job['interval_minutes'], args=[job['id'], job['script_path'], password_attempt], id=str(job['id']), next_run_time=datetime.now() + timedelta(seconds=10))
                    scheduler.start()
                    print("--- Scheduler Started ---")
                except Exception as e:
                    flash(f"Warning: Could not start the background scheduler. Error: {e}", "error")
            con.close()
            session['db_password'] = password_attempt
            flash('Database unlocked successfully!', 'success')
            return redirect(url_for('billing_dashboard'))
        except (ValueError, sqlite3.Error):
            flash(f"Login failed: Invalid master password.", 'error')
    return render_template('login.html')

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

@app.route('/')
def billing_dashboard():
    try:
        clients_query = """
            SELECT
                c.account_number, c.name, c.contract_type, c.billing_plan,
                COUNT(DISTINCT CASE WHEN a.operating_system LIKE '%Server%' THEN a.id END) as server_count,
                COUNT(DISTINCT CASE WHEN a.operating_system NOT LIKE '%Server%' AND a.operating_system IS NOT NULL THEN a.id END) as workstation_count,
                COUNT(DISTINCT u.id) as user_count,
                CASE
                    WHEN bp_client.override_enabled = 1 THEN bp_client.base_price
                    ELSE COALESCE(bp_default.base_price, 0)
                END as base_price,
                CASE
                    WHEN bp_client.override_enabled = 1 THEN bp_client.per_user_cost
                    ELSE COALESCE(bp_default.per_user_cost, 0)
                END as per_user_cost,
                CASE
                    WHEN bp_client.override_enabled = 1 THEN bp_client.per_server_cost
                    ELSE COALESCE(bp_default.per_server_cost, 0)
                END as per_server_cost,
                CASE
                    WHEN bp_client.override_enabled = 1 THEN bp_client.per_workstation_cost
                    ELSE COALESCE(bp_default.per_workstation_cost, 0)
                END as per_workstation_cost,
                CASE
                    WHEN bp_client.override_enabled = 1 THEN bp_client.billed_by
                    ELSE COALESCE(bp_default.billed_by, 'Not Configured')
                END as billed_by
            FROM companies c
            LEFT JOIN assets a ON c.account_number = a.company_account_number
            LEFT JOIN users u ON c.account_number = u.company_account_number
            LEFT JOIN billing_plans bp_client ON c.account_number = bp_client.company_account_number AND c.billing_plan = bp_client.billing_plan
            LEFT JOIN billing_plans bp_default ON bp_default.company_account_number IS NULL AND c.billing_plan = bp_default.billing_plan
            GROUP BY c.account_number ORDER BY c.name ASC;
        """
        clients_data = query_db(clients_query)
        clients_with_totals = []
        for client in clients_data:
            client_dict = dict(client)
            total = client_dict['base_price']
            if client_dict['billed_by'] == 'Per User':
                total += client_dict['user_count'] * client_dict['per_user_cost']
            elif client_dict['billed_by'] == 'Per Device':
                total += (client_dict['workstation_count'] * client_dict['per_workstation_cost'])
                total += (client_dict['server_count'] * client_dict['per_server_cost'])
            client_dict['total_bill'] = total
            clients_with_totals.append(client_dict)
        return render_template('billing.html', clients=clients_with_totals)
    except (ValueError, sqlite3.Error) as e:
        session.pop('db_password', None)
        flash(f"Database Error: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))


@app.route('/client/<account_number>', methods=['GET', 'POST'])
def client_settings(account_number):
    try:
        db = get_db()
        if request.method == 'POST':
            override_enabled = 1 if 'override_enabled' in request.form else 0
            billed_by = request.form.get('billed_by')
            base_price = float(request.form.get('base_price', 0))
            per_user_cost = float(request.form.get('per_user_cost', 0))
            per_server_cost = float(request.form.get('per_server_cost', 0))
            per_workstation_cost = float(request.form.get('per_workstation_cost', 0))

            client_info = query_db("SELECT billing_plan FROM companies WHERE account_number = ?", [account_number], one=True)

            db.execute("""
                INSERT OR REPLACE INTO billing_plans (company_account_number, billing_plan, billed_by, base_price, per_user_cost, per_server_cost, per_workstation_cost, override_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (account_number, client_info['billing_plan'], billed_by, base_price, per_user_cost, per_server_cost, per_workstation_cost, override_enabled))
            db.commit()
            flash("Client billing override saved successfully!", 'success')
            return redirect(url_for('client_settings', account_number=account_number))

        client_info = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        if not client_info:
            flash(f"Client with account number {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        # This query now gets the effective plan, whether it's the client's override or the default
        billing_plan_query = """
            SELECT
                COALESCE(bp_client.billed_by, bp_default.billed_by, 'Per Device') as billed_by,
                COALESCE(bp_client.base_price, bp_default.base_price, 0.0) as base_price,
                COALESCE(bp_client.per_user_cost, bp_default.per_user_cost, 0.0) as per_user_cost,
                COALESCE(bp_client.per_server_cost, bp_default.per_server_cost, 0.0) as per_server_cost,
                COALESCE(bp_client.per_workstation_cost, bp_default.per_workstation_cost, 0.0) as per_workstation_cost,
                bp_client.override_enabled as override_enabled
            FROM companies c
            LEFT JOIN billing_plans bp_client ON c.account_number = bp_client.company_account_number AND c.billing_plan = bp_client.billing_plan
            LEFT JOIN billing_plans bp_default ON bp_default.company_account_number IS NULL AND c.billing_plan = bp_default.billing_plan
            WHERE c.account_number = ?
        """
        billing_plan = query_db(billing_plan_query, [account_number], one=True)

        assets = query_db("SELECT * FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])
        users = query_db("SELECT * FROM users WHERE company_account_number = ? ORDER BY full_name", [account_number])
        ticket_hours = query_db("SELECT * FROM ticket_work_hours WHERE company_account_number = ? ORDER BY month DESC", [account_number])

        return render_template('client_settings.html', client=client_info, assets=assets, users=users, ticket_hours=ticket_hours, billing_plan=billing_plan)
    except (ValueError, sqlite3.Error) as e:
        session.pop('db_password', None)
        flash(f"Database Error: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
def billing_settings():
    try:
        db = get_db()
        if request.method == 'POST':
            plan_id = request.form.get('id')
            billing_plan_name = request.form.get('billing_plan')
            billed_by = request.form.get('billed_by')
            base_price = float(request.form.get('base_price', 0))
            per_user_cost = float(request.form.get('per_user_cost', 0))
            per_server_cost = float(request.form.get('per_server_cost', 0))
            per_workstation_cost = float(request.form.get('per_workstation_cost', 0))

            if plan_id: # Existing plan
                db.execute("""
                    UPDATE billing_plans SET billing_plan = ?, billed_by = ?, base_price = ?, per_user_cost = ?, per_server_cost = ?, per_workstation_cost = ?
                    WHERE id = ? AND company_account_number IS NULL
                """, (billing_plan_name, billed_by, base_price, per_user_cost, per_server_cost, per_workstation_cost, plan_id))
            else: # New plan
                 db.execute("""
                    INSERT INTO billing_plans (company_account_number, billing_plan, billed_by, base_price, per_user_cost, per_server_cost, per_workstation_cost)
                    VALUES (NULL, ?, ?, ?, ?, ?, ?)
                """, (billing_plan_name, billed_by, base_price, per_user_cost, per_server_cost, per_workstation_cost))

            db.commit()
            flash("Default billing plan settings saved successfully!", 'success')
            return redirect(url_for('billing_settings'))

        default_plans = query_db("SELECT * FROM billing_plans WHERE company_account_number IS NULL ORDER BY billing_plan;")
        scheduler_jobs = query_db("SELECT * FROM scheduler_jobs ORDER BY id")
        return render_template('settings.html', all_plans=default_plans, scheduler_jobs=scheduler_jobs)

    except (ValueError, sqlite3.Error) as e:
        session.pop('db_password', None)
        flash(f"Database Error: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/settings/plans/delete/<int:plan_id>', methods=['POST'])
def delete_billing_plan(plan_id):
    try:
        db = get_db()
        db.execute("DELETE FROM billing_plans WHERE id = ? AND company_account_number IS NULL", (plan_id,))
        db.commit()
        flash("Default billing plan deleted.", 'success')
    except (ValueError, sqlite3.Error) as e:
        flash(f"Error deleting plan: {e}", 'error')
    return redirect(url_for('billing_settings'))

@app.route('/settings/scheduler/update/<int:job_id>', methods=['POST'])
def update_scheduler_job(job_id):
    try:
        db = get_db()
        is_enabled = 1 if 'enabled' in request.form else 0
        interval = int(request.form.get('interval_minutes', 1))
        db.execute("UPDATE scheduler_jobs SET enabled = ?, interval_minutes = ? WHERE id = ?", (is_enabled, interval, job_id))
        db.commit()
        flash(f"Job {job_id} updated. Restart the application for changes to take effect.", 'success')
    except (ValueError, sqlite3.Error) as e:
        flash(f"Error updating job: {e}", 'error')
    return redirect(url_for('billing_settings'))

@app.route('/scheduler/run_now/<int:job_id>', methods=['POST'])
def run_now(job_id):
    password = session.get('db_password')
    if not password:
        flash("Session expired. Please log in again.", 'error')
        return redirect(url_for('login'))
    try:
        con = get_db_connection(password)
        job = con.execute("SELECT script_path FROM scheduler_jobs WHERE id = ?", (job_id,)).fetchone()
        con.close()
        if job:
            app.apscheduler.add_job(run_job, args=[job_id, job['script_path'], password], id=f"manual_run_{job_id}_{time.time()}")
            flash(f"Job '{job['script_path']}' has been triggered to run now.", 'success')
        else:
            flash(f"Job ID {job_id} not found.", 'error')
    except Exception as e:
        flash(f"Failed to trigger job: {e}", 'error')
    return redirect(url_for('billing_settings'))

@app.route('/scheduler/log/<int:job_id>')
def get_log(job_id):
    try:
        db = get_db()
        log = db.execute("SELECT last_run_log FROM scheduler_jobs WHERE id = ?", (job_id,)).fetchone()
        if log and log['last_run_log']:
            return jsonify({'log': log['last_run_log']})
        else:
            return jsonify({'log': 'No log found for this job yet.'})
    except (ValueError, sqlite3.Error) as e:
        return jsonify({'log': 'Error: Could not access database. Please log in again.'}), 500

# --- Main Execution Block ---
if __name__ == '__main__':
    if not (os.path.exists('cert.pem') and os.path.exists('key.pem')):
        print("Error: SSL certificate not found. Run 'python generate_cert.py' first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(DATABASE):
        print(f"Error: Database '{DATABASE}' not found. Run 'python init_db.py' first.", file=sys.stderr)
        sys.exit(1)

    app.apscheduler = scheduler
    print("--- Starting Flask Web Server ---")
    print("--- Background scheduler will start after first successful login. ---")
    try:
        app.run(debug=False, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
    except KeyboardInterrupt:
        print("\n--- Shutting down web server and scheduler ---")
    finally:
        if scheduler.running:
            scheduler.shutdown()
