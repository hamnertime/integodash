import requests
import os
import sys
import getpass
import json
import argparse
import re

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

def get_all_sites(api_endpoint, access_token):
    """Fetches all sites from the Datto RMM API."""
    all_sites = []
    next_page_url = f"{api_endpoint}/api/v2/account/sites"
    headers = {'Authorization': f'Bearer {access_token}'}
    print("Fetching all sites from Datto RMM...")
    while next_page_url:
        try:
            response = requests.get(next_page_url, headers=headers, timeout=30)
            response.raise_for_status()
            data = response.json()
            sites_on_page = data.get('sites', [])
            if not sites_on_page:
                break
            all_sites.extend(sites_on_page)
            next_page_url = data.get('pageDetails', {}).get('nextPageUrl')
        except requests.exceptions.RequestException as e:
            print(f"Error fetching sites: {e}", file=sys.stderr)
            return None
    return all_sites

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug script to fetch and display all data for a specific Datto RMM site.")
    parser.add_argument("client_name", help="The name of the client site to look up in Datto RMM.")
    args = parser.parse_args()

    print("--- Datto RMM Client Data Debugger ---")

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

        sites = get_all_sites(endpoint, token)
        if sites is None:
            sys.exit("Failed to fetch sites from Datto RMM.")

        found_site = None
        for site in sites:
            if args.client_name.lower() in site.get('name', '').lower():
                found_site = site
                break

        if found_site:
            print(f"\n--- Found data for site matching '{args.client_name}' ---")
            print(json.dumps(found_site, indent=4))

            # Also generate the URL for verification
            base_url = endpoint.replace('api.', '').replace('.datto.com', '.rmm.datto.com')
            client_name_slug = re.sub(r'[^a-z0-9]+', '-', found_site.get('name', '').lower()).strip('-')
            datto_site_url = f"{base_url}/site/{found_site['uid']}/{client_name_slug}"
            print("\n--- Generated URL ---")
            print(datto_site_url)
            print("-----------------------")

        else:
            print(f"\n--- No site found matching '{args.client_name}' ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
