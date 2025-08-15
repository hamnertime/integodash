import requests
import base64
import os
import sys
import time
import getpass
import argparse
from datetime import datetime, timedelta, timezone

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
ACCOUNT_NUMBER_FIELD = "account_number"
MAX_RETRIES = 3
DEFAULT_TICKET_HOURS = 0.25 # 15 minutes

def get_db_connection(db_path, password):
    if not password: raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con, cur

def get_freshservice_api_key(db_password):
    con, cur = get_db_connection(DB_FILE, db_password)
    cur.execute("SELECT api_key FROM api_keys WHERE service = 'freshservice'")
    creds = cur.fetchone()
    con.close()
    if not creds: raise ValueError("Freshservice credentials not found in the database.")
    return creds[0]

def get_latest_ticket_timestamp(cur):
    """Gets the timestamp of the most recently updated ticket in the local DB."""
    cur.execute("SELECT MAX(last_updated_at) as latest_timestamp FROM ticket_details")
    result = cur.fetchone()
    if result and result['latest_timestamp']:
        return datetime.fromisoformat(result['latest_timestamp'].replace('Z', '+00:00')) + timedelta(seconds=1)
    else:
        print("No existing tickets found. Performing initial sync for the past year.")
        return datetime.now(timezone.utc) - timedelta(days=365)

# --- THIS IS THE FIX ---
def get_fs_company_map_from_api(base_url, headers):
    """Fetches all companies from Freshservice and returns a map of fs_id to account_number."""
    all_companies = []
    page = 1
    print("Fetching company map directly from Freshservice API to ensure data integrity...")
    while True:
        params = {'page': page, 'per_page': 100}
        try:
            response = requests.get(f"{base_url}/api/v2/departments", headers=headers, params=params, timeout=90)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"  -> Rate limit hit, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            data = response.json()
            companies_on_page = data.get('departments', [])
            if not companies_on_page: break
            all_companies.extend(companies_on_page)
            page += 1
            time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            print(f"FATAL error fetching companies for mapping: {e}", file=sys.stderr)
            return None

    if all_companies is None:
        return {}

    fs_id_to_account_map = {}
    for company in all_companies:
        fs_id = company.get('id')
        custom_fields = company.get('custom_fields', {}) or {}
        account_number = custom_fields.get(ACCOUNT_NUMBER_FIELD)
        if fs_id and account_number:
            fs_id_to_account_map[fs_id] = str(account_number)

    print(f"Successfully built a map of {len(fs_id_to_account_map)} companies with account numbers.")
    return fs_id_to_account_map
# --- END OF FIX ---

# --- API Functions ---
def get_updated_tickets(base_url, headers, since_timestamp):
    all_tickets = []
    since_str = since_timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
    query = f"(updated_at:>'{since_str}' AND status:5)"
    page = 1
    print(f"Fetching CLOSED tickets updated since {since_str}...")

    while True:
        params = {'query': f'"{query}"', 'page': page, 'per_page': 100}
        try:
            response = requests.get(f"{base_url}/api/v2/tickets/filter", headers=headers, params=params, timeout=90)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"  -> Rate limit hit, waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            data = response.json()
            tickets_on_page = data.get('tickets', [])
            if not tickets_on_page: break
            all_tickets.extend(tickets_on_page)
            print(f"  -> Fetched page {page}, total tickets so far: {len(all_tickets)}")
            page += 1
            time.sleep(1)
        except requests.exceptions.RequestException as e:
            print(f"FATAL error fetching tickets: {e}", file=sys.stderr)
            return None
    return all_tickets

def get_time_entries_for_ticket(base_url, headers, ticket_id):
    total_hours = 0
    endpoint = f"{base_url}/api/v2/tickets/{ticket_id}/time_entries"
    retries = 0
    while retries < MAX_RETRIES:
        try:
            response = requests.get(endpoint, headers=headers, timeout=60)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                print(f"    [!] Rate limit on ticket #{ticket_id}. Retrying in {retry_after}s...")
                time.sleep(retry_after)
                retries += 1
                continue
            if response.status_code == 404:
                return 0
            response.raise_for_status()
            data = response.json()
            time_entries = data.get('time_entries', [])
            for entry in time_entries:
                time_str = entry.get('time_spent', '00:00')
                try:
                    h, m = map(int, time_str.split(':'))
                    total_hours += h + (m / 60.0)
                except ValueError:
                    parts = list(map(int, time_str.split(':')))
                    if len(parts) == 3:
                        h, m, s = parts
                        total_hours += h + m / 60.0 + s / 3600.0
            return total_hours
        except requests.exceptions.RequestException as e:
            print(f"  -> WARN: Could not fetch time for ticket {ticket_id}: {e}", file=sys.stderr)
            retries += 1
            time.sleep(5)
    print(f"  -> ERROR: Failed to fetch time for ticket {ticket_id} after {MAX_RETRIES} retries.", file=sys.stderr)
    return 0

def upsert_ticket_details(db_connection, ticket_data_to_upsert):
    if not ticket_data_to_upsert:
        print("\nNo new or updated ticket data to insert.")
        return
    cur = db_connection.cursor()
    cur.executemany("""
        INSERT INTO ticket_details (ticket_id, company_account_number, subject, last_updated_at, closed_at, total_hours_spent)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(ticket_id) DO UPDATE SET
            company_account_number = excluded.company_account_number,
            subject = excluded.subject,
            last_updated_at = excluded.last_updated_at,
            closed_at = excluded.closed_at,
            total_hours_spent = excluded.total_hours_spent
    """, ticket_data_to_upsert)
    print(f"\nSuccessfully inserted/updated details for {cur.rowcount} tickets.")

# --- Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync ticket details from Freshservice.")
    parser.add_argument('--full-sync', action='store_true', help="Force a full sync of all tickets from the past year.")
    args = parser.parse_args()

    print("--- Running Ticket Details Sync Script (Last Ticket Timestamp Method) ---")
    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database password: ")
        except (getpass.GetPassWarning, NameError):
             DB_MASTER_PASSWORD = input("Please enter the database password: ")
    if not DB_MASTER_PASSWORD: sys.exit("FATAL: No database password provided. Aborting.")

    try:
        API_KEY = get_freshservice_api_key(DB_MASTER_PASSWORD)
        base_url = f"https://{FRESHSERVICE_DOMAIN}"
        auth_str = f"{API_KEY}:X"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

        fs_id_to_account_map = get_fs_company_map_from_api(base_url, headers)
        if not fs_id_to_account_map:
            sys.exit("Could not build company map from Freshservice API. Aborting ticket sync.")

        con, cur = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)

        if args.full_sync:
            print("Full sync flag detected. Clearing all existing ticket data...")
            cur.execute("DELETE FROM ticket_details;")
            print("Fetching all closed tickets from the past year.")
            last_sync_time = datetime.now(timezone.utc) - timedelta(days=365)
        else:
            last_sync_time = get_latest_ticket_timestamp(cur)

        tickets = get_updated_tickets(base_url, headers, last_sync_time)
        if tickets is None: sys.exit("Aborting due to ticket fetch failure.")

        ticket_details_to_upsert = []
        if tickets:
            print("\nProcessing tickets and fetching their total time entries...")
            for ticket in tickets:
                department_id = ticket.get('department_id')
                account_number = fs_id_to_account_map.get(department_id)
                if not account_number:
                    continue

                ticket_id = ticket['id']
                print(f"  -> Processing Ticket #{ticket_id}...")

                total_hours = get_time_entries_for_ticket(base_url, headers, ticket_id)

                if total_hours == 0:
                    total_hours = DEFAULT_TICKET_HOURS
                    print(f"    -> No time entries found. Assigning default {DEFAULT_TICKET_HOURS} hours.")

                closed_date = ticket.get('updated_at')

                ticket_details_to_upsert.append((
                    ticket_id,
                    account_number,
                    ticket.get('subject', 'No Subject'),
                    ticket.get('updated_at'),
                    closed_date,
                    total_hours
                ))

        upsert_ticket_details(con, ticket_details_to_upsert)

        con.commit()
        con.close()
        print("\n--- Ticket Details Sync Successful ---")

    except Exception as e:
        print(f"\nAn error occurred during ticket sync: {e}", file=sys.stderr)
        sys.exit(1)
