# routes/settings.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from database import query_db, log_and_execute, get_user_widget_layout, default_widget_layouts, get_db_connection, save_user_widget_layout, delete_user_widget_layout
from collections import OrderedDict, defaultdict
import json
import re
import time
from routes.auth import active_sessions
# Import column definitions from other blueprints
from .clients import CLIENTS_COLUMNS
from .assets import ASSETS_COLUMNS
from .contacts import CONTACTS_COLUMNS
from werkzeug.security import generate_password_hash


settings_bp = Blueprint('settings', __name__)

def sanitize_column_name(name):
    """Sanitizes a string to be a valid SQL column name."""
    return 'feature_' + re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))

@settings_bp.route('/save_layout/<page_name>', methods=['POST'])
def save_layout(page_name):
    """Saves the GridStack layout for the current user and page."""
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    layout = request.json.get('layout')
    if not layout:
        return jsonify({'status': 'error', 'message': 'No layout data provided'}), 400

    try:
        save_user_widget_layout(session['user_id'], page_name, layout)
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error saving layout: {e}", file=sys.stderr)
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

@settings_bp.route('/delete_layout/<page_name>', methods=['POST'])
def delete_layout(page_name):
    """Deletes the layout for the current user and page."""
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    try:
        delete_user_widget_layout(session['user_id'], page_name)
        return jsonify({'status': 'success'})
    except Exception as e:
        print(f"Error deleting layout: {e}", file=sys.stderr)
        return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

@settings_bp.route('/save_column_prefs/<page_name>', methods=['POST'])
def save_column_prefs(page_name):
    if page_name not in ['clients', 'assets', 'contacts']:
        return jsonify({'status': 'error', 'message': 'Invalid page name'}), 400

    column_map = {
        'clients': CLIENTS_COLUMNS,
        'assets': ASSETS_COLUMNS,
        'contacts': CONTACTS_COLUMNS
    }

    columns = column_map[page_name]
    prefs = {}
    for col in columns.keys():
        prefs[col] = col in request.form

    session[f'{page_name}_cols'] = prefs
    session.modified = True

    return jsonify({'status': 'success'})

@settings_bp.route('/settings', methods=['GET', 'POST'])
def billing_settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_user':
            username = request.form.get('username')
            role = request.form.get('role')
            if username and role:
                try:
                    # By default, new users have no password and must have it set by an admin.
                    log_and_execute("INSERT INTO app_users (username, role, force_password_reset) VALUES (?, ?, ?)", (username, role, 1))
                    flash(f"User '{username}' added successfully. Please set their initial password.", "success")
                except Exception as e:
                    flash(f"Error adding user: {e}", "error")
            else:
                flash("Username and role are required.", "error")
            return redirect(url_for('settings.billing_settings'))

        elif action == 'save_session_timeout':
            timeout = request.form.get('session_timeout_minutes')
            if timeout and timeout.isdigit():
                log_and_execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", ('session_timeout_minutes', timeout))
                flash("Session timeout updated successfully.", "success")
            else:
                flash("Invalid timeout value.", "error")
            return redirect(url_for('settings.billing_settings'))

        elif action == 'reset_password':
            new_password = request.form.get('new_password')
            confirm_password = request.form.get('confirm_password')
            current_user_id = session.get('user_id')

            if not new_password or not confirm_password:
                flash("Both password fields are required.", "error")
                return redirect(url_for('settings.billing_settings'))

            if new_password != confirm_password:
                flash("Passwords do not match.", "error")
                return redirect(url_for('settings.billing_settings'))

            # This form only allows users to reset their own password.
            password_hash = generate_password_hash(new_password)
            log_and_execute("UPDATE app_users SET password_hash = ?, force_password_reset = 0 WHERE id = ?",
                            (password_hash, current_user_id))
            flash("Your password has been successfully reset.", "success")

            return redirect(url_for('settings.billing_settings'))


    all_plans_raw = query_db("SELECT * FROM billing_plans")
    grouped_plans_unsorted = OrderedDict()
    for plan in all_plans_raw:
        plan_dict = dict(plan)
        plan_name = plan_dict['billing_plan']
        if plan_name not in grouped_plans_unsorted:
            grouped_plans_unsorted[plan_name] = []
        grouped_plans_unsorted[plan_name].append(plan_dict)

    plan_order = [
        'MSP Basic', 'MSP Advanced', 'MSP Premium', 'MSP Platinum',
        'MSP Legacy', 'MSP Network', 'Break Fix', 'Pro Services'
    ]
    grouped_plans = OrderedDict()
    for plan_name in plan_order:
        if plan_name in grouped_plans_unsorted:
            grouped_plans[plan_name] = grouped_plans_unsorted.pop(plan_name)
    for plan_name in sorted(grouped_plans_unsorted.keys()):
        grouped_plans[plan_name] = grouped_plans_unsorted[plan_name]

    scheduler_jobs = query_db("SELECT * FROM scheduler_jobs ORDER BY id")
    app_users = query_db("SELECT * FROM app_users ORDER BY username")
    custom_links = query_db("SELECT * FROM custom_links ORDER BY link_order")

    session_timeout_setting = query_db("SELECT value FROM app_settings WHERE key = 'session_timeout_minutes'", one=True)
    session_timeout_minutes = session_timeout_setting['value'] if session_timeout_setting else 30

    feature_options_raw = query_db("SELECT * FROM feature_options ORDER BY feature_type, option_name")
    feature_options = defaultdict(list)
    feature_types = []
    for option in feature_options_raw:
        feature_options[option['feature_type']].append(dict(option))
        if option['feature_type'] not in feature_types:
            feature_types.append(option['feature_type'])

    layout = get_user_widget_layout(session['user_id'], 'settings')
    default_layout = default_widget_layouts.get('settings')

    return render_template('settings.html',
        grouped_plans=grouped_plans,
        scheduler_jobs=scheduler_jobs,
        app_users=app_users,
        custom_links=custom_links,
        session_timeout_minutes=session_timeout_minutes,
        feature_options=feature_options,
        feature_types=feature_types,
        active_sessions=active_sessions,
        layout=layout,
        default_layout=default_layout
    )

@settings_bp.route('/settings/audit_log')
def view_audit_log():
    audit_logs = query_db("SELECT al.*, au.username FROM audit_log al LEFT JOIN app_users au ON al.user_id = au.id ORDER BY al.timestamp DESC")
    layout = get_user_widget_layout(session['user_id'], 'audit_log')
    return render_template('audit_log.html', audit_logs=audit_logs, layout=layout)

@settings_bp.route('/settings/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if user_id == 1:
        flash("Cannot delete the default Admin user.", "error")
        return redirect(url_for('settings.billing_settings'))
    if user_id == session.get('user_id'):
        flash("You cannot delete the user you are currently logged in as.", "error")
        return redirect(url_for('settings.billing_settings'))

    log_and_execute("DELETE FROM app_users WHERE id = ?", (user_id,))
    flash("User deleted successfully.", "success")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/links/add', methods=['POST'])
def add_link():
    name = request.form.get('name')
    url = request.form.get('url')
    order = request.form.get('order', 0)
    if name and url:
        log_and_execute("INSERT INTO custom_links (name, url, link_order) VALUES (?, ?, ?)", (name, url, order))
        flash("Link added successfully.", "success")
    else:
        flash("Link name and URL are required.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/links/edit/<int:link_id>', methods=['POST'])
def edit_link(link_id):
    name = request.form.get('name')
    url = request.form.get('url')
    order = request.form.get('order', 0)
    if name and url:
        log_and_execute("UPDATE custom_links SET name = ?, url = ?, link_order = ? WHERE id = ?", (name, url, order, link_id))
        flash("Link updated successfully.", "success")
    else:
        flash("Link name and URL are required.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/user/edit/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    # Prevent editing the main Admin user
    if user_id == 1:
        flash("The Admin user cannot be edited.", "error")
        return redirect(url_for('settings.billing_settings'))

    new_username = request.form.get('username')
    new_role = request.form.get('role')
    new_password = request.form.get('new_password')

    # Update username and role
    if new_username and new_role:
        try:
            existing_user = query_db("SELECT id FROM app_users WHERE username = ? AND id != ?", [new_username, user_id], one=True)
            if existing_user:
                flash(f"Username '{new_username}' is already taken.", "error")
            else:
                log_and_execute("UPDATE app_users SET username = ?, role = ? WHERE id = ?", (new_username, new_role, user_id))
                flash("User updated successfully.", "success")
                if session.get('user_id') == user_id:
                    session['username'] = new_username
                    session['role'] = new_role
        except Exception as e:
            flash(f"An error occurred updating user details: {e}", "error")
    else:
        flash("Username and role are required.", "error")

    # Handle password reset by an Admin
    if session.get('role') == 'Admin' and new_password:
        password_hash = generate_password_hash(new_password)
        # Force the user to reset this password on their next login
        log_and_execute("UPDATE app_users SET password_hash = ?, force_password_reset = 1 WHERE id = ?",
                        (password_hash, user_id))
        flash(f"Password for user '{new_username}' has been reset. They will be required to change it on next login.", "success")

    return redirect(url_for('settings.billing_settings'))


@settings_bp.route('/settings/links/delete/<int:link_id>', methods=['POST'])
def delete_link(link_id):
    log_and_execute("DELETE FROM custom_links WHERE id = ?", (link_id,))
    flash("Link deleted successfully.", "success")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/add', methods=['POST'])
def add_feature_option():
    feature_type = request.form.get('feature_type')
    option_name = request.form.get('option_name')
    if feature_type and option_name:
        try:
            log_and_execute("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", (feature_type, option_name))
            flash("Feature option added.", "success")
        except Exception as e:
            flash(f"Could not add option: {e}", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/delete/<int:option_id>', methods=['POST'])
def delete_feature_option(option_id):
    log_and_execute("DELETE FROM feature_options WHERE id = ?", (option_id,))
    flash("Feature option deleted.", "success")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/edit/<int:option_id>', methods=['POST'])
def edit_feature_option(option_id):
    new_name = request.form.get('option_name')
    if new_name:
        try:
            log_and_execute("UPDATE feature_options SET option_name = ? WHERE id = ?", (new_name, option_id))
            flash("Feature option updated.", "success")
        except Exception as e:
            flash(f"Could not update option: {e}", "error")
    else:
        flash("Option name cannot be empty.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/type/add', methods=['POST'])
def add_feature_type():
    feature_type = request.form.get('feature_type')
    if feature_type:
        column_name = sanitize_column_name(feature_type)
        try:
            with get_db_connection(current_app.config['DB_PASSWORD']) as con:
                con.execute(f"ALTER TABLE billing_plans ADD COLUMN {column_name} TEXT DEFAULT 'Not Included'")
                con.execute(f"ALTER TABLE client_billing_overrides ADD COLUMN {column_name} TEXT")
                con.execute(f"ALTER TABLE client_billing_overrides ADD COLUMN override_{column_name}_enabled BOOLEAN DEFAULT 0")
                con.commit()
            log_and_execute("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", (feature_type, 'Not Included'))
            flash("Feature category added.", "success")
        except Exception as e:
            print(f"ERROR adding feature type '{feature_type}': {e}", file=sys.stderr)
            flash(f"Could not add feature category '{feature_type}': {e}", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/type/delete', methods=['POST'])
def delete_feature_type():
    feature_type = request.form.get('feature_type')
    if feature_type:
        # Note: This does not remove the columns from the database tables,
        # as this is not supported by SQLite's ALTER TABLE command.
        # The columns will be ignored by the application logic.
        log_and_execute("DELETE FROM feature_options WHERE feature_type = ?", (feature_type,))
        flash("Feature category deleted. Note: The corresponding columns are not removed from the database, but will be ignored.", "success")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/type/edit', methods=['POST'])
def edit_feature_type():
    original_feature_type = request.form.get('original_feature_type')
    new_feature_type = request.form.get('new_feature_type')
    if original_feature_type and new_feature_type:
        original_column_name = sanitize_column_name(original_feature_type)
        new_column_name = sanitize_column_name(new_feature_type)
        try:
            with get_db_connection(current_app.config['DB_PASSWORD']) as con:
                con.execute(f"ALTER TABLE billing_plans RENAME COLUMN {original_column_name} TO {new_column_name}")
                con.execute(f"ALTER TABLE client_billing_overrides RENAME COLUMN {original_column_name} TO {new_column_name}")
                con.execute(f"ALTER TABLE client_billing_overrides RENAME COLUMN override_{original_column_name}_enabled TO override_{new_column_name}_enabled")
                con.commit()
            log_and_execute("UPDATE feature_options SET feature_type = ? WHERE feature_type = ?", (new_feature_type, original_feature_type))
            flash("Feature category updated.", "success")
        except Exception as e:
            flash(f"Could not update feature category: {e}", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/export')
def export_settings():
    export_data = {
        'companies': [dict(row) for row in query_db("SELECT * FROM companies")],
        'client_locations': [dict(row) for row in query_db("SELECT * FROM client_locations")],
        'app_users': [dict(row) for row in query_db("SELECT * FROM app_users")],
        'billing_plans': [dict(row) for row in query_db("SELECT * FROM billing_plans")],
        'feature_options': [dict(row) for row in query_db("SELECT * FROM feature_options")],
        'custom_links': [dict(row) for row in query_db("SELECT * FROM custom_links")],
        'client_billing_overrides': [dict(row) for row in query_db("SELECT * FROM client_billing_overrides")],
        'asset_billing_overrides': [dict(row) for row in query_db("SELECT * FROM asset_billing_overrides")],
        'user_billing_overrides': [dict(row) for row in query_db("SELECT * FROM user_billing_overrides")],
        'manual_assets': [dict(row) for row in query_db("SELECT * FROM manual_assets")],
        'manual_users': [dict(row) for row in query_db("SELECT * FROM manual_users")],
        'billing_notes': [dict(row) for row in query_db("SELECT * FROM billing_notes")],
        'custom_line_items': [dict(row) for row in query_db("SELECT * FROM custom_line_items")],
    }
    response = jsonify(export_data)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    response.headers['Content-Disposition'] = f'attachment; filename=integodash_settings_export_{timestamp}.json'
    return response

@settings_bp.route('/settings/import', methods=['POST'])
def import_settings():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('settings.billing_settings'))
    file = request.files['file']
    from routes.clients import allowed_file
    if file.filename == '' or not allowed_file(file.filename):
        flash('No selected file or file type not allowed. Must be .json', 'error')
        return redirect(url_for('settings.billing_settings'))
    try:
        import_data = json.load(file)
        tables_to_process = [
            'companies', 'client_locations', 'app_users', 'billing_plans', 'feature_options', 'custom_links',
            'client_billing_overrides', 'asset_billing_overrides', 'user_billing_overrides',
            'manual_assets', 'manual_users', 'billing_notes', 'custom_line_items'
        ]
        for table_name in tables_to_process:
            if table_name in import_data and import_data[table_name]:
                log_and_execute(f"DELETE FROM {table_name};")
                records = import_data[table_name]
                if records:
                    columns = records[0].keys()
                    placeholders = ', '.join(['?'] * len(columns))
                    sql = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"
                    values = [tuple(rec.get(col) for col in columns) for rec in records]
                    for val in values:
                        log_and_execute(sql, val)
        flash('Settings imported successfully! Existing settings have been replaced.', 'success')
    except Exception as e:
        flash(f'An error occurred during import: {e}', 'error')
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/plan/action', methods=['POST'])
def billing_settings_action():
    form_action = request.form.get('form_action')
    plan_name = request.form.get('plan_name')
    if form_action == 'delete':
        log_and_execute("DELETE FROM billing_plans WHERE billing_plan = ?", [plan_name])
        flash(f"Billing plan '{plan_name}' and all its terms have been deleted.", 'success')
    elif form_action == 'save':
        plan_ids = request.form.getlist('plan_ids')
        feature_options_raw = query_db("SELECT DISTINCT feature_type FROM feature_options")
        feature_types = [row['feature_type'] for row in feature_options_raw]

        for plan_id in plan_ids:
            form = request.form

            sql = """
                UPDATE billing_plans SET
                    support_level = ?,
                    per_user_cost = ?, per_workstation_cost = ?, per_server_cost = ?, per_vm_cost = ?,
                    per_switch_cost = ?, per_firewall_cost = ?, per_hour_ticket_cost = ?, backup_base_fee_workstation = ?,
                    backup_base_fee_server = ?, backup_included_tb = ?, backup_per_tb_fee = ?,
            """
            params = [
                form.get(f'support_level_{plan_id}'),
                float(form.get(f'per_user_cost_{plan_id}', 0)),
                float(form.get(f'per_workstation_cost_{plan_id}', 0)),
                float(form.get(f'per_server_cost_{plan_id}', 0)),
                float(form.get(f'per_vm_cost_{plan_id}', 0)),
                float(form.get(f'per_switch_cost_{plan_id}', 0)),
                float(form.get(f'per_firewall_cost_{plan_id}', 0)),
                float(form.get(f'per_hour_ticket_cost_{plan_id}', 0)),
                float(form.get(f'backup_base_fee_workstation_{plan_id}', 0)),
                float(form.get(f'backup_base_fee_server_{plan_id}', 0)),
                float(form.get(f'backup_included_tb_{plan_id}', 0)),
                float(form.get(f'backup_per_tb_fee_{plan_id}', 0)),
            ]

            for feature_type in feature_types:
                column_name = sanitize_column_name(feature_type)
                sql += f"{column_name} = ?, "
                params.append(form.get(f'{column_name}_{plan_id}'))

            sql = sql.rstrip(', ') + " WHERE id = ?"
            params.append(plan_id)

            log_and_execute(sql, tuple(params))

        flash(f"Default plan '{plan_name}' updated successfully!", 'success')
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/plan/add', methods=['POST'])
def add_billing_plan():
    plan_name = request.form.get('new_plan_name')
    if not plan_name:
        flash("New plan name cannot be empty.", 'error')
        return redirect(url_for('settings.billing_settings'))
    if query_db("SELECT 1 FROM billing_plans WHERE billing_plan = ?", [plan_name], one=True):
        flash(f"A plan named '{plan_name}' already exists.", 'error')
        return redirect(url_for('settings.billing_settings'))
    terms = ["Month to Month", "1-Year", "2-Year", "3-Year"]
    for term in terms:
        log_and_execute("INSERT INTO billing_plans (billing_plan, term_length, support_level) VALUES (?, ?, ?)", (plan_name, term, 'Billed Hourly'))
    flash(f"New billing plan '{plan_name}' added with default terms.", 'success')
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/scheduler/update/<int:job_id>', methods=['POST'])
def update_scheduler_job(job_id):
    is_enabled = 1 if 'enabled' in request.form else 0
    interval = int(request.form.get('interval_minutes', 1))
    log_and_execute("UPDATE scheduler_jobs SET enabled = ?, interval_minutes = ? WHERE id = ?", (is_enabled, interval, job_id))
    flash(f"Job {job_id} updated. Restart app for changes to take effect.", 'success')
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/scheduler/run_now/<int:job_id>', methods=['POST'])
def run_now(job_id):
    from main import scheduler
    from scheduler import run_job
    password = current_app.config.get('DB_PASSWORD')
    job = query_db("SELECT script_path FROM scheduler_jobs WHERE id = ?", [job_id], one=True)
    if job and scheduler.running:
        scheduler.add_job(run_job, args=[job_id, job['script_path'], password], id=f"manual_run_{job_id}_{time.time()}", misfire_grace_time=None, coalesce=False)
        flash(f"Job '{job['script_path']}' has been triggered to run now.", 'success')
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/scheduler/log/<int:job_id>')
def get_log(job_id):
    log_data = query_db("SELECT last_run_log FROM scheduler_jobs WHERE id = ?", [job_id], one=True)
    return jsonify({'log': log_data['last_run_log'] if log_data and log_data['last_run_log'] else 'No log found.'})
