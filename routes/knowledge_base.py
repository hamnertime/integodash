# routes/knowledge_base.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from database import query_db, log_and_execute, get_db, get_user_widget_layout, default_widget_layouts
from utils import role_required
from datetime import datetime, timezone

kb_bp = Blueprint('kb', __name__)

@kb_bp.route('/')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def kb():
    layout = get_user_widget_layout(session['user_id'], 'kb')
    default_layout = default_widget_layouts.get('kb')
    return render_template('knowledge_base.html', layout=layout, default_layout=default_layout)

@kb_bp.route('/partial')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def get_articles_partial():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    search_query = request.args.get('search', '')
    sort_by = request.args.get('sort_by', 'updated_at')
    sort_order = request.args.get('sort_order', 'desc')

    base_query = """
        FROM kb_articles a
        JOIN app_users u ON a.author_id = u.id
        LEFT JOIN companies c ON a.company_account_number = c.account_number
        LEFT JOIN kb_article_category_link l ON a.id = l.article_id
        LEFT JOIN kb_categories cat ON l.category_id = cat.id
    """
    params = []
    where_clauses = []

    if search_query:
        where_clauses.append("(a.title LIKE ? OR a.content LIKE ? OR cat.name LIKE ? OR c.name LIKE ? OR u.username LIKE ?)")
        search_param = f'%{search_query}%'
        params.extend([search_param, search_param, search_param, search_param, search_param])

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)

    count_query = f"SELECT COUNT(DISTINCT a.id) as count {base_query}"
    total_articles = query_db(count_query, params, one=True)['count']
    total_pages = (total_articles + per_page - 1) // per_page

    allowed_sort_columns = {
        'title': 'a.title',
        'categories': 'categories',
        'author': 'author_name',
        'client': 'company_name',
        'updated_at': 'a.updated_at'
    }
    sort_column = allowed_sort_columns.get(sort_by, 'a.updated_at')

    if sort_order not in ['asc', 'desc']:
        sort_order = 'desc'

    offset = (page - 1) * per_page
    articles_query = f"""
        SELECT a.*, u.username as author_name, c.name as company_name, GROUP_CONCAT(cat.name, ', ') as categories
        {base_query}
        GROUP BY a.id
        ORDER BY {sort_column} {sort_order}
        LIMIT ? OFFSET ?
    """
    articles = query_db(articles_query, params + [per_page, offset])

    return render_template(
        'partials/kb_articles_table.html',
        articles=articles,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        sort_by=sort_by,
        sort_order=sort_order
    )


@kb_bp.route('/article/<int:article_id>')
@role_required(['Admin', 'Editor', 'Contributor', 'Read-Only'])
def view_article(article_id):
    article = query_db("""
        SELECT a.*, u.username as author_name, c.name as company_name
        FROM kb_articles a
        JOIN app_users u ON a.author_id = u.id
        LEFT JOIN companies c ON a.company_account_number = c.account_number
        WHERE a.id = ?
    """, [article_id], one=True)

    if not article:
        flash('Article not found.', 'error')
        return redirect(url_for('kb.kb'))

    categories = query_db("""
        SELECT c.name FROM kb_categories c
        JOIN kb_article_category_link l ON c.id = l.category_id
        WHERE l.article_id = ?
    """, [article_id])

    return render_template('kb_article.html', article=article, categories=categories)

@kb_bp.route('/article/new', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def create_article():
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

        now = datetime.now(timezone.utc).isoformat()

        db = get_db()
        with db:
            cur = log_and_execute(
                "INSERT INTO kb_articles (title, content, author_id, visibility, company_account_number, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [title, content, session['user_id'], visibility_text, company_account_number, now, now]
            )
            article_id = cur.lastrowid
            for cat_id in category_ids:
                db.execute("INSERT INTO kb_article_category_link (article_id, category_id) VALUES (?, ?)", (article_id, cat_id))

        flash('Article created successfully.', 'success')
        return redirect(url_for('kb.view_article', article_id=article_id))

    companies = query_db("SELECT account_number, name FROM companies ORDER BY name")
    categories = query_db("SELECT * FROM kb_categories ORDER BY name")
    return render_template('edit_kb_article.html', article=None, companies=companies, categories=categories, current_categories=[])

@kb_bp.route('/article/edit/<int:article_id>', methods=['GET', 'POST'])
@role_required(['Admin', 'Editor', 'Contributor'])
def edit_article(article_id):
    article = query_db("SELECT * FROM kb_articles WHERE id = ?", [article_id], one=True)
    if not article:
        flash('Article not found.', 'error')
        return redirect(url_for('kb.kb'))

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

        now = datetime.now(timezone.utc).isoformat()

        db = get_db()
        with db:
            log_and_execute(
                "UPDATE kb_articles SET title = ?, content = ?, visibility = ?, company_account_number = ?, updated_at = ? WHERE id = ?",
                [title, content, visibility_text, company_account_number, now, article_id]
            )
            # Update categories
            db.execute("DELETE FROM kb_article_category_link WHERE article_id = ?", [article_id])
            for cat_id in category_ids:
                db.execute("INSERT INTO kb_article_category_link (article_id, category_id) VALUES (?, ?)", (article_id, cat_id))

        flash('Article updated successfully.', 'success')
        return redirect(url_for('kb.view_article', article_id=article_id))

    companies = query_db("SELECT account_number, name FROM companies ORDER BY name")
    categories = query_db("SELECT * FROM kb_categories ORDER BY name")
    current_categories_raw = query_db("SELECT category_id FROM kb_article_category_link WHERE article_id = ?", [article_id])
    current_categories = [row['category_id'] for row in current_categories_raw]

    return render_template('edit_kb_article.html', article=article, companies=companies, categories=categories, current_categories=current_categories)

@kb_bp.route('/article/delete/<int:article_id>', methods=['POST'])
@role_required(['Admin', 'Editor'])
def delete_article(article_id):
    log_and_execute("DELETE FROM kb_articles WHERE id = ?", [article_id])
    flash('Article deleted successfully.', 'success')
    return redirect(url_for('kb.kb'))
