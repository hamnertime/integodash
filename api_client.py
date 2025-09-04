import requests
import sys
from flask import session, flash, redirect, url_for, current_app
from requests_toolbelt.multipart.encoder import MultipartEncoder
from io import BytesIO

def get_api_base_url():
    """Gets the API base url from the application config."""
    return current_app.config.get('API_BASE_URL', 'http://127.0.0.1:8000/api/v1')

def api_request(method, endpoint, params=None, json_data=None, data=None, files=None, timeout=30):
    """A centralized wrapper for making requests to the Integobase API."""
    url = f"{get_api_base_url()}/{endpoint}"
    headers = {}
    if 'api_token' in session:
        headers['Authorization'] = f"Bearer {session['api_token']}"

    try:
        if files:
            # Prepare multipart form data for file uploads
            fields = {**data} if data else {}
            for name, file in files.items():
                # file is a FileStorage object from Flask
                file_content = file.read()
                file_object = BytesIO(file_content)
                fields[name] = (file.filename, file_object, file.mimetype)

            multipart_data = MultipartEncoder(fields=fields)
            headers['Content-Type'] = multipart_data.content_type

            # Reset file stream position after reading
            for name, file in files.items():
                file.seek(0)

            response = requests.request(method, url, headers=headers, data=multipart_data, params=params, timeout=timeout)
        else:
            response = requests.request(method, url, headers=headers, params=params, json=json_data, data=data, timeout=timeout)

        if response.status_code == 401:
            session.clear()
            flash("Your session has expired. Please log in again.", "error")
            return None

        response.raise_for_status()
        if response.status_code == 204:
            return True
        return response.json()

    except requests.exceptions.RequestException as e:
        print(f"API request to '{url}' failed: {e}", file=sys.stderr)
        flash("Could not connect to the backend API. Please ensure Integobase is running.", "error")
        return None
