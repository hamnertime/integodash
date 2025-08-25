from collections import defaultdict
from datetime import datetime, timezone, timedelta
from database import query_db
import calendar
import sys

def get_billing_data_for_client(account_number, year, month):
    """
    A comprehensive function to fetch all data and calculate billing details for a specific client and period.
    This is the core logic that powers both the dashboard and the breakdown view.
    """
    client_info_raw = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
    if not client_info_raw:
        return None

    client_info = dict(client_info_raw) # Make it a mutable dictionary

    # --- 1. Fetch all raw data from the database ---
    assets = [dict(r) for r in query_db("SELECT * FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])]
    manual_assets = [dict(r) for r in query_db("SELECT * FROM manual_assets WHERE company_account_number = ? ORDER BY hostname", [account_number])]
    users = [dict(r) for r in query_db("SELECT * FROM users WHERE company_account_number = ? AND status = 'Active' ORDER BY full_name", [account_number])]
    manual_users = [dict(r) for r in query_db("SELECT * FROM manual_users WHERE company_account_number = ? ORDER BY full_name", [account_number])]
    custom_line_items = [dict(r) for r in query_db("SELECT * FROM custom_line_items WHERE company_account_number = ? ORDER BY name", [account_number])]

    asset_overrides = {r['asset_id']: dict(r) for r in query_db("SELECT * FROM asset_billing_overrides ao JOIN assets a ON a.id = ao.asset_id WHERE a.company_account_number = ?", [account_number])}
    user_overrides = {r['user_id']: dict(r) for r in query_db("SELECT * FROM user_billing_overrides uo JOIN users u ON u.id = uo.user_id WHERE u.company_account_number = ?", [account_number])}

    plan_details = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
    rate_overrides = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)

    # Fetch tickets for the entire year to calculate yearly totals and monthly breakdowns accurately
    current_year = datetime.now().year
    all_tickets_this_year = [dict(r) for r in query_db("SELECT * FROM ticket_details WHERE company_account_number = ? AND strftime('%Y', last_updated_at) = ?", [account_number, str(current_year)] )]

    # --- THIS IS THE FIX ---
    # If the plan doesn't exist in the database, we can't calculate a bill.
    # Return None to signal the calling route to handle this gracefully.
    if not plan_details:
        return None
    # --- END OF FIX ---

    # --- 2. Determine the Effective Billing Rates ---
    effective_rates = dict(plan_details) if plan_details else {}
    if rate_overrides:
        rate_key_map = {'nmf': 'network_management_fee', 'puc': 'per_user_cost', 'psc': 'per_server_cost', 'pwc': 'per_workstation_cost', 'pvc': 'per_vm_cost', 'pswitchc': 'per_switch_cost', 'pfirewallc': 'per_firewall_cost', 'phtc': 'per_hour_ticket_cost', 'bbfw': 'backup_base_fee_workstation', 'bbfs': 'backup_base_fee_server', 'bit': 'backup_included_tb', 'bpt': 'backup_per_tb_fee'}
        for short_key, rate_key in rate_key_map.items():
            if rate_overrides[f'override_{short_key}_enabled']:
                effective_rates[rate_key] = rate_overrides[rate_key]

        feature_key_map = {'antivirus': 'feature_antivirus', 'soc': 'feature_soc', 'training': 'feature_training', 'phone': 'feature_phone', 'email': 'feature_email'}
        for short_key, feature_key in feature_key_map.items():
            if rate_overrides[f'override_feature_{short_key}_enabled']:
                effective_rates[feature_key] = rate_overrides[feature_key]

    support_level_display = "Unlimited" if effective_rates.get('per_hour_ticket_cost', 0) == 0 else "Billed Hourly"

    # --- 2a. Calculate Contract End Date ---
    contract_end_date = "N/A"
    if client_info['contract_start_date'] and client_info['contract_term_length']:
        try:
            # Extract the date part from the string, which might contain extra text.
            date_str_full = client_info['contract_start_date'].split()[-1]
            # Isolate just the date part by splitting at 'T' and taking the first part.
            date_str_only = date_str_full.split('T')[0]
            # Clean and parse the extracted date string.
            start_date = datetime.fromisoformat(date_str_only)

            # Reformat the start date for clean display in the template
            client_info['contract_start_date'] = start_date.strftime('%Y-%m-%d')

            term = client_info['contract_term_length']
            years_to_add = 0
            if term == '1-Year':
                years_to_add = 1
            elif term == '2-Year':
                years_to_add = 2
            elif term == '3-Year':
                years_to_add = 3

            if years_to_add > 0:
                # Add years and subtract one day to get the end date
                contract_end_date = (start_date.replace(year=start_date.year + years_to_add) - timedelta(days=1)).strftime('%Y-%m-%d')
            elif term == 'Month to Month':
                contract_end_date = "Month to Month"

        except (ValueError, TypeError, IndexError):
            contract_end_date = "Invalid Start Date"

    # --- 3. Calculate Itemized Asset Charges ---
    billed_assets = []
    quantities = defaultdict(int)
    all_assets = assets + manual_assets
    total_asset_charges = 0.0
    for asset in all_assets:
        is_manual = 'datto_uid' not in asset
        override = asset_overrides.get(asset.get('id')) if not is_manual else asset

        billing_type = (override.get('billing_type') if override else None) or asset.get('billing_type', 'Workstation')

        cost = 0.0
        if billing_type == 'Custom':
            cost = (override.get('custom_cost') or 0.0) if override else 0.0
        elif billing_type != 'No Charge':
            rate_key = f"per_{billing_type.lower()}_cost"
            cost = effective_rates.get(rate_key, 0.0) or 0.0

        total_asset_charges += cost
        quantities[billing_type.lower()] += 1
        billed_assets.append({'name': asset['hostname'], 'type': billing_type, 'cost': cost})

    # --- 4. Calculate Itemized User Charges ---
    billed_users = []
    all_users = users + manual_users
    total_user_charges = 0.0
    for user in all_users:
        is_manual = 'freshservice_id' not in user
        override = user_overrides.get(user.get('id')) if not is_manual else user

        billing_type = (override.get('billing_type') if override else None) or 'Paid'

        cost = 0.0
        if billing_type == 'Custom':
            cost = (override.get('custom_cost') or 0.0) if override else 0.0
        elif billing_type == 'Paid':
            cost = effective_rates.get('per_user_cost', 0.0) or 0.0

        total_user_charges += cost
        quantities['regular_users' if billing_type == 'Paid' else 'free_users'] += 1
        billed_users.append({'name': user['full_name'], 'type': billing_type, 'cost': cost})

    # --- 5. Calculate Ticket Charges for the specified billing period (year, month) ---
    _, num_days = calendar.monthrange(year, month)
    start_of_billing_month = datetime(year, month, 1, tzinfo=timezone.utc)
    end_of_billing_month = datetime(year, month, num_days, 23, 59, 59, tzinfo=timezone.utc)

    tickets_for_period = [t for t in all_tickets_this_year if start_of_billing_month <= datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')) <= end_of_billing_month]
    hours_for_period = sum(t['total_hours_spent'] for t in tickets_for_period)

    prepaid_monthly = (rate_overrides['prepaid_hours_monthly'] if rate_overrides and rate_overrides['override_prepaid_hours_monthly_enabled'] else 0) or 0
    prepaid_yearly = (rate_overrides['prepaid_hours_yearly'] if rate_overrides and rate_overrides['override_prepaid_hours_yearly_enabled'] else 0) or 0

    hours_used_prior = sum(t['total_hours_spent'] for t in all_tickets_this_year if datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')) < start_of_billing_month)
    remaining_yearly_hours = max(0, prepaid_yearly - hours_used_prior)

    billable_hours = max(0, max(0, hours_for_period - prepaid_monthly) - remaining_yearly_hours)
    ticket_charge = billable_hours * (effective_rates.get('per_hour_ticket_cost', 0) or 0)

    # --- 5a. Calculate hours for dashboard view ---
    now = datetime.now(timezone.utc)
    first_day_of_current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_of_last_month = first_day_of_current_month - timedelta(days=1)

    hours_this_month = sum(t['total_hours_spent'] for t in all_tickets_this_year if datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')).month == now.month)
    hours_last_month = sum(t['total_hours_spent'] for t in all_tickets_this_year if datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')).month == last_day_of_last_month.month)


    # --- 6. Calculate Backup Charges ---
    backup_info = {
        'total_backup_bytes': sum(a.get('backup_data_bytes', 0) for a in assets if a.get('backup_data_bytes')),
        'backed_up_workstations': sum(1 for a in assets if a.get('billing_type') == 'Workstation' and a.get('backup_data_bytes')),
        'backed_up_servers': sum(1 for a in assets if a.get('billing_type') in ('Server', 'VM') and a.get('backup_data_bytes')),
    }
    total_backup_tb = backup_info['total_backup_bytes'] / 1099511627776.0
    included_tb = (backup_info['backed_up_workstations'] + backup_info['backed_up_servers']) * (effective_rates.get('backup_included_tb', 1) or 1)
    overage_tb = max(0, total_backup_tb - included_tb)

    backup_base_workstation_charge = backup_info['backed_up_workstations'] * (effective_rates.get('backup_base_fee_workstation', 0) or 0)
    backup_base_server_charge = backup_info['backed_up_servers'] * (effective_rates.get('backup_base_fee_server', 0) or 0)
    overage_charge = overage_tb * (effective_rates.get('backup_per_tb_fee', 0) or 0)
    backup_charge = backup_base_workstation_charge + backup_base_server_charge + overage_charge

    # --- 7. Calculate Custom Line Item Charges ---
    billed_line_items = []
    total_line_item_charges = 0.0
    for item in custom_line_items:
        cost = 0.0
        item_type = None
        if item['monthly_fee'] is not None:
            cost = item['monthly_fee']
            item_type = 'Recurring'
            total_line_item_charges += cost
        elif item['one_off_year'] == year and item['one_off_month'] == month:
            cost = item['one_off_fee']
            item_type = 'One-Off'
            total_line_item_charges += cost
        elif item['yearly_bill_month'] == month:
            # Simple check for now. We might need to check the day as well if it matters.
            cost = item['yearly_fee']
            item_type = 'Yearly'
            total_line_item_charges += cost

        if item_type:
            billed_line_items.append({'name': item['name'], 'type': item_type, 'cost': cost})

    # --- 8. Assemble Final Bill and Data Package ---
    nmf_charge = effective_rates.get('network_management_fee', 0) or 0
    total_bill = nmf_charge + total_asset_charges + total_user_charges + ticket_charge + backup_charge + total_line_item_charges

    receipt = {
        'nmf': nmf_charge,
        'billed_assets': billed_assets,
        'billed_users': billed_users,
        'billed_line_items': billed_line_items,
        'total_user_charges': total_user_charges,
        'total_asset_charges': total_asset_charges,
        'total_line_item_charges': total_line_item_charges,
        'ticket_charge': ticket_charge,
        'backup_charge': backup_charge,
        'total': total_bill,
        'hours_for_billing_period': hours_for_period,
        'prepaid_hours_monthly': prepaid_monthly,
        'billable_hours': billable_hours,
        'backup_base_workstation': backup_base_workstation_charge,
        'backup_base_server': backup_base_server_charge,
        'total_included_tb': included_tb,
        'overage_tb': overage_tb,
        'overage_charge': overage_charge,
    }

    return {
        'client': client_info,
        'assets': assets, 'manual_assets': manual_assets,
        'users': users, 'manual_users': manual_users,
        'custom_line_items': custom_line_items,
        'asset_overrides': asset_overrides, 'user_overrides': user_overrides,
        'all_tickets_this_year': all_tickets_this_year,
        'tickets_for_billing_period': tickets_for_period,
        'receipt_data': receipt,
        'effective_rates': effective_rates,
        'quantities': quantities,
        'backup_info': backup_info,
        'total_backup_tb': total_backup_tb,
        'remaining_yearly_hours': remaining_yearly_hours,
        'hours_this_month': hours_this_month,
        'hours_last_month': hours_last_month,
        'support_level_display': support_level_display,
        'contract_end_date': contract_end_date,
    }

def get_billing_dashboard_data(sort_by='name', sort_order='asc'):
    """Calculates and returns the data for the main billing dashboard."""
    # Fetch all clients without sorting in the DB
    clients_raw = query_db("SELECT * FROM companies")
    clients_data = []
    now = datetime.now()

    for client_row in clients_raw:
        # Get the full data package for each client for the current month
        data = get_billing_data_for_client(client_row['account_number'], now.year, now.month)
        if not data:
            # --- THIS IS THE FIX ---
            # If the billing plan isn't configured, we can't calculate a bill.
            # We'll still show the client on the dashboard, but with 0 values for calculated fields.
            client = dict(client_row)
            client['workstations'] = 0
            client['servers'] = 0
            client['vms'] = 0
            client['regular_users'] = 0
            client['total_hours'] = 0
            client['hours_this_month'] = 0
            client['hours_last_month'] = 0
            client['total_backup_bytes'] = 0
            client['total_bill'] = 0.00
            clients_data.append(client)
            # --- END OF FIX ---
            continue

        client = data['client']
        # Populate the dictionary with calculated values
        client['workstations'] = data['quantities'].get('workstation', 0)
        client['servers'] = data['quantities'].get('server', 0)
        client['vms'] = data['quantities'].get('vm', 0)
        client['regular_users'] = data['quantities'].get('regular_users', 0)
        client['total_hours'] = sum(t['total_hours_spent'] for t in data['all_tickets_this_year'])
        client['hours_this_month'] = data['hours_this_month']
        client['hours_last_month'] = data['hours_last_month']
        client['total_backup_bytes'] = data['backup_info']['total_backup_bytes']
        client['total_bill'] = data['receipt_data']['total']
        clients_data.append(client)

    # Perform sorting in Python after all data is calculated
    # Define a mapping from the URL sort_by parameter to the actual key in our client dictionary
    sort_map = {
        'name': 'name',
        'billing_plan': 'billing_plan',
        'workstations': 'workstations',
        'servers': 'servers',
        'vms': 'vms',
        'regular_users': 'regular_users',
        'backup': 'total_backup_bytes',
        'hours': 'total_hours',
        'hours_this_month': 'hours_this_month',
        'hours_last_month': 'hours_last_month',
        'bill': 'total_bill'
    }
    sort_key = sort_map.get(sort_by, 'name')

    # Sort the list of dictionaries
    clients_data.sort(key=lambda x: (x.get(sort_key) is None, x.get(sort_key, 0)), reverse=(sort_order == 'desc'))

    return clients_data

def get_client_breakdown_data(account_number, year, month):
    """Wrapper function to get the billing data for the breakdown template."""
    return get_billing_data_for_client(account_number, year, month)
