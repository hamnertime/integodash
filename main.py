import os
from flask import Flask, session, redirect, url_for, request, flash
from datetime import timedelta

# Import blueprints
from routes.auth import auth_bp
from routes.clients import clients_bp
from routes.assets import assets_bp
from routes.contacts import contacts_bp
from routes.settings import settings_bp
from routes.knowledge_base import kb_bp
from utils import register_template_filters, inject_custom_links

def create_app():
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.secret_key = os.urandom(24)
    app.config['UPLOAD_FOLDER'] = 'uploads'
    app.config['API_BASE_URL'] = 'http://127.0.0.1:8000/api/v1'
    app.permanent_session_lifetime = timedelta(hours=8)

    # Register blueprints
    register_template_filters(app)
    app.context_processor(inject_custom_links)
    app.register_blueprint(auth_bp)
    app.register_blueprint(clients_bp)
    app.register_blueprint(assets_bp, url_prefix='/assets')
    app.register_blueprint(contacts_bp, url_prefix='/contacts')
    app.register_blueprint(settings_bp)
    app.register_blueprint(kb_bp, url_prefix='/kb')

    @app.before_request
    def before_request_tasks():
        session.permanent = True
        # Allow access to login, user selection, and static files without a token
        if request.endpoint and (request.endpoint.startswith('static') or request.endpoint in ['auth.login', 'auth.select_user']):
            return
        # If there's no token, redirect to login
        if 'api_token' not in session:
            flash("Your session has expired. Please log in again.", "error")
            return redirect(url_for('auth.login'))

    return app

app = create_app()

if __name__ == '__main__':
    if not os.path.exists('cert.pem') or not os.path.exists('key.pem'):
        print("SSL certificate not found. Run 'python generate_cert.py' first.")
    else:
        app.run(debug=True, host='0.0.0.0', port=5002, ssl_context=('cert.pem', 'key.pem'))
