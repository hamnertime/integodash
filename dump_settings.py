import sys
import os
import getpass

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

DB_FILE = "brainhair.db"

def dump_billing_plans(password):
    """
    Connects to the database, queries the default billing plans,
    and prints them in a Python-friendly format suitable for init_db.py.
    """
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found in the current directory.", file=sys.stderr)
        sys.exit(1)

    con = None
    try:
        con = sqlite3.connect(DB_FILE)
        cur = con.cursor()
        cur.execute(f"PRAGMA key = '{password}';")

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='billing_plans';")
        if cur.fetchone() is None:
            print("Error: 'billing_plans' table not found. Is the database initialized correctly?", file=sys.stderr)
            sys.exit(1)

        print("\nReading default billing plans from the database...")

        # Updated to select all current billing columns
        cur.execute("""
            SELECT
                billing_plan,
                term_length,
                network_management_fee,
                per_user_cost,
                per_server_cost,
                per_workstation_cost,
                per_host_cost,
                per_vm_cost,
                backup_base_fee,
                backup_included_tb,
                backup_per_tb_fee
            FROM billing_plans
            ORDER BY billing_plan, term_length
        """)

        plans = cur.fetchall()

        if not plans:
            print("No default billing plans found in the database.")
            return

        print("\n--- Copy the following Python list into your init_db.py script ---")

        print("\ndefault_plans_data = [")

        for plan in plans:
            # Unpack all columns, including the new ones
            (billing_plan, term, nmf, puc, psc_legacy, pwc, phc, pvc, bbf, bit, bpt) = plan
            # Format the output string to match the new structure
            print(f"    ('{billing_plan}', '{term}', {nmf:.2f}, {puc:.2f}, {psc_legacy:.2f}, {pwc:.2f}, {phc:.2f}, {pvc:.2f}, {bbf:.2f}, {bit:.2f}, {bpt:.2f}),")

        print("]")
        print("\n--- End of list ---")

    except sqlite3.Error as e:
        print(f"\n❌ An error occurred: {e}", file=sys.stderr)
        print("This may be due to an incorrect password or a corrupted database file.", file=sys.stderr)
        sys.exit(1)
    finally:
        if con:
            con.close()

if __name__ == "__main__":
    print("--- Billing Plan Settings Dumper ---")

    master_password = getpass.getpass("Enter the master password for the database: ")
    if not master_password:
        print("Error: Master password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    dump_billing_plans(master_password)
