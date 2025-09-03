# routes/contacts.py
from flask import Blueprint, render_template, session, request, flash, redirect, url_for, jsonify
from database import query_db, log_and_execute, get_user_widget_layout, default_widget_layouts, get_db
from utils import role_required

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
    companies = query_db("SELECT * FROM companies ORDER BY name")
    layout = get_user_widget_layout(session['user_id'], 'contacts')
    default_layout = default_widget_layouts.get('contacts')
    return render_template('contacts.html',
        companies=companies,
        columns=CONTACTS_COLUMNS,
        visible_columns=session['contacts_cols'],
        layout=layout,
        default_layout=default_layout
    )

@contacts_bp.route('/partial')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_contacts_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    base_query = """
        FROM contacts c
        LEFT JOIN companies co ON c.company_account_number = co.account_number
        LEFT JOIN (
            SELECT
                acl.contact_id,
                '[' || GROUP_CONCAT(json_object('hostname', a.hostname, 'portal_url', a.portal_url)) || ']' as assets
            FROM asset_contact_links acl
            JOIN assets a ON acl.asset_id = a.id
            GROUP BY acl.contact_id
        ) as linked_assets ON c.id = linked_assets.contact_id
    """
    params = []
    where_clauses = []

    if search_query:
        where_clauses.append("(c.first_name LIKE ? OR c.last_name LIKE ? OR c.email LIKE ? OR co.name LIKE ? OR c.title LIKE ? OR linked_assets.assets LIKE ?)")
        search_param = f'%{search_query}%'
        params.extend([search_param, search_param, search_param, search_param, search_param, search_param])

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)

    count_query = f"SELECT COUNT(*) as count {base_query}"
    total_contacts = query_db(count_query, params, one=True)['count']
    total_pages = (total_contacts + per_page - 1) // per_page

    allowed_sort_columns = {
        'name': 'c.first_name',
        'email': 'c.email',
        'company': 'co.name',
        'work_phone': 'c.work_phone',
        'mobile_phone': 'c.mobile_phone',
        'status': 'c.status',
        'title': 'c.title',
        'employment_type': 'c.employment_type',
        'associated_assets': 'linked_assets.assets'
    }
    sort_column = allowed_sort_columns.get(sort_by, 'c.first_name')

    if sort_order not in ['asc', 'desc']:
        sort_order = 'asc'

    offset = (page - 1) * per_page
    contacts_query = f"""
        SELECT c.*, co.name as company_name, linked_assets.assets as associated_assets
        {base_query}
        ORDER BY {sort_column} {sort_order}
        LIMIT ? OFFSET ?
    """
    contacts = query_db(contacts_query, params + [per_page, offset])

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
    db = get_db()
    try:
        with db:
            cur = log_and_execute("""
                INSERT INTO contacts (first_name, last_name, email, title, company_account_number, work_phone, mobile_phone, employment_type, status, other_emails, address, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                request.form.get('first_name'),
                request.form.get('last_name'),
                request.form.get('email'),
                request.form.get('title'),
                request.form.get('company_account_number'),
                request.form.get('work_phone'),
                request.form.get('mobile_phone'),
                request.form.get('employment_type'),
                request.form.get('status'),
                request.form.get('other_emails'),
                request.form.get('address'),
                request.form.get('notes')
            ])
            contact_id = cur.lastrowid
            linked_assets = request.form.getlist('linked_assets')
            if linked_assets:
                for asset_id in linked_assets:
                    db.execute("INSERT INTO asset_contact_links (contact_id, asset_id) VALUES (?, ?)", (contact_id, asset_id))
        flash('Contact added successfully.', 'success')
    except Exception as e:
        flash(f'Error adding contact: {e}', 'error')

    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/edit/<int:contact_id>', methods=['POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def edit_contact(contact_id):
    # This operation involves multiple steps, so we manage the transaction manually.
    db = get_db()
    try:
        with db: # Start a transaction
            # Step 1: Update the main contact details
            log_and_execute("""
                UPDATE contacts
                SET first_name = ?, last_name = ?, email = ?, title = ?, company_account_number = ?, work_phone = ?, mobile_phone = ?, employment_type = ?, status = ?, other_emails = ?, address = ?, notes = ?
                WHERE id = ?
            """, [
                request.form.get('first_name'),
                request.form.get('last_name'),
                request.form.get('email'),
                request.form.get('title'),
                request.form.get('company_account_number'),
                request.form.get('work_phone'),
                request.form.get('mobile_phone'),
                request.form.get('employment_type'),
                request.form.get('status'),
                request.form.get('other_emails'),
                request.form.get('address'),
                request.form.get('notes'),
                contact_id
            ])

            # Step 2: Update the asset links
            linked_assets = request.form.getlist('linked_assets')
            # First, remove all existing links for this contact
            db.execute("DELETE FROM asset_contact_links WHERE contact_id = ?", [contact_id])
            # Then, add the new links from the form
            if linked_assets:
                for asset_id in linked_assets:
                    db.execute("INSERT INTO asset_contact_links (contact_id, asset_id) VALUES (?, ?)", (contact_id, asset_id))

        flash('Contact and associated assets updated successfully.', 'success')
    except Exception as e:
        flash(f'An error occurred during update: {e}', 'error')

    return redirect(url_for('contacts.contacts'))


@contacts_bp.route('/delete/<int:contact_id>')
@role_required(['Admin', 'Editor'])
def delete_contact(contact_id):
    log_and_execute("DELETE FROM contacts WHERE id = ?", [contact_id])
    flash('Contact deleted successfully.', 'success')
    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/api/get_assets_for_company/<account_number>')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_assets_for_company(account_number):
    """API endpoint to fetch assets for a given company."""
    assets = query_db("SELECT id, hostname FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])
    return jsonify([dict(row) for row in assets])

@contacts_bp.route('/api/get_linked_assets/<int:contact_id>')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_linked_assets(contact_id):
    """API endpoint to fetch assets already linked to a contact."""
    linked_assets = query_db("SELECT asset_id FROM asset_contact_links WHERE contact_id = ?", [contact_id])
    return jsonify([row['asset_id'] for row in linked_assets])
