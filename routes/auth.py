# hamnertime/integodash/integodash-api-refactor/routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from api_client import api_request

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # The form now sends 'username' and 'password' which OAuth2PasswordRequestForm expects
        username = request.form.get('username')
        password = request.form.get('password')

        # The data needs to be sent as form data, not JSON
        response = api_request('post', 'settings/users/login', data={'username': username, 'password': password})

        if response and response.get("access_token"):
            session.clear()
            session['api_token'] = response.get("access_token")
            user_details = response.get("user")
            session['user_id'] = user_details.get("id")
            session['username'] = user_details.get("username")
            session['role'] = user_details.get("role")

            flash('Login successful!', 'success')
            return redirect(url_for('clients.billing_dashboard'))
        else:
            flash("Invalid username or password.", 'error')
            return redirect(url_for('auth.login'))

    # For a GET request, fetch users for the dropdown
    users = api_request('get', 'settings/users/')
    if users is None:
        users = []

    return render_template('login.html', users=users)


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for('auth.login'))
