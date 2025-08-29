# hamnertime/integodash/integodash-b7a03f16877fb4e6590039b6f2c0b632176ef6cd/pull_freshservice.py
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
PHONE_NUMBER_FIELD = "company_main_number"
CLIENT_START_DATE_FIELD = "company_start_date"
BUSINESS_TYPE_FIELD = "profit_or_non_profit"
ADDRESS_FIELD = "address"


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
    locations_to_upsert = []
    start_of_year = date(date.today().year, 1, 1).isoformat()

    print("\nProcessing and logging contract details for each company...")
    for c in companies_data:
        custom_fields = c.get('custom_fields', {}) or {}
        company_name = c.get('name', 'Unknown Company')
        account_number = custom_fields.get(ACCOUNT_NUMBER_FIELD)

        if not account_number:
            continue

        phone_number = custom_fields.get(PHONE_NUMBER_FIELD)
        address = custom_fields.get(ADDRESS_FIELD)
        client_start_date = custom_fields.get(CLIENT_START_DATE_FIELD)
        domains = ', '.join(c.get('domains', []))
        company_owner = c.get('head_name')
        business_type = custom_fields.get(BUSINESS_TYPE_FIELD)


        log_msg_prefix = f"-> {company_name}:"

        companies_to_insert.append((
            str(account_number),
            c.get('name'),
            c.get('id'),
            custom_fields.get('type_of_client', 'Unknown'),
            custom_fields.get('plan_selected', 'Unknown'),
            custom_fields.get('support_level', 'Billed Hourly'),
            phone_number,
            client_start_date,
            domains,
            company_owner,
            business_type
        ))

        if address:
            locations_to_upsert.append({
                'account_number': str(account_number),
                'location_name': 'Main Office',
                'address': address
            })

    if not companies_to_insert: return

    cur.executemany("""
        INSERT INTO companies (account_number, name, freshservice_id, contract_type, billing_plan, support_level, phone_number, client_start_date, domains, company_owner, business_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(freshservice_id) DO UPDATE SET
            name=excluded.name,
            account_number=excluded.account_number,
            contract_type=excluded.contract_type,
            billing_plan=excluded.billing_plan,
            support_level=excluded.support_level,
            phone_number=excluded.phone_number,
            client_start_date=excluded.client_start_date,
            domains=excluded.domains,
            company_owner=excluded.company_owner,
            business_type=excluded.business_type
    """, companies_to_insert)
    print(f"\nSuccessfully inserted/updated {cur.rowcount} companies in the database.")

    if locations_to_upsert:
        print("\nUpserting Main Office locations...")
        upsert_count = 0
        for loc in locations_to_upsert:
            # Check if the company exists before trying to insert a location
            cur.execute("SELECT 1 FROM companies WHERE account_number = ?", (loc['account_number'],))
            if cur.fetchone():
                cur.execute("""
                    INSERT INTO client_locations (company_account_number, location_name, address)
                    VALUES (?, ?, ?)
                    ON CONFLICT(company_account_number, location_name) DO UPDATE SET
                        address=excluded.address
                """, (loc['account_number'], loc['location_name'], loc['address']))
                upsert_count += cur.rowcount
            else:
                print(f"  - ⚠️  Skipping location for non-existent company account: {loc['account_number']}", file=sys.stderr)

        print(f"Successfully upserted {upsert_count} Main Office locations.")


def populate_users_database(db_connection, users_to_insert):
    if not users_to_insert: return
    cur = db_connection.cursor()
    cur.executemany("""
        INSERT INTO users (company_account_number, freshservice_id, full_name, email, status, date_added, billing_type) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(freshservice_id) DO UPDATE SET
            company_account_number=excluded.company_account_number, full_name=excluded.full_name, email=excluded.email, status=excluded.status, billing_type=excluded.billing_type
    """, users_to_insert)
    print(f"Successfully inserted/updated {cur.rowcount} users in the database.")

def populate_contacts_database(db_connection, contacts_to_insert):
    if not contacts_to_insert: return
    cur = db_connection.cursor()
    cur.executemany("""
        INSERT INTO contacts (company_account_number, first_name, last_name, email, title, work_phone, mobile_phone, employment_type, status, other_emails, address, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(email) DO UPDATE SET
            company_account_number=excluded.company_account_number,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            title=excluded.title,
            work_phone=excluded.work_phone,
            mobile_phone=excluded.mobile_phone,
            employment_type=excluded.employment_type,
            status=excluded.status,
            other_emails=excluded.other_emails,
            address=excluded.address,
            notes=excluded.notes
    """, contacts_to_insert)
    print(f"Successfully inserted/updated {cur.rowcount} contacts in the database.")

def offboard_deactivated_users(db_connection, users_from_api):
    """
    Identifies users who are inactive in the API response and deletes them from the local database.
    """
    cur = db_connection.cursor()

    deactivated_users = {user['primary_email']: user['id'] for user in users_from_api if not user.get('active', False) and user.get('primary_email')}

    if not deactivated_users:
        print("\nNo deactivated users found in Freshservice to offboard.")
        return

    user_ids_to_delete = list(deactivated_users.values())
    emails_to_delete = list(deactivated_users.keys())

    user_id_tuples = [(user_id,) for user_id in user_ids_to_delete]
    email_tuples = [(email,) for email in emails_to_delete]


    print(f"\nFound {len(deactivated_users)} deactivated users. Removing from local database...")

    cur.execute("CREATE TEMP TABLE ids_to_delete (id INTEGER PRIMARY KEY);")
    cur.executemany("INSERT INTO ids_to_delete (id) VALUES (?)", user_id_tuples)

    cur.execute("CREATE TEMP TABLE emails_to_delete (email TEXT PRIMARY KEY);")
    cur.executemany("INSERT INTO emails_to_delete (email) VALUES (?)", email_tuples)

    cur.execute("DELETE FROM users WHERE freshservice_id IN (SELECT id FROM ids_to_delete);")
    cur.execute("DELETE FROM contacts WHERE email IN (SELECT email FROM emails_to_delete);")

    deleted_count = cur.rowcount
    if deleted_count > 0:
        print(f"Successfully removed {deleted_count} deactivated users from the local database.")

    db_connection.commit()


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

        con = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)

        offboard_deactivated_users(con, users)

        active_users_to_insert = []
        contacts_to_insert = []
        company_id_to_account_map = {c.get('id'): (c.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD) for c in companies}
        processed_emails = set()

        for user in users:
            if not user.get('active', False):
                continue

            email = user.get('primary_email')
            if not email or email in processed_emails:
                continue

            for dept_id in (user.get('department_ids') or []):
                if account_num := company_id_to_account_map.get(dept_id):
                    active_users_to_insert.append((
                        str(account_num),
                        user.get('id'),
                        f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                        email,
                        'Active',
                        user.get('created_at', datetime.now(timezone.utc).isoformat()),
                        'Regular'
                    ))
                    contacts_to_insert.append((
                        str(account_num),
                        user.get('first_name'),
                        user.get('last_name'),
                        email,
                        user.get('job_title'),
                        user.get('work_phone_number'),
                        user.get('mobile_phone_number'),
                        'Full Time', # Assuming full-time, can be changed later
                        'Active',
                        ', '.join(user.get('other_emails', [])),
                        user.get('address'),
                        user.get('description')
                    ))
                    processed_emails.add(email)
                    break

        populate_companies_database(con, companies)
        populate_users_database(con, active_users_to_insert)
        populate_contacts_database(con, contacts_to_insert)

        con.commit()
        con.close()
        print("\n--- Freshservice Data Sync Successful ---")

    except Exception as e:
        print(f"\nAn error occurred during data sync: {e}", file=sys.stderr)
        sys.exit(1)
