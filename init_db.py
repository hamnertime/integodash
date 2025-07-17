import sys
import os
import getpass

# This is provided by the sqlcipher3-wheels package
try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)


DB_FILE = "brainhair.db"

def create_database():
    """
    Initializes a new encrypted SQLite database, prompts for a master password
    and API keys, and creates the necessary schema for the app and the scheduler.
    """
    if os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' already exists.", file=sys.stderr)
        print("Please remove it manually to re-create the database from scratch.", file=sys.stderr)
        sys.exit(1)

    print("--- Database and API Key Setup ---")
    master_password = getpass.getpass("Enter a master password for the new encrypted database: ")
    if not master_password:
        print("Error: Master password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    print("\nEnter your Freshservice API credentials:")
    freshservice_key = getpass.getpass("  - Freshservice API Key: ")
    if not freshservice_key:
        print("Error: Freshservice API Key cannot be empty.", file=sys.stderr)
        sys.exit(1)

    print("\nEnter your Datto RMM API credentials:")
    datto_endpoint = input("  - Datto RMM API Endpoint (e.g., https://api.rmm.datto.com): ")
    datto_key = getpass.getpass("  - Datto RMM Public Key: ")
    datto_secret = getpass.getpass("  - Datto RMM Secret Key: ")
    if not all([datto_endpoint, datto_key, datto_secret]):
        print("Error: All Datto RMM credentials are required.", file=sys.stderr)
        sys.exit(1)


    con = None
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute(f"PRAGMA key = '{master_password}';")
        cur.execute("PRAGMA foreign_keys = ON;")

        print("\nCreating database schema...")
        cur.execute("CREATE TABLE IF NOT EXISTS api_keys (service TEXT PRIMARY KEY, api_key TEXT, api_secret TEXT, api_endpoint TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS companies (account_number TEXT PRIMARY KEY, name TEXT UNIQUE, freshservice_id INTEGER UNIQUE, contract_type TEXT, billing_plan TEXT, status TEXT)")
        cur.execute("CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY, company_account_number TEXT, datto_uid TEXT UNIQUE, hostname TEXT, friendly_name TEXT, device_type TEXT, status TEXT, date_added TEXT, operating_system TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, company_account_number TEXT, freshservice_id INTEGER UNIQUE, full_name TEXT, email TEXT UNIQUE, status TEXT, date_added TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
        cur.execute("CREATE TABLE IF NOT EXISTS billing_plans (contract_type TEXT, billing_plan TEXT, billed_by TEXT, base_price REAL, per_user_cost REAL, per_server_cost REAL, per_workstation_cost REAL, PRIMARY KEY (contract_type, billing_plan))")
        cur.execute("CREATE TABLE IF NOT EXISTS billing_events (id INTEGER PRIMARY KEY, company_account_number TEXT, event_date TEXT, description TEXT, notes TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
        cur.execute("CREATE TABLE IF NOT EXISTS ticket_work_hours (company_account_number TEXT, month TEXT, hours REAL, PRIMARY KEY (company_account_number, month), FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")

        print("Creating 'scheduler_jobs' table...")
        cur.execute("""
            CREATE TABLE scheduler_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT NOT NULL UNIQUE,
                script_path TEXT NOT NULL,
                interval_minutes INTEGER NOT NULL,
                enabled BOOLEAN NOT NULL CHECK (enabled IN (0, 1)),
                last_run TEXT,
                next_run TEXT,
                last_status TEXT,
                last_run_log TEXT
            )
        """)

        print("\nStoring API keys in the encrypted database...")
        cur.execute("INSERT INTO api_keys (service, api_key) VALUES (?, ?)", ("freshservice", freshservice_key))
        cur.execute("INSERT INTO api_keys (service, api_endpoint, api_key, api_secret) VALUES (?, ?, ?, ?)", ("datto", datto_endpoint, datto_key, datto_secret))

        print("Populating default job schedules...")
        default_jobs = [
            ('Sync Billing Data (Users, Companies, Hours)', 'pull_freshservice.py', 1440, 1),
            ('Sync Datto RMM Assets', 'pull_datto.py', 1440, 1),
            ('Assign Missing Freshservice IDs', 'set_account_numbers.py', 1440, 0),
            ('Push IDs to Datto', 'push_account_nums_to_datto.py', 1440, 0)
        ]
        cur.executemany("""
            INSERT INTO scheduler_jobs (job_name, script_path, interval_minutes, enabled)
            VALUES (?, ?, ?, ?)
        """, default_jobs)

        con.commit()
        print(f"\n✅ Success! Encrypted database '{DB_FILE}' created and configured with default schedules.")

    except sqlite3.Error as e:
        print(f"\n❌ An error occurred: {e}", file=sys.stderr)
        if con: con.close()
        if os.path.exists(DB_FILE): os.remove(DB_FILE)
        sys.exit(1)
    finally:
        if con: con.close()

if __name__ == "__main__":
    create_database()
