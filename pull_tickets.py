import requests
import base64
import os
import sys
import time
from datetime import datetime, timedelta, timezone
import getpass

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# --- Hardcoded Agent Map ---
# This is a temporary workaround. The best solution is to fix API key permissions.
MANUAL_AGENT_MAP = {
    19006246349: "David",
    19006246346: "Omar",
    19004120052: "Troy",
    19006163442: "Jesse",
    19000243812: "Matt"
}
# ---------------------------

# --- Configuration & Utility Functions ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
JOB_ID_FOR_THIS_SCRIPT = 1
API_DELAY_S = 0.2

def get_db_connection(db_path, password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    con.row_factory = sqlite3.Row
    return con

def get_freshservice_api_key(db_connection):
    """Reads the Freshservice API key from the encrypted database."""
    cur = db_connection.cursor()
    cur.execute("SELECT api_key FROM api_keys WHERE service = 'freshservice'")
    creds = cur.fetchone()
    if not creds:
        raise ValueError("Freshservice credentials not found in the database.")
    return creds[0]

def get_last_run_timestamp(db_connection, job_id):
    """Gets the timestamp of the last successful run for this specific job."""
    cur = db_connection.cursor()
    cur.execute("SELECT last_run FROM scheduler_jobs WHERE id = ? AND last_status = 'Success'", (job_id,))
    result = cur.fetchone()
    if result and result['last_run']:
        last_success = datetime.fromisoformat(result['last_run']) - timedelta(minutes=5)
        print(f"DEBUG: Last successful run was at {result['last_run']}. Fetching changes since {last_success.isoformat()}.")
        return last_success
    else:
        print("DEBUG: No previous successful run found. Performing a full sync for the last 30 days.")
        return datetime.now(timezone.utc) - timedelta(days=30)

def get_changed_tickets_since(base_url, headers, timestamp):
    """Fetches a LIST of tickets updated since the provided timestamp."""
    all_tickets = []
    updated_since_str = timestamp.strftime('%Y-%m-%dT%H:%M:%SZ')
    page = 1
    endpoint = f"{base_url}/api/v2/tickets"
    print(f"\nFetching list of tickets updated since {updated_since_str}...")
    while True:
        params = {'updated_since': updated_since_str, 'page': page, 'per_page': 100}
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=90)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 10))
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            tickets_on_page = response.json().get('tickets', [])
            if not tickets_on_page: break
            all_tickets.extend(tickets_on_page)
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"Fatal error fetching changed ticket list: {e}", file=sys.stderr)
            return None
    print(f"-> Found {len(all_tickets)} changed tickets since last sync.")
    return all_tickets

def get_ticket_details(ticket_id, base_url, headers):
    """Fetches the details for a single ticket. This call does NOT include agent details."""
    detail_endpoint = f"{base_url}/api/v2/tickets/{ticket_id}"
    try:
        response = requests.get(detail_endpoint, headers=headers, timeout=20)
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 10))
            time.sleep(retry_after)
            response = requests.get(detail_endpoint, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json().get("ticket")
    except requests.exceptions.RequestException as e:
        print(f"  -> Failed to fetch details for ticket {ticket_id}: {e}", file=sys.stderr)
        return None

def get_agent_name(agent_id, base_url, headers, cache):
    """Fetches an agent's name by their ID, using a cache to avoid redundant calls."""
    if agent_id in MANUAL_AGENT_MAP:
        return MANUAL_AGENT_MAP[agent_id]
    if agent_id in cache:
        return cache[agent_id]
    agent_endpoint = f"{base_url}/api/v2/agents/{agent_id}"
    try:
        response = requests.get(agent_endpoint, headers=headers, timeout=20)
        if response.status_code == 404:
            cache[agent_id] = f"Unknown Agent ({agent_id})"
            return cache[agent_id]
        response.raise_for_status()
        agent_data = response.json().get("agent", {})
        first_name = agent_data.get('first_name', '')
        last_name = agent_data.get('last_name', '')
        full_name = f"{first_name} {last_name}".strip()
        cache[agent_id] = full_name if full_name else f"Unnamed Agent ({agent_id})"
        return cache[agent_id]
    except requests.exceptions.RequestException as e:
        print(f"  -> Could not fetch agent {agent_id}: {e}", file=sys.stderr)
        cache[agent_id] = f"Error Fetching Agent ({agent_id})"
        return cache[agent_id]

def get_company_map(db_connection):
    """Fetches lookup map for companies from the local DB."""
    cur = db_connection.cursor()
    cur.execute("SELECT freshservice_id, account_number FROM companies")
    return {row['freshservice_id']: row['account_number'] for row in cur.fetchall()}

def process_tickets(db_connection, tickets_data, company_map, base_url, headers, agent_cache):
    """Processes tickets using the definitive status map from the ticket-dash repo."""
    if not tickets_data:
        return 0, 0

    # --- CORRECT STATUS MAP from hamnertime/ticket-dash gui.py ---
    status_map = {
        2: 'Open',
        3: 'Pending',
        4: 'Resolved',
        5: 'Closed',
        6: 'Waiting on Third Party',
        7: 'Waiting on Customer',
        8: 'In Review',
        9: 'On Hold',
        10: 'In Escrow',
        11: 'In Development',
        12: 'In Testing',
        13: 'Update Needed',
        14: 'Awaiting your review',
        15: 'Waiting on parts',
        16: 'Scheduled',
        17: 'Onsite',
        18: 'Ready for Deployment',
        19: 'Waiting on Agent'
    }

    # -- Statuses that are NOT Closed or Resolved, from ticket_watcher.py --
    open_statuses = {2, 3, 8, 9, 10, 13, 19, 23, 26} # Matches STATUS_IDS_TO_INCLUDE

    # Priority map is standard
    priority_map = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
    # ----------------------------------------------------

    tickets_to_upsert = []
    ids_to_delete = []

    print("\n--- Processing Changed Tickets (with correct status map) ---")
    for t in tickets_data:
        status_id = t.get('status')
        if status_id in open_statuses:
            responder_id = t.get('responder_id')
            agent_name = "Unassigned"
            if responder_id:
                agent_name = get_agent_name(responder_id, base_url, headers, agent_cache)

            requester_name = t.get('requester_name', 'Unknown')
            account_num = company_map.get(t.get('department_id'))
            status_text = status_map.get(status_id, f"Unknown ID ({status_id})")
            priority_text = priority_map.get(t.get('priority'), 'Unknown')

            print(f"  - Processing Ticket ID: {t['id']}, Subject: '{t['subject']}', Agent: '{agent_name}', Status: '{status_text}'")
            tickets_to_upsert.append((
                t['id'], t['subject'], status_text,
                priority_text, t.get('source'), t.get('type'),
                t['created_at'], t['updated_at'], responder_id,
                agent_name, t.get('requester_id'),
                requester_name, account_num
            ))
        else:
            ids_to_delete.append(t['id'])

    cur = db_connection.cursor()
    if tickets_to_upsert:
        print(f"\n-> Inserting/updating {len(tickets_to_upsert)} open tickets in the database...")
        cur.executemany("""
            INSERT OR REPLACE INTO tickets (id, subject, status, priority, source, ticket_type, created_at, updated_at,
                                             agent_id, agent_name, requester_id, requester_name, company_account_number)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
        """, tickets_to_upsert)
        updated_count = cur.rowcount
    else: updated_count = 0

    if ids_to_delete:
        print(f"-> Deleting {len(ids_to_delete)} closed/resolved tickets...")
        placeholders = ', '.join('?' for _ in ids_to_delete)
        cur.execute(f"DELETE FROM tickets WHERE id IN ({placeholders})", ids_to_delete)
        deleted_count = cur.rowcount
    else: deleted_count = 0

    return updated_count, deleted_count

# --- Main Execution ---
if __name__ == "__main__":
    print("--- Running Efficient Ticket Sync ---")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        print("DB_MASTER_PASSWORD environment variable not set.")
        try:
            DB_MASTER_PASSWORD = getpass.getpass("Please enter the database master password: ")
        except Exception as e: sys.exit(f"Could not read password: {e}")
    if not DB_MASTER_PASSWORD: sys.exit("FATAL: A database master password is required.")

    con = None
    agent_cache = {}
    try:
        con = get_db_connection(DB_FILE, DB_MASTER_PASSWORD)
        last_run = get_last_run_timestamp(con, JOB_ID_FOR_THIS_SCRIPT)

        API_KEY = get_freshservice_api_key(con)
        base_url = f"https://{FRESHSERVICE_DOMAIN}"
        auth_str = f"{API_KEY}:X"
        encoded_auth = base64.b64encode(auth_str.encode()).decode()
        headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}

        basic_changed_tickets = get_changed_tickets_since(base_url, headers, last_run)
        if basic_changed_tickets is None: sys.exit("Failed to fetch changed ticket list.")

        detailed_tickets = []
        if basic_changed_tickets:
            print(f"\n-> Fetching full details for {len(basic_changed_tickets)} tickets...")
            for i, basic_ticket in enumerate(basic_changed_tickets):
                ticket_id = basic_ticket.get('id')
                if not ticket_id: continue
                print(f"  ({i+1}/{len(basic_changed_tickets)}) Fetching ticket {ticket_id}...", end='\r')
                detailed_ticket = get_ticket_details(ticket_id, base_url, headers)
                if detailed_ticket: detailed_tickets.append(detailed_ticket)
                time.sleep(API_DELAY_S)
            print("\n  ...Detail fetch complete.                                          ")

        company_map = get_company_map(con)
        updated_count, deleted_count = process_tickets(con, detailed_tickets, company_map, base_url, headers, agent_cache)

        con.commit()
        print(f"\n-> Sync complete. Updated/inserted: {updated_count}. Deleted: {deleted_count}.")
        print("--- Efficient Ticket Sync Successful ---")

    except Exception as e:
        print(f"\nAn error occurred during ticket sync: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        if con: con.rollback()
        sys.exit(1)
    finally:
        if con: con.close()
