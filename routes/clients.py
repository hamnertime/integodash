# routes/clients.py
from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    jsonify, Response, send_from_directory, current_app
)
from datetime import datetime, timezone, timedelta
import os
import uuid
import io
import csv
import zipfile
from werkzeug.utils import secure_filename
from collections import defaultdict
from utils import role_required
from api_client import api_request

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
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def billing_dashboard():
    try:
        today = datetime.now(timezone.utc)
        month_options = []
        for i in range(1, 13):
            month_options.append({'value': i, 'name': datetime(today.year, i, 1).strftime('%B')})

        billing_plans_data = api_request('get', 'settings/billing-plans/')
        billing_plans = billing_plans_data if billing_plans_data else []

        if 'clients_cols' not in session:
            session['clients_cols'] = {k: v['default'] for k, v in CLIENTS_COLUMNS.items()}

        user_id = session['user_id']
        layout = api_request('get', f'settings/layouts/{user_id}/clients')
        default_layout = api_request('get', 'settings/layouts/default/clients')

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
    except Exception as e:
        session.clear()
        flash(f"An error occurred on the dashboard: {e}. Please log in again.", 'error')
        return redirect(url_for('auth.login'))


@clients_bp.route('/clients/partial')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_clients_partial():
    params = {
        'page': request.args.get('page', 1, type=int),
        'per_page': request.args.get('per_page', 50, type=int),
        'search': request.args.get('search', ''),
        'sort_by': request.args.get('sort_by', 'name'),
        'sort_order': request.args.get('sort_order', 'asc')
    }
    response_data = api_request('get', 'clients/dashboard/paginated', params=params)

    paginated_clients = response_data.get('clients', []) if response_data else []
    total_pages = response_data.get('total_pages', 1) if response_data else 1

    return render_template('partials/clients_table.html',
        clients=paginated_clients,
        page=params['page'],
        per_page=params['per_page'],
        total_pages=total_pages,
        search_query=params['search'],
        sort_by=params['sort_by'],
        sort_order=params['sort_order'],
        visible_columns=session.get('clients_cols', {k: v['default'] for k, v in CLIENTS_COLUMNS.items()})
    )


@clients_bp.route('/client/add', methods=['POST'])
@role_required(['Admin', 'Editor'])
def add_client():
    new_client_data = {
        "account_number": request.form.get('account_number'),
        "name": request.form.get('name'),
        "billing_plan": request.form.get('billing_plan')
    }
    if not all(new_client_data.values()):
        flash('Account Number, Name, and Billing Plan are required.', 'error')
    else:
        response = api_request('post', 'clients/', json_data=new_client_data)
        if response:
            flash(f"Client '{new_client_data['name']}' added successfully.", 'success')
        else:
            flash("Error adding client via API.", "error")
    return redirect(url_for('clients.billing_dashboard'))


@clients_bp.route('/client/delete/<account_number>', methods=['POST'])
@role_required(['Admin'])
def delete_client(account_number):
    if api_request('delete', f'clients/{account_number}'):
        flash('Client deleted successfully.', 'success')
    else:
        flash('Error deleting client via API.', 'error')
    return redirect(url_for('clients.billing_dashboard'))


@clients_bp.route('/client/<account_number>/details', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def client_billing_details(account_number):
    try:
        if request.method == 'POST':
            if session['role'] not in ['Admin', 'Editor', 'Contributor']:
                flash('You do not have permission to perform this action.', 'error')
                return redirect(url_for('clients.client_billing_details', account_number=account_number))

            note_content = request.form.get('note_content')
            if note_content:
                note_data = {"note_content": note_content, "author": session.get('username')}
                api_request('post', f'clients/{account_number}/notes', json_data=note_data)
                flash('Note added successfully.', 'success')
            else:
                flash('Note content cannot be empty.', 'error')

            return redirect(url_for('clients.client_billing_details', account_number=account_number))

        if request.args.get('delete_note'):
            if session['role'] not in ['Admin', 'Editor']:
                flash('You do not have permission to perform this action.', 'error')
            else:
                note_id = request.args.get('delete_note')
                api_request('delete', f'clients/notes/{note_id}')
                flash('Note deleted.', 'success')
            return redirect(url_for('clients.client_billing_details', account_number=account_number))

        today = datetime.now(timezone.utc)
        first_day_of_current_month = today.replace(day=1)
        last_month_date = first_day_of_current_month - timedelta(days=1)
        year = request.args.get('year', default=last_month_date.year, type=int)
        month = request.args.get('month', default=last_month_date.month, type=int)

        # A single API call to get all details for the client page
        breakdown_data = api_request('get', f'clients/{account_number}/billing-details', params={'year': year, 'month': month})

        if not breakdown_data:
            flash(f"Could not retrieve details for client {account_number}.", 'error')
            return redirect(url_for('clients.billing_dashboard'))

        month_options = []
        for i in range(12, 0, -1):
             month_options.append({'year': today.year if i <= today.month else today.year -1, 'month': i, 'name': datetime(today.year, i, 1).strftime('%B %Y')})

        user_id = session['user_id']
        layout = api_request('get', f'settings/layouts/{user_id}/client_details')
        default_layout = api_request('get', 'settings/layouts/default/client_details')

        return render_template(
            'client_billing_details.html',
            selected_year=year,
            selected_month=month,
            month_options=month_options,
            selected_billing_period=datetime(year, month, 1).strftime('%B %Y'),
            layout=layout,
            default_layout=default_layout,
            **breakdown_data
        )
    except Exception as e:
        current_app.config['DB_PASSWORD'] = None
        session.clear()
        flash(f"An error occurred on details page: {e}. Please log in again.", 'error')
        return redirect(url_for('auth.login'))


# ... (Other routes like edit_note, get_notes_partial, uploads, etc. would follow this pattern)
# For example, here is the refactored upload_file function:

@clients_bp.route('/client/<account_number>/upload', methods=['POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def upload_file(account_number):
    files = request.files.getlist('file[]')
    category = request.form.get('category')

    if not files or files[0].filename == '':
        flash('No selected file', 'error')
        return redirect(url_for('clients.client_billing_details', account_number=account_number))

    uploaded_count = 0
    for file in files:
        if file and allowed_file(file.filename):
            # The API client needs to be adapted to handle multipart/form-data
            # This is a conceptual example. `api_request` would need modification.
            files_data = {'file': (file.filename, file.stream, file.mimetype)}
            form_data = {'category': category}
            response = api_request('post', f'clients/{account_number}/attachments', data=form_data, files=files_data)
            if response:
                uploaded_count += 1
            else:
                flash(f"API error uploading '{file.filename}'.", 'error')
        else:
            flash(f"File type not allowed for '{file.filename}'.", 'error')

    if uploaded_count > 0:
        flash(f'{uploaded_count} file(s) uploaded successfully!', 'success')

    return redirect(url_for('clients.client_billing_details', account_number=account_number))
