import requests
import base64
import os
import sys
import getpass
import json
import argparse

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"

def get_db_connection(db_path, password):
    if not password: raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con

def get_freshservice_api_key(db_password):
    con = get_db_connection(DB_FILE, db_password)
    cur = con.cursor()
    cur.execute("SELECT api_key FROM api_keys WHERE service = 'freshservice'")
    creds = cur.fetchone()
    con.close()
    if not creds: raise ValueError("Freshservice credentials not found in the database.")
    return creds[0]

def get_all_companies(base_url, headers):
    """Fetches all companies (departments) from the Freshservice API."""
    all_companies, page = [], 1
    endpoint = f"{base_url}/api/v2/departments"
    print(f"Fetching all companies from: {endpoint}")

    while True:
        params = {'page': page, 'per_page': 100}
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                print(f"Rate limit exceeded. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            data = response.json()
            companies_on_page = data.get('departments', [])
            if not companies_on_page:
                break
            all_companies.extend(companies_on_page)
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"Error fetching companies: {e}", file=sys.stderr)
            return None
    return all_companies

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug script to fetch and display all data for a specific Freshservice client.")
    parser.add_argument("client_name", help="The name of the client to look up in Freshservice.")
    args = parser.parse_args()

    print("--- Freshservice Client Data Debugger ---")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database password: ")
        except (getpass.GetPassWarning, NameError):
             DB_MASTER_PASSWORD = input("Please enter the database password: ")
    if not DB_MASTER_PASSWORD:
        sys.exit("FATAL: No database password provided. Aborting.")

    try:
        API_KEY = get_freshservice_api_key(DB_MASTER_PASSWORD)
        base_url = f"https://{FRESHSERVICE_DOMAIN}"
        auth_str = f"{API_KEY}:X"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

        companies = get_all_companies(base_url, headers)
        if companies is None:
            sys.exit("Failed to fetch companies from Freshservice.")

        found_client = None
        for company in companies:
            if args.client_name.lower() in company.get('name', '').lower():
                found_client = company
                break
        
        if found_client:
            print(f"\n--- Found data for client matching '{args.client_name}' ---")
            print(json.dumps(found_client, indent=4))
            print("----------------------------------------------------")
        else:
            print(f"\n--- No client found matching '{args.client_name}' ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        sys.exit(1)
