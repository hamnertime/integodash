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
UPLOAD_FOLDER = 'uploads'

# --- Default Billing Plan Data ---
# (Your existing default_plans_data remains here)
default_plans_data = [
    # plan, term, nmf, puc, psc, pwc, pvc, pswitchc, pfirewallc, phtc, bbfw, bbfs, bit, bpt
    ('Break Fix', '1-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('Break Fix', '2-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('Break Fix', '3-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('Break Fix', 'Month to Month', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 100.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', '1-Year', 0.00, 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', '2-Year', 0.00, 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', '3-Year', 0.00, 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Advanced', 'Month to Month', 0.00, 0.00, 100.00, 25.00, 100.00, 25.00, 25.00, 100.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', '1-Year', 0.00, 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', '2-Year', 0.00, 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', '3-Year', 0.00, 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 90.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Basic', 'Month to Month', 0.00, 0.00, 100.00, 10.00, 100.00, 25.00, 25.00, 100.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', '1-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', '2-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', '3-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Legacy', 'Month to Month', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', '1-Year', 0.00, 120.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', '2-Year', 0.00, 115.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', '3-Year', 0.00, 110.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Platinum', 'Month to Month', 0.00, 125.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', '1-Year', 0.00, 95.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', '2-Year', 0.00, 90.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', '3-Year', 0.00, 85.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('MSP Premium', 'Month to Month', 0.00, 100.00, 100.00, 0.00, 100.00, 25.00, 25.00, 0.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', '1-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', '2-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', '3-Year', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
    ('Pro Services', 'Month to Month', 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 120.00, 25.00, 50.00, 1.0, 15.00),
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

    # Create the upload directory
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
        print(f"Created directory for file uploads: '{UPLOAD_FOLDER}'")

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
        # (Your existing table creation statements remain here)
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
                network_management_fee REAL DEFAULT 0,
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
                feature_phone TEXT DEFAULT 'Not Included',
                feature_email TEXT DEFAULT 'Not Included',
                UNIQUE (billing_plan, term_length)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS client_billing_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT UNIQUE,

                -- Rate Overrides
                network_management_fee REAL,
                per_user_cost REAL,
                per_server_cost REAL,
                per_workstation_cost REAL,
                per_vm_cost REAL,
                per_switch_cost REAL,
                per_firewall_cost REAL,
                per_hour_ticket_cost REAL,
                backup_base_fee_workstation REAL,
                backup_base_fee_server REAL,
                backup_included_tb REAL,
                backup_per_tb_fee REAL,
                prepaid_hours_monthly REAL,
                prepaid_hours_yearly REAL,

                -- Enable/Disable Flags for each override
                override_nmf_enabled BOOLEAN DEFAULT 0,
                override_puc_enabled BOOLEAN DEFAULT 0,
                override_psc_enabled BOOLEAN DEFAULT 0,
                override_pwc_enabled BOOLEAN DEFAULT 0,
                override_pvc_enabled BOOLEAN DEFAULT 0,
                override_pswitchc_enabled BOOLEAN DEFAULT 0,
                override_pfirewallc_enabled BOOLEAN DEFAULT 0,
                override_phtc_enabled BOOLEAN DEFAULT 0,
                override_bbfw_enabled BOOLEAN DEFAULT 0,
                override_bbfs_enabled BOOLEAN DEFAULT 0,
                override_bit_enabled BOOLEAN DEFAULT 0,
                override_bpt_enabled BOOLEAN DEFAULT 0,
                override_prepaid_hours_monthly_enabled BOOLEAN DEFAULT 0,
                override_prepaid_hours_yearly_enabled BOOLEAN DEFAULT 0,

                -- Feature Overrides
                feature_antivirus TEXT,
                feature_soc TEXT,
                feature_training TEXT,
                feature_phone TEXT,
                feature_email TEXT,

                -- Enable/Disable Flags for each feature override
                override_feature_antivirus_enabled BOOLEAN DEFAULT 0,
                override_feature_soc_enabled BOOLEAN DEFAULT 0,
                override_feature_training_enabled BOOLEAN DEFAULT 0,
                override_feature_phone_enabled BOOLEAN DEFAULT 0,
                override_feature_email_enabled BOOLEAN DEFAULT 0,

                FOREIGN KEY (company_account_number) REFERENCES companies (account_number)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS asset_billing_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id INTEGER UNIQUE,
                billing_type TEXT,
                custom_cost REAL,
                FOREIGN KEY (asset_id) REFERENCES assets (id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_billing_overrides (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                billing_type TEXT,
                custom_cost REAL,
                FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS manual_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT NOT NULL,
                hostname TEXT NOT NULL,
                device_type TEXT,
                billing_type TEXT,
                custom_cost REAL,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS manual_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT,
                billing_type TEXT,
                custom_cost REAL,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE
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
        cur.execute("""
            CREATE TABLE IF NOT EXISTS billing_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT NOT NULL,
                note_content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                author TEXT,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS client_attachments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL UNIQUE,
                uploaded_at TEXT NOT NULL,
                file_size INTEGER,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS custom_line_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_account_number TEXT NOT NULL,
                name TEXT NOT NULL,
                monthly_fee REAL,
                one_off_fee REAL,
                one_off_month INTEGER,
                one_off_year INTEGER,
                yearly_fee REAL,
                yearly_bill_month INTEGER,
                yearly_bill_day INTEGER,
                FOREIGN KEY (company_account_number) REFERENCES companies (account_number) ON DELETE CASCADE
            )
        """)

        # --- NEW TABLES ---
        cur.execute("""
            CREATE TABLE IF NOT EXISTS app_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                table_name TEXT NOT NULL,
                record_id INTEGER,
                details TEXT,
                FOREIGN KEY (user_id) REFERENCES app_users (id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS custom_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                url TEXT NOT NULL,
                link_order INTEGER DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS feature_options (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feature_type TEXT NOT NULL,
                option_name TEXT NOT NULL,
                UNIQUE (feature_type, option_name)
            )
        """)
        # --- END NEW TABLES ---

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
            INSERT INTO billing_plans (billing_plan, term_length, network_management_fee, per_user_cost, per_server_cost, per_workstation_cost, per_vm_cost, per_switch_cost, per_firewall_cost, per_hour_ticket_cost, backup_base_fee_workstation, backup_base_fee_server, backup_included_tb, backup_per_tb_fee)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, default_plans_data)

        print("Populating default feature options...")
        default_features = [
            ('antivirus', 'Not Included'),
            ('antivirus', 'SentinelOne'),
            ('antivirus', 'Datto EDR'),
            ('SOC', 'Not Included'),
            ('SOC', 'RocketCyber'),
            ('email', 'Not Included'),
            ('email', 'Microsoft 365'),
            ('email', 'Google Workspace'),
            ('phone', 'Not Included'),
            ('phone', 'VoIP Service'),
            ('SAT', 'Not Included'),
            ('SAT', 'KnowBe4'),
        ]
        cur.executemany("INSERT INTO feature_options (feature_type, option_name) VALUES (?, ?)", default_features)

        print("Adding default application user...")
        cur.execute("INSERT INTO app_users (username) VALUES ('Admin')")

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
