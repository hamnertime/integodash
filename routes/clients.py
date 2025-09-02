# routes/clients.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, Response, send_from_directory, current_app
from database import query_db, log_and_execute, get_user_widget_layout, default_widget_layouts, save_user_widget_layout, delete_user_widget_layout, log_read_action
from billing import get_billing_dashboard_data, get_client_breakdown_data
from datetime import datetime, timezone, timedelta
import os
import uuid
import io
import csv
import zipfile
from werkzeug.utils import secure_filename
from collections import defaultdict

clients_bp = Blueprint('clients', __name__)

CLIENTS_COLUMNS = {
    'name': {'label': 'Company Name', 'default': True},
    'account_number': {'label': 'Account #', 'default': False},
    'billing_plan': {'label': 'Billing Plan', 'default': True},
    'support_level': {'label': 'Support Level', 'default': False},
    'contract_term_length': {'label': 'Term', 'default': False},
    'contract_end_date': {'label': 'Contract End Date', 'default': True},
    'workstations': {'label': 'Workstations', 'default': True},
    'servers': {'label': 'Servers', 'default': True},
    'vms': {'label': 'VMs', 'default': True},
    'regular_users': {'label': 'Users', 'default': True},
    'backup': {'label': 'Backup (TB)', 'default': True},
    'hours': {'label': 'Hours (This Year)', 'default': True},
    'bill': {'label': 'Calculated Bill', 'default': True},
    'actions': {'label': 'Actions', 'default': True}
}

ALLOWED_EXTENSIONS = {'pdf', 'txt', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'json'}

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@clients_bp.route('/')
def billing_dashboard():
    try:
        today = datetime.now(timezone.utc)
        month_options = []
        billing_plans = query_db("SELECT DISTINCT billing_plan FROM billing_plans ORDER BY billing_plan")
        for i in range(1, 13):
            month_options.append({'value': i, 'name': datetime(today.year, i, 1).strftime('%B')})

        if 'clients_cols' not in session:
            session['clients_cols'] = {k: v['default'] for k, v in CLIENTS_COLUMNS.items()}

        layout = get_user_widget_layout(session['user_id'], 'clients')
        default_layout = default_widget_layouts.get('clients')

        return render_template('clients.html',
            month_options=month_options,
            current_year=today.year,
            current_month=today.month,
            billing_plans=billing_plans,
            columns=CLIENTS_COLUMNS,
            visible_columns=session['clients_cols'],
            layout=layout,
            default_layout=default_layout
        )
    except (ValueError, KeyError) as e:
        current_app.config['DB_PASSWORD'] = None
        session.clear()
        flash(f"An error occurred on the dashboard: {e}. Please log in again.", 'error')
        return redirect(url_for('auth.login'))

@clients_bp.route('/clients/partial')
def get_clients_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    all_clients = get_billing_dashboard_data()

    if search_query:
        search_query_lower = search_query.lower()
        all_clients = [
            client for client in all_clients
            if search_query_lower in client.get('name', '').lower() or
               search_query_lower in client.get('billing_plan', '').lower()
        ]

    if sort_by in ['name', 'billing_plan', 'support_level', 'contract_term_length', 'account_number', 'contract_end_date']:
        all_clients.sort(key=lambda x: str(x.get(sort_by, '')), reverse=sort_order == 'desc')
    else:
        all_clients.sort(key=lambda x: float(x.get(sort_by, 0) or 0), reverse=sort_order == 'desc')

    total_clients = len(all_clients)
    total_pages = (total_clients + per_page - 1) // per_page
    start = (page - 1) * per_page
    end = start + per_page
    paginated_clients = all_clients[start:end]

    return render_template('partials/clients_table.html',
        clients=paginated_clients,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search_query=search_query,
        sort_by=sort_by,
        sort_order=sort_order,
        visible_columns=session.get('clients_cols', {k: v['default'] for k, v in CLIENTS_COLUMNS.items()})
    )

@clients_bp.route('/client/add', methods=['POST'])
def add_client():
    account_number = request.form.get('account_number')
    name = request.form.get('name')
    billing_plan = request.form.get('billing_plan')

    if not account_number or not name or not billing_plan:
        flash('Account Number, Name, and Billing Plan are required.', 'error')
    else:
        try:
            log_and_execute(
                "INSERT INTO companies (account_number, name, billing_plan) VALUES (?, ?, ?)",
                (account_number, name, billing_plan)
            )
            flash(f"Client '{name}' added successfully.", 'success')
        except Exception as e:
            flash(f"Error adding client: {e}", "error")

    return redirect(url_for('clients.billing_dashboard'))

@clients_bp.route('/client/delete/<account_number>', methods=['POST'])
def delete_client(account_number):
    try:
        log_and_execute("DELETE FROM companies WHERE account_number = ?", [account_number])
        flash('Client deleted successfully.', 'success')
    except Exception as e:
        flash(f'Error deleting client: {e}', 'error')
    return redirect(url_for('clients.billing_dashboard'))

@clients_bp.route('/client/<account_number>/details', methods=['GET', 'POST'])
def client_billing_details(account_number):
    try:
        if request.method == 'POST':
            action = request.form.get('action')
            if action == 'add_note':
                note_content = request.form.get('note_content')
                if note_content:
                    log_and_execute("INSERT INTO billing_notes (company_account_number, note_content, created_at, author) VALUES (?, ?, ?, ?)",
                               [account_number, note_content, datetime.now(timezone.utc).isoformat(), session.get('username')])
                    flash('Note added successfully.', 'success')
                else:
                    flash('Note content cannot be empty.', 'error')
            return redirect(url_for('clients.client_billing_details', account_number=account_number))

        if request.args.get('delete_note'):
            log_and_execute("DELETE FROM billing_notes WHERE id = ?", [request.args.get('delete_note')])
            flash('Note deleted.', 'success')
            return redirect(url_for('clients.client_billing_details', account_number=account_number))

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
            return redirect(url_for('clients.billing_dashboard'))

        page = 1
        per_page = 10
        search_notes_query = ''
        notes_count = query_db("SELECT COUNT(*) as count FROM billing_notes WHERE company_account_number = ?", [account_number], one=True)['count']
        total_pages = (notes_count + per_page - 1) // per_page
        notes = []

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

        layout = get_user_widget_layout(session['user_id'], 'client_details')
        default_layout = default_widget_layouts.get('client_details')

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
            search_query=search_query,
            layout=layout,
            default_layout=default_layout
        )
    except (ValueError, KeyError) as e:
        current_app.config['DB_PASSWORD'] = None
        session.clear()
        flash(f"An error occurred on details page: {e}. Please log in again.", 'error')
        return redirect(url_for('auth.login'))

@clients_bp.route('/client/<account_number>/note/<int:note_id>/edit', methods=['POST'])
def edit_note(account_number, note_id):
    note = query_db("SELECT * FROM billing_notes WHERE id = ? AND company_account_number = ?", [note_id, account_number], one=True)
    if not note:
        flash("Note not found.", "error")
        return redirect(url_for('clients.client_billing_details', account_number=account_number))
    new_content = request.form.get('note_content')
    if new_content:
        log_and_execute("UPDATE billing_notes SET note_content = ? WHERE id = ?", [new_content, note_id])
        flash("Note updated successfully.", "success")
    else:
        flash("Note content cannot be empty.", "error")
    return redirect(url_for('clients.client_billing_details', account_number=account_number))

@clients_bp.route('/client/<account_number>/notes')
def get_notes_partial(account_number):
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

@clients_bp.route('/client/<account_number>/attachments')
def get_attachments_partial(account_number):
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

    allowed_sort_columns = ['original_filename', 'category', 'file_size', 'uploaded_at']
    if sort_by not in allowed_sort_columns:
        sort_by = 'uploaded_at'

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

@clients_bp.route('/client/<account_number>/upload', methods=['POST'])
def upload_file(account_number):
    files = request.files.getlist('file[]')
    category = request.form.get('category')

    if not files or files[0].filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('clients.client_billing_details', account_number=account_number))

    uploaded_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            original_filename = secure_filename(file.filename)
            stored_filename = f"{uuid.uuid4().hex}_{original_filename}"
            client_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], account_number)
            if not os.path.exists(client_upload_dir):
                os.makedirs(client_upload_dir)
            file_path = os.path.join(client_upload_dir, stored_filename)
            file.save(file_path)
            file_size = os.path.getsize(file_path)
            log_and_execute("INSERT INTO client_attachments (company_account_number, original_filename, stored_filename, uploaded_at, file_size, category) VALUES (?, ?, ?, ?, ?, ?)", (account_number, original_filename, stored_filename, datetime.now(timezone.utc).isoformat(), file_size, category))
            uploaded_count += 1
        else:
            flash(f"File type not allowed for '{file.filename}'.", 'error')

    if uploaded_count > 0:
        flash(f'{uploaded_count} file(s) uploaded successfully!', 'success')

    return redirect(url_for('clients.client_billing_details', account_number=account_number))

@clients_bp.route('/uploads/<account_number>/<filename>')
def download_file(account_number, filename):
    attachment = query_db("SELECT original_filename FROM client_attachments WHERE stored_filename = ? AND company_account_number = ?", [filename, account_number], one=True)
    if not attachment:
        return "File not found.", 404

    log_read_action(
        action='DOWNLOAD',
        details=f"Downloaded file '{attachment['original_filename']}' for client {account_number}."
    )

    client_upload_dir = os.path.join(current_app.config['UPLOAD_FOLDER'], account_number)
    return send_from_directory(client_upload_dir, filename, as_attachment=True, download_name=attachment['original_filename'])

@clients_bp.route('/client/<account_number>/delete_attachment/<int:attachment_id>')
def delete_attachment(account_number, attachment_id):
    attachment = query_db("SELECT stored_filename FROM client_attachments WHERE id = ? AND company_account_number = ?", [attachment_id, account_number], one=True)
    if attachment:
        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], account_number, attachment['stored_filename'])
        if os.path.exists(file_path):
            os.remove(file_path)
        log_and_execute("DELETE FROM client_attachments WHERE id = ?", [attachment_id])
        flash("Attachment deleted successfully.", 'success')
    else:
        flash("Attachment not found.", 'error')
    return redirect(url_for('clients.client_billing_details', account_number=account_number))

@clients_bp.route('/client/<account_number>/edit_attachment/<int:attachment_id>', methods=['POST'])
def edit_attachment(account_number, attachment_id):
    original_filename = request.form.get('original_filename')
    category = request.form.get('category')
    if original_filename:
        log_and_execute("UPDATE client_attachments SET original_filename = ?, category = ? WHERE id = ? AND company_account_number = ?",
                       [original_filename, category, attachment_id, account_number])
        flash('Attachment updated successfully.', 'success')
    else:
        flash('Filename cannot be empty.', 'error')
    return redirect(url_for('clients.client_billing_details', account_number=account_number))

@clients_bp.route('/export/all_bills', methods=['POST'])
def export_all_bills_zip():
    year = int(request.form.get('year'))
    month = int(request.form.get('month'))
    all_clients = get_billing_dashboard_data()
    if not all_clients:
        flash("No clients found to export.", "error")
        return redirect(url_for('clients.billing_dashboard'))
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

@clients_bp.route('/client/<account_number>/export/quickbooks')
def export_quickbooks_csv(account_number):
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    breakdown_data = get_client_breakdown_data(account_number, year, month)
    if not breakdown_data:
        flash(f"Could not generate export for client {account_number}.", 'error')
        return redirect(url_for('clients.billing_dashboard'))
    csv_content = generate_quickbooks_csv(breakdown_data)
    return Response(csv_content, mimetype="text/csv", headers={"Content-disposition": f"attachment; filename=quickbooks_export_{account_number}_{year}-{month:02d}.csv"})

@clients_bp.route('/client/<account_number>/settings', methods=['GET', 'POST'])
def client_settings(account_number):
    try:
        feature_options_raw = query_db("SELECT * FROM feature_options ORDER BY feature_type, option_name")
        feature_options = defaultdict(list)
        for option in feature_options_raw:
            feature_options[option['feature_type']].append(dict(option))

        all_billing_plans = query_db("SELECT DISTINCT billing_plan FROM billing_plans ORDER BY billing_plan")

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

                feature_map = {}
                for feature_type in feature_options.keys():
                    short_name = feature_type.lower().replace(' ', '_')
                    feature_map[short_name] = f'feature_{short_name}'

                columns_to_update, values_to_update = ['company_account_number'], [account_number]

                columns_to_update.append('billing_plan')
                values_to_update.append(request.form.get('billing_plan'))
                columns_to_update.append('override_billing_plan_enabled')
                values_to_update.append(1 if 'override_billing_plan_enabled' in request.form else 0)

                columns_to_update.append('support_level')
                values_to_update.append(request.form.get('support_level'))
                columns_to_update.append('override_support_level_enabled')
                values_to_update.append(1 if 'override_support_level_enabled' in request.form else 0)

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
                for user in query_db("SELECT id FROM users WHERE company_account_number = ? AND status = 'Active'", [account_number]):
                    user_id = user['id']
                    billing_type = request.form.get(f'user_billing_type_{user_id}')
                    custom_cost = request.form.get(f'user_custom_cost_{user_id}')
                    employment_type = request.form.get(f'user_employment_type_{user_id}')
                    if billing_type or employment_type:
                        log_and_execute("INSERT INTO user_billing_overrides (user_id, billing_type, custom_cost, employment_type) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET billing_type=excluded.billing_type, custom_cost=excluded.custom_cost, employment_type=excluded.employment_type", [user_id, billing_type, custom_cost if custom_cost else None, employment_type])
                    else:
                        log_and_execute("DELETE FROM user_billing_overrides WHERE user_id = ?", [user_id])
                flash("Overrides saved successfully!", 'success')
            return redirect(url_for('clients.client_settings', account_number=account_number))
        if request.args.get('delete_manual_asset'):
            log_and_execute("DELETE FROM manual_assets WHERE id = ?", [request.args.get('delete_manual_asset')])
            flash('Manual asset deleted.', 'success')
            return redirect(url_for('clients.client_settings', account_number=account_number))
        if request.args.get('delete_manual_user'):
            log_and_execute("DELETE FROM manual_users WHERE id = ?", [request.args.get('delete_manual_user')])
            flash('Manual user deleted.', 'success')
            return redirect(url_for('clients.client_settings', account_number=account_number))
        if request.args.get('delete_line_item'):
            log_and_execute("DELETE FROM custom_line_items WHERE id = ?", [request.args.get('delete_line_item')])
            flash('Custom line item deleted.', 'success')
            return redirect(url_for('clients.client_settings', account_number=account_number))
        if request.args.get('delete_location'):
            log_and_execute("DELETE FROM client_locations WHERE id = ?", [request.args.get('delete_location')])
            flash('Location deleted.', 'success')
            return redirect(url_for('clients.client_settings', account_number=account_number))

        client_info_raw = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
        if not client_info_raw:
            flash(f"Client {account_number} not found.", 'error')
            return redirect(url_for('clients.billing_dashboard'))

        client_info = dict(client_info_raw)

        for date_field in ['client_start_date', 'contract_start_date']:
            if client_info.get(date_field):
                try:
                    client_info[date_field] = client_info[date_field].split('T')[0]
                except (ValueError, TypeError, IndexError):
                    pass

        locations = query_db("SELECT * FROM client_locations WHERE company_account_number = ?", [account_number])
        default_plan = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
        overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)
        assets = query_db("""
            SELECT a.*, GROUP_CONCAT(c.first_name || ' ' || c.last_name, ', ') as associated_contacts
            FROM assets a
            LEFT JOIN asset_contact_links acl ON a.id = acl.asset_id
            LEFT JOIN contacts c ON acl.contact_id = c.id
            WHERE a.company_account_number = ?
            GROUP BY a.id
            ORDER BY a.hostname
        """, [account_number])
        users = query_db("""
            SELECT u.*, c.employment_type as default_employment_type,
                   '[' || GROUP_CONCAT(json_object('hostname', a.hostname, 'portal_url', a.portal_url)) || ']' as associated_assets
            FROM users u
            LEFT JOIN contacts c ON u.email = c.email
            LEFT JOIN asset_contact_links acl ON c.id = acl.contact_id
            LEFT JOIN assets a ON acl.asset_id = a.id
            WHERE u.company_account_number = ? AND u.status = 'Active'
            GROUP BY u.id
            ORDER BY u.full_name
        """, [account_number])
        manual_assets = query_db("SELECT * FROM manual_assets WHERE company_account_number = ?", [account_number])
        manual_users = query_db("SELECT * FROM manual_users WHERE company_account_number = ?", [account_number])
        custom_line_items = query_db("SELECT * FROM custom_line_items WHERE company_account_number = ?", [account_number])
        asset_overrides = {r['asset_id']: dict(r) for r in query_db("SELECT * FROM asset_billing_overrides ao JOIN assets a ON a.id = ao.asset_id WHERE a.company_account_number = ?", [account_number])}
        user_overrides = {r['user_id']: dict(r) for r in query_db("SELECT * FROM user_billing_overrides uo JOIN users u ON u.id = uo.user_id WHERE u.company_account_number = ?", [account_number])}
        today = datetime.now(timezone.utc)
        month_options = [{'value': (today + timedelta(days=31*i)).strftime('%Y-%m'), 'name': (today + timedelta(days=31*i)).strftime('%B %Y')} for i in range(12)]

        layout = get_user_widget_layout(session['user_id'], 'client_settings')
        default_layout = default_widget_layouts.get('client_settings')

        return render_template('client_settings.html', client=client_info, locations=locations, defaults=default_plan, overrides=dict(overrides_row) if overrides_row else {}, assets=assets, users=users, manual_assets=manual_assets, manual_users=manual_users, custom_line_items=custom_line_items, asset_overrides=asset_overrides, user_overrides=user_overrides, month_options=month_options, feature_options=feature_options, all_billing_plans=all_billing_plans, layout=layout, default_layout=default_layout)
    except (ValueError, KeyError) as e:
        current_app.config['DB_PASSWORD'] = None
        session.clear()
        flash(f"A database or key error occurred on settings page: {e}. Please log in again.", 'error')
        return redirect(url_for('auth.login'))

@clients_bp.route('/client/<account_number>/edit_location/<int:location_id>', methods=['POST'])
def edit_location(account_number, location_id):
    location_name = request.form.get('location_name')
    address = request.form.get('address')
    if location_name:
        log_and_execute("UPDATE client_locations SET location_name = ?, address = ? WHERE id = ? AND company_account_number = ?",
                       [location_name, address, location_id, account_number])
        flash('Location updated successfully.', 'success')
    else:
        flash('Location Name is required.', 'error')
    return redirect(url_for('clients.client_settings', account_number=account_number))

@clients_bp.route('/client/<account_number>/edit_manual_asset/<int:asset_id>', methods=['POST'])
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
    return redirect(url_for('clients.client_settings', account_number=account_number))

@clients_bp.route('/client/<account_number>/edit_manual_user/<int:user_id>', methods=['POST'])
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
    return redirect(url_for('clients.client_settings', account_number=account_number))

@clients_bp.route('/client/<account_number>/edit_line_item/<int:item_id>', methods=['POST'])
def edit_line_item(account_number, item_id):
    item = query_db("SELECT * FROM custom_line_items WHERE id = ? AND company_account_number = ?", [item_id, account_number], one=True)
    if not item:
        flash("Line item not found.", "error")
        return redirect(url_for('clients.client_settings', account_number=account_number))

    name = request.form.get('line_item_name')
    item_type = request.form.get('line_item_type')

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
    return redirect(url_for('clients.client_settings', account_number=account_number))
