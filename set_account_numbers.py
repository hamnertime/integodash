import requests
import base64
import json
import os
import sys
import time
import random

try:
    from sqlcipher3 import dbapi2 as sqlite3
except ImportError:
    print("Error: sqlcipher3-wheels is not installed. Please install it using: pip install sqlcipher3-wheels", file=sys.stderr)
    sys.exit(1)

# --- Configuration ---
DB_FILE = "brainhair.db"
FRESHSERVICE_DOMAIN = "integotecllc.freshservice.com"
BASE_URL = f"https://{FRESHSERVICE_DOMAIN}"
ACCOUNT_NUMBER_FIELD = "account_number"
COMPANIES_PER_PAGE = 100
MAX_RETRIES = 3
RETRY_DELAY = 5 # seconds

# --- Utility Functions ---
def get_db_connection(db_path, password):
    """Establishes a connection to the encrypted database."""
    if not password:
        raise ValueError("A database password is required.")
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(f"PRAGMA key = '{password}';")
    return con

def get_freshservice_api_key(db_password):
    """Reads the Freshservice API key from the encrypted database."""
    try:
        con = get_db_connection(DB_FILE, db_password)
        cur = con.cursor()
        cur.execute("SELECT api_key FROM api_keys WHERE service = 'freshservice'")
        creds = cur.fetchone()
        con.close()
        if not creds:
            raise ValueError("Freshservice credentials not found in the database.")
        return creds[0]
    except sqlite3.Error as e:
        sys.exit(f"Database error while fetching credentials: {e}. Is the password correct?")


# --- API Functions ---
def get_all_companies(base_url, headers):
    """Fetches all companies (departments) from the Freshservice API."""
    all_companies = []
    page = 1
    endpoint = f"{base_url}/api/v2/departments"
    print(f"Fetching all companies from: {endpoint}")

    while True:
        params = {'page': page, 'per_page': COMPANIES_PER_PAGE}
        try:
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', RETRY_DELAY))
                print(f"Rate limit exceeded. Waiting {retry_after} seconds...")
                time.sleep(retry_after)
                continue
            response.raise_for_status()
            data = response.json()
            companies_on_page = data.get('departments', [])
            if not companies_on_page:
                break
            all_companies.extend(companies_on_page)
            if len(companies_on_page) < COMPANIES_PER_PAGE:
                break
            page += 1
        except requests.exceptions.RequestException as e:
            print(f"Error fetching companies: {e}", file=sys.stderr)
            return None
    return all_companies

def update_company_account_number(base_url, headers, company_id, account_number):
    """Updates a single company with a new account number."""
    endpoint = f"{base_url}/api/v2/departments/{company_id}"

    payload = {
        "custom_fields": {
            ACCOUNT_NUMBER_FIELD: account_number
        }
    }

    try:
        response = requests.put(endpoint, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Failed to update company ID {company_id}: {e}", file=sys.stderr)
        if hasattr(e, 'response'):
            print(f"Response: {e.response.text}", file=sys.stderr)
        return False

# --- Main Execution ---
if __name__ == "__main__":
    print(" Freshservice Account Number Setter")
    print("==========================================")

    DB_MASTER_PASSWORD = os.environ.get('DB_MASTER_PASSWORD')
    if not DB_MASTER_PASSWORD:
        sys.exit("Error: The DB_MASTER_PASSWORD environment variable must be set.")

    API_KEY = get_freshservice_api_key(DB_MASTER_PASSWORD)
    auth_str = f"{API_KEY}:X"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Basic {encoded_auth}"
    }

    # 1. Fetch all companies
    companies = get_all_companies(BASE_URL, headers)
    if companies is None:
        print("Could not fetch companies. Aborting.", file=sys.stderr)
        sys.exit(1)

    print(f"\nFound {len(companies)} total companies in Freshservice.")

    # 2. Find existing account numbers and companies that need one
    existing_numbers = set()
    companies_to_update = []

    for company in companies:
        custom_fields = company.get('custom_fields', {})
        acc_num = custom_fields.get(ACCOUNT_NUMBER_FIELD)
        if acc_num:
            # Add the number to our set to prevent creating duplicates
            existing_numbers.add(int(acc_num))
        else:
            companies_to_update.append(company)

    print(f"Found {len(existing_numbers)} companies with existing account numbers.")
    print(f"Found {len(companies_to_update)} companies that need a new account number.")

    if not companies_to_update:
        print("\nAll companies already have an account number. Nothing to do.")
        sys.exit(0)

    # 3. Generate and assign unique numbers
    print("\n--- Assigning New Account Numbers ---")
    updated_count = 0
    for company in companies_to_update:
        new_number = None
        while new_number is None or new_number in existing_numbers:
            new_number = random.randint(100000, 999999)

        company_id = company['id']
        company_name = company['name']

        print(f"Updating '{company_name}' (ID: {company_id}) with new account number: {new_number}")

        # 4. Update the company in Freshservice
        success = update_company_account_number(BASE_URL, headers, company_id, new_number)

        if success:
            existing_numbers.add(new_number)
            updated_count += 1
            # Be respectful of API rate limits
            time.sleep(0.5)
        else:
            print(f"Skipping '{company_name}' due to update failure.")

    print("\n-----------------------------------------")
    print(f" Successfully updated {updated_count} companies.")
    print("\nScript finished.")
