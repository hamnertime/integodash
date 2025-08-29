import requests
import os
import sys
import getpass
import json
import time
from datetime import datetime, timezone

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
DB_FILE = "brainhair.db"
DATTO_VARIABLE_NAME = "AccountNumber"
BACKUP_UDF_ID = 6
SERVER_TYPE_UDF_ID = 7 # The UDF number set by the PowerShell component

# --- Utility Functions ---
def get_db_connection(db_path, password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con, cur

def get_datto_creds_from_db(db_password):
    """Reads Datto RMM credentials from the encrypted database."""
    try:
        con, cur = get_db_connection(DB_FILE, db_password)
        cur.execute("SELECT api_endpoint, api_key, api_secret FROM api_keys WHERE service = 'datto'")
        creds = cur.fetchone()
        con.close()
        if not creds:
            raise ValueError("Datto credentials not found in the database.")
        return creds[0], creds[1], creds[2] # endpoint, key, secret
    except sqlite3.Error as e:
        sys.exit(f"Database error while fetching credentials: {e}. Is the password correct?")

# --- API Functions ---
def get_datto_access_token(api_endpoint, api_key, api_secret_key):
    token_url = f"{api_endpoint}/auth/oauth/token"
    payload = {'grant_type': 'password', 'username': api_key, 'password': api_secret_key}
    headers = {'Content-Type': 'application/x-www-form-urlencoded', 'Authorization': 'Basic cHVibGljLWNsaWVudDpwdWJsaWM='}
    try:
        response = requests.post(token_url, headers=headers, data=payload, timeout=30)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.exceptions.RequestException as e:
        print(f"Error getting Datto access token: {e}", file=sys.stderr)
        return None

def get_paginated_api_request(api_endpoint, access_token, api_request_path):
    all_items = []
    next_page_url = f"{api_endpoint}/api{api_request_path}"
    headers = {'Authorization': f'Bearer {access_token}'}
    while next_page_url:
        try:
            response = requests.get(next_page_url, headers=headers, timeout=30)
            response.raise_for_status()
            response_data = response.json()
            items_on_page = response_data.get('items') or response_data.get('sites') or response_data.get('devices')
            if items_on_page is None: break
            all_items.extend(items_on_page)
            next_page_url = response_data.get('pageDetails', {}).get('nextPageUrl') or response_data.get('nextPageUrl')
        except requests.exceptions.RequestException as e:
            print(f"An error occurred during paginated API request for {api_request_path}: {e}", file=sys.stderr)
            return None
    return all_items

def get_site_variable(api_endpoint, access_token, site_uid, variable_name):
    request_url = f"{api_endpoint}/api/v2/site/{site_uid}/variables"
    headers = {'Authorization': f'Bearer {access_token}'}
    try:
        response = requests.get(request_url, headers=headers, timeout=30)
        if response.status_code == 404: return None
        response.raise_for_status()
        variables = response.json().get("variables", [])
        for var in variables:
            if var.get("name") == variable_name:
                return var.get("value")
        return None
    except requests.exceptions.RequestException:
        return None

# --- Database Function ---
def populate_assets_database(db_password, assets_to_insert):
    con = None
    try:
        con, cur = get_db_connection(DB_FILE, db_password)
        print(f"\nAttempting to insert/update {len(assets_to_insert)} assets into the database...")

        # The columns list must match the order of values in the assets_to_insert tuples
        columns = [
            'company_account_number', 'datto_uid', 'hostname', 'friendly_name', 'device_type',
            'billing_type', 'operating_system', 'status', 'date_added', 'backup_data_bytes',
            'internal_ip', 'external_ip', 'last_logged_in_user', 'domain', 'is_64_bit',
            'is_online', 'last_seen', 'last_reboot', 'last_audit_date', 'udf_data',
            'antivirus_data', 'patch_management_data', 'portal_url', 'web_remote_url'
        ]

        placeholders = ', '.join(['?'] * len(columns))
        update_setters = ', '.join([f"{col}=excluded.{col}" for col in columns])

        sql = f"""
            INSERT INTO assets ({', '.join(columns)})
            VALUES ({placeholders})
            ON CONFLICT(datto_uid) DO UPDATE SET {update_setters};
        """

        cur.executemany(sql, assets_to_insert)
        con.commit()
        print(f" Successfully inserted/updated {cur.rowcount} assets in '{DB_FILE}'.")
    except sqlite3.Error as e:
        print(f"\n❌ Database error: {e}", file=sys.stderr)
        if con: con.rollback()
        sys.exit(1)
    finally:
        if con: con.close()


def update_company_datto_info(db_password, account_number, site_uid, portal_url):
    """Updates the company record with the Datto site UID and Portal URL."""
    con = None
    try:
        con, cur = get_db_connection(DB_FILE, db_password)
        cur.execute("UPDATE companies SET datto_site_uid = ?, datto_portal_url = ? WHERE account_number = ?", (site_uid, portal_url, account_number))
        con.commit()
        if cur.rowcount > 0:
            print(f"   -> Successfully linked site UID {site_uid} and Portal URL to account {account_number}.")
    except sqlite3.Error as e:
        print(f"\n❌ Database error while updating Datto info: {e}", file=sys.stderr)
        if con: con.rollback()
    finally:
        if con: con.close()

def format_timestamp(ms_timestamp):
    """Converts a millisecond timestamp to an ISO 8601 string, or returns None."""
    if ms_timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(ms_timestamp / 1000, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        return None

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Datto RMM Data Syncer ---")
    if not os.path.exists(DB_FILE):
        sys.exit(f"Error: Database file '{DB_FILE}' not found. Please run init_db.py script first.")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database password: ")
        except (getpass.GetPassWarning, NameError):
             DB_MASTER_PASSWORD = input("Please enter the database password: ")
    if not DB_MASTER_PASSWORD:
        sys.exit("FATAL: No database password provided. Aborting.")

    endpoint, api_key, secret_key = get_datto_creds_from_db(DB_MASTER_PASSWORD)
    token = get_datto_access_token(endpoint, api_key, secret_key)
    if not token: sys.exit("\n❌ Failed to obtain access token.")

    sites = get_paginated_api_request(endpoint, token, "/v2/account/sites")
    if sites is None: sys.exit("\nCould not retrieve sites list.")
    print(f"\nFound {len(sites)} total sites in Datto.")

    assets_to_insert = []
    print("\n--- Processing Sites and Devices ---")
    for i, site in enumerate(sites, 1):
        site_uid, site_name = site.get('uid'), site.get('name')
        if not site_uid: continue

        print(f"-> ({i}/{len(sites)}) Processing site: '{site_name}'")

        account_number = get_site_variable(endpoint, token, site_uid, DATTO_VARIABLE_NAME)
        if not account_number:
            print(f"   -> Skipping: No '{DATTO_VARIABLE_NAME}' variable found.")
            continue

        portal_url = site.get('portalUrl')
        update_company_datto_info(DB_MASTER_PASSWORD, account_number, site_uid, portal_url)

        print(f"   -> Found Account Number: {account_number}. Fetching devices...")
        devices_in_site = get_paginated_api_request(endpoint, token, f"/v2/site/{site_uid}/devices")

        if devices_in_site:
            print(f"   -> Found {len(devices_in_site)} devices. Preparing for DB insert.")
            for device in devices_in_site:

                udf_dict = device.get('udf', {}) or {}

                billing_type = "Workstation"
                if (device.get('deviceType') or {}).get('category') == 'Server':
                    server_type_from_udf = udf_dict.get(f'udf{SERVER_TYPE_UDF_ID}')
                    if server_type_from_udf == 'VM':
                        billing_type = 'VM'
                    else:
                        billing_type = 'Server'

                backup_data_bytes = 0
                value_str = udf_dict.get(f'udf{BACKUP_UDF_ID}')
                if value_str:
                    try:
                        backup_data_bytes = int(value_str)
                    except (ValueError, TypeError):
                        backup_data_bytes = 0

                assets_to_insert.append((
                    account_number,
                    device.get('uid'),
                    device.get('hostname'),
                    device.get('description'),
                    (device.get('deviceType') or {}).get('category'),
                    billing_type,
                    device.get('operatingSystem'),
                    'Active',
                    format_timestamp(device.get('creationDate')),
                    backup_data_bytes,
                    device.get('intIpAddress'),
                    device.get('extIpAddress'),
                    device.get('lastLoggedInUser'),
                    device.get('domain'),
                    device.get('a64Bit'),
                    device.get('online'),
                    format_timestamp(device.get('lastSeen')),
                    format_timestamp(device.get('lastReboot')),
                    format_timestamp(device.get('lastAuditDate')),
                    json.dumps(udf_dict),
                    json.dumps(device.get('antivirus')),
                    json.dumps(device.get('patchManagement')),
                    device.get('portalUrl'),
                    device.get('webRemoteUrl')
                ))

    if assets_to_insert:
        populate_assets_database(DB_MASTER_PASSWORD, assets_to_insert)
    else:
        print("\nNo devices found with linked account numbers. DB not modified.")

    print("\nScript finished.")
