import requests
import base64
import os
import sys
import time
import getpass
from datetime import datetime, timezone, date
from collections import defaultdict

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
ACCOUNT_NUMBER_FIELD = "account_number"
CONTRACT_TERM_FIELD = "contract_term_length"
CONTRACT_START_DATE_FIELD = "contract_start_date"
COMPANIES_PER_PAGE = 100
MAX_RETRIES = 3

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

# --- API Functions ---
def get_all_companies(base_url, headers):
    print("Fetching companies from Freshservice...")
    all_companies, page = [], 1
    endpoint = f"{base_url}/api/v2/departments"
    while True:
        try:
            params = {'page': page, 'per_page': COMPANIES_PER_PAGE}
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            companies_on_page = data.get('departments', [])
            if not companies_on_page: break
            all_companies.extend(companies_on_page)
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"Error fetching Freshservice companies: {e}", file=sys.stderr)
            return None
    print(f" Found {len(all_companies)} companies in Freshservice.")
    return all_companies

def get_all_users(base_url, headers):
    print("\nFetching all users from Freshservice...")
    all_users, page = [], 1
    endpoint = f"{base_url}/api/v2/requesters"
    while True:
        params = {'page': page, 'per_page': 100}
        try:
            # print(f"-> Fetching user page {page}...") # Optional: uncomment for very verbose logging
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                print(f"   -> Rate limit exceeded, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            data = response.json()
            users_on_page = data.get('requesters', [])
            if not users_on_page: break
            all_users.extend(users_on_page)
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"   -> Error fetching users on page {page}: {e}", file=sys.stderr)
            return None
    print(f" Found {len(all_users)} total users in Freshservice.")
    return all_users

# --- Database Functions ---
def populate_companies_database(db_connection, companies_data):
    cur = db_connection.cursor()
    companies_to_insert = []
    start_of_year = date(date.today().year, 1, 1).isoformat()

    print("\nProcessing and logging contract details for each company...")
    for c in companies_data:
        custom_fields = c.get('custom_fields', {}) or {}
        company_name = c.get('name', 'Unknown Company')
        account_number = custom_fields.get(ACCOUNT_NUMBER_FIELD)

        if not account_number:
            continue

        term_length = custom_fields.get(CONTRACT_TERM_FIELD)
        start_date = custom_fields.get(CONTRACT_START_DATE_FIELD)

        log_msg_prefix = f"-> {company_name}:"

        if not term_length:
            print(f"{log_msg_prefix} No contract term found. Defaulting to '1-Year'.")
            term_length = '1-Year'
        else:
            print(f"{log_msg_prefix} Found contract term: '{term_length}'.")

        if not start_date:
            print(f"{log_msg_prefix} No start date found. Defaulting to '{start_of_year}'.")
            start_date = start_of_year
        else:
             print(f"{log_msg_prefix} Found start date: '{start_date}'.")

        companies_to_insert.append((
            str(account_number),
            c.get('name'),
            c.get('id'),
            custom_fields.get('type_of_client', 'Unknown'),
            custom_fields.get('plan_selected', 'Unknown'),
            term_length,
            start_date
        ))

    if not companies_to_insert: return

    cur.executemany("""
        INSERT INTO companies (account_number, name, freshservice_id, contract_type, billing_plan, contract_term_length, contract_start_date)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(account_number) DO UPDATE SET
            name=excluded.name, freshservice_id=excluded.freshservice_id, contract_type=excluded.contract_type,
            billing_plan=excluded.billing_plan, contract_term_length=excluded.contract_term_length, contract_start_date=excluded.contract_start_date
    """, companies_to_insert)
    print(f"\nSuccessfully inserted/updated {cur.rowcount} companies in the database.")


def populate_users_database(db_connection, users_to_insert):
    if not users_to_insert: return
    cur = db_connection.cursor()
    cur.executemany("""
        INSERT INTO users (company_account_number, freshservice_id, full_name, email, status, date_added) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(freshservice_id) DO UPDATE SET
            company_account_number=excluded.company_account_number, full_name=excluded.full_name, email=excluded.email, status=excluded.status
    """, users_to_insert)
    print(f"Successfully inserted/updated {cur.rowcount} users in the database.")


# --- Main Execution ---
if __name__ == "__main__":
    print("--- Running Freshservice Data Sync Script ---")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        print("DB_MASTER_PASSWORD environment variable not set.")
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database password: ")
        except getpass.GetPassWarning:
            print("Warning: Password input may be echoed.", file=sys.stderr)
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
        users = get_all_users(base_url, headers)

        if not companies or users is None:
            sys.exit("Could not fetch company or user data from Freshservice. Aborting sync.")

        all_users_to_insert = []
        company_id_to_account_map = {c.get('id'): (c.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD) for c in companies}
        for user in users:
            for dept_id in (user.get('department_ids') or []):
                if account_num := company_id_to_account_map.get(dept_id):
                    all_users_to_insert.append((
                        str(account_num), user.get('id'), f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                        user.get('primary_email'), 'Active' if user.get('active', False) else 'Inactive',
                        user.get('created_at', datetime.now(timezone.utc).isoformat())
                    ))
                    break

        con = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)
        populate_companies_database(con, companies)
        populate_users_database(con, all_users_to_insert)
        con.commit()
        con.close()
        print("\n--- Freshservice Data Sync Successful ---")

    except Exception as e:
        print(f"\nAn error occurred during data sync: {e}", file=sys.stderr)
        sys.exit(1)
