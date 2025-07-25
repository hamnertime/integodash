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

app.jinja_env.filters['humanize'] = humanize_time


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
    print(f"[{datetime.now()}] SCHEDULER: Running job '{job_id}': {script_path}")
    log_output, status = "", "Failure"
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
        if result.returncode == 0: status = "Success"
        print(f"[{datetime.now()}] SCHEDULER: Finished job '{job_id}' with status: {status}")
    except Exception as e:
        log_output = f"Scheduler failed to run script: {e}"
        print(f"[{datetime.now()}] SCHEDULER: FATAL ERROR running job '{job_id}': {e}", file=sys.stderr)
    finally:
        try:
            with get_db_connection(password) as con:
                con.execute("UPDATE scheduler_jobs SET last_run = ?, last_status = ?, last_run_log = ? WHERE id = ?",
                            (datetime.now().isoformat(timespec='seconds'), status, log_output, job_id))
                con.commit()
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
        except (ValueError, sqlite3.Error):
            flash("Login failed: Invalid master password.", 'error')
    return render_template('login.html')

@app.route('/')
def billing_dashboard():
    try:
        sort_by = request.args.get('sort_by', 'name')
        sort_order = request.args.get('sort_order', 'asc')
        allowed_sort = {'name', 'billing_plan', 'workstations', 'hosts', 'vms', 'backup', 'users', 'hours', 'bill'}
        sort_key = sort_by if sort_by in allowed_sort else 'name'

        clients_raw = query_db("SELECT * FROM companies")
        assets_raw = query_db("SELECT company_account_number, device_type, server_type, backup_data_bytes FROM assets")
        users_raw = query_db("SELECT company_account_number, COUNT(*) as user_count FROM users GROUP BY company_account_number")
        tickets_raw = query_db("SELECT company_account_number, SUM(total_hours_spent) as total_hours FROM ticket_details GROUP BY company_account_number")
        plans_raw = query_db("SELECT * FROM billing_plans")
        overrides_raw = query_db("SELECT * FROM client_billing_overrides")

        plans = {(p['billing_plan'], p['term_length']): p for p in plans_raw}
        overrides = {o['company_account_number']: o for o in overrides_raw}
        users_by_client = {u['company_account_number']: u['user_count'] for u in users_raw}
        hours_by_client = {t['company_account_number']: t['total_hours'] for t in tickets_raw}

        assets_by_client = defaultdict(lambda: {'workstations': 0, 'hosts': 0, 'vms': 0, 'backup_bytes': 0})
        for asset in assets_raw:
            acc_num = asset['company_account_number']
            if asset['server_type'] == 'Host': assets_by_client[acc_num]['hosts'] += 1
            elif asset['server_type'] == 'VM': assets_by_client[acc_num]['vms'] += 1
            else: assets_by_client[acc_num]['workstations'] += 1
            if asset['backup_data_bytes']: assets_by_client[acc_num]['backup_bytes'] += asset['backup_data_bytes']

        clients_data = []
        rate_key_map = {
            'network_management_fee': 'nmf', 'per_user_cost': 'puc', 'per_workstation_cost': 'pwc',
            'per_host_cost': 'phc', 'per_vm_cost': 'pvc', 'per_switch_cost': 'psc', 'per_firewall_cost': 'pfc',
            'backup_base_fee_workstation': 'bbfw', 'backup_base_fee_server': 'bbfs',
            'backup_included_tb': 'bit', 'backup_per_tb_fee': 'bpt'
        }
        for client in clients_raw:
            client_dict = dict(client)
            acc_num = client['account_number']
            client_assets_counts = assets_by_client.get(acc_num, {})
            client_overrides = overrides.get(acc_num)
            default_plan = plans.get((client['billing_plan'], client['contract_term_length']))

            quantities = {
                'users': client_overrides['override_user_count'] if client_overrides and 'override_user_count_enabled' in client_overrides.keys() and client_overrides['override_user_count_enabled'] else users_by_client.get(acc_num, 0),
                'workstations': client_overrides['override_workstation_count'] if client_overrides and 'override_workstation_count_enabled' in client_overrides.keys() and client_overrides['override_workstation_count_enabled'] else client_assets_counts.get('workstations', 0),
                'hosts': client_overrides['override_host_count'] if client_overrides and 'override_host_count_enabled' in client_overrides.keys() and client_overrides['override_host_count_enabled'] else client_assets_counts.get('hosts', 0),
                'vms': client_overrides['override_vm_count'] if client_overrides and 'override_vm_count_enabled' in client_overrides.keys() and client_overrides['override_vm_count_enabled'] else client_assets_counts.get('vms', 0),
                'switches': client_overrides['override_switch_count'] if client_overrides and 'override_switch_count_enabled' in client_overrides.keys() and client_overrides['override_switch_count_enabled'] else 0,
                'firewalls': client_overrides['override_firewall_count'] if client_overrides and 'override_firewall_count_enabled' in client_overrides.keys() and client_overrides['override_firewall_count_enabled'] else 0,
            }
            client_dict.update(quantities)
            client_dict['total_hours'] = hours_by_client.get(acc_num, 0)
            client_dict['total_backup_bytes'] = client_assets_counts.get('backup_bytes', 0)

            rates = {}
            if default_plan:
                for rate_key in default_plan.keys():
                    if rate_key in ['id', 'billing_plan', 'term_length', 'per_server_cost']: continue
                    short_key = rate_key_map.get(rate_key)
                    if not short_key: continue
                    override_key_enabled = f'override_{short_key}_enabled'
                    rates[rate_key] = client_overrides[rate_key] if client_overrides and override_key_enabled in client_overrides.keys() and client_overrides[override_key_enabled] else default_plan[rate_key]


            total_bill = rates.get('network_management_fee', 0) or 0
            total_bill += quantities['users'] * (rates.get('per_user_cost', 0) or 0)
            total_bill += quantities['workstations'] * (rates.get('per_workstation_cost', 0) or 0)
            total_bill += quantities['hosts'] * (rates.get('per_host_cost', 0) or 0)
            total_bill += quantities['vms'] * (rates.get('per_vm_cost', 0) or 0)
            total_bill += quantities['switches'] * (rates.get('per_switch_cost', 0) or 0)
            total_bill += quantities['firewalls'] * (rates.get('per_firewall_cost', 0) or 0)

            total_backup_tb = client_dict['total_backup_bytes'] / 1000000000000.0
            backed_up_assets = query_db("SELECT device_type, server_type FROM assets WHERE company_account_number = ? AND backup_data_bytes > 0", [acc_num])
            backed_up_workstations = sum(1 for a in backed_up_assets if not (a['server_type'] in ('Host', 'VM') or a['device_type'] == 'Server'))
            backed_up_servers = len(backed_up_assets) - backed_up_workstations

            total_included_tb = (backed_up_workstations + backed_up_servers) * (rates.get('backup_included_tb', 1) or 1)
            overage_tb = max(0, total_backup_tb - total_included_tb)
            total_bill += backed_up_workstations * (rates.get('backup_base_fee_workstation', 25) or 25)
            total_bill += backed_up_servers * (rates.get('backup_base_fee_server', 50) or 50)
            total_bill += overage_tb * (rates.get('backup_per_tb_fee', 15) or 15)

            client_dict['total_bill'] = total_bill
            clients_data.append(client_dict)

        sort_map = {'workstations': 'workstations', 'hosts': 'hosts', 'vms': 'vms', 'users': 'users', 'backup': 'total_backup_bytes', 'hours': 'total_hours', 'bill': 'total_bill', 'name': 'name', 'billing_plan': 'billing_plan'}
        sort_column = sort_map.get(sort_key, 'name')
        clients_data.sort(key=lambda x: (x.get(sort_column, 0) is None, x.get(sort_column, 0)), reverse=(sort_order == 'desc'))

        return render_template('billing.html', clients=clients_data, sort_by=sort_key, sort_order=sort_order)

    except (ValueError, sqlite3.Error, KeyError) as e:
        session.pop('db_password', None)
        flash(f"An error occurred on the dashboard: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/breakdown')
def client_breakdown(account_number):
    try:
        client_info = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        if not client_info:
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        assets = query_db("SELECT *, (backup_data_bytes / 1000000000000.0) as backup_data_tb FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])
        users = query_db("SELECT * FROM users WHERE company_account_number = ? ORDER BY full_name", [account_number])
        recent_tickets = query_db("SELECT * FROM ticket_details WHERE company_account_number = ? ORDER BY last_updated_at DESC", [account_number])
        plan_details = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
        overrides = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)

        quantities = {
            'users': overrides['override_user_count'] if overrides and 'override_user_count_enabled' in overrides.keys() and overrides['override_user_count_enabled'] else len(users),
            'workstations': overrides['override_workstation_count'] if overrides and 'override_workstation_count_enabled' in overrides.keys() and overrides['override_workstation_count_enabled'] else sum(1 for a in assets if a['device_type'] == 'Computer' or a['server_type'] is None),
            'hosts': overrides['override_host_count'] if overrides and 'override_host_count_enabled' in overrides.keys() and overrides['override_host_count_enabled'] else sum(1 for a in assets if a['server_type'] == 'Host'),
            'vms': overrides['override_vm_count'] if overrides and 'override_vm_count_enabled' in overrides.keys() and overrides['override_vm_count_enabled'] else sum(1 for a in assets if a['server_type'] == 'VM'),
            'switches': overrides['override_switch_count'] if overrides and 'override_switch_count_enabled' in overrides.keys() and overrides['override_switch_count_enabled'] else 0,
            'firewalls': overrides['override_firewall_count'] if overrides and 'override_firewall_count_enabled' in overrides.keys() and overrides['override_firewall_count_enabled'] else 0,
        }

        rates = {}
        rate_key_map = {
            'network_management_fee': 'nmf', 'per_user_cost': 'puc', 'per_workstation_cost': 'pwc',
            'per_host_cost': 'phc', 'per_vm_cost': 'pvc', 'per_switch_cost': 'psc', 'per_firewall_cost': 'pfc',
            'backup_base_fee_workstation': 'bbfw', 'backup_base_fee_server': 'bbfs',
            'backup_included_tb': 'bit', 'backup_per_tb_fee': 'bpt'
        }
        if plan_details:
            for rate_key in plan_details.keys():
                if rate_key in ['id', 'billing_plan', 'term_length', 'per_server_cost']: continue
                short_key = rate_key_map.get(rate_key)
                if not short_key: continue
                override_key_enabled = f'override_{short_key}_enabled'
                rates[rate_key] = overrides[rate_key] if overrides and override_key_enabled in overrides.keys() and overrides[override_key_enabled] else plan_details[rate_key]


        receipt = {
            'nmf': rates.get('network_management_fee', 0) or 0,
            'user_charge': quantities['users'] * (rates.get('per_user_cost', 0) or 0),
            'workstation_charge': quantities['workstations'] * (rates.get('per_workstation_cost', 0) or 0),
            'host_charge': quantities['hosts'] * (rates.get('per_host_cost', 0) or 0),
            'vm_charge': quantities['vms'] * (rates.get('per_vm_cost', 0) or 0),
            'switch_charge': quantities['switches'] * (rates.get('per_switch_cost', 0) or 0),
            'firewall_charge': quantities['firewalls'] * (rates.get('per_firewall_cost', 0) or 0),
        }

        backed_up_workstations = sum(1 for a in assets if a['backup_data_bytes'] and not (a['server_type'] in ('Host', 'VM') or a['device_type'] == 'Server'))
        backed_up_servers = sum(1 for a in assets if a['backup_data_bytes'] and (a['server_type'] in ('Host', 'VM') or a['device_type'] == 'Server'))
        total_backup_bytes = sum(a['backup_data_bytes'] for a in assets if a['backup_data_bytes'])
        total_backup_tb = total_backup_bytes / 1000000000000.0 if total_backup_bytes else 0

        receipt['backup_base_workstation'] = backed_up_workstations * (rates.get('backup_base_fee_workstation', 25) or 25)
        receipt['backup_base_server'] = backed_up_servers * (rates.get('backup_base_fee_server', 50) or 50)
        receipt['total_included_tb'] = (backed_up_workstations + backed_up_servers) * (rates.get('backup_included_tb', 1) or 1)
        receipt['overage_tb'] = max(0, total_backup_tb - receipt['total_included_tb'])
        receipt['overage_charge'] = receipt['overage_tb'] * (rates.get('backup_per_tb_fee', 15) or 15)

        receipt['backup_charge'] = receipt['backup_base_workstation'] + receipt['backup_base_server'] + receipt['overage_charge']

        receipt['total'] = (
            receipt.get('nmf', 0) +
            receipt.get('user_charge', 0) +
            receipt.get('workstation_charge', 0) +
            receipt.get('host_charge', 0) +
            receipt.get('vm_charge', 0) +
            receipt.get('switch_charge', 0) +
            receipt.get('firewall_charge', 0) +
            receipt.get('backup_charge', 0)
        )

        return render_template('client_breakdown.html',
                               client=client_info, assets=assets, users=users,
                               recent_tickets=recent_tickets, receipt_data=receipt,
                               effective_rates=rates, quantities=quantities,
                               backed_up_workstations=backed_up_workstations,
                               backed_up_servers=backed_up_servers,
                               total_backup_tb=total_backup_tb)

    except (ValueError, sqlite3.Error, KeyError) as e:
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
                    if 'count' in col: values[col] = int(form_data[col])
                    else: values[col] = float(form_data[col])
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
        overrides = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)

        return render_template('client_settings.html', client=client_info, defaults=default_plan, overrides=overrides)

    except (ValueError, sqlite3.Error, KeyError) as e:
        session.pop('db_password', None)
        flash(f"A database or key error occurred on settings page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/settings', methods=['GET', 'POST'])
def billing_settings():
    db = get_db()
    if request.method == 'POST':
        plan_id = request.form.get('plan_id')
        form = request.form
        db.execute("""
            UPDATE billing_plans SET
                network_management_fee = ?, per_user_cost = ?, per_workstation_cost = ?,
                per_host_cost = ?, per_vm_cost = ?, per_switch_cost = ?, per_firewall_cost = ?,
                backup_base_fee_workstation = ?, backup_base_fee_server = ?,
                backup_included_tb = ?, backup_per_tb_fee = ?
            WHERE id = ?
        """, (
            float(form.get('network_management_fee',0)), float(form.get('per_user_cost',0)),
            float(form.get('per_workstation_cost',0)), float(form.get('per_host_cost',0)),
            float(form.get('per_vm_cost',0)), float(form.get('per_switch_cost',0)),
            float(form.get('per_firewall_cost',0)), float(form.get('backup_base_fee_workstation',0)),
            float(form.get('backup_base_fee_server',0)), float(form.get('backup_included_tb',0)),
            float(form.get('backup_per_tb_fee',0)), plan_id
        ))
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

@app.route('/settings/plan/delete', methods=['POST'])
def delete_billing_plan_group():
    db = get_db()
    plan_name = request.form.get('plan_name_to_delete')
    db.execute("DELETE FROM billing_plans WHERE billing_plan = ?", [plan_name])
    db.commit()
    flash(f"Billing plan '{plan_name}' and all its terms have been deleted.", 'success')
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
    log = query_db("SELECT last_run_log FROM scheduler_jobs WHERE id = ?", [job_id], one=True)
    return jsonify({'log': log['last_run_log'] if log and log['last_run_log'] else 'No log found.'})


if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print(f"Database not found. Run 'python init_db.py' first.", file=sys.stderr)
        sys.exit(1)

    app.apscheduler = scheduler
    print("--- Starting Flask Web Server ---")
    try:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
    finally:
        if scheduler.running:
            scheduler.shutdown()
