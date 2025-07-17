import requests
import base64
import os
import sys
import time
import getpass
from datetime import datetime, timedelta, timezone

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
MAX_RETRIES = 3

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

# --- API Functions ---
def get_tickets_for_period(base_url, headers, start_date_str, end_date_str):
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
            time.sleep(0.5)
        except requests.exceptions.RequestException as e:
            print(f"FATAL error fetching tickets: {e}", file=sys.stderr)
            if hasattr(e, 'response') and e.response: print(f"Response: {e.response.text}", file=sys.stderr)
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
                entry_created_at = datetime.fromisoformat(entry['created_at'].replace('Z', '+00:00'))
                if start_date <= entry_created_at <= end_date:
                    time_str = entry.get('time_spent', '00:00')
                    h, m = map(int, time_str.split(':'))
                    total_hours += h + (m / 60.0)

            return total_hours

        except requests.exceptions.RequestException as e:
            print(f"  -> WARN: Could not fetch time for ticket {ticket_id}: {e}", file=sys.stderr)
            retries += 1
            time.sleep(5)

    print(f"  -> ERROR: Failed to fetch time for ticket {ticket_id} after {MAX_RETRIES} retries.", file=sys.stderr)
    return 0

# --- Database Functions ---
def populate_ticket_details(db_connection, ticket_data_to_insert):
    if not ticket_data_to_insert:
        print("\nNo new ticket data with time entries to insert.")
        return
    cur = db_connection.cursor()
    cur.execute("DELETE FROM ticket_details;")
    cur.executemany("""
        INSERT INTO ticket_details (ticket_id, company_account_number, subject, last_updated_at, closed_at, total_hours_spent)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ticket_data_to_insert)
    print(f"\nSuccessfully inserted details for {cur.rowcount} tickets into the database.")

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Running Ticket Details Sync Script ---")
    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        print("DB_MASTER_PASSWORD environment variable not set.")
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database password: ")
        except (getpass.GetPassWarning, NameError):
             DB_MASTER_PASSWORD = input("Please enter the database password: ")
    if not DB_MASTER_PASSWORD: sys.exit("FATAL: No database password provided. Aborting.")

    try:
        con, cur = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)

        cur.execute("SELECT freshservice_id, account_number, name FROM companies WHERE freshservice_id IS NOT NULL")
        fs_id_to_company_map = {row['freshservice_id']: {'account': row['account_number'], 'name': row['name']} for row in cur.fetchall()}

        API_KEY = get_freshservice_api_key(DB_MASTER_PASSWORD)
        base_url = f"https://{FRESHSERVICE_DOMAIN}"
        auth_str = f"{API_KEY}:X"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

        today = datetime.now(timezone.utc)
        first_day_of_current_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
        first_day_of_last_month = last_day_of_last_month.replace(day=1)
        end_of_last_month = last_day_of_last_month.replace(hour=23, minute=59, second=59)

        tickets = get_tickets_for_period(base_url, headers, first_day_of_last_month.strftime('%Y-%m-%d'), end_of_last_month.strftime('%Y-%m-%d'))
        if tickets is None: sys.exit("Aborting due to ticket fetch failure.")

        ticket_details_to_insert = []
        print("\nProcessing tickets and fetching time entries for the previous month...")
        for ticket in tickets:
            department_id = ticket.get('department_id')
            if not department_id or department_id not in fs_id_to_company_map:
                continue

            company_info = fs_id_to_company_map[department_id]
            account_number = company_info['account']
            ticket_id = ticket['id']

            total_hours = get_time_entries_for_ticket(base_url, headers, ticket_id, first_day_of_last_month, end_of_last_month)

            if total_hours > 0:
                print(f"  -> Found {total_hours:.2f} hours for Ticket #{ticket_id} ('{company_info['name']}')")

                # CORRECTED LOGIC: Check status and use updated_at if closed
                closed_date = None
                if ticket.get('status') == 5:
                    closed_date = ticket.get('updated_at')

                ticket_details_to_insert.append((
                    ticket_id,
                    account_number,
                    ticket.get('subject', 'No Subject'),
                    ticket.get('updated_at'),
                    closed_date,
                    total_hours
                ))

        populate_ticket_details(con, ticket_details_to_insert)
        con.commit()
        con.close()
        print("\n--- Ticket Details Sync Successful ---")

    except Exception as e:
        print(f"\nAn error occurred during ticket sync: {e}", file=sys.stderr)
        sys.exit(1)
