import requests
import base64
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
ACCOUNT_NUMBER_FIELD = "account_number"
COMPANIES_PER_PAGE = 100
MAX_RETRIES = 3

def get_db_connection(db_path, password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con

def get_freshservice_api_key(db_password):
    """Reads the Freshservice API key from the encrypted database."""
    con = get_db_connection(DB_FILE, db_password)
    cur = con.cursor()
    cur.execute("SELECT api_key FROM api_keys WHERE service = 'freshservice'")
    creds = cur.fetchone()
    con.close()
    if not creds:
        raise ValueError("Freshservice credentials not found in the database.")
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
    print("\nFetching all users from Freshservice (this may take a moment)...")
    all_users, page = [], 1
    endpoint = f"{base_url}/api/v2/requesters"
    while True:
        params = {'page': page, 'per_page': 100}
        try:
            print(f"-> Fetching user page {page}...")
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

def get_all_tickets_for_last_month(base_url, headers, start_date_str, end_date_str):
    all_tickets = []
    # --- FIX: Use the correct /filter endpoint ---
    endpoint = f"{base_url}/api/v2/tickets/filter"
    query = f"updated_at:>'{start_date_str}' AND updated_at:<'{end_date_str}'"
    page = 1
    print(f"Fetching all tickets updated between {start_date_str} and {end_date_str}...")
    while True:
        # --- FIX: The query needs to be wrapped in double quotes for the API ---
        params = {'query': f'"{query}"', 'page': page, 'per_page': 100}
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=90)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            data = response.json()
            tickets_on_page = data.get('tickets', [])
            if not tickets_on_page: break
            all_tickets.extend(tickets_on_page)
            page += 1
            time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            print(f"Fatal error fetching tickets for billing: {e}", file=sys.stderr)
            if hasattr(e, 'response') and e.response:
                print(f"Response: {e.response.text}", file=sys.stderr)
            return None
    return all_tickets

def get_time_entries_for_ticket(base_url, headers, ticket_id, start_date, end_date):
    total_hours = 0
    endpoint = f"{base_url}/api/v2/tickets/{ticket_id}/time_entries"
    retries = 0
    while retries < MAX_RETRIES:
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)
            if response.status_code == 429:
                time.sleep(int(response.headers.get('Retry-After', 10)))
                retries += 1
                continue
            if response.status_code == 404: return 0
            response.raise_for_status()
            data = response.json()
            for entry in data.get('time_entries', []):
                entry_created_at = datetime.fromisoformat(entry['created_at'].replace('Z', '+00:00'))
                if start_date <= entry_created_at <= end_date:
                    h, m = map(int, entry.get('time_spent', '00:00').split(':'))
                    total_hours += h + (m / 60.0)
            return total_hours
        except requests.exceptions.RequestException:
            retries += 1
            time.sleep(5)
    return 0

# --- Database Functions ---
def populate_companies_database(db_connection, companies_data):
    cur = db_connection.cursor()
    companies_to_insert = [(str(c.get('custom_fields', {}).get(ACCOUNT_NUMBER_FIELD)), c.get('name'), c.get('id'), c.get('custom_fields', {}).get('type_of_client', 'Unknown'), c.get('custom_fields', {}).get('plan_selected', 'Unknown')) for c in companies_data if (c.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD)]
    if not companies_to_insert: return
    cur.executemany("INSERT INTO companies (account_number, name, freshservice_id, contract_type, billing_plan) VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_number) DO UPDATE SET name=excluded.name, freshservice_id=excluded.freshservice_id, contract_type=excluded.contract_type, billing_plan=excluded.billing_plan;", companies_to_insert)

def populate_users_database(db_connection, users_to_insert):
    if not users_to_insert: return
    cur = db_connection.cursor()
    cur.executemany("INSERT INTO users (company_account_number, freshservice_id, full_name, email, status, date_added) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(freshservice_id) DO UPDATE SET company_account_number=excluded.company_account_number, full_name=excluded.full_name, email=excluded.email, status=excluded.status;", users_to_insert)

def update_ticket_hours(db_connection, hours_data):
    if not hours_data: return
    cur = db_connection.cursor()
    cur.executemany("INSERT INTO ticket_work_hours (company_account_number, month, hours) VALUES (?, ?, ?) ON CONFLICT(company_account_number, month) DO UPDATE SET hours=excluded.hours;", hours_data)

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Running Billing Data Sync (Companies, Users, Hours) ---")
    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        sys.exit("FATAL: DB_MASTER_PASSWORD environment variable not set.")

    try:
        API_KEY = get_freshservice_api_key(DB_MASTER_PASSWORD)
        base_url = f"https://{FRESHSERVICE_DOMAIN}"
        auth_str = f"{API_KEY}:X"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

        companies = get_all_companies(base_url, headers)
        users = get_all_users(base_url, headers)

        if not companies or users is None:
            sys.exit("Could not fetch company or user data from Freshservice. Aborting.")

        # --- Process Billable Hours ---
        today = datetime.now(timezone.utc)
        first_day_of_current_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        month_str = first_day_of_last_month.strftime('%Y-%m')

        all_tickets_last_month = get_all_tickets_for_last_month(base_url, headers, first_day_of_last_month.strftime('%Y-%m-%d'), last_day_of_last_month.strftime('%Y-%m-%d'))

        time_tracking_data = []
        if all_tickets_last_month is None:
            sys.exit("Aborting: Could not fetch tickets for billing period. Skipping hour calculation.")

        tickets_by_company = defaultdict(list)
        for ticket in all_tickets_last_month:
            if ticket.get('department_id'):
                tickets_by_company[ticket['department_id']].append(ticket)

        company_id_map = {c['id']: c for c in companies}
        for company_id, tickets in tickets_by_company.items():
            company_info = company_id_map.get(company_id)
            account_number = (company_info.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD) if company_info else None
            if not account_number: continue

            total_hours_for_company = sum(get_time_entries_for_ticket(base_url, headers, ticket['id'], first_day_of_last_month, last_day_of_last_month.replace(hour=23, minute=59, second=59)) for ticket in tickets)
            if total_hours_for_company > 0:
                time_tracking_data.append((str(account_number), month_str, total_hours_for_company))

        # --- Process Users ---
        all_users_to_insert = []
        company_id_to_account_map = {c.get('id'): (c.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD) for c in companies}
        for user in users:
            for dept_id in (user.get('department_ids') or []):
                if account_num := company_id_to_account_map.get(dept_id):
                    all_users_to_insert.append((str(account_num), user.get('id'), f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(), user.get('primary_email'), 'Active' if user.get('active', False) else 'Inactive', user.get('created_at', datetime.now(timezone.utc).isoformat())))
                    break

        # --- Commit to DB ---
        con = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)
        populate_companies_database(con, companies)
        populate_users_database(con, all_users_to_insert)
        update_ticket_hours(con, time_tracking_data)
        con.commit()
        con.close()
        print("--- Billing Data Sync Successful ---")

    except Exception as e:
        print(f"An error occurred during billing data sync: {e}", file=sys.stderr)
        sys.exit(1)
