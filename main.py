# hamnertime/integodash/integodash-da8c97dfedb79ff8b1c5a3267951a55358e6f2a9/main.py
import os
import sys
import time
import uuid
import json
import io
import csv
import zipfile
from datetime import datetime, timedelta, timezone
from flask import Flask, render_template, g, request, redirect, url_for, flash, session, jsonify, Response, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler
from collections import OrderedDict, defaultdict
from werkzeug.utils import secure_filename
import markdown
import bleach
import re

# Local module imports
from database import init_app_db, get_db, query_db, log_and_execute, log_read_action, log_page_view, get_db_connection, set_master_password, get_master_password
from scheduler import run_job
from billing import get_billing_dashboard_data, get_client_breakdown_data

# --- App Configuration ---
app = Flask(__name__)
app.secret_key = os.urandom(24)
DATABASE = 'brainhair.db'
UPLOAD_FOLDER = 'uploads'
STATIC_CSS_FOLDER = 'static/css'
ALLOWED_EXTENSIONS = {'pdf', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'json'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

scheduler = BackgroundScheduler()

# Initialize database hooks
init_app_db(app)

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Helper Functions for Template ---
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

@app.template_filter('filesizeformat')
def filesizeformat(value, binary=False):
    """Formats a file size."""
    if value is None:
        return '0 Bytes'
    return '{:.1f} {}'.format(value / 1024, 'KiB') if value < 1024*1024 else '{:.1f} {}'.format(value / (1024*1024), 'MiB')

@app.template_filter('markdown')
def to_markdown(text):
    """Converts a string of text to markdown and sanitizes it."""
    if not text:
        return ""
    allowed_tags = ['p', 'b', 'i', 'strong', 'em', 'br', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'pre', 'code', 'a', 'blockquote']
    allowed_attrs = {'a': ['href', 'title']}
    html = markdown.markdown(text, extensions=['fenced_code', 'tables'])
    clean_html = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs)
    return clean_html

# --- Context Processors ---
@app.context_processor
def inject_custom_links():
    if get_master_password() and 'user_id' in session:
        try:
            links = query_db("SELECT * FROM custom_links ORDER BY link_order")
            return dict(custom_links=links)
        except Exception:
            return dict(custom_links=[])
    return dict(custom_links=[])

# --- Web Application Routes ---
@app.before_request
def require_login():
    if get_master_password() is None and request.endpoint not in ['login', 'static']:
        return redirect(url_for('login'))
    if 'user_id' not in session and request.endpoint not in ['login', 'select_user', 'static']:
        return redirect(url_for('select_user'))

@app.after_request
def log_request(response):
    if get_master_password() and 'user_id' in session:
        try:
            # Avoid logging the partial fetch requests to keep the audit log clean
            if request.endpoint not in ['get_notes_partial', 'get_attachments_partial']:
                log_page_view(response)
        except Exception as e:
            # This might fail if the DB password is wrong, etc.
            # Don't crash the whole app if logging fails.
            print(f"Failed to log page view: {e}", file=sys.stderr)
    return response

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        password_attempt = request.form.get('password')
        try:
            with get_db_connection(password_attempt) as con:
                set_master_password(password_attempt)
                if not scheduler.running:
                    print("--- First successful login. Starting background scheduler. ---")
                    jobs = con.execute("SELECT id, script_path, interval_minutes FROM scheduler_jobs WHERE enabled = 1").fetchall()
                    for job in jobs:
                        scheduler.add_job(run_job, 'interval', minutes=job['interval_minutes'], args=[job['id'], job['script_path'], get_master_password()], id=str(job['id']), next_run_time=datetime.now() + timedelta(seconds=10))
                    scheduler.start()
            flash('Database unlocked successfully!', 'success')
            return redirect(url_for('select_user'))
        except (ValueError, Exception):
            flash("Login failed: Invalid master password.", 'error')
    return render_template('login.html')

@app.route('/select_user', methods=['GET', 'POST'])
def select_user():
    if get_master_password() is None:
        return redirect(url_for('login'))

    if request.method == 'POST':
        user_id = request.form.get('user_id')
        user = query_db("SELECT * FROM app_users WHERE id = ?", [user_id], one=True)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            return redirect(url_for('billing_dashboard'))
        else:
            flash("Invalid user selected.", 'error')

    users = query_db("SELECT * FROM app_users ORDER BY username")
    return render_template('user_selection.html', users=users)
# ... (the rest of the main.py file remains the same)

@app.route('/logout')
def logout():
    """Logs out the current user and redirects to the user selection screen."""
    session.pop('user_id', None)
    session.pop('username', None)
    flash("You have been logged out.", "success")
    return redirect(url_for('select_user'))

@app.route('/')
def billing_dashboard():
    try:
        clients_data = get_billing_dashboard_data()
        today = datetime.now(timezone.utc)
        month_options = []
        for i in range(1, 13):
            month_options.append({'value': i, 'name': datetime(today.year, i, 1).strftime('%B')})

        return render_template('billing.html', clients=clients_data, month_options=month_options, current_year=today.year)
    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        session.pop('user_id', None)
        session.pop('username', None)
        flash(f"An error occurred on the dashboard: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/notes')
def get_notes_partial(account_number):
    """Renders just the notes section for AJAX updates."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)
    search_query = request.args.get('search_notes', '')

    base_query = "FROM billing_notes WHERE company_account_number = ?"
    params = [account_number]

    if search_query:
        base_query += " AND note_content LIKE ?"
        params.append(f'%{search_query}%')

    notes_count_query = f"SELECT COUNT(*) as count {base_query}"
    notes_count = query_db(notes_count_query, params, one=True)['count']
    total_pages = (notes_count + per_page - 1) // per_page
    offset = (page - 1) * per_page
    notes = query_db(f"SELECT * {base_query} ORDER BY created_at DESC LIMIT ? OFFSET ?", params + [per_page, offset])

    client = query_db("SELECT account_number, name FROM companies WHERE account_number = ?", [account_number], one=True)

    return render_template('partials/notes_section.html',
        client=client,
        notes=notes,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        selected_year=request.args.get('year'),
        selected_month=request.args.get('month'),
        search_query=search_query
    )

@app.route('/client/<account_number>/attachments')
def get_attachments_partial(account_number):
    """Renders just the attachments section for AJAX updates."""
    sort_by = request.args.get('sort_by', 'uploaded_at')
    sort_order = request.args.get('sort_order', 'desc')
    search_query = request.args.get('search', '')
    attachment_page = request.args.get('attachment_page', 1, type=int)
    attachment_per_page = request.args.get('attachment_per_page', 10, type=int)

    base_query = "FROM client_attachments WHERE company_account_number = ?"
    params = [account_number]

    if search_query:
        base_query += " AND (original_filename LIKE ? OR category LIKE ?)"
        params.extend([f'%{search_query}%', f'%{search_query}%'])

    # Validate sort_by to prevent SQL injection
    allowed_sort_columns = ['original_filename', 'category', 'file_size', 'uploaded_at']
    if sort_by not in allowed_sort_columns:
        sort_by = 'uploaded_at'

    # Validate sort_order
    if sort_order not in ['asc', 'desc']:
        sort_order = 'desc'

    attachments_count_query = f"SELECT COUNT(*) as count {base_query}"
    attachments_count = query_db(attachments_count_query, params, one=True)['count']
    attachment_total_pages = (attachments_count + attachment_per_page - 1) // attachment_per_page
    offset = (attachment_page - 1) * attachment_per_page

    attachments_query = f"SELECT * {base_query} ORDER BY {sort_by} {sort_order} LIMIT ? OFFSET ?"
    attachments = query_db(attachments_query, params + [attachment_per_page, offset])

    client = query_db("SELECT account_number FROM companies WHERE account_number = ?", [account_number], one=True)

    return render_template('partials/attachments_section.html',
        client=client,
        attachments=attachments,
        attachment_page=attachment_page,
        attachment_per_page=attachment_per_page,
        attachment_total_pages=attachment_total_pages,
        attachments_count=attachments_count,
        sort_by=sort_by,
        sort_order=sort_order,
        search_query=search_query,
        selected_year=request.args.get('year'),
        selected_month=request.args.get('month')
    )

@app.route('/client/<account_number>/details', methods=['GET', 'POST'])
def client_billing_details(account_number):
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add_note':
                note_content = request.form.get('note_content')
                if note_content:
                    log_and_execute("INSERT INTO billing_notes (company_account_number, note_content, created_at) VALUES (?, ?, ?)",
                               [account_number, note_content, datetime.now(timezone.utc).isoformat()])
                    flash('Note added successfully.', 'success')
                else:
                    flash('Note content cannot be empty.', 'error')
            return redirect(url_for('client_billing_details', account_number=account_number))

        if request.args.get('delete_note'):
            log_and_execute("DELETE FROM billing_notes WHERE id = ?", [request.args.get('delete_note')])
            flash('Note deleted.', 'success')
            return redirect(url_for('client_billing_details', account_number=account_number))

        today = datetime.now(timezone.utc)
        first_day_of_current_month = today.replace(day=1)
        last_month_date = first_day_of_current_month - timedelta(days=1)
        year = request.args.get('year', default=last_month_date.year, type=int)
        month = request.args.get('month', default=last_month_date.month, type=int)

        breakdown_data = get_client_breakdown_data(account_number, year, month)

        if breakdown_data is None:
            client_info = query_db("SELECT name, billing_plan FROM companies WHERE account_number = ?", [account_number], one=True)
            flash(f"The billing plan '{client_info['billing_plan']}' assigned to {client_info['name']} is not configured.", 'error')
            return render_template('unconfigured_plan.html', client=client_info)

        if not breakdown_data.get('client'):
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        # --- PAGINATION AND SEARCH LOGIC FOR NOTES (Initial Load) ---
        page = 1
        per_page = 10
        search_notes_query = ''
        notes_count = query_db("SELECT COUNT(*) as count FROM billing_notes WHERE company_account_number = ?", [account_number], one=True)['count']
        total_pages = (notes_count + per_page - 1) // per_page
        notes = []

        # Attachment sorting, searching, and pagination
        sort_by = 'uploaded_at'
        sort_order = 'desc'
        search_query = ''
        attachment_page = 1
        attachment_per_page = 10
        attachments_count = query_db("SELECT COUNT(*) as count FROM client_attachments WHERE company_account_number = ?", [account_number], one=True)['count']
        attachment_total_pages = (attachments_count + attachment_per_page - 1) // attachment_per_page
        all_attachments = query_db("SELECT * FROM client_attachments WHERE company_account_number = ?", [account_number])


        month_options = []
        for i in range(12, 0, -1):
             month_options.append({'year': today.year if i <= today.month else today.year -1, 'month': i, 'name': datetime(today.year, i, 1).strftime('%B %Y')})
        selected_billing_period = datetime(year, month, 1).strftime('%B %Y')

        return render_template(
            'client_billing_details.html',
            **breakdown_data,
            selected_year=year,
            selected_month=month,
            month_options=month_options,
            selected_billing_period=selected_billing_period,
            notes=notes,
            page=page,
            per_page=per_page,
            total_pages=total_pages,
            search_notes_query=search_notes_query,
            attachments=all_attachments,
            attachment_page=attachment_page,
            attachment_per_page=attachment_per_page,
            attachment_total_pages=attachment_total_pages,
            sort_by=sort_by,
            sort_order=sort_order,
            search_query=search_query
        )
    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        session.pop('user_id', None)
        session.pop('username', None)
        flash(f"An error occurred on details page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/note/<int:note_id>/edit', methods=['GET', 'POST'])
def edit_note(account_number, note_id):
    note = query_db("SELECT * FROM billing_notes WHERE id = ? AND company_account_number = ?", [note_id, account_number], one=True)
    if not note:
        flash("Note not found.", "error")
        return redirect(url_for('client_billing_details', account_number=account_number))
    if request.method == 'POST':
        new_content = request.form.get('note_content')
        if new_content:
            log_and_execute("UPDATE billing_notes SET note_content = ? WHERE id = ?", [new_content, note_id])
            flash("Note updated successfully.", "success")
        else:
            flash("Note content cannot be empty.", "error")
        return redirect(url_for('client_billing_details', account_number=account_number))
    # This part is no longer needed as we are using a modal
    flash("This action should be performed via the modal.", "error")
    return redirect(url_for('client_billing_details', account_number=account_number))

@app.route('/client/<account_number>/edit_line_item/<int:item_id>', methods=['GET', 'POST'])
def edit_line_item(account_number, item_id):
    item = query_db("SELECT * FROM custom_line_items WHERE id = ? AND company_account_number = ?", [item_id, account_number], one=True)
    if not item:
        flash("Line item not found.", "error")
        return redirect(url_for('client_settings', account_number=account_number))

    if request.method == 'POST':
        name = request.form.get('line_item_name')
        item_type = request.form.get('line_item_type')

        # Clear old fee values first
        log_and_execute("UPDATE custom_line_items SET monthly_fee=NULL, one_off_fee=NULL, one_off_year=NULL, one_off_month=NULL, yearly_fee=NULL, yearly_bill_month=NULL, yearly_bill_day=NULL WHERE id = ?", [item_id])

        if item_type == 'recurring':
            fee = request.form.get('line_item_recurring_fee')
            log_and_execute("UPDATE custom_line_items SET name = ?, monthly_fee = ? WHERE id = ?", [name, fee if fee else None, item_id])
        elif item_type == 'one_off':
            fee = request.form.get('line_item_one_off_fee')
            billing_period = request.form.get('line_item_one_off_month')
            year, month = billing_period.split('-')
            log_and_execute("UPDATE custom_line_items SET name = ?, one_off_fee = ?, one_off_year = ?, one_off_month = ? WHERE id = ?", [name, fee if fee else None, int(year), int(month), item_id])
        elif item_type == 'yearly':
            fee = request.form.get('line_item_yearly_fee')
            month = request.form.get('line_item_yearly_month')
            day = request.form.get('line_item_yearly_day')
            log_and_execute("UPDATE custom_line_items SET name = ?, yearly_fee = ?, yearly_bill_month = ?, yearly_bill_day = ? WHERE id = ?", [name, fee if fee else None, int(month), int(day), item_id])

        flash("Line item updated successfully.", "success")
        return redirect(url_for('client_settings', account_number=account_number))

    # This part is no longer needed as we are using a modal
    flash("This action should be performed via the modal.", "error")
    return redirect(url_for('client_settings', account_number=account_number))

@app.route('/client/<account_number>/settings', methods=['GET', 'POST'])
def client_settings(account_number):
    try:
        feature_options_raw = query_db("SELECT * FROM feature_options ORDER BY feature_type, option_name")
        feature_options = defaultdict(list)
        for option in feature_options_raw:
            feature_options[option['feature_type']].append(dict(option))

        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add_manual_asset':
                log_and_execute("INSERT INTO manual_assets (company_account_number, hostname, billing_type, custom_cost) VALUES (?, ?, ?, ?)",
                           [account_number, request.form['manual_asset_hostname'], request.form['manual_asset_billing_type'], request.form.get('manual_asset_custom_cost')])
                flash('Manual asset added.', 'success')
            elif action == 'add_manual_user':
                log_and_execute("INSERT INTO manual_users (company_account_number, full_name, billing_type, custom_cost) VALUES (?, ?, ?, ?)",
                           [account_number, request.form['manual_user_name'], request.form['manual_user_billing_type'], request.form.get('manual_user_custom_cost')])
                flash('Manual user added.', 'success')
            elif action == 'add_line_item':
                item_type = request.form.get('line_item_type')
                name = request.form.get('line_item_name')
                if item_type == 'recurring':
                    fee = request.form.get('line_item_recurring_fee')
                    log_and_execute("INSERT INTO custom_line_items (company_account_number, name, monthly_fee) VALUES (?, ?, ?)", [account_number, name, fee])
                elif item_type == 'one_off':
                    fee = request.form.get('line_item_one_off_fee')
                    billing_period = request.form.get('line_item_one_off_month')
                    year, month = billing_period.split('-')
                    log_and_execute("INSERT INTO custom_line_items (company_account_number, name, one_off_fee, one_off_year, one_off_month) VALUES (?, ?, ?, ?, ?)", [account_number, name, fee, int(year), int(month)])
                elif item_type == 'yearly':
                    fee = request.form.get('line_item_yearly_fee')
                    month = request.form.get('line_item_yearly_month')
                    day = request.form.get('line_item_yearly_day')
                    log_and_execute("INSERT INTO custom_line_items (company_account_number, name, yearly_fee, yearly_bill_month, yearly_bill_day) VALUES (?, ?, ?, ?, ?)", [account_number, name, fee, int(month), int(day)])
                flash('Custom line item added.', 'success')
            elif action == 'add_location':
                location_name = request.form.get('location_name')
                address = request.form.get('address')
                if location_name:
                    log_and_execute("INSERT INTO client_locations (company_account_number, location_name, address) VALUES (?, ?, ?)",
                                   [account_number, location_name, address])
                    flash('Location added successfully.', 'success')
                else:
                    flash('Location Name is required.', 'error')
            elif action == 'save_overrides':
                # Update client details
                phone_number = request.form.get('phone_number')
                client_start_date = request.form.get('client_start_date')
                contract_start_date = request.form.get('contract_start_date')
                contract_term_length = request.form.get('contract_term_length')
                domains = request.form.get('domains')
                company_owner = request.form.get('company_owner')
                business_type = request.form.get('business_type')
                description = request.form.get('description')


                log_and_execute("UPDATE companies SET phone_number = ?, client_start_date = ?, contract_start_date = ?, contract_term_length = ?, domains = ?, company_owner = ?, business_type = ?, description = ? WHERE account_number = ?",
                               [phone_number, client_start_date, contract_start_date, contract_term_length, domains, company_owner, business_type, description, account_number])

                rate_map = {'puc': 'per_user_cost', 'pwc': 'per_workstation_cost', 'psc': 'per_server_cost', 'pvc': 'per_vm_cost', 'pswitchc': 'per_switch_cost', 'pfirewallc': 'per_firewall_cost', 'phtc': 'per_hour_ticket_cost', 'bbfw': 'backup_base_fee_workstation', 'bbfs': 'backup_base_fee_server', 'bit': 'backup_included_tb', 'bpt': 'backup_per_tb_fee', 'prepaid_hours_monthly': 'prepaid_hours_monthly', 'prepaid_hours_yearly': 'prepaid_hours_yearly'}

                # Dynamically build the feature_map
                feature_map = {}
                for feature_type in feature_options.keys():
                    short_name = feature_type.lower().replace(' ', '_')
                    feature_map[short_name] = f'feature_{short_name}'

                columns_to_update, values_to_update = ['company_account_number'], [account_number]

                for short_name, full_name in rate_map.items():
                    columns_to_update.append(full_name)
                    value = request.form.get(full_name)
                    values_to_update.append(float(value) if value else None)
                    columns_to_update.append(f'override_{short_name}_enabled')
                    values_to_update.append(1 if f'override_{short_name}_enabled' in request.form else 0)

                for short_name, full_name in feature_map.items():
                    columns_to_update.append(full_name)
                    value = request.form.get(full_name)
                    values_to_update.append(value if value else None)
                    columns_to_update.append(f'override_feature_{short_name}_enabled')
                    values_to_update.append(1 if f'override_feature_{short_name}_enabled' in request.form else 0)

                placeholders = ', '.join(['?'] * len(columns_to_update))
                update_setters = ', '.join([f"{col}=excluded.{col}" for col in columns_to_update[1:]])
                sql = f"INSERT INTO client_billing_overrides ({', '.join(columns_to_update)}) VALUES ({placeholders}) ON CONFLICT(company_account_number) DO UPDATE SET {update_setters}"
                log_and_execute(sql, values_to_update)
                for asset in query_db("SELECT id FROM assets WHERE company_account_number = ?", [account_number]):
                    asset_id = asset['id']
                    billing_type = request.form.get(f'asset_billing_type_{asset_id}')
                    custom_cost = request.form.get(f'asset_custom_cost_{asset_id}')
                    if billing_type:
                         log_and_execute("INSERT INTO asset_billing_overrides (asset_id, billing_type, custom_cost) VALUES (?, ?, ?) ON CONFLICT(asset_id) DO UPDATE SET billing_type=excluded.billing_type, custom_cost=excluded.custom_cost", [asset_id, billing_type, custom_cost if custom_cost else None])
                    else:
                        log_and_execute("DELETE FROM asset_billing_overrides WHERE asset_id = ?", [asset_id])
                for user in query_db("SELECT id FROM users WHERE company_account_number = ?", [account_number]):
                    user_id = user['id']
                    billing_type = request.form.get(f'user_billing_type_{user_id}')
                    custom_cost = request.form.get(f'user_custom_cost_{user_id}')
                    if billing_type:
                        log_and_execute("INSERT INTO user_billing_overrides (user_id, billing_type, custom_cost) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET billing_type=excluded.billing_type, custom_cost=excluded.custom_cost", [user_id, billing_type, custom_cost if custom_cost else None])
                    else:
                        log_and_execute("DELETE FROM user_billing_overrides WHERE user_id = ?", [user_id])
                flash("Overrides saved successfully!", 'success')
            return redirect(url_for('client_settings', account_number=account_number))
        if request.args.get('delete_manual_asset'):
            log_and_execute("DELETE FROM manual_assets WHERE id = ?", [request.args.get('delete_manual_asset')])
            flash('Manual asset deleted.', 'success')
            return redirect(url_for('client_settings', account_number=account_number))
        if request.args.get('delete_manual_user'):
            log_and_execute("DELETE FROM manual_users WHERE id = ?", [request.args.get('delete_manual_user')])
            flash('Manual user deleted.', 'success')
            return redirect(url_for('client_settings', account_number=account_number))
        if request.args.get('delete_line_item'):
            log_and_execute("DELETE FROM custom_line_items WHERE id = ?", [request.args.get('delete_line_item')])
            flash('Custom line item deleted.', 'success')
            return redirect(url_for('client_settings', account_number=account_number))
        if request.args.get('delete_location'):
            log_and_execute("DELETE FROM client_locations WHERE id = ?", [request.args.get('delete_location')])
            flash('Location deleted.', 'success')
            return redirect(url_for('client_settings', account_number=account_number))

        client_info_raw = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        if not client_info_raw:
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('billing_dashboard'))

        client_info = dict(client_info_raw)

        # Sanitize date formats for the settings page input fields
        for date_field in ['client_start_date', 'contract_start_date']:
            if client_info.get(date_field):
                try:
                    client_info[date_field] = client_info[date_field].split('T')[0]
                except (ValueError, TypeError, IndexError):
                    pass # Keep original if format is unexpected

        locations = query_db("SELECT * FROM client_locations WHERE company_account_number = ?", [account_number])
        default_plan = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
        overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)
        assets = query_db("SELECT * FROM assets WHERE company_account_number = ?", [account_number])
        users = query_db("SELECT * FROM users WHERE company_account_number = ? AND status = 'Active'", [account_number])
        manual_assets = query_db("SELECT * FROM manual_assets WHERE company_account_number = ?", [account_number])
        manual_users = query_db("SELECT * FROM manual_users WHERE company_account_number = ?", [account_number])
        custom_line_items = query_db("SELECT * FROM custom_line_items WHERE company_account_number = ?", [account_number])
        asset_overrides = {r['asset_id']: dict(r) for r in query_db("SELECT * FROM asset_billing_overrides ao JOIN assets a ON a.id = ao.asset_id WHERE a.company_account_number = ?", [account_number])}
        user_overrides = {r['user_id']: dict(r) for r in query_db("SELECT * FROM user_billing_overrides uo JOIN users u ON u.id = uo.user_id WHERE u.company_account_number = ?", [account_number])}
        today = datetime.now(timezone.utc)
        month_options = [{'value': (today + timedelta(days=31*i)).strftime('%Y-%m'), 'name': (today + timedelta(days=31*i)).strftime('%B %Y')} for i in range(12)]

        return render_template('client_settings.html', client=client_info, locations=locations, defaults=default_plan, overrides=dict(overrides_row) if overrides_row else {}, assets=assets, users=users, manual_assets=manual_assets, manual_users=manual_users, custom_line_items=custom_line_items, asset_overrides=asset_overrides, user_overrides=user_overrides, month_options=month_options, feature_options=feature_options)
    except (ValueError, KeyError) as e:
        session.pop('db_password', None)
        session.pop('user_id', None)
        session.pop('username', None)
        flash(f"A database or key error occurred on settings page: {e}. Please log in again.", 'error')
        return redirect(url_for('login'))

@app.route('/client/<account_number>/edit_location/<int:location_id>', methods=['POST'])
def edit_location(account_number, location_id):
    location_name = request.form.get('location_name')
    address = request.form.get('address')
    if location_name:
        log_and_execute("UPDATE client_locations SET location_name = ?, address = ? WHERE id = ? AND company_account_number = ?",
                       [location_name, address, location_id, account_number])
        flash('Location updated successfully.', 'success')
    else:
        flash('Location Name is required.', 'error')
    return redirect(url_for('client_settings', account_number=account_number))

@app.route('/client/<account_number>/edit_manual_asset/<int:asset_id>', methods=['POST'])
def edit_manual_asset(account_number, asset_id):
    hostname = request.form.get('hostname')
    billing_type = request.form.get('billing_type')
    custom_cost = request.form.get('custom_cost')
    if hostname and billing_type:
        log_and_execute("""
            UPDATE manual_assets
            SET hostname = ?, billing_type = ?, custom_cost = ?
            WHERE id = ? AND company_account_number = ?
        """, (hostname, billing_type, custom_cost if custom_cost else None, asset_id, account_number))
        flash('Manual asset updated successfully.', 'success')
    else:
        flash('Hostname and Billing Type are required.', 'error')
    return redirect(url_for('client_settings', account_number=account_number))

@app.route('/client/<account_number>/edit_manual_user/<int:user_id>', methods=['POST'])
def edit_manual_user(account_number, user_id):
    full_name = request.form.get('full_name')
    billing_type = request.form.get('billing_type')
    custom_cost = request.form.get('custom_cost')
    if full_name and billing_type:
        log_and_execute("""
            UPDATE manual_users
            SET full_name = ?, billing_type = ?, custom_cost = ?
            WHERE id = ? AND company_account_number = ?
        """, (full_name, billing_type, custom_cost if custom_cost else None, user_id, account_number))
        flash('Manual user updated successfully.', 'success')
    else:
        flash('Full Name and Billing Type are required.', 'error')
    return redirect(url_for('client_settings', account_number=account_number))

@app.route('/client/<account_number>/upload', methods=['POST'])
def upload_file(account_number):
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('client_billing_details', account_number=account_number))
    file = request.files['file']
    category = request.form.get('category')
    if file.filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('client_billing_details', account_number=account_number))
    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        stored_filename = f"{uuid.uuid4().hex}_{original_filename}"
        client_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], account_number)
        if not os.path.exists(client_upload_dir):
            os.makedirs(client_upload_dir)
        file_path = os.path.join(client_upload_dir, stored_filename)
        file.save(file_path)
        file_size = os.path.getsize(file_path)
        log_and_execute("INSERT INTO client_attachments (company_account_number, original_filename, stored_filename, uploaded_at, file_size, category) VALUES (?, ?, ?, ?, ?, ?)", (account_number, original_filename, stored_filename, datetime.now(timezone.utc).isoformat(), file_size, category))
        flash('File uploaded successfully!', 'success')
    else:
        flash('File type not allowed.', 'error')
    return redirect(url_for('client_billing_details', account_number=account_number))

@app.route('/uploads/<account_number>/<filename>')
def download_file(account_number, filename):
    attachment = query_db("SELECT original_filename FROM client_attachments WHERE stored_filename = ? AND company_account_number = ?", [filename, account_number], one=True)
    if not attachment:
        return "File not found.", 404

    log_read_action(
        action='DOWNLOAD',
        details=f"Downloaded file '{attachment['original_filename']}' for client {account_number}."
    )

    client_upload_dir = os.path.join(app.config['UPLOAD_FOLDER'], account_number)
    return send_from_directory(client_upload_dir, filename, as_attachment=True, download_name=attachment['original_filename'])

@app.route('/client/<account_number>/delete_attachment/<int:attachment_id>')
def delete_attachment(account_number, attachment_id):
    attachment = query_db("SELECT stored_filename FROM client_attachments WHERE id = ? AND company_account_number = ?", [attachment_id, account_number], one=True)
    if attachment:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], account_number, attachment['stored_filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
        log_and_execute("DELETE FROM client_attachments WHERE id = ?", [attachment_id])
        flash("Attachment deleted successfully.", 'success')
    else:
        flash("Attachment not found.", 'error')
    return redirect(url_for('client_billing_details', account_number=account_number))

@app.route('/client/<account_number>/edit_attachment/<int:attachment_id>', methods=['POST'])
def edit_attachment(account_number, attachment_id):
    original_filename = request.form.get('original_filename')
    category = request.form.get('category')
    if original_filename:
        log_and_execute("UPDATE client_attachments SET original_filename = ?, category = ? WHERE id = ? AND company_account_number = ?",
                       [original_filename, category, attachment_id, account_number])
        flash('Attachment updated successfully.', 'success')
    else:
        flash('Filename cannot be empty.', 'error')
    return redirect(url_for('client_billing_details', account_number=account_number))

@app.route('/settings', methods=['GET', 'POST'])
def billing_settings():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_user':
            username = request.form.get('username')
            if username:
                try:
                    log_and_execute("INSERT INTO app_users (username) VALUES (?)", (username,))
                    flash(f"User '{username}' added successfully.", "success")
                except Exception as e:
                    flash(f"Error adding user: {e}", "error")
            else:
                flash("Username cannot be empty.", "error")
            return redirect(url_for('billing_settings'))

    all_plans_raw = query_db("SELECT * FROM billing_plans ORDER BY billing_plan, term_length")
    grouped_plans = OrderedDict()
    for plan in all_plans_raw:
        if plan['billing_plan'] not in grouped_plans:
            grouped_plans[plan['billing_plan']] = []
        grouped_plans[plan['billing_plan']].append(dict(plan))

    scheduler_jobs = query_db("SELECT * FROM scheduler_jobs ORDER BY id")
    app_users = query_db("SELECT * FROM app_users ORDER BY username")
    custom_links = query_db("SELECT * FROM custom_links ORDER BY link_order")

    feature_options_raw = query_db("SELECT * FROM feature_options ORDER BY feature_type, option_name")
    feature_options = defaultdict(list)
    feature_types = []
    for option in feature_options_raw:
        feature_options[option['feature_type']].append(dict(option))
        if option['feature_type'] not in feature_types:
            feature_types.append(option['feature_type'])

    return render_template('settings.html',
        grouped_plans=grouped_plans,
        scheduler_jobs=scheduler_jobs,
        app_users=app_users,
        custom_links=custom_links,
        feature_options=feature_options,
        feature_types=feature_types
    )

@app.route('/settings/audit_log')
def view_audit_log():
    audit_logs = query_db("SELECT al.*, au.username FROM audit_log al LEFT JOIN app_users au ON al.user_id = au.id ORDER BY al.timestamp DESC")
    return render_template('audit_log.html', audit_logs=audit_logs)

@app.route('/settings/delete_user/<int:user_id>', methods=['POST'])
def delete_user(user_id):
    if user_id == 1:
        flash("Cannot delete the default Admin user.", "error")
        return redirect(url_for('billing_settings'))
    if user_id == session.get('user_id'):
        flash("You cannot delete the user you are currently logged in as.", "error")
        return redirect(url_for('billing_settings'))

    log_and_execute("DELETE FROM app_users WHERE id = ?", (user_id,))
    flash("User deleted successfully.", "success")
    return redirect(url_for('billing_settings'))

@app.route('/settings/links/add', methods=['POST'])
def add_link():
    name = request.form.get('name')
    url = request.form.get('url')
    order = request.form.get('order', 0)
    if name and url:
        log_and_execute("INSERT INTO custom_links (name, url, link_order) VALUES (?, ?, ?)", (name, url, order))
        flash("Link added successfully.", "success")
    else:
        flash("Link name and URL are required.", "error")
    return redirect(url_for('billing_settings'))

@app.route('/settings/links/edit/<int:link_id>', methods=['POST'])
def edit_link(link_id):
    name = request.form.get('name')
    url = request.form.get('url')
    order = request.form.get('order', 0)
    if name and url:
        log_and_execute("UPDATE custom_links SET name = ?, url = ?, link_order = ? WHERE id = ?", (name, url, order, link_id))
        flash("Link updated successfully.", "success")
    else:
        flash("Link name and URL are required.", "error")
    return redirect(url_for('billing_settings'))

@app.route('/settings/user/edit/<int:user_id>', methods=['POST'])
def edit_user(user_id):
    if user_id == 1:
        flash("The Admin user cannot be edited.", "error")
        return redirect(url_for('billing_settings'))

    new_username = request.form.get('username')
    if new_username:
        try:
            existing_user = query_db("SELECT id FROM app_users WHERE username = ? AND id != ?", [new_username, user_id], one=True)
            if existing_user:
                flash(f"Username '{new_username}' is already taken.", "error")
            else:
                log_and_execute("UPDATE app_users SET username = ? WHERE id = ?", (new_username, user_id))
                flash("Username updated successfully.", "success")
                if session.get('user_id') == user_id:
                    session['username'] = new_username
        except Exception as e:
            flash(f"An error occurred: {e}", "error")
    else:
        flash("Username cannot be empty.", "error")
    return redirect(url_for('billing_settings'))

@app.route('/settings/links/delete/<int:link_id>', methods=['POST'])
def delete_link(link_id):
    log_and_execute("DELETE FROM custom_links WHERE id = ?", (link_id,))
    flash("Link deleted successfully.", "success")
    return redirect(url_for('billing_settings'))

def sanitize_column_name(name):
    """Sanitizes a string to be a valid SQL column name."""
    return 'feature_' + re.sub(r'[^a-zA-Z0-9_]', '', name.lower().replace(' ', '_'))

@app.route('/settings/features/add', methods=['POST'])
def add_feature_option():
    feature_type = request.form.get('feature_type')
    option_name = request.form.get('option_name')
    if feature_type and option_name:
        try:
            log_and_execute("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", (feature_type, option_name))
            flash("Feature option added.", "success")
        except Exception as e:
            flash(f"Could not add option: {e}", "error")
    return redirect(url_for('billing_settings'))

@app.route('/settings/features/delete/<int:option_id>', methods=['POST'])
def delete_feature_option(option_id):
    log_and_execute("DELETE FROM feature_options WHERE id = ?", (option_id,))
    flash("Feature option deleted.", "success")
    return redirect(url_for('billing_settings'))

@app.route('/settings/features/edit/<int:option_id>', methods=['POST'])
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
    return redirect(url_for('billing_settings'))

@app.route('/settings/features/type/add', methods=['POST'])
def add_feature_type():
    feature_type = request.form.get('feature_type')
    if feature_type:
        column_name = sanitize_column_name(feature_type)
        try:
            with get_db_connection(session['db_password']) as con:
                con.execute(f"ALTER TABLE billing_plans ADD COLUMN {column_name} TEXT DEFAULT 'Not Included'")
                con.execute(f"ALTER TABLE client_billing_overrides ADD COLUMN {column_name} TEXT")
                con.execute(f"ALTER TABLE client_billing_overrides ADD COLUMN override_{column_name}_enabled BOOLEAN DEFAULT 0")
                con.commit()
            log_and_execute("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", (feature_type, 'Not Included'))
            flash("Feature category added.", "success")
        except Exception as e:
            print(f"ERROR adding feature type '{feature_type}': {e}", file=sys.stderr)
            flash(f"Could not add feature category '{feature_type}': {e}", "error")
    return redirect(url_for('billing_settings'))

@app.route('/settings/features/type/delete', methods=['POST'])
def delete_feature_type():
    feature_type = request.form.get('feature_type')
    if feature_type:
        # Note: This does not remove the columns from the database tables,
        # as this is not supported by SQLite's ALTER TABLE command.
        # The columns will be ignored by the application logic.
        log_and_execute("DELETE FROM feature_options WHERE feature_type = ?", (feature_type,))
        flash("Feature category deleted. Note: The corresponding columns are not removed from the database, but will be ignored.", "success")
    return redirect(url_for('billing_settings'))

@app.route('/settings/features/type/edit', methods=['POST'])
def edit_feature_type():
    original_feature_type = request.form.get('original_feature_type')
    new_feature_type = request.form.get('new_feature_type')
    if original_feature_type and new_feature_type:
        original_column_name = sanitize_column_name(original_feature_type)
        new_column_name = sanitize_column_name(new_feature_type)
        try:
            with get_db_connection(session['db_password']) as con:
                con.execute(f"ALTER TABLE billing_plans RENAME COLUMN {original_column_name} TO {new_column_name}")
                con.execute(f"ALTER TABLE client_billing_overrides RENAME COLUMN {original_column_name} TO {new_column_name}")
                con.execute(f"ALTER TABLE client_billing_overrides RENAME COLUMN override_{original_column_name}_enabled TO override_{new_column_name}_enabled")
                con.commit()
            log_and_execute("UPDATE feature_options SET feature_type = ? WHERE feature_type = ?", (new_feature_type, original_feature_type))
            flash("Feature category updated.", "success")
        except Exception as e:
            flash(f"Could not update feature category: {e}", "error")
    return redirect(url_for('billing_settings'))

@app.route('/settings/export')
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

@app.route('/settings/import', methods=['POST'])
def import_settings():
    if 'file' not in request.files:
        flash('No file part', 'error')
        return redirect(url_for('billing_settings'))
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        flash('No selected file or file type not allowed. Must be .json', 'error')
        return redirect(url_for('billing_settings'))
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
    return redirect(url_for('billing_settings'))

@app.route('/settings/plan/action', methods=['POST'])
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

            # Base update statement
            sql = """
                UPDATE billing_plans SET
                    per_user_cost = ?, per_workstation_cost = ?, per_server_cost = ?, per_vm_cost = ?,
                    per_switch_cost = ?, per_firewall_cost = ?, per_hour_ticket_cost = ?, backup_base_fee_workstation = ?,
                    backup_base_fee_server = ?, backup_included_tb = ?, backup_per_tb_fee = ?,
            """
            params = [
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

            # Dynamically add feature updates
            for feature_type in feature_types:
                column_name = sanitize_column_name(feature_type)
                sql += f"{column_name} = ?, "
                params.append(form.get(f'{column_name}_{plan_id}'))

            sql = sql.rstrip(', ') + " WHERE id = ?"
            params.append(plan_id)

            log_and_execute(sql, tuple(params))

        flash(f"Default plan '{plan_name}' updated successfully!", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/settings/plan/add', methods=['POST'])
def add_billing_plan():
    plan_name = request.form.get('new_plan_name')
    if not plan_name:
        flash("New plan name cannot be empty.", 'error')
        return redirect(url_for('billing_settings'))
    if query_db("SELECT 1 FROM billing_plans WHERE billing_plan = ?", [plan_name], one=True):
        flash(f"A plan named '{plan_name}' already exists.", 'error')
        return redirect(url_for('billing_settings'))
    terms = ["Month to Month", "1-Year", "2-Year", "3-Year"]
    for term in terms:
        log_and_execute("INSERT INTO billing_plans (billing_plan, term_length) VALUES (?, ?)", (plan_name, term))
    flash(f"New billing plan '{plan_name}' added with default terms.", 'success')
    return redirect(url_for('billing_settings'))

@app.route('/settings/scheduler/update/<int:job_id>', methods=['POST'])
def update_scheduler_job(job_id):
    is_enabled = 1 if 'enabled' in request.form else 0
    interval = int(request.form.get('interval_minutes', 1))
    log_and_execute("UPDATE scheduler_jobs SET enabled = ?, interval_minutes = ? WHERE id = ?", (is_enabled, interval, job_id))
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

def generate_quickbooks_csv(client_data):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['InvoiceNo', 'Customer', 'InvoiceDate', 'DueDate', 'Item(Product/Service)', 'Description', 'Qty', 'Rate', 'Amount'])
    receipt = client_data['receipt_data']
    client_name = client_data['client']['name']
    invoice_date = datetime.now().strftime('%Y-%m-%d')
    due_date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    invoice_number = f"{client_data['client']['account_number']}-{datetime.now().strftime('%Y%m')}"
    for user in receipt['billed_users']:
        writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Managed Services', f"User: {user['name']} ({user['type']})", 1, f"{user['cost']:.2f}", f"{user['cost']:.2f}"])
    for asset in receipt['billed_assets']:
        writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Managed Services', f"Asset: {asset['name']} ({asset['type']})", 1, f"{asset['cost']:.2f}", f"{asset['cost']:.2f}"])
    for item in receipt['billed_line_items']:
        writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Custom Services', f"Custom Item: {item['name']} ({item['type']})", 1, f"{item['cost']:.2f}", f"{item['cost']:.2f}"])
    if receipt['ticket_charge'] > 0:
         writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Hourly Labor', f"Billable Hours ({receipt['billable_hours']:.2f} hrs)", f"{receipt['billable_hours']:.2f}", f"{client_data['effective_rates']['per_hour_ticket_cost']:.2f}", f"{receipt['ticket_charge']:.2f}"])
    if receipt['backup_charge'] > 0:
        if receipt['backup_base_workstation'] > 0:
            writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Backup Services', 'Workstation Backup Base Fee', len([a for a in client_data['assets'] if a['billing_type']=='Workstation' and a.get('backup_data_bytes',0)>0]), f"{client_data['effective_rates']['backup_base_fee_workstation']:.2f}", f"{receipt['backup_base_workstation']:.2f}"])
        if receipt['backup_base_server'] > 0:
            writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Backup Services', 'Server Backup Base Fee', len([a for a in client_data['assets'] if a['billing_type'] in ['Server','VM'] and a.get('backup_data_bytes',0)>0]), f"{client_data['effective_rates']['backup_base_fee_server']:.2f}", f"{receipt['backup_base_server']:.2f}"])
        if receipt['overage_charge'] > 0:
            writer.writerow([invoice_number, client_name, invoice_date, due_date, 'Backup Services', f"Storage Overage ({receipt['overage_tb']:.2f} TB)", f"{receipt['overage_tb']:.2f}", f"{client_data['effective_rates']['backup_per_tb_fee']:.2f}", f"{receipt['overage_charge']:.2f}"])
    return output.getvalue()

@app.route('/client/<account_number>/export/quickbooks')
def export_quickbooks_csv(account_number):
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    breakdown_data = get_client_breakdown_data(account_number, year, month)
    if not breakdown_data:
        flash(f"Could not generate export for client {account_number}.", 'error')
        return redirect(url_for('billing_dashboard'))
    csv_content = generate_quickbooks_csv(breakdown_data)
    return Response(csv_content, mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=quickbooks_export_{account_number}_{year}-{month:02d}.csv"})

@app.route('/export/all_bills', methods=['POST'])
def export_all_bills_zip():
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    all_clients = get_billing_dashboard_data()
    if not all_clients:
        flash("No clients found to export.", "error")
        return redirect(url_for('billing_dashboard'))
    memory_file = io.BytesIO()
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
        for client in all_clients:
            client_data = get_client_breakdown_data(client['account_number'], year, month)
            if client_data:
                csv_content = generate_quickbooks_csv(client_data)
                sanitized_name = client['name'].replace('/', '_').replace(' ', '_')
                file_name = f"{sanitized_name}_{year}-{month:02d}.csv"
                zf.writestr(file_name, csv_content)
    memory_file.seek(0)
    return Response(memory_file, mimetype='application/zip', headers={'Content-Disposition': f'attachment;filename=all_invoices_{year}-{month:02d}.zip'})

if __name__ == '__main__':
    if not os.path.exists(DATABASE):
        print(f"Database not found. Run 'python init_db.py' first.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    if not os.path.exists(STATIC_CSS_FOLDER):
        os.makedirs(STATIC_CSS_FOLDER)
    print("--- Starting Flask Web Server ---")
    try:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
    finally:
        if scheduler.running:
            print("--- Shutting down scheduler ---")
            scheduler.shutdown()
