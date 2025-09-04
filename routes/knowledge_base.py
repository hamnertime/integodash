# hamnertime/integodash/integodash-api-refactor/routes/knowledge_base.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from api_client import api_request
from database import get_user_widget_layout, default_widget_layouts
from utils import role_required
from datetime import datetime, timezone

kb_bp = Blueprint('kb', __name__)

KB_COLUMNS = {
    'title': {'label': 'Title', 'default': True},
    'categories': {'label': 'Categories', 'default': True},
    'author': {'label': 'Author', 'default': True},
    'client': {'label': 'Client', 'default': True},
    'updated_at': {'label': 'Last Updated', 'default': True},
    'actions': {'label': 'Actions', 'default': True}
}

@kb_bp.route('/')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def kb():
    if 'kb_cols' not in session:
        session['kb_cols'] = {k: v['default'] for k, v in KB_COLUMNS.items()}
    layout = get_user_widget_layout(session['user_id'], 'kb')
    default_layout = default_widget_layouts.get('kb')
    return render_template('knowledge_base.html',
                           layout=layout,
                           default_layout=default_layout,
                           columns=KB_COLUMNS,
                           visible_columns=session['kb_cols'])

@kb_bp.route('/partial')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_articles_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'updated_at')
    sort_order = request.args.get('sort_order', 'desc')

    params = {'page': page, 'per_page': per_page, 'search': search_query, 'sort_by': sort_by, 'sort_order': sort_order}
    response_data = api_request('get', 'kb/articles/paginated', params=params)

    articles = response_data.get('articles', []) if response_data else []
    total_pages = response_data.get('total_pages', 1) if response_data else 1

    return render_template(
        'partials/kb_articles_table.html',
        articles=articles,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_order=sort_order,
        visible_columns=session.get('kb_cols', {k: v['default'] for k, v in KB_COLUMNS.items()})
    )

@kb_bp.route('/article/<int:article_id>')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def view_article(article_id):
    article = api_request('get', f'kb/articles/{article_id}')
    if not article:
        flash('Article not found.', 'error')
        return redirect(url_for('kb.kb'))

    categories = article.get('categories', [])

    return render_template('kb_article.html', article=article, categories=categories)

@kb_bp.route('/article/new', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def create_article():
    companies = api_request('get', 'clients/')
    categories = api_request('get', 'kb/categories/')

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        visibility = request.form.get('visibility')
        category_ids = request.form.getlist('categories')

        is_internal = visibility == 'Internal'
        company_account_number = None if is_internal else visibility
        visibility_text = 'Internal' if is_internal else 'Client'

        if not title or not content:
            flash('Title and content are required.', 'error')
            return redirect(url_for('kb.create_article'))

        article_data = {
            "title": title,
            "content": content,
            "author_id": session['user_id'],
            "visibility": visibility_text,
            "company_account_number": company_account_number,
            "category_ids": [int(cid) for cid in category_ids]
        }

        response = api_request('post', 'kb/articles/', json_data=article_data)

        if response:
            flash('Article created successfully.', 'success')
            return redirect(url_for('kb.view_article', article_id=response['id']))
        else:
            flash('Error creating article via API.', 'error')
            return redirect(url_for('kb.create_article'))

    return render_template('edit_kb_article.html', article=None, companies=companies, categories=categories, current_categories=[])

@kb_bp.route('/article/edit/<int:article_id>', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def edit_article(article_id):
    article = api_request('get', f'kb/articles/{article_id}')
    if not article:
        flash('Article not found.', 'error')
        return redirect(url_for('kb.kb'))

    companies = api_request('get', 'clients/')
    categories = api_request('get', 'kb/categories/')
    current_categories = [cat['id'] for cat in article.get('categories', [])]

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        visibility = request.form.get('visibility')
        category_ids = request.form.getlist('categories')

        is_internal = visibility == 'Internal'
        company_account_number = None if is_internal else visibility
        visibility_text = 'Internal' if is_internal else 'Client'

        if not title or not content:
            flash('Title and content are required.', 'error')
            return redirect(url_for('kb.edit_article', article_id=article_id))

        article_data = {
            "title": title,
            "content": content,
            "visibility": visibility_text,
            "company_account_number": company_account_number,
            "category_ids": [int(cid) for cid in category_ids]
        }

        response = api_request('put', f'kb/articles/{article_id}', json_data=article_data)

        if response:
            flash('Article updated successfully.', 'success')
            return redirect(url_for('kb.view_article', article_id=article_id))
        else:
            flash('Error updating article via API.', 'error')
            return redirect(url_for('kb.edit_article', article_id=article_id))

    return render_template('edit_kb_article.html', article=article, companies=companies, categories=categories, current_categories=current_categories)

@kb_bp.route('/article/delete/<int:article_id>', methods=['POST'])
@role_required(['Admin', 'Editor'])
def delete_article(article_id):
    if api_request('delete', f'kb/articles/{article_id}'):
        flash('Article deleted successfully.', 'success')
    else:
        flash('Error deleting article via API.', 'error')
    return redirect(url_for('kb.kb'))

@kb_bp.route('/save_column_prefs/kb', methods=['POST'])
def save_kb_column_prefs():
    prefs = {}
    for col in KB_COLUMNS.keys():
        prefs[col] = col in request.form
    session['kb_cols'] = prefs
    session.modified = True
    return jsonify({'status': 'success'})
