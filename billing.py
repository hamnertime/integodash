# hamnertime/integodash/integodash-fda17dde7f19ded546de5dbffc8ee99ff55ec5f3/billing.py
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from database import query_db
import calendar
import sys
import re

def get_billing_data_for_client(account_number, year, month):
    """
    A comprehensive function to fetch all data and calculate billing details for a specific client and period.
    This is the core logic that powers both the dashboard and the breakdown view.
    """
    client_info_raw = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
    if not client_info_raw:
        return None

    client_info = dict(client_info_raw) # Make it a mutable dictionary

    # --- THIS IS THE FIX ---
    # Default contract term to 'Month to Month' if it's not set
    if not client_info.get('contract_term_length'):
        client_info['contract_term_length'] = 'Month to Month'
    # --- END OF FIX ---

    # Sanitize date formats before doing anything else
    for date_field in ['client_start_date', 'contract_start_date']:
        if client_info.get(date_field):
            try:
                date_str_only = client_info[date_field].split('T')[0]
                datetime.fromisoformat(date_str_only) # Validate it's a date
                client_info[date_field] = date_str_only
            except (ValueError, TypeError, IndexError):
                pass # Keep original value if it's not a valid date string

    # --- 1. Fetch all raw data from the database ---
    locations = [dict(r) for r in query_db("SELECT * FROM client_locations WHERE company_account_number = ? ORDER BY location_name", [account_number])]
    assets = [dict(r) for r in query_db("""
        SELECT a.*, GROUP_CONCAT(c.first_name || ' ' || c.last_name, ', ') as associated_contacts
        FROM assets a
        LEFT JOIN asset_contact_links acl ON a.id = acl.asset_id
        LEFT JOIN contacts c ON acl.contact_id = c.id
        WHERE a.company_account_number = ?
        GROUP BY a.id
        ORDER BY a.hostname
    """, [account_number])]
    manual_assets = [dict(r) for r in query_db("SELECT * FROM manual_assets WHERE company_account_number = ? ORDER BY hostname", [account_number])]
    users = [dict(r) for r in query_db("""
        SELECT u.*, c.id as contact_id, '[' || GROUP_CONCAT(json_object('hostname', a.hostname, 'portal_url', a.portal_url)) || ']' as associated_assets
        FROM users u
        LEFT JOIN contacts c ON u.email = c.email
        LEFT JOIN asset_contact_links acl ON c.id = acl.contact_id
        LEFT JOIN assets a ON acl.asset_id = a.id
        WHERE u.company_account_number = ? AND u.status = 'Active'
        GROUP BY u.id
        ORDER BY u.full_name
    """, [account_number])]
    manual_users = [dict(r) for r in query_db("SELECT * FROM manual_users WHERE company_account_number = ? ORDER BY full_name", [account_number])]
    custom_line_items = [dict(r) for r in query_db("SELECT * FROM custom_line_items WHERE company_account_number = ? ORDER BY name", [account_number])]

    asset_overrides = {r['asset_id']: dict(r) for r in query_db("SELECT * FROM asset_billing_overrides ao JOIN assets a ON a.id = ao.asset_id WHERE a.company_account_number = ?", [account_number])}
    user_overrides = {r['user_id']: dict(r) for r in query_db("SELECT * FROM user_billing_overrides uo JOIN users u ON u.id = uo.user_id WHERE u.company_account_number = ?", [account_number])}

    rate_overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)
    rate_overrides = dict(rate_overrides_row) if rate_overrides_row else {}

    # Determine the effective billing plan
    billing_plan_name = (client_info.get('billing_plan') or '').strip()
    if rate_overrides and rate_overrides.get('override_billing_plan_enabled') and rate_overrides.get('billing_plan'):
        billing_plan_name = rate_overrides['billing_plan']

    client_info['billing_plan'] = billing_plan_name

    contract_term = (client_info.get('contract_term_length') or '').strip()
    plan_details = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [billing_plan_name, contract_term], one=True)

    # Fetch tickets for the entire year to calculate yearly totals and monthly breakdowns accurately
    current_year = datetime.now().year
    all_tickets_this_year = [dict(r) for r in query_db("SELECT * FROM ticket_details WHERE company_account_number = ? AND strftime('%Y', last_updated_at) = ?", [account_number, str(current_year)] )]

    if not plan_details:
        return None

    # --- 2. Determine the Effective Billing Rates ---
    effective_rates = dict(plan_details) if plan_details else {}
    if rate_overrides:
        rate_key_map = {'puc': 'per_user_cost', 'psc': 'per_server_cost', 'pwc': 'per_workstation_cost', 'pvc': 'per_vm_cost', 'pswitchc': 'per_switch_cost', 'pfirewallc': 'per_firewall_cost', 'phtc': 'per_hour_ticket_cost', 'bbfw': 'backup_base_fee_workstation', 'bbfs': 'backup_base_fee_server', 'bit': 'backup_included_tb', 'bpt': 'backup_per_tb_fee'}

        if rate_overrides.get('override_support_level_enabled'):
            effective_rates['support_level'] = rate_overrides['support_level']

        for short_key, rate_key in rate_key_map.items():
            if f'override_{short_key}_enabled' in rate_overrides and rate_overrides[f'override_{short_key}_enabled']:
                effective_rates[rate_key] = rate_overrides[rate_key]

        feature_types_raw = query_db("SELECT DISTINCT feature_type FROM feature_options")
        feature_types = [row['feature_type'] for row in feature_types_raw]
        for feature_type in feature_types:
            short_key = feature_type.lower().replace(' ', '_')
            feature_key = f'feature_{short_key}'
            override_enabled_key = f'override_feature_{short_key}_enabled'
            if override_enabled_key in rate_overrides and rate_overrides[override_enabled_key]:
                effective_rates[feature_key] = rate_overrides[feature_key]

    support_level_display = effective_rates.get('support_level', 'Billed Hourly')

    # --- 2a. Calculate Contract End Date ---
    contract_end_date = "N/A"
    contract_expired = False
    if client_info['contract_start_date'] and client_info['contract_term_length']:
        try:
            start_date = datetime.fromisoformat(client_info['contract_start_date'])

            term = client_info['contract_term_length']
            years_to_add = 0
            if term == '1-Year':
                years_to_add = 1
            elif term == '2-Year':
                years_to_add = 2
            elif term == '3-Year':
                years_to_add = 3

            if years_to_add > 0:
                end_date = start_date.replace(year=start_date.year + years_to_add) - timedelta(days=1)
                contract_end_date = end_date.strftime('%Y-%m-%d')
                if datetime.now().date() > end_date.date():
                    contract_expired = True
            elif term == 'Month to Month':
                contract_end_date = "Month to Month"

        except (ValueError, TypeError, IndexError):
            contract_end_date = "Invalid Start Date"

    # --- 2b. Get Datto RMM Portal URL ---
    datto_portal_url = client_info.get('datto_portal_url')


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
            cost = float(override.get('custom_cost') or 0.0) if override else 0.0
        elif billing_type != 'No Charge':
            rate_key = f"per_{billing_type.lower()}_cost"
            cost = float(effective_rates.get(rate_key, 0.0) or 0.0)

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
            cost = float(override.get('custom_cost') or 0.0) if override else 0.0
        elif billing_type == 'Paid':
            cost = float(effective_rates.get('per_user_cost', 0.0) or 0.0)

        total_user_charges += cost
        quantities['regular_users' if billing_type == 'Paid' else 'free_users'] += 1
        billed_users.append({'name': user['full_name'], 'type': billing_type, 'cost': cost})

    # --- 5. Calculate Ticket Charges for the specified billing period (year, month) ---
    _, num_days = calendar.monthrange(year, month)
    start_of_billing_month = datetime(year, month, 1, tzinfo=timezone.utc)
    end_of_billing_month = datetime(year, month, num_days, 23, 59, 59, tzinfo=timezone.utc)

    tickets_for_period = [t for t in all_tickets_this_year if start_of_billing_month <= datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')) <= end_of_billing_month]
    hours_for_period = sum(t['total_hours_spent'] for t in tickets_for_period)

    prepaid_monthly = float((rate_overrides.get('prepaid_hours_monthly') if rate_overrides and rate_overrides.get('override_prepaid_hours_monthly_enabled') else 0) or 0)
    prepaid_yearly = float((rate_overrides.get('prepaid_hours_yearly') if rate_overrides and rate_overrides.get('override_prepaid_hours_yearly_enabled') else 0) or 0)

    hours_used_prior = sum(t['total_hours_spent'] for t in all_tickets_this_year if datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')) < start_of_billing_month)
    remaining_yearly_hours = max(0, prepaid_yearly - hours_used_prior)

    billable_hours = max(0, max(0, hours_for_period - prepaid_monthly) - remaining_yearly_hours)
    ticket_charge = billable_hours * float((effective_rates.get('per_hour_ticket_cost', 0) or 0))

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
    included_tb = (backup_info['backed_up_workstations'] + backup_info['backed_up_servers']) * float((effective_rates.get('backup_included_tb', 1) or 1))
    overage_tb = max(0, total_backup_tb - included_tb)

    backup_base_workstation_charge = backup_info['backed_up_workstations'] * float((effective_rates.get('backup_base_fee_workstation', 0) or 0))
    backup_base_server_charge = backup_info['backed_up_servers'] * float((effective_rates.get('backup_base_fee_server', 0) or 0))
    overage_charge = overage_tb * float((effective_rates.get('backup_per_tb_fee', 0) or 0))
    backup_charge = backup_base_workstation_charge + backup_base_server_charge + overage_charge

    # --- 7. Calculate Custom Line Item Charges ---
    billed_line_items = []
    total_line_item_charges = 0.0
    for item in custom_line_items:
        cost = 0.0
        item_type = None
        fee = 0.0
        if item['monthly_fee'] is not None:
            try:
                fee = float(item['monthly_fee'])
                item_type = 'Recurring'
            except (ValueError, TypeError):
                fee = 0.0
        elif item['one_off_year'] == year and item['one_off_month'] == month:
            try:
                fee = float(item['one_off_fee'])
                item_type = 'One-Off'
            except (ValueError, TypeError):
                fee = 0.0
        elif item['yearly_bill_month'] == month:
            try:
                fee = float(item['yearly_fee'])
                item_type = 'Yearly'
            except (ValueError, TypeError):
                fee = 0.0

        if item_type:
            cost = fee
            total_line_item_charges += cost
            billed_line_items.append({'name': item['name'], 'type': item_type, 'cost': cost})

    # --- 8. Assemble Final Bill and Data Package ---
    total_bill = total_asset_charges + total_user_charges + ticket_charge + backup_charge + total_line_item_charges

    receipt = {
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
        'locations': locations,
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
        'contract_expired': contract_expired,
        'datto_portal_url': datto_portal_url,
    }

def get_billing_dashboard_data():
    """
    An optimized function to calculate and return data for the main billing dashboard.
    It fetches data in bulk to reduce database queries.
    """
    now = datetime.now()
    year, month = now.year, now.month
    start_of_year = datetime(year, 1, 1, tzinfo=timezone.utc)
    start_of_billing_month = datetime(year, month, 1, tzinfo=timezone.utc)

    # 1. Bulk Data Fetching
    all_companies = [dict(r) for r in query_db("SELECT * FROM companies")]
    all_assets = [dict(r) for r in query_db("SELECT id, company_account_number, hostname, billing_type, backup_data_bytes, datto_uid FROM assets")]
    all_manual_assets = [dict(r) for r in query_db("SELECT id, company_account_number, hostname, billing_type, custom_cost FROM manual_assets")]
    all_users = [dict(r) for r in query_db("SELECT id, company_account_number, full_name, freshservice_id FROM users WHERE status = 'Active'")]
    all_manual_users = [dict(r) for r in query_db("SELECT id, company_account_number, full_name, billing_type, custom_cost FROM manual_users")]
    all_tickets_this_year = [dict(r) for r in query_db("SELECT company_account_number, last_updated_at, total_hours_spent FROM ticket_details WHERE strftime('%Y', last_updated_at) = ?", [str(year)])]
    all_line_items = [dict(r) for r in query_db("SELECT * FROM custom_line_items")]
    all_asset_overrides = {r['asset_id']: dict(r) for r in query_db("SELECT * FROM asset_billing_overrides")}
    all_user_overrides = {r['user_id']: dict(r) for r in query_db("SELECT * FROM user_billing_overrides")}
    all_rate_overrides = {r['company_account_number']: dict(r) for r in query_db("SELECT * FROM client_billing_overrides")}
    all_plans_raw = query_db("SELECT * FROM billing_plans")
    plans_map = {(p['billing_plan'], p['term_length']): dict(p) for p in all_plans_raw}

    # 2. Group data by client for fast access
    assets_by_client = defaultdict(list)
    for asset in all_assets + all_manual_assets:
        assets_by_client[asset['company_account_number']].append(asset)
    users_by_client = defaultdict(list)
    for user in all_users + all_manual_users:
        users_by_client[user['company_account_number']].append(user)
    tickets_by_client = defaultdict(list)
    for ticket in all_tickets_this_year:
        tickets_by_client[ticket['company_account_number']].append(ticket)
    line_items_by_client = defaultdict(list)
    for item in all_line_items:
        line_items_by_client[item['company_account_number']].append(item)

    clients_data = []

    # 3. Loop and Calculate for each client
    for client_info in all_companies:
        account_number = client_info['account_number']
        client_assets = assets_by_client.get(account_number, [])
        client_users = users_by_client.get(account_number, [])
        client_tickets_this_year = tickets_by_client.get(account_number, [])
        client_line_items = line_items_by_client.get(account_number, [])
        rate_overrides = all_rate_overrides.get(account_number, {})

        if not client_info.get('contract_term_length'):
            client_info['contract_term_length'] = 'Month to Month'

        billing_plan_name = (client_info.get('billing_plan') or '').strip()
        if rate_overrides.get('override_billing_plan_enabled') and rate_overrides.get('billing_plan'):
            billing_plan_name = rate_overrides['billing_plan']
        client_info['billing_plan'] = billing_plan_name

        contract_term = client_info['contract_term_length'].strip()
        plan_details = plans_map.get((billing_plan_name, contract_term))

        if not plan_details:
            client_info.update({'workstations': 0, 'servers': 0, 'vms': 0, 'regular_users': 0, 'total_hours': 0, 'total_backup_bytes': 0, 'total_bill': 0.0, 'support_level': client_info.get('support_level', 'N/A')})
            clients_data.append(client_info)
            continue

        effective_rates = dict(plan_details) # Start with base plan
        # Apply global rate overrides
        if rate_overrides:
             rate_key_map = {'puc': 'per_user_cost', 'psc': 'per_server_cost', 'pwc': 'per_workstation_cost', 'pvc': 'per_vm_cost', 'pswitchc': 'per_switch_cost', 'pfirewallc': 'per_firewall_cost', 'phtc': 'per_hour_ticket_cost', 'bbfw': 'backup_base_fee_workstation', 'bbfs': 'backup_base_fee_server', 'bit': 'backup_included_tb', 'bpt': 'backup_per_tb_fee'}
             for short_key, rate_key in rate_key_map.items():
                if f'override_{short_key}_enabled' in rate_overrides and rate_overrides[f'override_{short_key}_enabled']:
                    effective_rates[rate_key] = rate_overrides[rate_key]

        # Calculate Asset Charges and Quantities
        quantities = defaultdict(int)
        total_asset_charges = 0.0
        backup_info = {'total_backup_bytes': 0, 'backed_up_workstations': 0, 'backed_up_servers': 0}
        for asset in client_assets:
            is_manual = 'datto_uid' not in asset
            override = all_asset_overrides.get(asset.get('id')) if not is_manual else asset
            billing_type = (override.get('billing_type') if override else None) or asset.get('billing_type', 'Workstation')
            cost = 0.0
            if billing_type == 'Custom':
                cost = float(override.get('custom_cost') or 0.0) if override else 0.0
            elif billing_type != 'No Charge':
                rate_key = f"per_{billing_type.lower()}_cost"
                cost = float(effective_rates.get(rate_key, 0.0) or 0.0)
            total_asset_charges += cost
            quantities[billing_type.lower()] += 1
            if not is_manual and asset.get('backup_data_bytes'):
                backup_info['total_backup_bytes'] += asset.get('backup_data_bytes', 0)
                if asset.get('billing_type') == 'Workstation':
                    backup_info['backed_up_workstations'] += 1
                elif asset.get('billing_type') in ('Server', 'VM'):
                    backup_info['backed_up_servers'] += 1

        # Calculate User Charges
        total_user_charges = 0.0
        for user in client_users:
            is_manual = 'freshservice_id' not in user
            override = all_user_overrides.get(user.get('id')) if not is_manual else user
            billing_type = (override.get('billing_type') if override else None) or 'Paid'
            cost = 0.0
            if billing_type == 'Custom':
                cost = float(override.get('custom_cost') or 0.0) if override else 0.0
            elif billing_type == 'Paid':
                cost = float(effective_rates.get('per_user_cost', 0.0) or 0.0)
            total_user_charges += cost
            quantities['regular_users' if billing_type == 'Paid' else 'free_users'] += 1

        # Calculate Ticket Charges
        hours_for_period = sum(t['total_hours_spent'] for t in client_tickets_this_year if datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')).month == month)
        prepaid_monthly = float((rate_overrides.get('prepaid_hours_monthly') if rate_overrides.get('override_prepaid_hours_monthly_enabled') else 0) or 0)
        billable_hours = max(0, hours_for_period - prepaid_monthly) # Simplified for dashboard
        ticket_charge = billable_hours * float((effective_rates.get('per_hour_ticket_cost', 0) or 0))

        # Calculate Backup Charges
        total_backup_tb = backup_info['total_backup_bytes'] / 1099511627776.0
        included_tb = (backup_info['backed_up_workstations'] + backup_info['backed_up_servers']) * float((effective_rates.get('backup_included_tb', 1) or 1))
        overage_tb = max(0, total_backup_tb - included_tb)
        backup_charge = (backup_info['backed_up_workstations'] * float((effective_rates.get('backup_base_fee_workstation', 0) or 0))) + \
                        (backup_info['backed_up_servers'] * float((effective_rates.get('backup_base_fee_server', 0) or 0))) + \
                        (overage_tb * float((effective_rates.get('backup_per_tb_fee', 0) or 0)))

        # Calculate Custom Line Item Charges
        total_line_item_charges = 0.0
        for item in client_line_items:
            if item['monthly_fee'] is not None:
                total_line_item_charges += float(item['monthly_fee'])
            elif item['one_off_year'] == year and item['one_off_month'] == month:
                total_line_item_charges += float(item.get('one_off_fee') or 0.0)
            elif item['yearly_bill_month'] == month:
                total_line_item_charges += float(item.get('yearly_fee') or 0.0)

        # Final Bill and Data Assembly
        total_bill = total_asset_charges + total_user_charges + ticket_charge + backup_charge + total_line_item_charges

        client_info.update({
            'workstations': quantities.get('workstation', 0), 'servers': quantities.get('server', 0),
            'vms': quantities.get('vm', 0), 'regular_users': quantities.get('regular_users', 0),
            'total_hours': sum(t['total_hours_spent'] for t in client_tickets_this_year),
            'total_backup_bytes': backup_info['total_backup_bytes'], 'total_bill': total_bill,
            'support_level': effective_rates.get('support_level', 'Billed Hourly'),
        })

        # Contract End Date
        contract_end_date = "N/A"
        contract_expired = False
        if client_info.get('contract_start_date') and client_info.get('contract_term_length'):
            try:
                start_date_str = str(client_info['contract_start_date']).split('T')[0]
                start_date = datetime.fromisoformat(start_date_str)
                term = client_info['contract_term_length']
                years_to_add = {'1-Year': 1, '2-Year': 2, '3-Year': 3}.get(term, 0)
                if years_to_add > 0:
                    end_date = start_date.replace(year=start_date.year + years_to_add) - timedelta(days=1)
                    contract_end_date = end_date.strftime('%Y-%m-%d')
                    if datetime.now().date() > end_date.date():
                        contract_expired = True
                elif term == 'Month to Month':
                    contract_end_date = "Month to Month"
            except (ValueError, TypeError):
                contract_end_date = "Invalid Start Date"
        client_info['contract_end_date'] = contract_end_date
        client_info['contract_expired'] = contract_expired

        clients_data.append(client_info)

    return clients_data


def get_client_breakdown_data(account_number, year, month):
    """Wrapper function to get the billing data for the breakdown template."""
    return get_billing_data_for_client(account_number, year, month)
