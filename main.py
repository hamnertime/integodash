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
        today = datetime.now(timezone.utc)
        first_day_of_current_month = today.replace(day=1)
        last_month_date = first_day_of_current_month - timedelta(days=1)

        year = request.args.get('year', default=last_month_date.year, type=int)
        month = request.args.get('month', default=last_month_date.month, type=int)

        breakdown_data = get_client_breakdown_data(account_number, year, month)
        if not breakdown_data.get('client'):
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        month_options = []
        for i in range(12, 0, -1):
             month_options.append({'year': today.year if i <= today.month else today.year -1, 'month': i, 'name': datetime(today.year, i, 1).strftime('%B %Y')})

        selected_billing_period = datetime(year, month, 1).strftime('%B %Y')

        return render_template(
            'client_breakdown.html',
            **breakdown_data,
            selected_year=year,
            selected_month=month,
            month_options=month_options,
            selected_billing_period=selected_billing_period
        )

    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        flash(f"An error occurred on breakdown page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/settings', methods=['GET', 'POST'])
def client_settings(account_number):
    try:
        db = get_db()

        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add_manual_asset':
                db.execute("INSERT INTO manual_assets (company_account_number, hostname, billing_type, custom_cost) VALUES (?, ?, ?, ?)",
                           [account_number, request.form['manual_asset_hostname'], request.form['manual_asset_billing_type'], request.form.get('manual_asset_custom_cost')])
                flash('Manual asset added.', 'success')
            elif action == 'add_manual_user':
                db.execute("INSERT INTO manual_users (company_account_number, full_name, billing_type, custom_cost) VALUES (?, ?, ?, ?)",
                           [account_number, request.form['manual_user_name'], request.form['manual_user_billing_type'], request.form.get('manual_user_custom_cost')])
                flash('Manual user added.', 'success')
            elif action == 'save_overrides':
                # Process rate overrides
                # ... (code from previous version)

                # Process asset overrides
                assets = query_db("SELECT id FROM assets WHERE company_account_number = ?", [account_number])
                for asset in assets:
                    asset_id = asset['id']
                    billing_type = request.form.get(f'asset_billing_type_{asset_id}')
                    custom_cost = request.form.get(f'asset_custom_cost_{asset_id}')
                    if billing_type:
                         db.execute("INSERT INTO asset_billing_overrides (asset_id, billing_type, custom_cost) VALUES (?, ?, ?) ON CONFLICT(asset_id) DO UPDATE SET billing_type=excluded.billing_type, custom_cost=excluded.custom_cost", [asset_id, billing_type, custom_cost if custom_cost else None])
                    else:
                        db.execute("DELETE FROM asset_billing_overrides WHERE asset_id = ?", [asset_id])

                # Process user overrides
                users = query_db("SELECT id FROM users WHERE company_account_number = ?", [account_number])
                for user in users:
                    user_id = user['id']
                    billing_type = request.form.get(f'user_billing_type_{user_id}')
                    custom_cost = request.form.get(f'user_custom_cost_{user_id}')
                    if billing_type:
                        db.execute("INSERT INTO user_billing_overrides (user_id, billing_type, custom_cost) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET billing_type=excluded.billing_type, custom_cost=excluded.custom_cost", [user_id, billing_type, custom_cost if custom_cost else None])
                    else:
                        db.execute("DELETE FROM user_billing_overrides WHERE user_id = ?", [user_id])
                flash("Overrides saved successfully!", 'success')

            db.commit()
            return redirect(url_for('client_settings', account_number=account_number))

        if request.args.get('delete_manual_asset'):
            db.execute("DELETE FROM manual_assets WHERE id = ?", [request.args.get('delete_manual_asset')])
            db.commit()
            flash('Manual asset deleted.', 'success')
            return redirect(url_for('client_settings', account_number=account_number))
        if request.args.get('delete_manual_user'):
            db.execute("DELETE FROM manual_users WHERE id = ?", [request.args.get('delete_manual_user')])
            db.commit()
            flash('Manual user deleted.', 'success')
            return redirect(url_for('client_settings', account_number=account_number))

        # --- Data for GET request ---
        client_info = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        default_plan = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
        overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)

        assets = query_db("SELECT * FROM assets WHERE company_account_number = ?", [account_number])
        users = query_db("SELECT * FROM users WHERE company_account_number = ? AND status = 'Active'", [account_number])
        manual_assets = query_db("SELECT * FROM manual_assets WHERE company_account_number = ?", [account_number])
        manual_users = query_db("SELECT * FROM manual_users WHERE company_account_number = ?", [account_number])

        asset_overrides = {r['asset_id']: dict(r) for r in query_db("SELECT * FROM asset_billing_overrides ao JOIN assets a ON a.id = ao.asset_id WHERE a.company_account_number = ?", [account_number])}
        user_overrides = {r['user_id']: dict(r) for r in query_db("SELECT * FROM user_billing_overrides uo JOIN users u ON u.id = uo.user_id WHERE u.company_account_number = ?", [account_number])}

        return render_template('client_settings.html', client=client_info, defaults=default_plan,
                               overrides=dict(overrides_row) if overrides_row else {},
                               assets=assets, users=users, manual_assets=manual_assets, manual_users=manual_users,
                               asset_overrides=asset_overrides, user_overrides=user_overrides)

    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        flash(f"A database or key error occurred on settings page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

# ... (The rest of the routes remain the same) ...

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
    # ... (code from previous version)
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
    # ... (code from previous version)
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
    # ... (code from previous version)
    db = get_db()
    is_enabled = 1 if 'enabled' in request.form else 0
    interval = int(request.form.get('interval_minutes', 1))
    db.execute("UPDATE scheduler_jobs SET enabled = ?, interval_minutes = ? WHERE id = ?", (is_enabled, interval, job_id))
    db.commit()
    flash(f"Job {job_id} updated. Restart app for changes to take effect.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/scheduler/run_now/<int:job_id>', methods=['POST'])
def run_now(job_id):
    # ... (code from previous version)
    password = session.get('db_password')
    job = query_db("SELECT script_path FROM scheduler_jobs WHERE id = ?", [job_id], one=True)
    if job and scheduler.running:
        scheduler.add_job(run_job, args=[job_id, job['script_path'], password], id=f"manual_run_{job_id}_{time.time()}", misfire_grace_time=None, coalesce=False)
        flash(f"Job '{job['script_path']}' has been triggered to run now.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/scheduler/log/<int:job_id>')
def get_log(job_id):
    # ... (code from previous version)
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
