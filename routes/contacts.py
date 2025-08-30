# routes/contacts.py
from flask import Blueprint, render_template, session, request, flash, redirect, url_for
from database import query_db, log_and_execute, get_user_widget_layout, default_widget_layouts

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
    'actions': {'label': 'Actions', 'default': True}
}

@contacts_bp.route('/')
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
def get_contacts_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'name')
    sort_order = request.args.get('sort_order', 'asc')

    base_query = """
        FROM contacts c
        LEFT JOIN companies co ON c.company_account_number = co.account_number
    """
    params = []
    where_clauses = []

    if search_query:
        where_clauses.append("(c.first_name LIKE ? OR c.last_name LIKE ? OR c.email LIKE ? OR co.name LIKE ? OR c.title LIKE ?)")
        search_param = f'%{search_query}%'
        params.extend([search_param, search_param, search_param, search_param, search_param])

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
        'employment_type': 'c.employment_type'
    }
    sort_column = allowed_sort_columns.get(sort_by, 'c.first_name')

    if sort_order not in ['asc', 'desc']:
        sort_order = 'asc'

    offset = (page - 1) * per_page
    contacts_query = f"""
        SELECT c.*, co.name as company_name
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
def add_contact():
    log_and_execute("""
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
    flash('Contact added successfully.', 'success')
    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/edit/<int:contact_id>', methods=['POST'])
def edit_contact(contact_id):
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
    flash('Contact updated successfully.', 'success')
    return redirect(url_for('contacts.contacts'))

@contacts_bp.route('/delete/<int:contact_id>')
def delete_contact(contact_id):
    log_and_execute("DELETE FROM contacts WHERE id = ?", [contact_id])
    flash('Contact deleted successfully.', 'success')
    return redirect(url_for('contacts.contacts'))
