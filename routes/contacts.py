# hamnertime/integodash/integodash-api-refactor/routes/contacts.py
from flask import Blueprint, render_template, session, request, flash, redirect, url_for, jsonify
from api_client import api_request
from database import get_user_widget_layout, default_widget_layouts
from utils import role_required, from_json
from datetime import datetime, timezone

contacts_bp = Blueprint('contacts', __name__)

CONTACTS_COLUMNS = {
    'name': {'label': 'Name', 'default': True},
    'email': {'label': 'Email', 'default': True},
    'company': {'label': 'Company', 'default': True},
    'title': {'label': 'Title', 'default': False},
    'work_phone': {'label': 'Work Phone', 'default': True},
    'mobile_phone': {'label': 'Mobile Phone', 'default': False},
    'employment_type': {'label': 'Employment Type', 'default': False},
    'status': {'label': 'Status', 'default': True},
    'associated_assets': {'label': 'Associated Assets', 'default': True},
    'actions': {'label': 'Actions', 'default': True}
}

@contacts_bp.route('/')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def contacts():
    if 'contacts_cols' not in session:
        session['contacts_cols'] = {k: v['default'] for k, v in CONTACTS_COLUMNS.items()}

    # Fetch all companies to populate the "add new contact" form dropdown
    companies = api_request('get', 'clients/')

    layout = get_user_widget_layout(session['user_id'], 'contacts')
    default_layout = default_widget_layouts.get('contacts')

    return render_template('contacts.html',
        companies=companies,
        columns=CONTACTS_COLUMNS,
        visible_columns=session['contacts_cols'],
        layout=layout,
        default_layout=default_layout
    )

@contacts_bp.route('/<int:contact_id>/details', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def contact_details(contact_id):
    if request.method == 'POST':
        if session['role'] not in ['Admin', 'Editor', 'Contributor']:
            flash('You do not have permission to perform this action.', 'error')
            return redirect(url_for('contacts.contact_details', contact_id=contact_id))

        action = request.form.get('action')

        if action == 'save_details':
            contact_data = {
                'first_name': request.form.get('first_name'),
                'last_name': request.form.get('last_name'),
                'email': request.form.get('email'),
                'title': request.form.get('title'),
                'company_account_number': request.form.get('company_account_number'),
                'work_phone': request.form.get('work_phone'),
                'mobile_phone': request.form.get('mobile_phone'),
                'employment_type': request.form.get('employment_type'),
                'status': request.form.get('status'),
                'other_emails': request.form.get('other_emails'),
                'address': request.form.get('address'),
                'notes': request.form.get('notes')
            }
            if api_request('put', f'contacts/{contact_id}', json_data=contact_data):
                # Update asset links separately
                linked_assets = request.form.getlist('linked_assets')
                api_request('post', f'contacts/{contact_id}/link-assets', json_data={'asset_ids': linked_assets})
                flash('Contact updated successfully.', 'success')
            else:
                flash('An error occurred updating the contact via API.', 'error')
        elif action == 'add_note':
            note_content = request.form.get('note_content')
            if note_content:
                note_data = {"note_content": note_content, "author": session.get('username')}
                api_request('post', f'clients/{contact.company_account_number}/notes', json_data=note_data) # This still seems to reference the old file structure.
                flash('Note added successfully.', 'success')
            else:
                flash('Note content cannot be empty.', 'error')

        return redirect(url_for('contacts.contact_details', contact_id=contact_id))

    # GET Request Logic
    contact = api_request('get', f'contacts/{contact_id}')
    if not contact:
        flash('Contact not found.', 'error')
        return redirect(url_for('contacts.contacts'))

    companies = api_request('get', 'clients/')
    company_assets = api_request('get', f'contacts/api/get_assets_for_company/{contact["company_account_number"]}')
    linked_assets_raw = api_request('get', f'contacts/api/get_linked_assets/{contact_id}')
    linked_assets = linked_assets_raw if linked_assets_raw else []

    layout = get_user_widget_layout(session['user_id'], 'contact_details')
    default_layout = default_widget_layouts.get('contact_details')

    return render_template('contact_details.html',
        contact=contact,
        companies=companies,
        company_assets=company_assets,
        linked_assets=linked_assets,
        layout=layout,
        default_layout=default_layout)

@contacts_bp.route('/<int:contact_id>/notes')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_contact_notes_partial(contact_id):
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 10, type=int)

    # Assuming API endpoint for notes pagination exists now
    params = {'page': page, 'per_page': per_page}
    notes_data = api_request('get', f'contacts/{contact_id}/notes', params=params)

    notes = notes_data.get('notes', []) if notes_data else []
    total_pages = notes_data.get('total_pages', 1) if notes_data else 1

    contact = api_request('get', f'contacts/{contact_id}')

    return render_template('partials/contact_notes_section.html',
        contact=contact,
        notes=notes,
        page=page,
        per_page=per_page,
        total_pages=total_pages
    )

@contacts_bp.route('/partial')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_contacts_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    params = {'page': page, 'per_page': per_page, 'search': search_query, 'sort_by': sort_by, 'sort_order': sort_order}
    response_data = api_request('get', 'contacts/paginated', params=params)

    contacts = response_data.get('contacts', []) if response_data else []
    total_pages = response_data.get('total_pages', 1) if response_data else 1

    return render_template('partials/contacts_table.html',
        contacts=contacts,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search_query=search_query,
        sort_by=sort_by,
        sort_order=sort_order,
        visible_columns=session.get('contacts_cols', {k: v['default'] for k, v in CONTACTS_COLUMNS.items()})
    )

@contacts_bp.route('/add', methods=['POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def add_contact():
    contact_data = {
        'first_name': request.form.get('first_name'),
        'last_name': request.form.get('last_name'),
        'email': request.form.get('email'),
        'title': request.form.get('title'),
        'company_account_number': request.form.get('company_account_number'),
        'work_phone': request.form.get('work_phone'),
        'mobile_phone': request.form.get('mobile_phone'),
        'employment_type': request.form.get('employment_type'),
        'status': request.form.get('status'),
        'other_emails': request.form.get('other_emails'),
        'address': request.form.get('address'),
        'notes': request.form.get('notes')
    }

    response = api_request('post', 'contacts/', json_data=contact_data)
    if response:
        contact_id = response.get('id')
        linked_assets = request.form.getlist('linked_assets')
        if linked_assets:
             api_request('post', f'contacts/{contact_id}/link-assets', json_data={'asset_ids': linked_assets})
        flash('Contact added successfully.', 'success')
    else:
        flash('Error adding contact via API.', 'error')

    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/delete/<int:contact_id>', methods=['POST'])
@role_required(['Admin', 'Editor'])
def delete_contact(contact_id):
    if api_request('delete', f'contacts/{contact_id}'):
        flash('Contact deleted successfully.', 'success')
    else:
        flash('Error deleting contact via API.', 'error')
    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/api/get_assets_for_company/<account_number>')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_assets_for_company(account_number):
    """API endpoint to fetch assets for a given company."""
    assets = api_request('get', f'clients/{account_number}/assets')
    return jsonify(assets or [])

@contacts_bp.route('/api/get_linked_assets/<int:contact_id>')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_linked_assets(contact_id):
    """API endpoint to fetch assets already linked to a contact."""
    linked_assets = api_request('get', f'contacts/{contact_id}/linked-assets')
    return jsonify(linked_assets or [])
