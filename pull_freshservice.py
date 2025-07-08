import requests
import base64
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
ACCOUNT_NUMBER_FIELD = "account_number"
COMPANIES_PER_PAGE = 100
MAX_RETRIES = 3 # Max number of retries for a single API call

# --- Utility Functions ---
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
    try:
        con = get_db_connection(DB_FILE, db_password)
        cur = con.cursor()
        cur.execute("SELECT api_key FROM api_keys WHERE service = 'freshservice'")
        creds = cur.fetchone()
        con.close()
        if not creds:
            raise ValueError("Freshservice credentials not found in the database.")
        return creds[0]
    except sqlite3.Error as e:
        sys.exit(f"Database error while fetching credentials: {e}. Is the password correct?")

# --- API Functions (Unchanged from your version) ---
def get_all_companies(base_url, headers):
    """Fetches all companies (departments) from the Freshservice API."""
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
    """Fetches ALL users (requesters) from the Freshservice API."""
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
    """Fetches ALL tickets updated in the last month."""
    all_tickets = []
    endpoint = f"{base_url}/api/v2/tickets/filter"
    query = f"updated_at:>'{start_date_str}' AND updated_at:<'{end_date_str}'"
    page = 1

    print(f"Fetching all tickets updated between {start_date_str} and {end_date_str}...")

    while True:
        params = {'query': f'"{query}"', 'page': page, 'per_page': 100}
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=90)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"   -> Rate limit hit, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue

            response.raise_for_status()
            data = response.json()

            tickets_on_page = data.get('tickets', [])
            if not tickets_on_page:
                break

            all_tickets.extend(tickets_on_page)
            print(f"  -> Fetched page {page}, total tickets so far: {len(all_tickets)}")
            page += 1
            time.sleep(0.5)

        except requests.exceptions.RequestException as e:
            print(f"Fatal error fetching tickets: {e}", file=sys.stderr)
            if hasattr(e, 'response') and e.response is not None:
                 print(f"   -> Response: {e.response.text}", file=sys.stderr)
            return None

    return all_tickets

def get_time_entries_for_ticket(base_url, headers, ticket_id, start_date, end_date):
    """Fetches time entries for a single ticket, with retries for rate limiting."""
    total_hours = 0
    endpoint = f"{base_url}/api/v2/tickets/{ticket_id}/time_entries"
    retries = 0

    while retries < MAX_RETRIES:
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)

            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"  [!] Rate limit hit on ticket {ticket_id}. Waiting {retry_after} seconds to retry...")
                time.sleep(retry_after)
                retries += 1
                continue

            if response.status_code == 404:
                return 0

            response.raise_for_status()
            data = response.json()
            time_entries = data.get('time_entries', [])

            for entry in time_entries:
                entry_created_at = datetime.fromisoformat(entry['created_at'].replace('Z', '+00:00'))
                if start_date <= entry_created_at <= end_date:
                    time_str = entry.get('time_spent', '00:00')
                    h, m = map(int, time_str.split(':'))
                    total_hours += h + (m / 60.0)

            return total_hours

        except requests.exceptions.RequestException as e:
            print(f"Warning: Could not fetch time for ticket {ticket_id}: {e}", file=sys.stderr)
            retries += 1
            time.sleep(5)

    print(f"Warning: Failed to fetch time for ticket {ticket_id} after {MAX_RETRIES} retries.", file=sys.stderr)
    return 0


# --- Database Functions ---
def populate_companies_database(db_connection, companies_data):
    """Populates the companies table."""
    cur = db_connection.cursor()
    companies_to_insert = [
        (str(c.get('custom_fields', {}).get(ACCOUNT_NUMBER_FIELD)), c.get('name'), c.get('id'), c.get('custom_fields', {}).get('type_of_client', 'Unknown'), c.get('custom_fields', {}).get('plan_selected', 'Unknown'))
        for c in companies_data if (c.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD)
    ]
    if not companies_to_insert:
        print("No companies with account numbers to process.")
        return
    print(f"\nAttempting to insert/update {len(companies_to_insert)} companies...")
    cur.executemany("""
        INSERT INTO companies (account_number, name, freshservice_id, contract_type, billing_plan)
        VALUES (?, ?, ?, ?, ?) ON CONFLICT(account_number) DO UPDATE SET
        name=excluded.name, freshservice_id=excluded.freshservice_id, contract_type=excluded.contract_type, billing_plan=excluded.billing_plan;
    """, companies_to_insert)
    print(f"-> Successfully inserted/updated {cur.rowcount} companies.")

def populate_users_database(db_connection, users_to_insert):
    """Populates the users table."""
    if not users_to_insert:
        print("No users to insert into the database.")
        return
    cur = db_connection.cursor()
    print(f"\nAttempting to insert/update {len(users_to_insert)} users...")
    cur.executemany("""
        INSERT INTO users (company_account_number, freshservice_id, full_name, email, status, date_added)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(freshservice_id) DO UPDATE SET
        company_account_number=excluded.company_account_number, full_name=excluded.full_name, email=excluded.email, status=excluded.status;
    """, users_to_insert)
    print(f"-> Successfully inserted/updated {cur.rowcount} users.")

def update_ticket_hours(db_connection, hours_data):
    """Updates the ticket_work_hours table with the hours for the last month."""
    if not hours_data:
        print("\nNo billable time entries found to update in the database for the specified period.")
        return
    cur = db_connection.cursor()
    print(f"\nAttempting to insert/update {len(hours_data)} company time entries...")
    cur.executemany("""
        INSERT INTO ticket_work_hours (company_account_number, month, hours)
        VALUES (?, ?, ?) ON CONFLICT(company_account_number, month) DO UPDATE SET hours=excluded.hours;
    """, hours_data)
    print(f"-> Successfully inserted/updated {cur.rowcount} time entries.")

# --- Main Execution ---
if __name__ == "__main__":
    print(" Freshservice Company, User, and Time Syncer")
    print("================================================")

    if not os.path.exists(DB_FILE):
        sys.exit(f"Error: Database file '{DB_FILE}' not found. Run init_db.py first.")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        sys.exit("Error: The DB_MASTER_PASSWORD environment variable must be set.")

    API_KEY = get_freshservice_api_key(DB_MASTER_PASSWORD)
    auth_str = f"{API_KEY}:X"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}
    base_url = f"https://{FRESHSERVICE_DOMAIN}"

    companies = get_all_companies(base_url, headers)
    users = get_all_users(base_url, headers)

    if not companies or users is None:
        sys.exit("Could not fetch company or user data from Freshservice. Aborting.")

    today = datetime.now(timezone.utc)
    first_day_of_current_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
    first_day_of_last_month = last_day_of_last_month.replace(day=1)
    end_of_last_month = last_day_of_last_month.replace(hour=23, minute=59, second=59)
    month_str = first_day_of_last_month.strftime('%Y-%m')

    all_tickets_last_month = get_all_tickets_for_last_month(
        base_url, headers,
        first_day_of_last_month.strftime('%Y-%m-%d'),
        end_of_last_month.strftime('%Y-%m-%d')
    )

    if all_tickets_last_month is None:
        sys.exit("Aborting due to failure in fetching tickets.")

    print(f"Grouping {len(all_tickets_last_month)} tickets by company...")
    tickets_by_company = defaultdict(list)
    for ticket in all_tickets_last_month:
        if ticket.get('department_id'):
            tickets_by_company[ticket['department_id']].append(ticket)

    print("\n--- Processing Time Entries per Company ---")
    time_tracking_data = []
    company_id_map = {c['id']: c for c in companies}
    companies_with_hours = 0

    for company_id, tickets in tickets_by_company.items():
        company_info = company_id_map.get(company_id)
        account_number = (company_info.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD) if company_info else None
        if not account_number:
            continue

        company_name = company_info.get('name')
        total_hours_for_company = 0
        print(f"-> Processing '{company_name}' ({len(tickets)} tickets)...")
        for i, ticket in enumerate(tickets):
            hours_for_ticket = get_time_entries_for_ticket(
                base_url, headers, ticket['id'], first_day_of_last_month, end_of_last_month
            )
            if hours_for_ticket > 0:
                print(f"  - Found {hours_for_ticket:.2f} hours for ticket #{ticket['id']}")
                total_hours_for_company += hours_for_ticket

        if total_hours_for_company > 0:
            print(f"  => Total for '{company_name}': {total_hours_for_company:.2f} hours")
            time_tracking_data.append((str(account_number), month_str, total_hours_for_company))
            companies_with_hours += 1
        else:
            print(f"  => No billable time entries found for '{company_name}' in the period.")

    print(f"\nTime entry processing complete. Found logged hours for {companies_with_hours} companies.")

    all_users_to_insert = []
    company_id_to_account_map = {c.get('id'): (c.get('custom_fields') or {}).get(ACCOUNT_NUMBER_FIELD) for c in companies}
    print("\n--- Mapping Users to Companies ---")
    for user in users:
        for dept_id in (user.get('department_ids') or []):
            account_num = company_id_to_account_map.get(dept_id)
            if account_num:
                all_users_to_insert.append((
                    str(account_num), user.get('id'),
                    f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
                    user.get('primary_email'), 'Active' if user.get('active', False) else 'Inactive',
                    user.get('created_at', datetime.now(timezone.utc).isoformat())
                ))
                break

    print(f"Mapped {len(all_users_to_insert)} user-company links.")

    con = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)
    try:
        populate_companies_database(con, companies)
        populate_users_database(con, all_users_to_insert)
        update_ticket_hours(con, time_tracking_data)
        con.commit()
        print("\n All database operations committed successfully.")
    except sqlite3.Error as e:
        print(f"\n❌ Database error occurred: {e}", file=sys.stderr)
        con.rollback()
        sys.exit(1)
    finally:
        if con:
            con.close()

    print("\nScript finished.")
