import sys
import os
import getpass
from datetime import datetime

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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS companies (
                account_number TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                freshservice_id INTEGER UNIQUE,
                contract_type TEXT,
                billing_plan TEXT,
                status TEXT,
                contract_term_length TEXT,
                contract_start_date TEXT
            )
        """)
        cur.execute("CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY, company_account_number TEXT, datto_uid TEXT UNIQUE, hostname TEXT, friendly_name TEXT, device_type TEXT, status TEXT, date_added TEXT, operating_system TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
        cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, company_account_number TEXT, freshservice_id INTEGER UNIQUE, full_name TEXT, email TEXT UNIQUE, status TEXT, date_added TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS billing_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                billing_plan TEXT,
                term_length TEXT,
                network_management_fee REAL DEFAULT 0,
                per_user_cost REAL DEFAULT 0,
                per_server_cost REAL DEFAULT 0,
                per_workstation_cost REAL DEFAULT 0,
                UNIQUE (billing_plan, term_length)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS client_billing_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT UNIQUE,
                network_management_fee REAL,
                per_user_cost REAL,
                per_server_cost REAL,
                per_workstation_cost REAL,
                override_enabled BOOLEAN DEFAULT 0,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number)
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS ticket_details (
                ticket_id INTEGER PRIMARY KEY,
                company_account_number TEXT,
                subject TEXT,
                last_updated_at TEXT,
                closed_at TEXT,
                total_hours_spent REAL,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number)
            )
        """)

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
        print("Schema creation complete.")

        print("\nStoring API keys in the encrypted database...")
        cur.execute("INSERT INTO api_keys (service, api_key) VALUES (?, ?)", ("freshservice", freshservice_key))
        cur.execute("INSERT INTO api_keys (service, api_endpoint, api_key, api_secret) VALUES (?, ?, ?, ?)", ("datto", datto_endpoint, datto_key, datto_secret))

        print("Populating default job schedules...")
        default_jobs = [
            ('Sync Billing Data (Companies & Users)', 'pull_freshservice.py', 1440, 1),
            ('Sync Datto RMM Assets', 'pull_datto.py', 1440, 1),
            ('Sync Ticket Details & Hours', 'pull_ticket_details.py', 1440, 1),
            ('Assign Missing Freshservice Account Numbers', 'set_account_numbers.py', 1440, 0),
            ('Push Account Numbers to Datto RMM', 'push_account_nums_to_datto.py', 1440, 0)
        ]
        cur.executemany("""
            INSERT INTO scheduler_jobs (job_name, script_path, interval_minutes, enabled)
            VALUES (?, ?, ?, ?)
        """, default_jobs)

        print("Populating default billing plans...")
        default_plans_data = []
        plans = ["MSP Basic", "MSP Advanced", "MSP Premium", "MSP Platinum", "MSP Legacy", "Break Fix", "Pro Services"]
        terms = ["Month to Month", "1-Year", "2-Year", "3-Year"]

        for plan in plans:
            for term in terms:
                base_fee = 100.0 if "MSP" in plan else 0
                user_cost = 20.0 if "Platinum" in plan else 10.0
                workstation_cost = 25.0 if "MSP" in plan else 0
                server_cost = 50.0 if "MSP" in plan else 0

                if term == "2-Year":
                    user_cost *= 0.95
                    workstation_cost *= 0.95
                elif term == "3-Year":
                    user_cost *= 0.9
                    workstation_cost *= 0.9

                default_plans_data.append((plan, term, base_fee, user_cost, server_cost, workstation_cost))

        cur.executemany("""
            INSERT INTO billing_plans (billing_plan, term_length, network_management_fee, per_user_cost, per_server_cost, per_workstation_cost)
            VALUES (?, ?, ?, ?, ?, ?)
        """, default_plans_data)

        con.commit()
        print(f"\n✅ Success! Encrypted database '{DB_FILE}' created and configured.")

    except sqlite3.Error as e:
        print(f"\n❌ An error occurred: {e}", file=sys.stderr)
        if con:
            con.close()
        if os.path.exists(DB_FILE):
            os.remove(DB_FILE)
        sys.exit(1)
    finally:
        if con:
            con.close()

if __name__ == "__main__":
    create_database()
