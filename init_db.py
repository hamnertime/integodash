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

# --- Default Billing Plan Data ---
# This list contains the default billing rates for all plans and terms.
# You can customize these values before running the script for the first time.
default_plans_data = [
    ('Break Fix', '1-Year', 0.00, 0.00, 0.00, 0.00),
    ('Break Fix', '2-Year', 0.00, 0.00, 0.00, 0.00),
    ('Break Fix', '3-Year', 0.00, 0.00, 0.00, 0.00),
    ('Break Fix', 'Month to Month', 0.00, 0.00, 0.00, 0.00),
    ('MSP Advanced', '1-Year', 0.00, 0.00, 25.00, 25.00),
    ('MSP Advanced', '2-Year', 0.00, 0.00, 25.00, 25.00),
    ('MSP Advanced', '3-Year', 0.00, 0.00, 25.00, 25.00),
    ('MSP Advanced', 'Month to Month', 0.00, 0.00, 25.00, 25.00),
    ('MSP Basic', '1-Year', 0.00, 0.00, 10.00, 10.00),
    ('MSP Basic', '2-Year', 0.00, 0.00, 10.00, 10.00),
    ('MSP Basic', '3-Year', 0.00, 0.00, 10.00, 10.00),
    ('MSP Basic', 'Month to Month', 0.00, 0.00, 10.00, 10.00),
    ('MSP Legacy', '1-Year', 100.00, 10.00, 50.00, 25.00),
    ('MSP Legacy', '2-Year', 100.00, 9.50, 50.00, 23.75),
    ('MSP Legacy', '3-Year', 100.00, 9.00, 50.00, 22.50),
    ('MSP Legacy', 'Month to Month', 100.00, 10.00, 50.00, 25.00),
    ('MSP Platinum', '1-Year', 0.00, 120.00, 0.00, 0.00),
    ('MSP Platinum', '2-Year', 0.00, 115.00, 0.00, 0.00),
    ('MSP Platinum', '3-Year', 0.00, 110.00, 0.00, 0.00),
    ('MSP Platinum', 'Month to Month', 0.00, 125.00, 0.00, 0.00),
    ('MSP Premium', '1-Year', 0.00, 95.00, 0.00, 0.00),
    ('MSP Premium', '2-Year', 0.00, 90.00, 0.00, 0.00),
    ('MSP Premium', '3-Year', 0.00, 85.00, 0.00, 0.00),
    ('MSP Premium', 'Month to Month', 0.00, 100.00, 0.00, 0.00),
    ('Pro Services', '1-Year', 0.00, 0.00, 0.00, 0.00),
    ('Pro Services', '2-Year', 0.00, 0.00, 0.00, 0.00),
    ('Pro Services', '3-Year', 0.00, 0.00, 0.00, 0.00),
    ('Pro Services', 'Month to Month', 0.00, 0.00, 0.00, 0.00),
]


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
