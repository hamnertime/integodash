import os
import sys
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, g, request, redirect, url_for, flash, session, jsonify, Response
from apscheduler.schedulers.background import BackgroundScheduler
from collections import OrderedDict

# Local module imports
from database import init_app_db, get_db, query_db
from scheduler import run_job
from billing import get_billing_dashboard_data, get_client_breakdown_data

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
DATABASE = 'brainhair.db'
scheduler = BackgroundScheduler()

# Initialize database hooks
init_app_db(app)

# --- Helper Function for Template ---
@app.template_filter('humanize')
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
            # Test the connection to validate the password
            from database import get_db_connection
            with get_db_connection(password_attempt) as con:
                if not scheduler.running:
                    print("--- First successful login. Starting background scheduler. ---")
                    jobs = con.execute("SELECT id, script_path, interval_minutes FROM scheduler_jobs WHERE enabled = 1").fetchall()
                    for job in jobs:
                        scheduler.add_job(run_job, 'interval', minutes=job['interval_minutes'], args=[job['id'], job['script_path'], password_attempt], id=str(job['id']), next_run_time=datetime.now() + timedelta(seconds=10))
                    scheduler.start()
            session['db_password'] = password_attempt
            flash('Database unlocked successfully!', 'success')
            return redirect(url_for('billing_dashboard'))
        except (ValueError, Exception):
            flash("Login failed: Invalid master password.", 'error')
    return render_template('login.html')

@app.route('/')
def billing_dashboard():
    try:
        sort_by = request.args.get('sort_by', 'name')
        sort_order = request.args.get('sort_order', 'asc')

        clients_data = get_billing_dashboard_data(sort_by, sort_order)

        return render_template('billing.html', clients=clients_data, sort_by=sort_by, sort_order=sort_order)
    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        flash(f"An error occurred on the dashboard: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/breakdown')
def client_breakdown(account_number):
    try:
        breakdown_data = get_client_breakdown_data(account_number)
        if not breakdown_data.get('client'):
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        return render_template('client_breakdown.html', **breakdown_data)

    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        flash(f"An error occurred on breakdown page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/settings', methods=['GET', 'POST'])
def client_settings(account_number):
    try:
        db = get_db()
        if request.method == 'POST':
            form_data = request.form.to_dict()
            values = {'company_account_number': account_number}

            table_info = query_db("PRAGMA table_info(client_billing_overrides)")
            override_columns = {c['name'] for c in table_info if c['name'] not in ['id', 'company_account_number']}

            for col in override_columns:
                if col.endswith('_enabled'):
                    values[col] = 1 if col in form_data else 0
                elif col in form_data and form_data[col]:
                    if 'count' in col or 'hours' in col:
                        values[col] = int(form_data[col])
                    else:
                        values[col] = float(form_data[col])
                else:
                    values[col] = None

            columns = ', '.join(values.keys())
            placeholders = ', '.join(['?'] * len(values))
            update_setters = ', '.join([f"{key} = excluded.{key}" for key in values if key != 'company_account_number'])

            sql = f"""
                INSERT INTO client_billing_overrides ({columns}) VALUES ({placeholders})
                ON CONFLICT(company_account_number) DO UPDATE SET {update_setters};
            """
            db.execute(sql, list(values.values()))
            db.commit()
            flash("Client override settings saved successfully!", 'success')
            return redirect(url_for('client_settings', account_number=account_number))

        client_info = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        default_plan = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
        overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)
        overrides = dict(overrides_row) if overrides_row else {}


        return render_template('client_settings.html', client=client_info, defaults=default_plan, overrides=overrides)

    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        flash(f"A database or key error occurred on settings page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/settings', methods=['GET'])
def billing_settings():
    all_plans_raw = query_db("SELECT * FROM billing_plans ORDER BY billing_plan, term_length")
    grouped_plans = OrderedDict()
    for plan in all_plans_raw:
        if plan['billing_plan'] not in grouped_plans:
            grouped_plans[plan['billing_plan']] = []
        grouped_plans[plan['billing_plan']].append(dict(plan))

    scheduler_jobs = query_db("SELECT * FROM scheduler_jobs ORDER BY id")
    return render_template('settings.html', grouped_plans=grouped_plans, scheduler_jobs=scheduler_jobs)

@app.route('/settings/plan/action', methods=['POST'])
def billing_settings_action():
    db = get_db()
    form_action = request.form.get('form_action')
    plan_name = request.form.get('plan_name')

    if form_action == 'delete':
        db.execute("DELETE FROM billing_plans WHERE billing_plan = ?", [plan_name])
        db.commit()
        flash(f"Billing plan '{plan_name}' and all its terms have been deleted.", 'success')

    elif form_action == 'save':
        plan_ids = request.form.getlist('plan_ids')
        for plan_id in plan_ids:
            form = request.form
            db.execute("""
                UPDATE billing_plans SET
                    network_management_fee = ?, per_user_cost = ?,
                    per_workstation_cost = ?, per_host_cost = ?, per_vm_cost = ?,
                    per_switch_cost = ?, per_firewall_cost = ?, per_hour_ticket_cost = ?,
                    backup_base_fee_workstation = ?, backup_base_fee_server = ?,
                    backup_included_tb = ?, backup_per_tb_fee = ?
                WHERE id = ?
            """, (
                float(form.get(f'network_management_fee_{plan_id}',0)),
                float(form.get(f'per_user_cost_{plan_id}',0)),
                float(form.get(f'per_workstation_cost_{plan_id}',0)),
                float(form.get(f'per_host_cost_{plan_id}',0)),
                float(form.get(f'per_vm_cost_{plan_id}',0)),
                float(form.get(f'per_switch_cost_{plan_id}',0)),
                float(form.get(f'per_firewall_cost_{plan_id}',0)),
                float(form.get(f'per_hour_ticket_cost_{plan_id}',0)),
                float(form.get(f'backup_base_fee_workstation_{plan_id}',0)),
                float(form.get(f'backup_base_fee_server_{plan_id}',0)),
                float(form.get(f'backup_included_tb_{plan_id}',0)),
                float(form.get(f'backup_per_tb_fee_{plan_id}',0)),
                plan_id
            ))
        db.commit()
        flash(f"Default plan '{plan_name}' updated successfully!", 'success')

    return redirect(url_for('billing_settings'))


@app.route('/settings/plan/add', methods=['POST'])
def add_billing_plan():
    db = get_db()
    plan_name = request.form.get('new_plan_name')
    if not plan_name:
        flash("New plan name cannot be empty.", 'error')
        return redirect(url_for('billing_settings'))

    if query_db("SELECT 1 FROM billing_plans WHERE billing_plan = ?", [plan_name], one=True):
        flash(f"A plan named '{plan_name}' already exists.", 'error')
        return redirect(url_for('billing_settings'))

    terms = ["Month to Month", "1-Year", "2-Year", "3-Year"]
    new_plan_entries = [(plan_name, term) for term in terms]
    db.executemany("""
        INSERT INTO billing_plans (billing_plan, term_length) VALUES (?, ?)
    """, new_plan_entries)
    db.commit()
    flash(f"New billing plan '{plan_name}' added with default terms.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/settings/scheduler/update/<int:job_id>', methods=['POST'])
def update_scheduler_job(job_id):
    db = get_db()
    is_enabled = 1 if 'enabled' in request.form else 0
    interval = int(request.form.get('interval_minutes', 1))
    db.execute("UPDATE scheduler_jobs SET enabled = ?, interval_minutes = ? WHERE id = ?", (is_enabled, interval, job_id))
    db.commit()
    flash(f"Job {job_id} updated. Restart app for changes to take effect.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/scheduler/run_now/<int:job_id>', methods=['POST'])
def run_now(job_id):
    password = session.get('db_password')
    job = query_db("SELECT script_path FROM scheduler_jobs WHERE id = ?", [job_id], one=True)
    if job and scheduler.running:
        scheduler.add_job(run_job, args=[job_id, job['script_path'], password], id=f"manual_run_{job_id}_{time.time()}", misfire_grace_time=None, coalesce=False)
        flash(f"Job '{job['script_path']}' has been triggered to run now.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/scheduler/log/<int:job_id>')
def get_log(job_id):
    log_data = query_db("SELECT last_run_log FROM scheduler_jobs WHERE id = ?", [job_id], one=True)
    return jsonify({'log': log_data['last_run_log'] if log_data and log_data['last_run_log'] else 'No log found.'})


if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print(f"Database not found. Run 'python init_db.py' first.", file=sys.stderr)
        sys.exit(1)

    print("--- Starting Flask Web Server ---")
    try:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
    finally:
        if scheduler.running:
            print("--- Shutting down scheduler ---")
            scheduler.shutdown()
