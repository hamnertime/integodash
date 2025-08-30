# routes/assets.py
from flask import Blueprint, render_template, session, request
from database import query_db, get_user_widget_layout, default_widget_layouts

assets_bp = Blueprint('assets', __name__)

ASSETS_COLUMNS = {
    'hostname': {'label': 'Hostname', 'default': True},
    'company': {'label': 'Company', 'default': True},
    'device_type': {'label': 'Device Type', 'default': False},
    'os': {'label': 'Operating System', 'default': True},
    'internal_ip': {'label': 'Internal IP', 'default': False},
    'external_ip': {'label': 'External IP', 'default': False},
    'last_user': {'label': 'Last Logged In User', 'default': True},
    'last_seen': {'label': 'Last Seen', 'default': False},
    'status': {'label': 'Status', 'default': True},
    'actions': {'label': 'Actions', 'default': True}
}

@assets_bp.route('/')
def assets():
    if 'assets_cols' not in session:
        session['assets_cols'] = {k: v['default'] for k, v in ASSETS_COLUMNS.items()}
    layout = get_user_widget_layout(session['user_id'], 'assets')
    default_layout = default_widget_layouts.get('assets')
    return render_template('assets.html',
        columns=ASSETS_COLUMNS,
        visible_columns=session['assets_cols'],
        layout=layout,
        default_layout=default_layout
    )

@assets_bp.route('/partial')
def get_assets_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'hostname')
    sort_order = request.args.get('sort_order', 'asc')

    base_query = """
        FROM assets a
        LEFT JOIN companies c ON a.company_account_number = c.account_number
    """
    params = []
    where_clauses = []

    if search_query:
        where_clauses.append("(a.hostname LIKE ? OR a.operating_system LIKE ? OR a.last_logged_in_user LIKE ? OR c.name LIKE ? OR a.internal_ip LIKE ? OR a.external_ip LIKE ?)")
        search_param = f'%{search_query}%'
        params.extend([search_param] * 6)

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)

    count_query = f"SELECT COUNT(*) as count {base_query}"
    total_assets = query_db(count_query, params, one=True)['count']
    total_pages = (total_assets + per_page - 1) // per_page

    allowed_sort_columns = {
        'hostname': 'a.hostname',
        'company': 'c.name',
        'os': 'a.operating_system',
        'last_user': 'a.last_logged_in_user',
        'status': 'a.is_online',
        'device_type': 'a.device_type',
        'internal_ip': 'a.internal_ip',
        'external_ip': 'a.external_ip',
        'last_seen': 'a.last_seen'
    }
    sort_column = allowed_sort_columns.get(sort_by, 'a.hostname')

    if sort_order not in ['asc', 'desc']:
        sort_order = 'asc'

    offset = (page - 1) * per_page
    assets_query = f"""
        SELECT a.*, c.name as company_name
        {base_query}
        ORDER BY {sort_column} {sort_order}
        LIMIT ? OFFSET ?
    """
    assets_data = query_db(assets_query, params + [per_page, offset])

    return render_template('partials/assets_table.html',
        assets=assets_data,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        search_query=search_query,
        sort_by=sort_by,
        sort_order=sort_order,
        visible_columns=session.get('assets_cols', {k: v['default'] for k, v in ASSETS_COLUMNS.items()})
    )
