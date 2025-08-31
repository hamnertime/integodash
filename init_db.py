# hamnertime/integodash/integodash-b7a03f16877fb4e6590039b6f2c0b632176ef6cd/init_db.py
import sys
import os
import getpass
import time
import shutil
import re
import json

# This is provided by the sqlcipher3-wheels package
try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)


DB_FILE = "brainhair.db"
CONFIG_FILE = "config.json"
CONFIG_OVERRIDE_FILE = "config.override.json"
UPLOAD_FOLDER = 'uploads'

def load_config():
    """Loads the configuration from the JSON file, preferring the override file if it exists."""
    if os.path.exists(CONFIG_OVERRIDE_FILE):
        print(f"Using custom configuration from '{CONFIG_OVERRIDE_FILE}'.")
        with open(CONFIG_OVERRIDE_FILE, 'r') as f:
            return json.load(f)
    elif os.path.exists(CONFIG_FILE):
        print(f"Using default configuration from '{CONFIG_FILE}'.")
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    else:
        print(f"Error: Neither '{CONFIG_OVERRIDE_FILE}' nor '{CONFIG_FILE}' found.", file=sys.stderr)
        sys.exit(1)

# --- Default Billing Plan Data ---
# This data is used to populate a fresh database. It is ignored during migration.
config = load_config()
default_plans_data = config.get('default_plans_data', [])
default_features = config.get('default_features', [])
default_users = config.get('default_users', [])

default_widget_layouts = {
    "client_details": [
        {"w": 12, "h": 1, "id": "billing-period-selector-widget", "x": 0, "y": 0},
        {"w": 6, "h": 4, "id": "client-details-widget", "x": 0, "y": 1},
        {"w": 6, "h": 4, "id": "client-features-widget", "x": 6, "y": 1},
        {"w": 6, "h": 2, "id": "locations-widget", "x": 0, "y": 5},
        {"w": 6, "h": 5, "id": "billing-receipt-widget", "x": 6, "y": 5},
        {"w": 6, "h": 3, "id": "contract-details-widget", "x": 0, "y": 7},
        {"w": 6, "h": 4, "id": "notes-widget", "x": 0, "y": 10},
        {"w": 6, "h": 4, "id": "attachments-widget", "x": 6, "y": 10},
        {"w": 12, "h": 3, "id": "tracked-assets-widget", "x": 0, "y": 14},
        {"w": 12, "h": 3, "id": "ticket-breakdown-widget", "x": 0, "y": 17}
    ],
    "client_settings": [
        {"w": 6, "h": 5, "id": "client-details-widget", "x": 0, "y": 0},
        {"x": 6, "w": 6, "h": 5, "id": "contract-details-widget", "y": 0},
        {"y": 5, "w": 12, "h": 7, "id": "billing-overrides-widget", "x": 0},
        {"y": 12, "w": 12, "h": 4, "id": "feature-overrides-widget", "x": 0},
        {"y": 16, "w": 12, "h": 4, "id": "custom-line-items-widget", "x": 0},
        {"x": 0, "y": 20, "w": 6, "h": 4, "id": "add-manual-user-widget"},
        {"y": 20, "w": 6, "h": 4, "id": "add-manual-asset-widget", "x": 6},
        {"y": 24, "w": 12, "h": 3, "id": "user-overrides-widget", "x": 0},
        {"y": 27, "w": 12, "h": 4, "id": "asset-overrides-widget", "x": 0}
    ],
    "clients": [
        {"x": 0, "y": 0, "w": 12, "h": 8, "id": "clients-table-widget"},
        {"w": 12, "h": 2, "id": "export-all-widget", "x": 0, "y": 8}
    ],
    "settings": [
        {"w": 12, "h": 2, "id": "import-export-widget", "x": 0, "y": 0},
        {"x": 0, "w": 12, "h": 4, "id": "scheduler-widget", "y": 2},
        {"y": 6, "w": 12, "h": 7, "id": "users-auditing-widget", "x": 0},
        {"y": 13, "w": 12, "h": 3, "id": "custom-links-widget", "x": 0},
        {"y": 16, "w": 12, "h": 8, "id": "billing-plans-widget", "x": 0},
        {"x": 0, "y": 24, "w": 12, "h": 8, "id": "feature-options-widget"}
    ]
}

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

    # Define the correct order for table imports to respect foreign key constraints
    table_import_order = [
        'api_keys',
        'companies',
        'app_users',
        'billing_plans',
        'feature_options',
        'custom_links',
        'scheduler_jobs',
        'assets',
        'users',
        'contacts',
        'client_locations',
        'manual_assets',
        'manual_users',
        'custom_line_items',
        'billing_notes',
        'client_attachments',
        'ticket_details',
        'client_billing_overrides',
        'asset_billing_overrides',
        'user_billing_overrides',
        'asset_contact_links',
        'audit_log',
        'user_widget_layouts'
    ]

    for table_name in table_import_order:
        if table_name not in data or not data[table_name]:
            continue

        rows = data[table_name]

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
            datto_site_uid TEXT,
            datto_portal_url TEXT,
            contract_type TEXT,
            billing_plan TEXT,
            status TEXT,
            contract_term_length TEXT,
            contract_start_date TEXT,
            support_level TEXT,
            phone_number TEXT,
            client_start_date TEXT,
            domains TEXT,
            company_owner TEXT,
            business_type TEXT,
            description TEXT
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS client_locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_account_number TEXT NOT NULL,
            location_name TEXT NOT NULL,
            address TEXT,
            FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE,
            UNIQUE (company_account_number, location_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY,
            company_account_number TEXT,
            datto_uid TEXT UNIQUE,
            hostname TEXT,
            friendly_name TEXT,
            device_type TEXT,
            billing_type TEXT,
            status TEXT,
            date_added TEXT,
            operating_system TEXT,
            backup_data_bytes INTEGER,
            internal_ip TEXT,
            external_ip TEXT,
            last_logged_in_user TEXT,
            domain TEXT,
            is_64_bit BOOLEAN,
            is_online BOOLEAN,
            last_seen TEXT,
            last_reboot TEXT,
            last_audit_date TEXT,
            udf_data TEXT,
            antivirus_data TEXT,
            patch_management_data TEXT,
            portal_url TEXT,
            web_remote_url TEXT,
            FOREIGN KEY (company_account_number) REFERENCES companies (account_number)
        )
    """)
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
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_account_number TEXT,
            first_name TEXT,
            last_name TEXT,
            email TEXT UNIQUE,
            title TEXT,
            work_phone TEXT,
            mobile_phone TEXT,
            employment_type TEXT,
            status TEXT,
            other_emails TEXT,
            address TEXT,
            notes TEXT,
            FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE
        )
    """)

    # Dynamically build the CREATE TABLE statements for billing_plans and client_billing_overrides
    billing_plans_sql = """
        CREATE TABLE IF NOT EXISTS billing_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            billing_plan TEXT,
            term_length TEXT,
            support_level TEXT DEFAULT 'Billed Hourly',
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
    """
    client_overrides_sql = """
        CREATE TABLE IF NOT EXISTS client_billing_overrides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_account_number TEXT UNIQUE,
            billing_plan TEXT,
            support_level TEXT,
            per_user_cost REAL, per_server_cost REAL,
            per_workstation_cost REAL, per_vm_cost REAL, per_switch_cost REAL,
            per_firewall_cost REAL, per_hour_ticket_cost REAL, backup_base_fee_workstation REAL,
            backup_base_fee_server REAL, backup_included_tb REAL, backup_per_tb_fee REAL,
            prepaid_hours_monthly REAL, prepaid_hours_yearly REAL,
            override_billing_plan_enabled BOOLEAN DEFAULT 0,
            override_support_level_enabled BOOLEAN DEFAULT 0,
            override_puc_enabled BOOLEAN DEFAULT 0,
            override_psc_enabled BOOLEAN DEFAULT 0, override_pwc_enabled BOOLEAN DEFAULT 0,
            override_pvc_enabled BOOLEAN DEFAULT 0, override_pswitchc_enabled BOOLEAN DEFAULT 0,
            override_pfirewallc_enabled BOOLEAN DEFAULT 0, override_phtc_enabled BOOLEAN DEFAULT 0,
            override_bbfw_enabled BOOLEAN DEFAULT 0, override_bbfs_enabled BOOLEAN DEFAULT 0,
            override_bit_enabled BOOLEAN DEFAULT 0, override_bpt_enabled BOOLEAN DEFAULT 0,
            override_prepaid_hours_monthly_enabled BOOLEAN DEFAULT 0,
            override_prepaid_hours_yearly_enabled BOOLEAN DEFAULT 0,
    """

    default_feature_types = sorted(list(set([f[0] for f in default_features])))

    for feature_type in default_feature_types:
        column_name = 'feature_' + re.sub(r'[^a-zA-Z0-9_]', '', feature_type.lower().replace(' ', '_'))
        default_value = "'Not Included'"
        if feature_type == 'Email':
            default_value = "'No Business Email'"
        elif feature_type == 'Phone':
            default_value = "'No Business Phone'"
        billing_plans_sql += f"        {column_name} TEXT DEFAULT {default_value},\n"
        client_overrides_sql += f"        {column_name} TEXT,\n"
        client_overrides_sql += f"        override_{column_name}_enabled BOOLEAN DEFAULT 0,\n"

    billing_plans_sql += "        UNIQUE (billing_plan, term_length)\n    )"
    client_overrides_sql = client_overrides_sql.rstrip(',\n') + "\n, FOREIGN KEY (company_account_number) REFERENCES companies (account_number)\n    )"

    cur.execute(billing_plans_sql)
    cur.execute(client_overrides_sql)

    cur.execute("CREATE TABLE IF NOT EXISTS asset_billing_overrides (id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id INTEGER UNIQUE, billing_type TEXT, custom_cost REAL, FOREIGN KEY (asset_id) REFERENCES assets (id) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS user_billing_overrides (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER UNIQUE, billing_type TEXT, custom_cost REAL, employment_type TEXT, FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS manual_assets (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, hostname TEXT NOT NULL, device_type TEXT, billing_type TEXT, custom_cost REAL, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS manual_users (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, full_name TEXT NOT NULL, email TEXT, billing_type TEXT, custom_cost REAL, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS ticket_details (ticket_id INTEGER PRIMARY KEY, company_account_number TEXT, subject TEXT, last_updated_at TEXT, closed_at TEXT, total_hours_spent REAL, FOREIGN KEY (company_account_number) REFERENCES companies (account_number))")
    cur.execute("CREATE TABLE scheduler_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, job_name TEXT NOT NULL UNIQUE, script_path TEXT NOT NULL, interval_minutes INTEGER NOT NULL, enabled BOOLEAN NOT NULL CHECK (enabled IN (0, 1)), last_run TEXT, next_run TEXT, last_status TEXT, last_run_log TEXT)")
    cur.execute("CREATE TABLE IF NOT EXISTS billing_notes (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, note_content TEXT NOT NULL, created_at TEXT NOT NULL, author TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS client_attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, original_filename TEXT NOT NULL, stored_filename TEXT NOT NULL UNIQUE, uploaded_at TEXT NOT NULL, file_size INTEGER, category TEXT, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS custom_line_items (id INTEGER PRIMARY KEY AUTOINCREMENT, company_account_number TEXT NOT NULL, name TEXT NOT NULL, monthly_fee REAL, one_off_fee REAL, one_off_month INTEGER, one_off_year INTEGER, yearly_fee REAL, yearly_bill_month INTEGER, yearly_bill_day INTEGER, FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE)")
    cur.execute("CREATE TABLE IF NOT EXISTS app_users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, role TEXT NOT NULL DEFAULT 'Read-Only')")
    cur.execute("CREATE TABLE IF NOT EXISTS audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, timestamp TEXT NOT NULL, action TEXT NOT NULL, table_name TEXT NOT NULL, record_id INTEGER, details TEXT, FOREIGN KEY (user_id) REFERENCES app_users (id))")
    cur.execute("CREATE TABLE IF NOT EXISTS custom_links (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, url TEXT NOT NULL, link_order INTEGER DEFAULT 0)")
    cur.execute("CREATE TABLE IF NOT EXISTS feature_options (id INTEGER PRIMARY KEY AUTOINCREMENT, feature_type TEXT NOT NULL, option_name TEXT NOT NULL, UNIQUE (feature_type, option_name))")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_widget_layouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            page_name TEXT NOT NULL,
            layout TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES app_users (id) ON DELETE CASCADE,
            UNIQUE (user_id, page_name)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS asset_contact_links (
            asset_id INTEGER NOT NULL,
            contact_id INTEGER NOT NULL,
            PRIMARY KEY (asset_id, contact_id),
            FOREIGN KEY (asset_id) REFERENCES assets (id) ON DELETE CASCADE,
            FOREIGN KEY (contact_id) REFERENCES contacts (id) ON DELETE CASCADE
        )
    """)

    print("Schema creation complete.")

    # --- Data Population ---
    if existing_data:
        # If we are migrating, import the old data
        import_data_to_new_db(con, existing_data)
        # After importing, ensure all default features exist.
        # This handles cases where new features were added in an update.
        print("\nVerifying and inserting missing default feature options...")
        cur = con.cursor()
        cur.executemany("INSERT OR IGNORE INTO feature_options (feature_type, option_name) VALUES (?, ?)", default_features)
        con.commit()
        print("Default features are up to date.")
        # If api_keys were not in the export for some reason, we still need to ask for them.
        if 'api_keys' not in existing_data or not existing_data['api_keys']:
             print("\nCould not find existing API keys. Please enter them now.")
             get_and_set_api_keys(cur)
        else:
            print("\nSuccessfully imported existing API keys.")

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
        cur.executemany("INSERT INTO billing_plans (billing_plan, term_length, per_user_cost, per_server_cost, per_workstation_cost, per_vm_cost, per_switch_cost, per_firewall_cost, per_hour_ticket_cost, backup_base_fee_workstation, backup_base_fee_server, backup_included_tb, backup_per_tb_fee, support_level, feature_antivirus, feature_soc, feature_password_manager, feature_sat, feature_network_management) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", default_plans_data)

        print("Populating default feature options...")
        cur.executemany("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", default_features)

        print("Adding default application users...")
        cur.executemany("INSERT INTO app_users (username, role) VALUES (?, ?)", default_users)

        # This is a fresh install, so we must get the API keys
        get_and_set_api_keys(cur)

        # Set the default widget layout for the Admin user (ID 1)
        print("Setting default widget layouts for Admin user...")
        for page_name, layout in default_widget_layouts.items():
            layout_json = json.dumps(layout)
            cur.execute(
                "INSERT INTO user_widget_layouts (user_id, page_name, layout) VALUES (?, ?, ?)",
                (1, page_name, layout_json)
            )


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
