# hamnertime/integodash/integodash-api-refactor/database.py
import json
import sys
from flask import session, current_app
from api_client import api_request

# This file has been refactored to use the backend API for all data access.
# All functions related to direct database connection, querying, and execution
# have been removed as the frontend no longer has a local database.

# The default_widget_layouts dictionary is a fallback if the API call fails.
default_widget_layouts = {
    "client_details": [
        {"w": 12, "h": 1, "id": "billing-period-selector-widget", "x": 0, "y": 0},
        {"w": 6, "h": 4, "id": "client-details-widget", "x": 0, "y": 1},
        {"w": 6, "h": 4, "id": "client-features-widget", "x": 6, "y": 1},
        {"w": 6, "h": 2, "id": "locations-widget", "x": 0, "y": 5},
        {"w": 6, "h": 5, "id": "billing-receipt-widget", "x": 6, "y": 5},
        {"w": 6, "h": 3, "id": "contract-details-widget", "x": 0, "y": 7},
        {"w": 6, "h": 4, "id": "notes-widget", "x": 0, "y": 10},
        {"w": 6, "h": 4, "id": "attachments-widget", "x": 6, "y": 10},
        {"w": 12, "h": 3, "id": "tracked-assets-widget", "x": 0, "y": 14},
        {"w": 12, "h": 3, "id": "ticket-breakdown-widget", "x": 0, "y": 17}
    ],
    "client_settings": [
        {"w": 6, "h": 5, "id": "client-details-widget", "x": 0, "y": 0},
        {"x": 6, "w": 6, "h": 5, "id": "contract-details-widget", "y": 0},
        {"y": 5, "w": 12, "h": 4, "id": "locations-settings-widget", "x": 0},
        {"y": 9, "w": 12, "h": 7, "id": "billing-overrides-widget", "x": 0},
        {"y": 16, "w": 12, "h": 4, "id": "feature-overrides-widget", "x": 0},
        {"y": 20, "w": 12, "h": 4, "id": "custom-line-items-widget", "x": 0},
        {"x": 0, "y": 24, "w": 6, "h": 4, "id": "add-manual-user-widget"},
        {"y": 24, "w": 6, "h": 4, "id": "add-manual-asset-widget", "x": 6},
        {"y": 28, "w": 12, "h": 3, "id": "user-overrides-widget", "x": 0},
        {"y": 31, "w": 12, "h": 4, "id": "asset-overrides-widget", "x": 0}
    ],
    "clients": [
        {"x": 0, "y": 0, "w": 12, "h": 8, "id": "clients-table-widget"},
        {"w": 12, "h": 2, "id": "export-all-widget", "x": 0, "y": 8}
    ],
    "settings": [
        {"w": 12, "h": 2, "id": "import-export-widget", "x": 0, "y": 0},
        {"x": 0, "w": 12, "h": 4, "id": "scheduler-widget", "y": 2},
        {"y": 6, "w": 12, "h": 7, "id": "users-auditing-widget", "x": 0},
        {"y": 13, "w": 12, "h": 4, "id": "password-reset-widget", "x": 0},
        {"y": 17, "w": 12, "h": 3, "id": "custom-links-widget", "x": 0},
        {"y": 20, "w": 12, "h": 8, "id": "billing-plans-widget", "x": 0},
        {"x": 0, "y": 28, "w": 12, "h": 8, "id": "feature-options-widget"}
    ],
    "kb": [
        {"x": 0, "y": 0, "w": 12, "h": 8, "id": "kb-articles-table-widget"}
    ],
    "contact_details": [
        {"x": 0, "y": 0, "w": 7, "h": 6, "id": "contact-info-widget"},
        {"x": 7, "y": 0, "w": 5, "h": 6, "id": "associated-assets-widget"},
        {"x": 0, "y": 6, "w": 12, "h": 4, "id": "contact-notes-widget"}
    ]
}

def get_user_widget_layout(user_id, page_name):
    """
    Fetches the widget layout for a specific user and page from the API.
    If the API call fails, it falls back to the default layout.
    """
    layout_data = api_request('get', f'settings/layouts/{user_id}/{page_name}')
    if layout_data:
        return layout_data

    return default_widget_layouts.get(page_name)


def save_user_widget_layout(user_id, page_name, layout):
    """Saves or updates the widget layout for a specific user and page via the API."""
    api_request(
        'post',
        f'settings/layouts/{user_id}/{page_name}',
        json_data={'layout': json.dumps(layout)}
    )

def delete_user_widget_layout(user_id, page_name):
    """Deletes the saved widget layout for a specific user and page via the API."""
    api_request('delete', f'settings/layouts/{user_id}/{page_name}')
