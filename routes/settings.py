# routes/settings.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, current_app
from api_client import api_request
from database import get_user_widget_layout, default_widget_layouts, save_user_widget_layout, delete_user_widget_layout
from collections import OrderedDict, defaultdict
import json
from utils import role_required
# Import column definitions from other blueprints
from .clients import CLIENTS_COLUMNS
from .assets import ASSETS_COLUMNS
from .contacts import CONTACTS_COLUMNS
from .knowledge_base import KB_COLUMNS


settings_bp = Blueprint('settings', __name__)

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
    if page_name not in ['clients', 'assets', 'contacts', 'kb']:
        return jsonify({'status': 'error', 'message': 'Invalid page name'}), 400

    column_map = {
        'clients': CLIENTS_COLUMNS,
        'assets': ASSETS_COLUMNS,
        'contacts': CONTACTS_COLUMNS,
        'kb': KB_COLUMNS
    }

    columns = column_map[page_name]
    prefs = {}
    for col in columns.keys():
        prefs[col] = col in request.form

    session[f'{page_name}_cols'] = prefs
    session.modified = True

    return jsonify({'status': 'success'})

@settings_bp.route('/settings', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def billing_settings():
    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'add_user' and session['role'] == 'Admin':
            username = request.form.get('username')
            role = request.form.get('role')
            if username and role:
                user_data = {"username": username, "role": role}
                response = api_request('post', 'settings/users/', json_data=user_data)
                if response:
                    flash(f"User '{username}' added successfully. Please set their initial password.", "success")
                else:
                    flash("Error adding user via API.", "error")
            else:
                flash("Username and role are required.", "error")
            return redirect(url_for('settings.billing_settings'))

        elif action == 'save_session_timeout' and session['role'] == 'Admin':
            timeout = request.form.get('session_timeout_minutes')
            if timeout and timeout.isdigit():
                if api_request('post', 'settings/app_settings/session_timeout_minutes', json_data={'value': timeout}):
                    flash("Session timeout updated successfully.", "success")
                else:
                    flash("Error updating session timeout via API.", "error")
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

            user_data = {"new_password": new_password}
            if api_request('put', f'settings/users/{current_user_id}/password', json_data=user_data):
                flash("Your password has been successfully reset.", "success")
            else:
                flash("Error resetting password via API.", "error")

            return redirect(url_for('settings.billing_settings'))

    all_plans_raw = api_request('get', 'settings/billing-plans/all')
    grouped_plans_unsorted = defaultdict(list)
    if all_plans_raw:
        for plan in all_plans_raw:
            plan_name = plan['billing_plan']
            grouped_plans_unsorted[plan_name].append(plan)

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

    scheduler_jobs = api_request('get', 'settings/scheduler/jobs')
    app_users = api_request('get', 'settings/users/')
    custom_links = api_request('get', 'settings/links')
    session_timeout_setting = api_request('get', 'settings/app_settings/session_timeout_minutes')
    session_timeout_minutes = session_timeout_setting['value'] if session_timeout_setting else 30

    feature_options_data = api_request('get', 'settings/features/')
    feature_options = feature_options_data if feature_options_data else {}
    feature_types = sorted(feature_options.keys())

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
        layout=layout,
        default_layout=default_layout
    )

@settings_bp.route('/settings/audit_log')
@role_required(['Admin'])
def view_audit_log():
    audit_logs = api_request('get', 'settings/audit-log')
    layout = get_user_widget_layout(session['user_id'], 'audit_log')
    return render_template('audit_log.html', audit_logs=audit_logs, layout=layout)

@settings_bp.route('/settings/delete_user/<int:user_id>', methods=['POST'])
@role_required(['Admin'])
def delete_user(user_id):
    if user_id == 1:
        flash("Cannot delete the default Admin user.", "error")
    elif user_id == session.get('user_id'):
        flash("You cannot delete the user you are currently logged in as.", "error")
    else:
        if api_request('delete', f'settings/users/{user_id}'):
            flash("User deleted successfully.", "success")
        else:
            flash("Error deleting user via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/links/add', methods=['POST'])
@role_required(['Admin', 'Editor'])
def add_link():
    name = request.form.get('name')
    url = request.form.get('url')
    order = request.form.get('order', 0, type=int)
    if name and url:
        link_data = {"name": name, "url": url, "link_order": order}
        if api_request('post', 'settings/links', json_data=link_data):
            flash("Link added successfully.", "success")
        else:
            flash("Error adding link via API.", "error")
    else:
        flash("Link name and URL are required.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/links/edit/<int:link_id>', methods=['POST'])
@role_required(['Admin', 'Editor'])
def edit_link(link_id):
    name = request.form.get('name')
    url = request.form.get('url')
    order = request.form.get('order', 0, type=int)
    if name and url:
        link_data = {"name": name, "url": url, "link_order": order}
        if api_request('put', f'settings/links/{link_id}', json_data=link_data):
            flash("Link updated successfully.", "success")
        else:
            flash("Error updating link via API.", "error")
    else:
        flash("Link name and URL are required.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/user/edit/<int:user_id>', methods=['POST'])
@role_required(['Admin'])
def edit_user(user_id):
    new_username = request.form.get('username')
    new_role = request.form.get('role')
    new_password = request.form.get('new_password')

    user_data = {"username": new_username, "role": new_role}
    if new_password:
        user_data['new_password'] = new_password

    if api_request('put', f'settings/users/{user_id}', json_data=user_data):
        flash("User updated successfully.", "success")
        if session.get('user_id') == user_id:
            session['username'] = new_username
            session['role'] = new_role
    else:
        flash("An error occurred updating user via API.", "error")

    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/links/delete/<int:link_id>', methods=['POST'])
@role_required(['Admin', 'Editor'])
def delete_link(link_id):
    if api_request('delete', f'settings/links/{link_id}'):
        flash("Link deleted successfully.", "success")
    else:
        flash("Error deleting link via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/add', methods=['POST'])
@role_required(['Admin', 'Editor'])
def add_feature_option():
    feature_type = request.form.get('feature_type')
    option_name = request.form.get('option_name')
    if feature_type and option_name:
        feature_data = {"feature_type": feature_type, "option_name": option_name}
        if api_request('post', 'settings/features', json_data=feature_data):
            flash("Feature option added.", "success")
        else:
            flash("Could not add option via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/delete/<int:option_id>', methods=['POST'])
@role_required(['Admin'])
def delete_feature_option(option_id):
    if api_request('delete', f'settings/features/{option_id}'):
        flash("Feature option deleted.", "success")
    else:
        flash("Error deleting option via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/edit/<int:option_id>', methods=['POST'])
@role_required(['Admin', 'Editor'])
def edit_feature_option(option_id):
    new_name = request.form.get('option_name')
    if new_name:
        option_data = {"option_name": new_name}
        if api_request('put', f'settings/features/{option_id}', json_data=option_data):
            flash("Feature option updated.", "success")
        else:
            flash("Could not update option via API.", "error")
    else:
        flash("Option name cannot be empty.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/type/add', methods=['POST'])
@role_required(['Admin'])
def add_feature_type():
    feature_type = request.form.get('feature_type')
    if feature_type:
        feature_data = {"feature_type": feature_type}
        if api_request('post', 'settings/features/types', json_data=feature_data):
            flash("Feature category added.", "success")
        else:
            flash("Could not add feature category via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/type/delete', methods=['POST'])
@role_required(['Admin'])
def delete_feature_type():
    feature_type = request.form.get('feature_type')
    if feature_type:
        if api_request('delete', f'settings/features/types/{feature_type}'):
            flash("Feature category deleted.", "success")
        else:
            flash("Error deleting feature category via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/features/type/edit', methods=['POST'])
@role_required(['Admin'])
def edit_feature_type():
    original_feature_type = request.form.get('original_feature_type')
    new_feature_type = request.form.get('new_feature_type')
    if original_feature_type and new_feature_type:
        feature_data = {"new_feature_type": new_feature_type}
        if api_request('put', f'settings/features/types/{original_feature_type}', json_data=feature_data):
            flash("Feature category updated.", "success")
        else:
            flash("Could not update feature category via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/export')
@role_required(['Admin'])
def export_settings():
    export_data = api_request('get', 'settings/export')
    if not export_data:
        flash("Error exporting settings from API.", "error")
        return redirect(url_for('settings.billing_settings'))

    response = jsonify(export_data)
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    response.headers['Content-Disposition'] = f'attachment; filename=integodash_settings_export_{timestamp}.json'
    return response

@settings_bp.route('/settings/import', methods=['POST'])
@role_required(['Admin'])
def import_settings():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('settings.billing_settings'))

    file = request.files['file']
    from routes.clients import allowed_file
    if file.filename == '' or not allowed_file(file.filename):
        flash('No selected file or file type not allowed. Must be .json', 'error')
        return redirect(url_for('settings.billing_settings'))

    files_data = {'file': (file.filename, file.stream, file.mimetype)}
    if api_request('post', 'settings/import', files=files_data):
        flash('Settings imported successfully! Existing settings have been replaced.', 'success')
    else:
        flash('An error occurred during import via API.', 'error')

    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/plan/action', methods=['POST'])
@role_required(['Admin', 'Editor'])
def billing_settings_action():
    form_action = request.form.get('form_action')
    plan_name = request.form.get('plan_name')

    if form_action == 'delete' and session['role'] == 'Admin':
        if api_request('delete', f'settings/billing-plans/{plan_name}'):
            flash(f"Billing plan '{plan_name}' and all its terms have been deleted.", 'success')
        else:
            flash("Error deleting plan via API.", "error")

    elif form_action == 'save':
        plan_ids = request.form.getlist('plan_ids')
        for plan_id in plan_ids:
            # Gather all form data for the specific plan ID
            plan_data = {
                'support_level': request.form.get(f'support_level_{plan_id}'),
                'per_user_cost': float(request.form.get(f'per_user_cost_{plan_id}', 0)),
                'per_workstation_cost': float(request.form.get(f'per_workstation_cost_{plan_id}', 0)),
                'per_server_cost': float(request.form.get(f'per_server_cost_{plan_id}', 0)),
                'per_vm_cost': float(request.form.get(f'per_vm_cost_{plan_id}', 0)),
                'per_switch_cost': float(request.form.get(f'per_switch_cost_{plan_id}', 0)),
                'per_firewall_cost': float(request.form.get(f'per_firewall_cost_{plan_id}', 0)),
                'per_hour_ticket_cost': float(request.form.get(f'per_hour_ticket_cost_{plan_id}', 0)),
                'backup_base_fee_workstation': float(request.form.get(f'backup_base_fee_workstation_{plan_id}', 0)),
                'backup_base_fee_server': float(request.form.get(f'backup_base_fee_server_{plan_id}', 0)),
                'backup_included_tb': float(request.form.get(f'backup_included_tb_{plan_id}', 0)),
                'backup_per_tb_fee': float(request.form.get(f'backup_per_tb_fee_{plan_id}', 0)),
            }
            # Add dynamic feature columns
            feature_options_data = api_request('get', 'settings/features/')
            if feature_options_data:
                for feature_type in feature_options_data.keys():
                    column_name = sanitize_column_name(feature_type)
                    plan_data[column_name] = request.form.get(f'{column_name}_{plan_id}')

            if not api_request('put', f'settings/billing-plans/{plan_id}', json_data=plan_data):
                flash(f"Error saving plan {plan_id} via API.", 'error')
                return redirect(url_for('settings.billing_settings'))

        flash(f"Default plan '{plan_name}' updated successfully!", 'success')

    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/plan/add', methods=['POST'])
@role_required(['Admin', 'Editor'])
def add_billing_plan():
    plan_name = request.form.get('new_plan_name')
    if not plan_name:
        flash("New plan name cannot be empty.", 'error')
    else:
        plan_data = {"billing_plan": plan_name}
        if api_request('post', 'settings/billing-plans', json_data=plan_data):
            flash(f"New billing plan '{plan_name}' added with default terms.", 'success')
        else:
            flash(f"Error adding new plan '{plan_name}' via API.", 'error')

    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/settings/scheduler/update/<int:job_id>', methods=['POST'])
@role_required(['Admin'])
def update_scheduler_job(job_id):
    is_enabled = 'enabled' in request.form
    interval = request.form.get('interval_minutes', type=int)
    job_data = {"enabled": is_enabled, "interval_minutes": interval}
    if api_request('put', f'settings/scheduler/jobs/{job_id}', json_data=job_data):
        flash(f"Job {job_id} updated. Restart app for changes to take effect.", 'success')
    else:
        flash("Error updating job via API.", "error")
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/scheduler/run_now/<int:job_id>', methods=['POST'])
@role_required(['Admin'])
def run_now(job_id):
    if api_request('post', f'settings/scheduler/run-now/{job_id}'):
        flash(f"Job {job_id} has been triggered to run now.", 'success')
    else:
        flash(f"Error triggering job {job_id} via API.", 'error')
    return redirect(url_for('settings.billing_settings'))

@settings_bp.route('/scheduler/log/<int:job_id>')
@role_required(['Admin'])
def get_log(job_id):
    log_data = api_request('get', f'settings/scheduler/log/{job_id}')
    return jsonify({'log': log_data.get('log', 'No log found.') if log_data else 'Error fetching log.'})
