import os
import sys
import subprocess
import time
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, g, request, redirect, url_for, flash, session, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from collections import defaultdict, OrderedDict

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
scheduler = BackgroundScheduler()

# --- Helper Function for Template ---
def humanize_time(dt_str):
    """Converts an ISO 8601 string to a human-readable relative time."""
    if not dt_str:
        return "N/A"
    try:
        # Handle timezone-aware strings
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
    except (ValueError, TypeError):
        return dt_str # Return original string if parsing fails

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

# CORRECTED: Register the custom filters with the Jinja2 environment
app.jinja_env.filters['humanize'] = humanize_time
app.jinja_env.filters['days_old'] = days_old


# --- Database Functions ---
def get_db_connection(password):
    if not password: raise ValueError("A database password is required.")
    con = sqlite3.connect(DATABASE, timeout=10)
    con.execute(f"PRAGMA key = '{password}';")
    con.row_factory = sqlite3.Row
    return con

def get_db():
    if not hasattr(g, '_database'):
        password = session.get('db_password')
        if not password: raise ValueError("Database password not found in session.")
        try:
            g._database = get_db_connection(password)
            g._database.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1;")
        except sqlite3.DatabaseError:
            g._database = None
            raise ValueError("Invalid master password.")
    return g._database

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None: db.close()

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

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
                        scheduler.add_job(
                            run_job, 'interval',
                            minutes=job['interval_minutes'],
                            args=[job['id'], job['script_path'], password_attempt],
                            id=str(job['id']),
                            next_run_time=datetime.now() + timedelta(seconds=10)
                        )
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

@app.route('/')
def billing_dashboard():
    try:
        sort_by = request.args.get('sort_by', 'name')
        sort_order = request.args.get('sort_order', 'asc')

        allowed_sort_columns = {
            'name': 'name',
            'billing_plan': 'billing_plan',
            'workstations': 'workstation_count',
            'hosts': 'host_count',
            'vms': 'vm_count',
            'backup': 'total_backup_bytes',
            'users': 'user_count',
            'hours': 'total_hours',
            'bill': 'total_bill'
        }

        if sort_by not in allowed_sort_columns:
            sort_by = 'name'
        if sort_order not in ['asc', 'desc']:
            sort_order = 'asc'

        order_by_clause = f"ORDER BY {allowed_sort_columns[sort_by]} {sort_order.upper()}"

        clients_query = f"""
            WITH monthly_hours AS (
                SELECT
                    company_account_number,
                    SUM(total_hours_spent) as total_hours
                FROM ticket_details
                GROUP BY company_account_number
            ),
            asset_counts AS (
                SELECT
                    company_account_number,
                    COUNT(id) FILTER (WHERE server_type = 'Host') as host_count,
                    COUNT(id) FILTER (WHERE server_type = 'VM') as vm_count,
                    COUNT(id) FILTER (WHERE server_type = 'Computer' OR server_type IS NULL) as workstation_count,
                    SUM(backup_data_bytes) as total_backup_bytes
                FROM assets
                GROUP BY company_account_number
            ),
            user_counts AS (
                SELECT
                    company_account_number,
                    COUNT(id) as user_count
                FROM users
                GROUP BY company_account_number
            )
            SELECT
                c.account_number,
                c.name,
                c.billing_plan,
                COALESCE(ac.workstation_count, 0) as workstation_count,
                COALESCE(ac.host_count, 0) as host_count,
                COALESCE(ac.vm_count, 0) as vm_count,
                COALESCE(ac.total_backup_bytes, 0) as total_backup_bytes,
                COALESCE(uc.user_count, 0) as user_count,
                COALESCE(mh.total_hours, 0) as total_hours,
                (
                    (CASE WHEN override.override_enabled = 1 THEN override.network_management_fee ELSE COALESCE(defaults.network_management_fee, 0.0) END) +
                    (COALESCE(uc.user_count, 0) * (CASE WHEN override.override_enabled = 1 THEN override.per_user_cost ELSE COALESCE(defaults.per_user_cost, 0.0) END)) +
                    (COALESCE(ac.workstation_count, 0) * (CASE WHEN override.override_enabled = 1 THEN override.per_workstation_cost ELSE COALESCE(defaults.per_workstation_cost, 0.0) END)) +
                    (COALESCE(ac.host_count, 0) * (CASE WHEN override.override_enabled = 1 THEN override.per_host_cost ELSE COALESCE(defaults.per_host_cost, 0.0) END)) +
                    (COALESCE(ac.vm_count, 0) * (CASE WHEN override.override_enabled = 1 THEN override.per_vm_cost ELSE COALESCE(defaults.per_vm_cost, 0.0) END)) +
                    (CASE WHEN COALESCE(ac.total_backup_bytes, 0) > 0 THEN (CASE WHEN override.override_enabled = 1 THEN override.backup_base_fee ELSE COALESCE(defaults.backup_base_fee, 0.0) END) ELSE 0 END) +
                    (MAX(0, (COALESCE(ac.total_backup_bytes, 0) / 1099511627776.0) - (CASE WHEN override.override_enabled = 1 THEN override.backup_included_tb ELSE COALESCE(defaults.backup_included_tb, 1.0) END)) * (CASE WHEN override.override_enabled = 1 THEN override.backup_per_tb_fee ELSE COALESCE(defaults.backup_per_tb_fee, 15.0) END))
                ) as total_bill
            FROM companies c
            LEFT JOIN asset_counts ac ON c.account_number = ac.company_account_number
            LEFT JOIN user_counts uc ON c.account_number = uc.company_account_number
            LEFT JOIN monthly_hours mh ON c.account_number = mh.company_account_number
            LEFT JOIN billing_plans defaults ON c.billing_plan = defaults.billing_plan AND c.contract_term_length = defaults.term_length
            LEFT JOIN client_billing_overrides override ON c.account_number = override.company_account_number
            {order_by_clause};
        """

        clients_data = query_db(clients_query)
        return render_template('billing.html', clients=clients_data, sort_by=sort_by, sort_order=sort_order)

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
            nmf = float(request.form.get('network_management_fee', 0))
            puc = float(request.form.get('per_user_cost', 0))
            pwc = float(request.form.get('per_workstation_cost', 0))
            phc = float(request.form.get('per_host_cost', 0))
            pvc = float(request.form.get('per_vm_cost', 0))
            bbf = float(request.form.get('backup_base_fee', 0))
            bit = float(request.form.get('backup_included_tb', 0))
            bpt = float(request.form.get('backup_per_tb_fee', 0))

            db.execute("""
                INSERT INTO client_billing_overrides (company_account_number, network_management_fee, per_user_cost, per_workstation_cost, per_host_cost, per_vm_cost, backup_base_fee, backup_included_tb, backup_per_tb_fee, override_enabled)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_account_number) DO UPDATE SET
                    network_management_fee = excluded.network_management_fee,
                    per_user_cost = excluded.per_user_cost,
                    per_workstation_cost = excluded.per_workstation_cost,
                    per_host_cost = excluded.per_host_cost,
                    per_vm_cost = excluded.per_vm_cost,
                    backup_base_fee = excluded.backup_base_fee,
                    backup_included_tb = excluded.backup_included_tb,
                    backup_per_tb_fee = excluded.backup_per_tb_fee,
                    override_enabled = excluded.override_enabled;
            """, (account_number, nmf, puc, pwc, phc, pvc, bbf, bit, bpt, override_enabled))
            db.commit()
            flash("Client billing settings saved successfully!", 'success')
            return redirect(url_for('client_settings', account_number=account_number))

        client_info = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        if not client_info:
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        effective_plan_query = """
            SELECT
                defaults.network_management_fee as default_nmf,
                defaults.per_user_cost as default_puc,
                defaults.per_workstation_cost as default_pwc,
                defaults.per_host_cost as default_phc,
                defaults.per_vm_cost as default_pvc,
                defaults.backup_base_fee as default_bbf,
                defaults.backup_included_tb as default_bit,
                defaults.backup_per_tb_fee as default_bpt,
                override.network_management_fee as override_nmf,
                override.per_user_cost as override_puc,
                override.per_workstation_cost as override_pwc,
                override.per_host_cost as override_phc,
                override.per_vm_cost as override_pvc,
                override.backup_base_fee as override_bbf,
                override.backup_included_tb as override_bit,
                override.backup_per_tb_fee as override_bpt,
                COALESCE(override.override_enabled, 0) as override_enabled
            FROM companies c
            LEFT JOIN billing_plans defaults ON c.billing_plan = defaults.billing_plan AND c.contract_term_length = defaults.term_length
            LEFT JOIN client_billing_overrides override ON c.account_number = override.company_account_number
            WHERE c.account_number = ?
        """
        plan_details = query_db(effective_plan_query, [account_number], one=True)

        effective_rates = {
            'nmf': plan_details['override_nmf'] if plan_details['override_enabled'] else plan_details['default_nmf'],
            'puc': plan_details['override_puc'] if plan_details['override_enabled'] else plan_details['default_puc'],
            'pwc': plan_details['override_pwc'] if plan_details['override_enabled'] else plan_details['default_pwc'],
            'phc': plan_details['override_phc'] if plan_details['override_enabled'] else plan_details['default_phc'],
            'pvc': plan_details['override_pvc'] if plan_details['override_enabled'] else plan_details['default_pvc'],
            'bbf': plan_details['override_bbf'] if plan_details['override_enabled'] else plan_details['default_bbf'],
            'bit': plan_details['override_bit'] if plan_details['override_enabled'] else plan_details['default_bit'],
            'bpt': plan_details['override_bpt'] if plan_details['override_enabled'] else plan_details['default_bpt'],
        }

        assets = query_db("SELECT *, (backup_data_bytes / 1099511627776.0) as backup_data_tb FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])
        users = query_db("SELECT * FROM users WHERE company_account_number = ? ORDER BY full_name", [account_number])

        user_count = len(users)
        host_count = sum(1 for asset in assets if asset['server_type'] == 'Host')
        vm_count = sum(1 for asset in assets if asset['server_type'] == 'VM')
        workstation_count = len(assets) - host_count - vm_count
        total_backup_bytes = sum(asset['backup_data_bytes'] or 0 for asset in assets)
        total_backup_tb = total_backup_bytes / 1099511627776.0

        backup_charge = 0
        if total_backup_bytes > 0:
            backup_charge += effective_rates['bbf'] or 0
            overage_tb = max(0, total_backup_tb - (effective_rates['bit'] or 0))
            backup_charge += overage_tb * (effective_rates['bpt'] or 0)


        receipt_data = {
            "nmf": effective_rates['nmf'],
            "user_charge": user_count * effective_rates['puc'],
            "workstation_charge": workstation_count * effective_rates['pwc'],
            "host_charge": host_count * effective_rates['phc'],
            "vm_charge": vm_count * effective_rates['pvc'],
            "backup_charge": backup_charge,
            "total": (effective_rates['nmf'] or 0) + (user_count * effective_rates['puc']) + (workstation_count * effective_rates['pwc']) + (host_count * effective_rates['phc']) + (vm_count * effective_rates['pvc']) + backup_charge
        }

        recent_tickets = query_db("SELECT * FROM ticket_details WHERE company_account_number = ? ORDER BY last_updated_at DESC", [account_number])

        return render_template('client_settings.html',
                               client=client_info,
                               assets=assets,
                               users=users,
                               plan_details=plan_details,
                               effective_rates=effective_rates,
                               receipt_data=receipt_data,
                               user_count=user_count,
                               host_count=host_count,
                               vm_count=vm_count,
                               workstation_count=workstation_count,
                               total_backup_tb=total_backup_tb,
                               recent_tickets=recent_tickets)
    except (ValueError, sqlite3.Error) as e:
        session.pop('db_password', None)
        flash(f"Database Error: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
def billing_settings():
    db = get_db()
    if request.method == 'POST':
        plan_id = request.form.get('plan_id')
        nmf = float(request.form.get('network_management_fee', 0))
        puc = float(request.form.get('per_user_cost', 0))
        pwc = float(request.form.get('per_workstation_cost', 0))
        phc = float(request.form.get('per_host_cost', 0))
        pvc = float(request.form.get('per_vm_cost', 0))
        bbf = float(request.form.get('backup_base_fee', 0))
        bit = float(request.form.get('backup_included_tb', 0))
        bpt = float(request.form.get('backup_per_tb_fee', 0))
        db.execute("""
            UPDATE billing_plans SET
                network_management_fee = ?, per_user_cost = ?, per_workstation_cost = ?, per_host_cost = ?, per_vm_cost = ?, backup_base_fee = ?, backup_included_tb = ?, backup_per_tb_fee = ?
            WHERE id = ?
        """, (nmf, puc, pwc, phc, pvc, bbf, bit, bpt, plan_id))
        db.commit()
        flash("Default plan updated successfully!", 'success')
        return redirect(url_for('billing_settings'))

    all_plans_raw = query_db("SELECT * FROM billing_plans ORDER BY billing_plan, term_length")
    grouped_plans = OrderedDict()
    for plan in all_plans_raw:
        if plan['billing_plan'] not in grouped_plans:
            grouped_plans[plan['billing_plan']] = []
        grouped_plans[plan['billing_plan']].append(plan)

    scheduler_jobs = query_db("SELECT * FROM scheduler_jobs ORDER BY id")
    return render_template('settings.html', grouped_plans=grouped_plans, scheduler_jobs=scheduler_jobs)

@app.route('/settings/plan/add', methods=['POST'])
def add_billing_plan():
    db = get_db()
    plan_name = request.form.get('new_plan_name')
    if not plan_name:
        flash("New plan name cannot be empty.", 'error')
        return redirect(url_for('billing_settings'))

    existing = query_db("SELECT 1 FROM billing_plans WHERE billing_plan = ?", [plan_name], one=True)
    if existing:
        flash(f"A plan named '{plan_name}' already exists.", 'error')
        return redirect(url_for('billing_settings'))

    terms = ["Month to Month", "1-Year", "2-Year", "3-Year"]
    new_plan_entries = [(plan_name, term, 0, 0, 0, 0, 0, 0, 30.00, 1.0, 15.00) for term in terms]

    db.executemany("""
        INSERT INTO billing_plans (billing_plan, term_length, network_management_fee, per_user_cost, per_workstation_cost, per_host_cost, per_vm_cost, backup_base_fee, backup_included_tb, backup_per_tb_fee)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, new_plan_entries)
    db.commit()
    flash(f"New billing plan '{plan_name}' added successfully.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/settings/plan/delete', methods=['POST'])
def delete_billing_plan_group():
    db = get_db()
    plan_name = request.form.get('plan_name_to_delete')
    if not plan_name:
        flash("Invalid request to delete a plan.", 'error')
        return redirect(url_for('billing_settings'))

    db.execute("DELETE FROM billing_plans WHERE billing_plan = ?", [plan_name])
    db.commit()
    flash(f"Billing plan '{plan_name}' and all its terms have been deleted.", 'success')
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

        if job and scheduler.running:
            scheduler.add_job(
                run_job,
                args=[job_id, job['script_path'], password],
                id=f"manual_run_{job_id}_{time.time()}",
                misfire_grace_time=None,
                coalesce=False
            )
            flash(f"Job '{job['script_path']}' has been triggered to run now.", 'success')
        elif not scheduler.running:
             flash("Cannot run job: Scheduler is not running.", 'error')
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
    except (ValueError, sqlite3.Error):
        return jsonify({'log': 'Error: Could not access database. Please log in again.'}), 500


if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print(f"Database not found at '{DATABASE}'. Run 'python init_db.py' first.", file=sys.stderr)
        sys.exit(1)

    app.apscheduler = scheduler
    print("--- Starting Flask Web Server ---")
    print("--- Background scheduler will start after first successful login. ---")

    try:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context='adhoc')
    except KeyboardInterrupt:
        print("\n--- Shutting down web server... ---")
    finally:
        if scheduler.running:
            print("--- Shutting down scheduler... ---")
            scheduler.shutdown()
