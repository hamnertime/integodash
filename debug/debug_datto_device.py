import requests
import os
import sys
import getpass
import json
import argparse
import time

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"

def get_db_connection(db_path, password):
    if not password: raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con

def get_datto_creds_from_db(db_password):
    """Reads Datto RMM credentials from the encrypted database."""
    try:
        con = get_db_connection(DB_FILE, db_password)
        cur = con.cursor()
        cur.execute("SELECT api_endpoint, api_key, api_secret FROM api_keys WHERE service = 'datto'")
        creds = cur.fetchone()
        con.close()
        if not creds:
            raise ValueError("Datto credentials not found in the database.")
        return creds[0], creds[1], creds[2] # endpoint, key, secret
    except sqlite3.Error as e:
        sys.exit(f"Database error while fetching credentials: {e}. Is the password correct?")

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
            time.sleep(0.5) # Be respectful of API limits
        except requests.exceptions.RequestException as e:
            print(f"An error occurred during paginated API request for {api_request_path}: {e}", file=sys.stderr)
            return None
    return all_items

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug script to fetch and display all data for a specific Datto RMM device.")
    parser.add_argument("hostname", help="The hostname of the device to look up in Datto RMM.")
    args = parser.parse_args()

    print("--- Datto RMM Device Data Debugger ---")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database password: ")
        except (getpass.GetPassWarning, NameError):
             DB_MASTER_PASSWORD = input("Please enter the database password: ")
    if not DB_MASTER_PASSWORD:
        sys.exit("FATAL: No database password provided. Aborting.")

    try:
        endpoint, api_key, secret_key = get_datto_creds_from_db(DB_MASTER_PASSWORD)
        token = get_datto_access_token(endpoint, api_key, secret_key)
        if not token:
            sys.exit("Failed to obtain Datto RMM access token.")

        sites = get_paginated_api_request(endpoint, token, "/v2/account/sites")
        if sites is None:
            sys.exit("Failed to fetch sites from Datto RMM.")

        print(f"\nSearching for device with hostname '{args.hostname}' across {len(sites)} sites...")
        found_device = None
        
        for site in sites:
            site_uid = site.get('uid')
            site_name = site.get('name')
            print(f"  -> Searching in site: {site_name}")
            devices_in_site = get_paginated_api_request(endpoint, token, f"/v2/site/{site_uid}/devices")
            if devices_in_site:
                for device in devices_in_site:
                    if args.hostname.lower() == device.get('hostname', '').lower():
                        found_device = device
                        break
            if found_device:
                break
        
        if found_device:
            print(f"\n--- Found data for device '{args.hostname}' in site '{site_name}' ---")
            print(json.dumps(found_device, indent=4))
            print("----------------------------------------------------")
        else:
            print(f"\n--- No device found with hostname matching '{args.hostname}' ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
