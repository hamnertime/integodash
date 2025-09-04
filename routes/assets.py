# hamnertime/integodash/integodash-api-refactor/routes/assets.py
from flask import Blueprint, render_template, session, request, flash, redirect, url_for
from api_client import api_request
from database import get_user_widget_layout, default_widget_layouts
from utils import role_required

assets_bp = Blueprint('assets', __name__)

ASSETS_COLUMNS = {
    'hostname': {'label': 'Hostname', 'default': True},
    'company': {'label': 'Company', 'default': True},
    'associated_contacts': {'label': 'Associated Contacts', 'default': True},
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
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def assets():
    if 'assets_cols' not in session:
        session['assets_cols'] = {k: v['default'] for k, v in ASSETS_COLUMNS.items()}

    # Using the refactored database.py to get layouts from the API
    layout = get_user_widget_layout(session['user_id'], 'assets')
    default_layout = default_widget_layouts.get('assets')

    return render_template('assets.html',
        columns=ASSETS_COLUMNS,
        visible_columns=session['assets_cols'],
        layout=layout,
        default_layout=default_layout
    )

@assets_bp.route('/partial')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_assets_partial():
    params = {
        'page': request.args.get('page', 1, type=int),
        'per_page': request.args.get('per_page', 50, type=int),
        'search': request.args.get('search', ''),
        'sort_by': request.args.get('sort_by', 'hostname'),
        'sort_order': request.args.get('sort_order', 'asc')
    }

    response_data = api_request('get', 'assets/paginated', params=params)

    paginated_assets = response_data.get('assets', []) if response_data else []
    total_pages = response_data.get('total_pages', 1) if response_data else 1

    # If API fails, redirect to login
    if response_data is None:
        return redirect(url_for('auth.login'))

    return render_template('partials/assets_table.html',
        assets=paginated_assets,
        page=params['page'],
        per_page=params['per_page'],
        total_pages=total_pages,
        sort_by=params['sort_by'],
        sort_order=params['sort_order'],
        visible_columns=session.get('assets_cols', {k: v['default'] for k, v in ASSETS_COLUMNS.items()})
    )
