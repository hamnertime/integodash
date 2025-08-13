from collections import defaultdict
from datetime import datetime, timezone, timedelta
from database import query_db
import calendar

def _calculate_bill(rates, quantities, hours_for_period, backup_info, overrides, remaining_yearly_hours):
    """A centralized function to calculate the total bill for a specific period."""
    q = {k: v or 0 for k, v in quantities.items()}

    total_bill = rates.get('network_management_fee', 0) or 0
    total_bill += q['regular_users'] * (rates.get('per_user_cost', 0) or 0)
    total_bill += q['workstations'] * (rates.get('per_workstation_cost', 0) or 0)
    total_bill += q['servers'] * (rates.get('per_host_cost', 0) or 0)
    total_bill += q['vms'] * (rates.get('per_vm_cost', 0) or 0)
    total_bill += q['switches'] * (rates.get('per_switch_cost', 0) or 0)
    total_bill += q['firewalls'] * (rates.get('per_firewall_cost', 0) or 0)

    # Backup Calculation
    total_backup_tb = backup_info['total_backup_bytes'] / 1099511627776.0 if backup_info['total_backup_bytes'] else 0
    total_included_tb = (backup_info['backed_up_workstations'] + backup_info['backed_up_servers']) * (rates.get('backup_included_tb', 1) or 1)
    overage_tb = max(0, total_backup_tb - total_included_tb)
    total_bill += backup_info['backed_up_workstations'] * (rates.get('backup_base_fee_workstation', 25) or 25)
    total_bill += backup_info['backed_up_servers'] * (rates.get('backup_base_fee_server', 50) or 50)
    total_bill += overage_tb * (rates.get('backup_per_tb_fee', 15) or 15)

    # Hours Calculation
    prepaid_hours_monthly = overrides.get('prepaid_hours_monthly', 0) or 0

    hours_after_monthly = max(0, (hours_for_period or 0) - prepaid_hours_monthly)
    billable_hours = max(0, hours_after_monthly - remaining_yearly_hours)

    total_bill += billable_hours * (rates.get('per_hour_ticket_cost', 0) or 0)

    return total_bill

def get_billing_dashboard_data(sort_by='name', sort_order='asc'):
    """Calculates and returns the data for the main billing dashboard (annual view)."""
    clients_raw = query_db("SELECT * FROM companies")
    assets_raw = query_db("SELECT company_account_number, billing_type, backup_data_bytes FROM assets")
    users_raw = query_db("SELECT company_account_number, billing_type, COUNT(*) as user_count FROM users WHERE status = 'Active' GROUP BY company_account_number, billing_type")
    tickets_raw = query_db("SELECT company_account_number, SUM(total_hours_spent) as total_hours FROM ticket_details GROUP BY company_account_number")
    plans_raw = query_db("SELECT * FROM billing_plans")
    overrides_raw = query_db("SELECT * FROM client_billing_overrides")

    plans = {(p['billing_plan'], p['term_length']): dict(p) for p in plans_raw}
    overrides = {o['company_account_number']: dict(o) for o in overrides_raw}
    hours_by_client = {t['company_account_number']: t['total_hours'] for t in tickets_raw}

    clients_data = []
    for client_row in clients_raw:
        client = dict(client_row)
        acc_num = client['account_number']

        assets_for_client = [a for a in assets_raw if a['company_account_number'] == acc_num]
        users_for_client = [u for u in users_raw if u['company_account_number'] == acc_num]
        client_overrides = overrides.get(acc_num, {})
        default_plan = plans.get((client['billing_plan'], client['contract_term_length']), {})

        quantities = {
            'regular_users': client_overrides.get('override_regular_user_count') if client_overrides.get('override_regular_user_count_enabled') else sum(u['user_count'] for u in users_for_client if u['billing_type'] == 'Regular'),
            'workstations': client_overrides.get('override_workstation_count') if client_overrides.get('override_workstation_count_enabled') else sum(1 for a in assets_for_client if a['billing_type'] == 'Workstation'),
            'servers': client_overrides.get('override_host_count') if client_overrides.get('override_host_count_enabled') else sum(1 for a in assets_for_client if a['billing_type'] == 'Server'),
            'vms': client_overrides.get('override_vm_count') if client_overrides.get('override_vm_count_enabled') else sum(1 for a in assets_for_client if a['billing_type'] == 'VM'),
            'switches': client_overrides.get('override_switch_count') if client_overrides.get('override_switch_count_enabled') else 0,
            'firewalls': client_overrides.get('override_firewall_count') if client_overrides.get('override_firewall_count_enabled') else 0,
        }

        rates = {}
        rate_key_map = {
            'network_management_fee': 'nmf', 'per_user_cost': 'puc',
            'per_workstation_cost': 'pwc', 'per_host_cost': 'phc', 'per_vm_cost': 'pvc',
            'per_switch_cost': 'psc', 'per_firewall_cost': 'pfc', 'per_hour_ticket_cost': 'phtc',
            'backup_base_fee_workstation': 'bbfw', 'backup_base_fee_server': 'bbfs',
            'backup_included_tb': 'bit', 'backup_per_tb_fee': 'bpt'
        }
        for rate_key, short_key in rate_key_map.items():
            override_key_enabled = f'override_{short_key}_enabled'
            if client_overrides.get(override_key_enabled):
                rates[rate_key] = client_overrides.get(rate_key)
            else:
                rates[rate_key] = default_plan.get(rate_key)

        backup_info = {
            'total_backup_bytes': sum(a['backup_data_bytes'] for a in assets_for_client if a['backup_data_bytes']),
            'backed_up_workstations': sum(1 for a in assets_for_client if a['billing_type'] == 'Workstation' and a['backup_data_bytes']),
            'backed_up_servers': sum(1 for a in assets_for_client if a['billing_type'] in ('Server', 'VM') and a['backup_data_bytes']),
        }

        total_hours = hours_by_client.get(acc_num, 0)
        total_yearly_prepaid = client_overrides.get('prepaid_hours_yearly', 0) if client_overrides.get('override_prepaid_hours_yearly_enabled') else 0
        total_bill = _calculate_bill(rates, quantities, total_hours, backup_info, client_overrides, total_yearly_prepaid)

        client.update(quantities)
        client['total_hours'] = total_hours
        client['total_backup_bytes'] = backup_info['total_backup_bytes']
        client['total_bill'] = total_bill
        clients_data.append(client)

    sort_map = {
        'name': 'name', 'billing_plan': 'billing_plan', 'workstations': 'workstations',
        'servers': 'servers', 'vms': 'vms', 'regular_users': 'regular_users',
        'backup': 'total_backup_bytes', 'hours': 'total_hours', 'bill': 'total_bill'
    }
    sort_column = sort_map.get(sort_by, 'name')
    clients_data.sort(key=lambda x: (x.get(sort_column, 0) is None, x.get(sort_column, 0)), reverse=(sort_order == 'desc'))

    return clients_data

def get_client_breakdown_data(account_number, year, month):
    client_info_row = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
    if not client_info_row:
        return {'client': None}

    client_info = dict(client_info_row)

    assets_raw = query_db("SELECT * FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])
    assets = []
    for row in assets_raw:
        asset = dict(row)
        backup_bytes = asset.get('backup_data_bytes') or 0
        asset['backup_data_tb'] = backup_bytes / 1099511627776.0
        assets.append(asset)

    users = [dict(row) for row in query_db("SELECT * FROM users WHERE company_account_number = ? AND status = 'Active' ORDER BY full_name", [account_number])]
    all_tickets_this_year = [dict(row) for row in query_db("SELECT * FROM ticket_details WHERE company_account_number = ? and strftime('%Y', last_updated_at) = ?", [account_number, str(year)])]

    plan_details_row = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
    plan_details = dict(plan_details_row) if plan_details_row else {}
    overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)
    overrides = dict(overrides_row) if overrides_row else {}

    today = datetime.now(timezone.utc)

    first_day_of_current_month = today.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_day_of_last_month = first_day_of_current_month - timedelta(days=1)
    first_day_of_last_month = last_day_of_last_month.replace(day=1)

    tickets_this_month = [
        t for t in all_tickets_this_year
        if t['last_updated_at'] and datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')).month == today.month
    ]

    tickets_last_month = [
        t for t in all_tickets_this_year
        if t['last_updated_at'] and datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')).month == last_day_of_last_month.month
    ]

    _, num_days = calendar.monthrange(year, month)
    start_of_billing_month = datetime(year, month, 1, tzinfo=timezone.utc)
    end_of_billing_month = datetime(year, month, num_days, 23, 59, 59, tzinfo=timezone.utc)

    tickets_for_billing_period = [
        t for t in all_tickets_this_year
        if t['last_updated_at'] and start_of_billing_month <= datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')) <= end_of_billing_month
    ]
    hours_for_billing_period = sum(t['total_hours_spent'] for t in tickets_for_billing_period if t['total_hours_spent'])

    hours_used_prior_to_this_month = sum(
        t['total_hours_spent'] for t in all_tickets_this_year
        if t['last_updated_at'] and datetime.fromisoformat(t['last_updated_at'].replace('Z', '+00:00')) < start_of_billing_month
    )

    total_yearly_prepaid = overrides.get('prepaid_hours_yearly', 0) if overrides.get('override_prepaid_hours_yearly_enabled') else 0
    remaining_yearly_hours = max(0, total_yearly_prepaid - hours_used_prior_to_this_month)

    quantities = {
        'regular_users': overrides.get('override_regular_user_count') if overrides.get('override_regular_user_count_enabled') else sum(1 for u in users if u['billing_type'] == 'Regular'),
        'workstations': overrides.get('override_workstation_count') if overrides.get('override_workstation_count_enabled') else sum(1 for a in assets if a['billing_type'] == 'Workstation'),
        'servers': overrides.get('override_host_count') if overrides.get('override_host_count_enabled') else sum(1 for a in assets if a['billing_type'] == 'Server'),
        'vms': overrides.get('override_vm_count') if overrides.get('override_vm_count_enabled') else sum(1 for a in assets if a['billing_type'] == 'VM'),
        'switches': overrides.get('override_switch_count') if overrides.get('override_switch_count_enabled') else 0,
        'firewalls': overrides.get('override_firewall_count') if overrides.get('override_firewall_count_enabled') else 0,
    }

    rates = {}
    rate_key_map = {
        'network_management_fee': 'nmf', 'per_user_cost': 'puc',
        'per_workstation_cost': 'pwc', 'per_host_cost': 'phc', 'per_vm_cost': 'pvc',
        'per_switch_cost': 'psc', 'per_firewall_cost': 'pfc', 'per_hour_ticket_cost': 'phtc',
        'backup_base_fee_workstation': 'bbfw', 'backup_base_fee_server': 'bbfs',
        'backup_included_tb': 'bit', 'backup_per_tb_fee': 'bpt'
    }
    if plan_details:
        for rate_key, short_key in rate_key_map.items():
            override_key_enabled = f'override_{short_key}_enabled'
            if overrides.get(override_key_enabled):
                rates[rate_key] = overrides.get(rate_key)
            else:
                rates[rate_key] = plan_details.get(rate_key)

    backup_info = {
        'total_backup_bytes': sum(a['backup_data_bytes'] for a in assets if a['backup_data_bytes']),
        'backed_up_workstations': sum(1 for a in assets if a['billing_type'] == 'Workstation' and a['backup_data_bytes']),
        'backed_up_servers': sum(1 for a in assets if a['billing_type'] in ('Server', 'VM') and a['backup_data_bytes']),
    }

    total_bill = _calculate_bill(rates, quantities, hours_for_billing_period, backup_info, overrides, remaining_yearly_hours)

    prepaid_hours_monthly = overrides.get('prepaid_hours_monthly', 0) if overrides.get('override_prepaid_hours_monthly_enabled') else 0
    hours_after_monthly = max(0, hours_for_billing_period - prepaid_hours_monthly)
    billable_hours = max(0, hours_after_monthly - remaining_yearly_hours)

    # --- THIS IS THE FIX ---
    receipt = {
        'nmf': rates.get('network_management_fee', 0) or 0,
        'regular_user_charge': (quantities.get('regular_users') or 0) * (rates.get('per_user_cost', 0) or 0),
        'workstation_charge': (quantities.get('workstations') or 0) * (rates.get('per_workstation_cost', 0) or 0),
        'server_charge': (quantities.get('servers') or 0) * (rates.get('per_host_cost', 0) or 0),
        'vm_charge': (quantities.get('vms') or 0) * (rates.get('per_vm_cost', 0) or 0),
        'switch_charge': (quantities.get('switches') or 0) * (rates.get('per_switch_cost', 0) or 0),
        'firewall_charge': (quantities.get('firewalls') or 0) * (rates.get('per_firewall_cost', 0) or 0),
        'ticket_charge': billable_hours * (rates.get('per_hour_ticket_cost', 0) or 0),
        'hours_for_billing_period': hours_for_billing_period,
        'prepaid_hours_monthly': prepaid_hours_monthly,
        'prepaid_hours_yearly': total_yearly_prepaid,
        'billable_hours': billable_hours,
        'total': total_bill
    }
    # -----------------------

    total_backup_tb = backup_info['total_backup_bytes'] / 1099511627776.0 if backup_info['total_backup_bytes'] else 0
    receipt['backup_base_workstation'] = backup_info['backed_up_workstations'] * (rates.get('backup_base_fee_workstation', 25) or 25)
    receipt['backup_base_server'] = backup_info['backed_up_servers'] * (rates.get('backup_base_fee_server', 50) or 50)
    receipt['total_included_tb'] = (backup_info['backed_up_workstations'] + backup_info['backed_up_servers']) * (rates.get('backup_included_tb', 1) or 1)
    receipt['overage_tb'] = max(0, total_backup_tb - receipt['total_included_tb'])
    receipt['overage_charge'] = receipt['overage_tb'] * (rates.get('backup_per_tb_fee', 15) or 15)
    receipt['backup_charge'] = receipt['backup_base_workstation'] + receipt['backup_base_server'] + receipt['overage_charge']

    return {
        'client': client_info,
        'assets': assets,
        'users': users,
        'all_tickets_this_year': all_tickets_this_year,
        'tickets_this_month': tickets_this_month,
        'tickets_last_month': tickets_last_month,
        'tickets_for_billing_period': tickets_for_billing_period,
        'receipt_data': receipt,
        'effective_rates': rates,
        'quantities': quantities,
        'backup_info': backup_info,
        'total_backup_tb': total_backup_tb,
        'backed_up_workstations': backup_info['backed_up_workstations'],
        'backed_up_servers': backup_info['backed_up_servers'],
        'prepaid_hours_monthly': prepaid_hours_monthly,
        'total_yearly_prepaid': total_yearly_prepaid,
        'remaining_yearly_hours': remaining_yearly_hours,
        'billable_hours': billable_hours
    }
