# hamnertime/integodash/integodash-fda17dde7f19ded546de5dbffc8ee99ff55ec5f3/init_db.py
import sys
import os
import getpass
import time
import shutil

# This is provided by the sqlcipher3-wheels package
try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)


DB_FILE = "brainhair.db"
UPLOAD_FOLDER = 'uploads'

# --- Default Billing Plan Data ---
# This data is used to populate a fresh database. It is ignored during migration.
default_plans_data = [
    # plan, term, puc, psc, pwc, pvc, pswitchc, pfirewallc, phtc, bbfw, bbfs, bit, bpt
    ('Break Fix', '1-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('Break Fix', '2-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('Break Fix', '3-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('Break Fix', 'Month to Month', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 100.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', '1-Year', 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', '2-Year', 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', '3-Year', 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', 'Month to Month', 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 100.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', '1-Year', 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', '2-Year', 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', '3-Year', 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', 'Month to Month', 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 100.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', '1-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', '2-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', '3-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', 'Month to Month', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', '1-Year', 120.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', '2-Year', 115.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', '3-Year', 110.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', 'Month to Month', 125.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', '1-Year', 95.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', '2-Year', 90.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', '3-Year', 85.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', 'Month to Month', 100.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', '1-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', '2-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', '3-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', 'Month to Month', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
]

def export_data_from_old_db(password):
    """
    Connects to the existing database, exports all data from all tables,
    and returns it as a dictionary.
    """
    print("Connecting to the old database to export data...")
    try:
        con = sqlite3.connect(DB_FILE)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        cur.execute(f"PRAGMA key = '{password}';")
        # Test the key
        cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
    except sqlite3.DatabaseError:
        print("\n❌ Incorrect password for the old database. Aborting.", file=sys.stderr)
        con.close()
        return None
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}", file=sys.stderr)
        con.close()
        return None

    tables = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';").fetchall()
    table_names = [table['name'] for table in tables]

    exported_data = {}
    print(f"Found tables: {', '.join(table_names)}")
    for table_name in table_names:
        print(f"  - Exporting data from '{table_name}'...")
        rows = cur.execute(f"SELECT * FROM {table_name}").fetchall()
        exported_data[table_name] = [dict(row) for row in rows]
        print(f"    -> Found {len(exported_data[table_name])} rows.")

    con.close()
    return exported_data

def import_data_to_new_db(con, data):
    """
    Imports data into the new database, gracefully handling schema differences.
    """
    cur = con.cursor()
    print("\nImporting data into the new database schema...")

    for table_name, rows in data.items():
        if not rows:
            continue

        try:
            # Get the columns of the *new* table
            new_table_info = cur.execute(f"PRAGMA table_info({table_name});").fetchall()
            new_columns = {info['name'] for info in new_table_info}

            print(f"  - Importing data into '{table_name}'...")

            for row in rows:
                # Filter the old row data to only include columns that exist in the new table
                columns_to_insert = {k: v for k, v in row.items() if k in new_columns}

                if not columns_to_insert:
                    print(f"    -> Skipping a row, no matching columns found.")
                    continue

                cols = ', '.join(columns_to_insert.keys())
                placeholders = ', '.join(['?'] * len(columns_to_insert))

                # Use INSERT OR IGNORE to prevent crashes on unique constraint violations,
                # which can happen with default data.
                sql = f"INSERT OR IGNORE INTO {table_name} ({cols}) VALUES ({placeholders})"

                try:
                    cur.execute(sql, list(columns_to_insert.values()))
                except sqlite3.Error as e:
                    print(f"    -> ⚠️  Warning: Could not insert a row into '{table_name}': {e}", file=sys.stderr)

        except sqlite3.OperationalError:
            print(f"  - ⚠️  Skipping table '{table_name}': It does not exist in the new schema.", file=sys.stderr)

    con.commit()
    print("Data import process complete.")


def create_database(new_password, existing_data=None):
    """
    Initializes a new encrypted database, creates the schema, and optionally imports old data.
    """
    if not new_password:
        print("Error: A new master password is required.", file=sys.stderr)
        sys.exit(1)

    # Always create a fresh file for the new database
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)

    con = sqlite3.connect(DB_FILE)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{new_password}';")
    cur.execute("PRAGMA foreign_keys = ON;")

    print("\nCreating new database schema...")
    # --- Schema Definition ---
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
            contract_start_date TEXT,
            support_level TEXT
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS assets (id INTEGER PRIMARY KEY, company_account_number TEXT, datto_uid TEXT UNIQUE, hostname TEXT, friendly_name TEXT, device_type TEXT, billing_type TEXT, status TEXT, date_added TEXT, operating_system TEXT, backup_data_bytes INTEGER, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            company_account_number TEXT,
            freshservice_id INTEGER UNIQUE,
            full_name TEXT,
            email TEXT UNIQUE,
            status TEXT,
            date_added TEXT,
            billing_type TEXT NOT NULL DEFAULT 'Regular',
            FOREIGN KEY (company_account_number) REFERENCES companies (account_number)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS billing_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            billing_plan TEXT,
            term_length TEXT,
            per_user_cost REAL DEFAULT 0,
            per_server_cost REAL DEFAULT 0,
            per_workstation_cost REAL DEFAULT 0,
            per_vm_cost REAL DEFAULT 0,
            per_switch_cost REAL DEFAULT 0,
            per_firewall_cost REAL DEFAULT 0,
            per_hour_ticket_cost REAL DEFAULT 0,
            backup_base_fee_workstation REAL DEFAULT 25,
            backup_base_fee_server REAL DEFAULT 50,
            backup_included_tb REAL DEFAULT 1,
            backup_per_tb_fee REAL DEFAULT 15,
            feature_antivirus TEXT DEFAULT 'Not Included',
            feature_soc TEXT DEFAULT 'Not Included',
            feature_training TEXT DEFAULT 'Not Included',
            feature_email TEXT DEFAULT 'No Business Email',
            feature_phone TEXT DEFAULT 'No Business Phone',
            feature_password_manager TEXT DEFAULT 'Not Included',
            UNIQUE (billing_plan, term_length)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS client_billing_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_account_number TEXT UNIQUE,
            per_user_cost REAL, per_server_cost REAL,
            per_workstation_cost REAL, per_vm_cost REAL, per_switch_cost REAL,
            per_firewall_cost REAL, per_hour_ticket_cost REAL, backup_base_fee_workstation REAL,
            backup_base_fee_server REAL, backup_included_tb REAL, backup_per_tb_fee REAL,
            prepaid_hours_monthly REAL, prepaid_hours_yearly REAL,
            override_puc_enabled BOOLEAN DEFAULT 0,
            override_psc_enabled BOOLEAN DEFAULT 0, override_pwc_enabled BOOLEAN DEFAULT 0,
            override_pvc_enabled BOOLEAN DEFAULT 0, override_pswitchc_enabled BOOLEAN DEFAULT 0,
            override_pfirewallc_enabled BOOLEAN DEFAULT 0, override_phtc_enabled BOOLEAN DEFAULT 0,
            override_bbfw_enabled BOOLEAN DEFAULT 0, override_bbfs_enabled BOOLEAN DEFAULT 0,
            override_bit_enabled BOOLEAN DEFAULT 0, override_bpt_enabled BOOLEAN DEFAULT 0,
            override_prepaid_hours_monthly_enabled BOOLEAN DEFAULT 0,
            override_prepaid_hours_yearly_enabled BOOLEAN DEFAULT 0,
            feature_antivirus TEXT, feature_soc TEXT, feature_training TEXT,
            feature_phone TEXT, feature_email TEXT, feature_password_manager TEXT,
            override_feature_antivirus_enabled BOOLEAN DEFAULT 0,
            override_feature_soc_enabled BOOLEAN DEFAULT 0,
            override_feature_training_enabled BOOLEAN DEFAULT 0,
            override_feature_phone_enabled BOOLEAN DEFAULT 0,
            override_feature_email_enabled BOOLEAN DEFAULT 0,
            override_feature_password_manager_enabled BOOLEAN DEFAULT 0,
            FOREIGN KEY (company_account_number) REFERENCES companies (account_number)
        )
    """)
    cur.execute("CREATE TABLE IF NOT EXISTS asset_billing_overrides (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER UNIQUE, billing_type TEXT, custom_cost REAL, FOREIGN KEY (asset_id) REFERENCES assets (id) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_billing_overrides (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, billing_type TEXT, custom_cost REAL, FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS manual_assets (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, hostname TEXT NOT NULL, device_type TEXT, billing_type TEXT, custom_cost REAL, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS manual_users (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, full_name TEXT NOT NULL, email TEXT, billing_type TEXT, custom_cost REAL, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS ticket_details (ticket_id INTEGER PRIMARY KEY, company_account_number TEXT, subject TEXT, last_updated_at TEXT, closed_at TEXT, total_hours_spent REAL, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
    cur.execute("CREATE TABLE scheduler_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_name TEXT NOT NULL UNIQUE, script_path TEXT NOT NULL, interval_minutes INTEGER NOT NULL, enabled BOOLEAN NOT NULL CHECK (enabled IN (0, 1)), last_run TEXT, next_run TEXT, last_status TEXT, last_run_log TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS billing_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, note_content TEXT NOT NULL, created_at TEXT NOT NULL, author TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS client_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL UNIQUE, uploaded_at TEXT NOT NULL, file_size INTEGER, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS custom_line_items (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, name TEXT NOT NULL, monthly_fee REAL, one_off_fee REAL, one_off_month INTEGER, one_off_year INTEGER, yearly_fee REAL, yearly_bill_month INTEGER, yearly_bill_day INTEGER, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS app_users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE)")
    cur.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, timestamp TEXT NOT NULL, action TEXT NOT NULL, table_name TEXT NOT NULL, record_id INTEGER, details TEXT, FOREIGN KEY (user_id) REFERENCES app_users (id))")
    cur.execute("CREATE TABLE IF NOT EXISTS custom_links (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL, link_order INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS feature_options (id INTEGER PRIMARY KEY AUTOINCREMENT, feature_type TEXT NOT NULL, option_name TEXT NOT NULL, UNIQUE (feature_type, option_name))")

    print("Schema creation complete.")

    # --- Data Population ---
    if existing_data:
        # If we are migrating, import the old data
        import_data_to_new_db(con, existing_data)
        # --- THIS IS THE FIX ---
        # If api_keys were not in the export for some reason, we still need to ask for them.
        if 'api_keys' not in existing_data or not existing_data['api_keys']:
             print("\nCould not find existing API keys. Please enter them now.")
             get_and_set_api_keys(cur)
        else:
            print("\nSuccessfully imported existing API keys.")
        # --- END OF FIX ---

    else:
        # If this is a fresh install, populate with defaults
        print("\nThis is a fresh install. Populating with default data...")
        print("Populating default job schedules...")
        default_jobs = [
            ('Sync Billing Data (Companies & Users)', 'pull_freshservice.py', 1440, 1),
            ('Sync Datto RMM Assets', 'pull_datto.py', 1440, 1),
            ('Sync Ticket Details & Hours', 'pull_ticket_details.py', 1440, 1),
            ('Assign Missing Freshservice Account Numbers', 'set_account_numbers.py', 1440, 0),
            ('Push Account Numbers to Datto RMM', 'push_account_nums_to_datto.py', 1440, 0)
        ]
        cur.executemany("INSERT INTO scheduler_jobs (job_name, script_path, interval_minutes, enabled) VALUES (?, ?, ?, ?)", default_jobs)

        print("Populating default billing plans...")
        cur.executemany("INSERT INTO billing_plans (billing_plan, term_length, per_user_cost, per_server_cost, per_workstation_cost, per_vm_cost, per_switch_cost, per_firewall_cost, per_hour_ticket_cost, backup_base_fee_workstation, backup_base_fee_server, backup_included_tb, backup_per_tb_fee) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", default_plans_data)

        print("Populating default feature options...")
        default_features = [
            ('antivirus', 'Datto EDR'), ('antivirus', 'SentinelOne'), ('antivirus', 'Not Included'),
            ('SOC', 'RocketCyber'), ('SOC', 'Not Included'),
            ('email', 'Google Workspace'), ('email', 'Microsoft 365'), ('email', 'Other Business Email'), ('email', 'No Business Email'),
            ('phone', 'Zoom'), ('phone', 'DFN'), ('phone', 'Spectrum'), ('phone', 'RingCentral'), ('phone', 'Personal Cell'), ('phone', 'No Business Phone'),
            ('SAT', 'BSN'), ('SAT', 'Not Included'),
            ('Password Manager', 'Keeper'), ('Password Manager', 'Not Included'),
        ]
        cur.executemany("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", default_features)

        print("Adding default application user...")
        cur.execute("INSERT INTO app_users (username) VALUES ('Admin')")

        # This is a fresh install, so we must get the API keys
        get_and_set_api_keys(cur)


    con.commit()
    con.close()

def get_and_set_api_keys(cursor):
    """Prompts the user for API keys and saves them to the database."""
    print("\nPlease enter your API credentials. They will be stored securely.")
    freshservice_key = getpass.getpass("  - Freshservice API Key: ")
    datto_endpoint = input("  - Datto RMM API Endpoint (e.g., https://api.rmm.datto.com): ")
    datto_key = getpass.getpass("  - Datto RMM Public Key: ")
    datto_secret = getpass.getpass("  - Datto RMM Secret Key: ")
    if not all([freshservice_key, datto_endpoint, datto_key, datto_secret]):
        print("Error: All API credentials are required.", file=sys.stderr)
        # We don't want to leave the DB in a broken state, so we exit here.
        sys.exit(1)

    cursor.execute("DELETE FROM api_keys;") # Clear any old keys before inserting
    cursor.execute("INSERT INTO api_keys (service, api_key) VALUES (?, ?)", ("freshservice", freshservice_key))
    cursor.execute("INSERT INTO api_keys (service, api_endpoint, api_key, api_secret) VALUES (?, ?, ?, ?)", ("datto", datto_endpoint, datto_key, datto_secret))


if __name__ == "__main__":
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"Created directory for file uploads: '{UPLOAD_FOLDER}'")

    if os.path.exists(DB_FILE):
        print(f"An existing database file ('{DB_FILE}') was found.")
        print("This script will export your data, create a new database with the latest schema, and re-import your data.")

        old_password = getpass.getpass("Enter the CURRENT master password to unlock the database: ")
        exported_data = export_data_from_old_db(old_password)

        if exported_data:
            backup_filename = f"{DB_FILE}.{int(time.time())}.bak"
            shutil.move(DB_FILE, backup_filename)
            print(f"\nOld database has been backed up to '{backup_filename}'")

            new_password = getpass.getpass("Enter the NEW master password for the recreated database: ")
            create_database(new_password, existing_data=exported_data)
            print(f"\n✅ Success! Database has been migrated and re-encrypted.")

    else:
        print("--- New Database Setup ---")
        new_password = getpass.getpass("Enter a master password for the new encrypted database: ")
        create_database(new_password, existing_data=None)
        print(f"\n✅ Success! New encrypted database '{DB_FILE}' created and configured.")
