from collections import defaultdict
from datetime import datetime, timezone
from database import query_db

def get_billing_dashboard_data(sort_by='name', sort_order='asc'):
    """Calculates and returns the data for the main billing dashboard."""
    clients_raw = query_db("SELECT * FROM companies")
    assets_raw = query_db("SELECT company_account_number, billing_type, backup_data_bytes FROM assets")
    users_raw = query_db("SELECT company_account_number, billing_type, COUNT(*) as user_count FROM users WHERE status = 'Active' GROUP BY company_account_number, billing_type")
    tickets_raw = query_db("SELECT company_account_number, SUM(total_hours_spent) as total_hours FROM ticket_details GROUP BY company_account_number")
    plans_raw = query_db("SELECT * FROM billing_plans")
    overrides_raw = query_db("SELECT * FROM client_billing_overrides")

    plans = {(p['billing_plan'], p['term_length']): dict(p) for p in plans_raw}
    overrides = {o['company_account_number']: dict(o) for o in overrides_raw}

    users_by_client = defaultdict(lambda: {'Regular': 0})
    for u in users_raw:
        users_by_client[u['company_account_number']][u['billing_type']] = u['user_count']

    hours_by_client = {t['company_account_number']: t['total_hours'] for t in tickets_raw}

    assets_by_client = defaultdict(lambda: {'Workstation': 0, 'Server': 0, 'VM': 0, 'backup_bytes': 0})
    for asset in assets_raw:
        acc_num = asset['company_account_number']
        billing_type = asset['billing_type']
        if billing_type in assets_by_client[acc_num]:
            assets_by_client[acc_num][billing_type] += 1
        if asset['backup_data_bytes']:
            assets_by_client[acc_num]['backup_bytes'] += asset['backup_data_bytes']

    clients_data = []
    rate_key_map = {
        'network_management_fee': 'nmf', 'per_user_cost': 'puc',
        'per_workstation_cost': 'pwc', 'per_host_cost': 'phc', 'per_vm_cost': 'pvc',
        'per_switch_cost': 'psc', 'per_firewall_cost': 'pfc', 'per_hour_ticket_cost': 'phtc',
        'backup_base_fee_workstation': 'bbfw', 'backup_base_fee_server': 'bbfs',
        'backup_included_tb': 'bit', 'backup_per_tb_fee': 'bpt'
    }

    for client_row in clients_raw:
        client = dict(client_row)
        acc_num = client['account_number']
        client_assets_counts = assets_by_client.get(acc_num, {})
        client_overrides = overrides.get(acc_num, {})
        default_plan = plans.get((client['billing_plan'], client['contract_term_length']), {})
        client_user_counts = users_by_client.get(acc_num, {})

        quantities = {
            'regular_users': client_overrides.get('override_regular_user_count') if client_overrides.get('override_regular_user_count_enabled') else client_user_counts.get('Regular', 0),
            'workstations': client_overrides.get('override_workstation_count') if client_overrides.get('override_workstation_count_enabled') else client_assets_counts.get('Workstation', 0),
            'servers': client_overrides.get('override_host_count') if client_overrides.get('override_host_count_enabled') else client_assets_counts.get('Server', 0),
            'vms': client_overrides.get('override_vm_count') if client_overrides.get('override_vm_count_enabled') else client_assets_counts.get('VM', 0),
            'switches': client_overrides.get('override_switch_count') if client_overrides.get('override_switch_count_enabled') else 0,
            'firewalls': client_overrides.get('override_firewall_count') if client_overrides.get('override_firewall_count_enabled') else 0,
        }
        client.update(quantities)
        client['total_hours'] = hours_by_client.get(acc_num, 0)
        client['total_backup_bytes'] = client_assets_counts.get('backup_bytes', 0)

        rates = {}
        for rate_key, short_key in rate_key_map.items():
            override_key_enabled = f'override_{short_key}_enabled'
            if client_overrides.get(override_key_enabled):
                rates[rate_key] = client_overrides.get(rate_key)
            else:
                rates[rate_key] = default_plan.get(rate_key)

        total_bill = rates.get('network_management_fee', 0) or 0
        total_bill += quantities['regular_users'] * (rates.get('per_user_cost', 0) or 0)
        total_bill += quantities['workstations'] * (rates.get('per_workstation_cost', 0) or 0)
        total_bill += quantities['servers'] * (rates.get('per_host_cost', 0) or 0)
        total_bill += quantities['vms'] * (rates.get('per_vm_cost', 0) or 0)
        total_bill += quantities['switches'] * (rates.get('per_switch_cost', 0) or 0)
        total_bill += quantities['firewalls'] * (rates.get('per_firewall_cost', 0) or 0)

        total_backup_tb = client['total_backup_bytes'] / 1099511627776.0 if client['total_backup_bytes'] else 0
        backed_up_assets = query_db("SELECT billing_type FROM assets WHERE company_account_number = ? AND backup_data_bytes > 0", [acc_num])
        backed_up_workstations = sum(1 for a in backed_up_assets if a['billing_type'] == 'Workstation')
        backed_up_servers = len(backed_up_assets) - backed_up_workstations

        total_included_tb = (backed_up_workstations + backed_up_servers) * (rates.get('backup_included_tb', 1) or 1)
        overage_tb = max(0, total_backup_tb - total_included_tb)
        total_bill += backed_up_workstations * (rates.get('backup_base_fee_workstation', 25) or 25)
        total_bill += backed_up_servers * (rates.get('backup_base_fee_server', 50) or 50)
        total_bill += overage_tb * (rates.get('backup_per_tb_fee', 15) or 15)

        prepaid_hours_monthly = client_overrides.get('prepaid_hours_monthly', 0) if client_overrides.get('override_prepaid_hours_monthly_enabled') else 0
        prepaid_hours_yearly = client_overrides.get('prepaid_hours_yearly', 0) if client_overrides.get('override_prepaid_hours_yearly_enabled') else 0
        billable_hours = max(0, (client['total_hours'] or 0) - (prepaid_hours_monthly or 0) - (prepaid_hours_yearly or 0))
        total_bill += billable_hours * (rates.get('per_hour_ticket_cost', 0) or 0)

        # --- THIS IS THE FIX ---
        client['total_bill'] = total_bill
        # -----------------------

        clients_data.append(client)

    sort_map = {
        'name': 'name', 'billing_plan': 'billing_plan', 'workstations': 'workstations',
        'servers': 'servers', 'vms': 'vms', 'regular_users': 'regular_users',
        'backup': 'total_backup_bytes', 'hours': 'total_hours', 'bill': 'total_bill'
    }
    sort_column = sort_map.get(sort_by, 'name')
    clients_data.sort(key=lambda x: (x.get(sort_column, 0) is None, x.get(sort_column, 0)), reverse=(sort_order == 'desc'))

    return clients_data

def get_client_breakdown_data(account_number):
    """Calculates and returns the data for the client breakdown page."""
    client_info_row = query_db("SELECT * FROM companies WHERE account_number = ?", [account_number], one=True)
    if not client_info_row:
        return {'client': None}

    client_info = dict(client_info_row)
    assets = [dict(row) for row in query_db("SELECT *, (backup_data_bytes / 1099511627776.0) as backup_data_tb FROM assets WHERE company_account_number = ? ORDER BY hostname", [account_number])]
    users = [dict(row) for row in query_db("SELECT * FROM users WHERE company_account_number = ? AND status = 'Active' ORDER BY full_name", [account_number])]
    recent_tickets = [dict(row) for row in query_db("SELECT * FROM ticket_details WHERE company_account_number = ? ORDER BY last_updated_at DESC", [account_number])]
    plan_details_row = query_db("SELECT * FROM billing_plans WHERE billing_plan = ? AND term_length = ?", [client_info['billing_plan'], client_info['contract_term_length']], one=True)
    plan_details = dict(plan_details_row) if plan_details_row else {}
    overrides_row = query_db("SELECT * FROM client_billing_overrides WHERE company_account_number = ?", [account_number], one=True)
    overrides = dict(overrides_row) if overrides_row else {}

    detected_workstations = sum(1 for a in assets if a['billing_type'] == 'Workstation')
    detected_servers = sum(1 for a in assets if a['billing_type'] == 'Server')
    detected_vms = sum(1 for a in assets if a['billing_type'] == 'VM')
    detected_regular_users = sum(1 for u in users if u['billing_type'] == 'Regular')

    quantities = {
        'regular_users': overrides.get('override_regular_user_count') if overrides.get('override_regular_user_count_enabled') else detected_regular_users,
        'workstations': overrides.get('override_workstation_count') if overrides.get('override_workstation_count_enabled') else detected_workstations,
        'servers': overrides.get('override_host_count') if overrides.get('override_host_count_enabled') else detected_servers,
        'vms': overrides.get('override_vm_count') if overrides.get('override_vm_count_enabled') else detected_vms,
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

    receipt = {
        'nmf': rates.get('network_management_fee', 0) or 0,
        'regular_user_charge': quantities['regular_users'] * (rates.get('per_user_cost', 0) or 0),
        'workstation_charge': quantities['workstations'] * (rates.get('per_workstation_cost', 0) or 0),
        'server_charge': quantities['servers'] * (rates.get('per_host_cost', 0) or 0),
        'vm_charge': quantities['vms'] * (rates.get('per_vm_cost', 0) or 0),
        'switch_charge': quantities['switches'] * (rates.get('per_switch_cost', 0) or 0),
        'firewall_charge': quantities['firewalls'] * (rates.get('per_firewall_cost', 0) or 0),
    }

    backed_up_workstations = sum(1 for a in assets if a['backup_data_bytes'] and a['billing_type'] == 'Workstation')
    backed_up_servers = sum(1 for a in assets if a['backup_data_bytes'] and a['billing_type'] in ('Server', 'VM'))
    total_backup_bytes = sum(a['backup_data_bytes'] for a in assets if a['backup_data_bytes'])
    total_backup_tb = total_backup_bytes / 1099511627776.0 if total_backup_bytes else 0

    receipt['backup_base_workstation'] = backed_up_workstations * (rates.get('backup_base_fee_workstation', 25) or 25)
    receipt['backup_base_server'] = backed_up_servers * (rates.get('backup_base_fee_server', 50) or 50)
    receipt['total_included_tb'] = (backed_up_workstations + backed_up_servers) * (rates.get('backup_included_tb', 1) or 1)
    receipt['overage_tb'] = max(0, total_backup_tb - receipt['total_included_tb'])
    receipt['overage_charge'] = receipt['overage_tb'] * (rates.get('backup_per_tb_fee', 15) or 15)
    receipt['backup_charge'] = receipt['backup_base_workstation'] + receipt['backup_base_server'] + receipt['overage_charge']

    total_hours_this_year = sum(t['total_hours_spent'] for t in recent_tickets if t['total_hours_spent'])
    prepaid_hours_monthly = overrides.get('prepaid_hours_monthly', 0) if overrides.get('override_prepaid_hours_monthly_enabled') else 0
    prepaid_hours_yearly = overrides.get('prepaid_hours_yearly', 0) if overrides.get('override_prepaid_hours_yearly_enabled') else 0
    billable_hours = max(0, total_hours_this_year - (prepaid_hours_monthly or 0) - (prepaid_hours_yearly or 0))

    receipt['prepaid_hours_monthly'] = prepaid_hours_monthly or 0
    receipt['prepaid_hours_yearly'] = prepaid_hours_yearly or 0
    receipt['billable_hours'] = billable_hours
    receipt['ticket_charge'] = billable_hours * (rates.get('per_hour_ticket_cost', 0) or 0)

    # Calculate total by summing all the individual charge components
    receipt['total'] = (
        receipt['nmf'] + receipt['regular_user_charge'] + receipt['workstation_charge'] +
        receipt['server_charge'] + receipt['vm_charge'] + receipt['switch_charge'] +
        receipt['firewall_charge'] + receipt['backup_charge'] + receipt['ticket_charge']
    )


    today = datetime.now(timezone.utc)
    current_year_str = today.strftime('%Y')

    return {
        'client': client_info,
        'assets': assets,
        'users': users,
        'recent_tickets': recent_tickets,
        'receipt_data': receipt,
        'effective_rates': rates,
        'quantities': quantities,
        'backed_up_workstations': backed_up_workstations,
        'backed_up_servers': backed_up_servers,
        'total_backup_tb': total_backup_tb,
        'total_hours_this_year': total_hours_this_year,
        'current_year_str': current_year_str
    }
