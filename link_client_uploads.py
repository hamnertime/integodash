import os
import sys
import getpass
from datetime import datetime, timezone

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    sys.exit("Error: sqlcipher3-wheels is not installed. Run: pip install sqlcipher3-wheels")

# Configuration
DB_FILE = "brainhair.db"
UPLOAD_FOLDER = 'uploads'
DEFAULT_CATEGORY = 'Recovered'

def get_db_connection(db_path, password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con, cur

def relink_uploads(password):
    """
    Scans the uploads directory and links any orphaned files back to clients
    in the database.
    """
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found.", file=sys.stderr)
        sys.exit(1)
    if not os.path.exists(UPLOAD_FOLDER):
        print(f"Error: Uploads folder '{UPLOAD_FOLDER}' not found.", file=sys.stderr)
        sys.exit(1)

    con = None
    try:
        con, cur = get_db_connection(DB_FILE, password)
        print("Successfully connected to the database.")

        total_files_scanned = 0
        total_files_linked = 0

        # Get a list of all client account numbers from the uploads folder
        client_dirs = [d for d in os.listdir(UPLOAD_FOLDER) if os.path.isdir(os.path.join(UPLOAD_FOLDER, d))]

        print(f"\nFound {len(client_dirs)} client directories in '{UPLOAD_FOLDER}'. Starting scan...")

        for account_number in client_dirs:
            client_path = os.path.join(UPLOAD_FOLDER, account_number)
            print(f"\n--- Scanning for client: {account_number} ---")

            # Check if this company exists in the database
            cur.execute("SELECT 1 FROM companies WHERE account_number = ?", (account_number,))
            if not cur.fetchone():
                print(f"  -> Skipping: No company with account number '{account_number}' found in the database.")
                continue

            for stored_filename in os.listdir(client_path):
                total_files_scanned += 1
                file_path = os.path.join(client_path, stored_filename)

                # Check if this file already has a record in the database
                cur.execute("SELECT 1 FROM client_attachments WHERE stored_filename = ?", (stored_filename,))
                if cur.fetchone():
                    print(f"  -> Skipping: '{stored_filename}' already linked in the database.")
                    continue

                # If not found, create a new record
                try:
                    # Extract original filename (part after the UUID and underscore)
                    original_filename = '_'.join(stored_filename.split('_')[1:])
                    file_size = os.path.getsize(file_path)
                    creation_time = os.path.getctime(file_path)
                    uploaded_at = datetime.fromtimestamp(creation_time, tz=timezone.utc).isoformat()

                    print(f"  -> Relinking: '{original_filename}'")
                    cur.execute("""
                        INSERT INTO client_attachments
                        (company_account_number, original_filename, stored_filename, uploaded_at, file_size, category)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (account_number, original_filename, stored_filename, uploaded_at, file_size, DEFAULT_CATEGORY))
                    total_files_linked += 1

                except Exception as e:
                    print(f"  -> ERROR linking '{stored_filename}': {e}", file=sys.stderr)

        con.commit()

        print("\n--- Scan Complete ---")
        print(f"Total files scanned: {total_files_scanned}")
        print(f"New files linked to database: {total_files_linked}")
        print("---------------------")

    except sqlite3.Error as e:
        print(f"\n❌ An error occurred with the database: {e}", file=sys.stderr)
        print("Please ensure the password is correct and the database is not corrupted.", file=sys.stderr)
        sys.exit(1)
    finally:
        if con:
            con.close()

if __name__ == "__main__":
    print("--- Client Upload Relinking Script ---")
    master_password = getpass.getpass("Enter the master password for the database: ")
    if not master_password:
        print("Error: Master password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    relink_uploads(master_password)
