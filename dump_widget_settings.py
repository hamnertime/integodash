import sys
import os
import getpass
import json

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

DB_FILE = "brainhair.db"

def get_db_connection(db_path, password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con, cur

def get_user_id(cur, username):
    """Fetches the user ID for a given username."""
    cur.execute("SELECT id FROM app_users WHERE username = ?", (username,))
    user = cur.fetchone()
    if user:
        return user['id']
    return None

def dump_user_widget_layouts(password, username):
    """
    Connects to the database, queries the widget layouts for a specific user,
    and prints them in a JSON format.
    """
    if not os.path.exists(DB_FILE):
        print(f"Error: Database file '{DB_FILE}' not found in the current directory.", file=sys.stderr)
        sys.exit(1)

    con = None
    try:
        con, cur = get_db_connection(DB_FILE, password)

        user_id = get_user_id(cur, username)
        if not user_id:
            print(f"Error: User '{username}' not found in the database.", file=sys.stderr)
            cur.execute("SELECT username FROM app_users")
            users = cur.fetchall()
            print("\nAvailable users:")
            for user in users:
                print(f"  - {user['username']}")
            sys.exit(1)


        print(f"\nReading widget layouts for user '{username}' (ID: {user_id}) from the database...")

        cur.execute("""
            SELECT page_name, layout
            FROM user_widget_layouts
            WHERE user_id = ?
            ORDER BY page_name
        """, (user_id,))

        layouts = cur.fetchall()

        if not layouts:
            print(f"No widget layouts found for user '{username}'.")
            return

        print("\n--- Copy the following JSON into your init_db.py script ---")

        default_layouts = {layout['page_name']: json.loads(layout['layout']) for layout in layouts}

        print("\ndefault_widget_layouts = " + json.dumps(default_layouts, indent=4))

        print("\n--- End of JSON ---")

    except sqlite3.Error as e:
        print(f"\n❌ An error occurred: {e}", file=sys.stderr)
        print("This may be due to an incorrect password or a corrupted database file.", file=sys.stderr)
        sys.exit(1)
    finally:
        if con:
            con.close()

if __name__ == "__main__":
    print("--- User Widget Layout Dumper ---")

    if len(sys.argv) != 2:
        print("Usage: python dump_widget_settings.py <username>")
        sys.exit(1)

    target_username = sys.argv[1]
    master_password = getpass.getpass(f"Enter the master password for the database to fetch settings for '{target_username}': ")
    if not master_password:
        print("Error: Master password cannot be empty.", file=sys.stderr)
        sys.exit(1)

    dump_user_widget_layouts(master_password, target_username)
