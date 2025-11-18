# Activate env: .\jira_env\Scripts\Activate.ps1 
# Navigate to project root: cd .\jira_workload_dashboard 
# Run app: python -m jira_workload.app.dashboard

import os
import sys
from urllib.parse import quote_plus
import pandas as pd


from dotenv import load_dotenv
from dash import Dash, html, dcc, Input, Output, dash_table
from jira_workload.api.jira_api import connect_to_jira, get_users_from_groups, get_user_workload, get_group_members, get_user_issues_raw

load_dotenv()

def normalize_name(name: str) -> str:
    # Title-case words; preserve hyphens; uppercase dotted initials (e.g., J.s. -> J.S.)
    if not isinstance(name, str):
        return ""

    def title_or_initials(token: str) -> str:
        # If token contains dots, uppercase each dotted segment like initials
        if "." in token:
            segs = token.split(".")
            new = []
            for s in segs:
                if s == "":
                    new.append("")
                elif len(s) == 1:
                    new.append(s.upper())
                else:
                    new.append(s.capitalize())
            return ".".join(new)
        # Otherwise normal title-case
        return token.capitalize()

    words = []
    for w in name.split(" "):
        hy = []
        for h in w.split("-"):
            hy.append(title_or_initials(h))
        words.append("-".join(hy))
    return " ".join(words)

app = Dash(__name__)

session = connect_to_jira()

# Get users from specific Jira groups (comma-separated in .env as JIRA_GROUP_NAMES)
GROUP_NAMES = [g.strip() for g in os.getenv("JIRA_GROUP_NAMES", "").split(",") if g.strip()]
APPLY_DOMAIN_FILTER = os.getenv("APPLY_DOMAIN_FILTER", "true").lower() == "true"
EMAIL_DOMAIN = os.getenv("JIRA_EMAIL_DOMAIN", "@apscorp.ca").lower()
JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")

users = get_users_from_groups(session, GROUP_NAMES)
 

if APPLY_DOMAIN_FILTER:
    def keep(u):
        email = str(u.get("emailAddress", "")).strip().lower()
        return (not email) or email.endswith(EMAIL_DOMAIN)
    users = [u for u in users if keep(u)]
# else: keep all users unfiltered


app.layout = html.Div([
    dcc.Tabs(id='tabs', value='tab-user', children=[
        dcc.Tab(label='Employee Workload Dashboard', value='tab-user', children=[
            html.Div([
                html.H2("Employee Workload Dashboard"),
                dcc.Dropdown(
                    id='user-dropdown',
                    options=[{'label': normalize_name(u.get('displayName', '')), 'value': u['accountId']} for u in users],
                    placeholder='Select a user'
                ),
                dcc.DatePickerRange(
                    id='user-date-range',
                    minimum_nights=0,
                    clearable=True
                ),
                dash_table.DataTable(
                    id='workload-table',
                    columns=[
                        {"name": "Project", "id": "Project", "presentation": "markdown"},
                        {"name": "Issues", "id": "Issues", "presentation": "markdown"},
                        {"name": "Workload (hours)", "id": "Workload (hours)"},
                        {"name": "Workload (weeks, days, hours)", "id": "Workload (weeks, days, hours)"},
                    ],
                    data=[],
                    style_as_list_view=True,
                    style_table={"width": "100%"},
                    style_header={"fontWeight": "bold", "textAlign": "center"},
                    style_cell={"textAlign": "center", "padding": "8px"},
                    style_data={"textAlign": "center"},
                    style_data_conditional=[
                        {
                            "if": {"filter_query": '{Project} = "Total"'},
                            "fontWeight": "bold",
                        }
                    ],
                )
            ])
        ]),
        dcc.Tab(label='Group Workload Dashboard', value='tab-group', children=[
            html.Div([
                html.H2("Group Workload Dashboard"),
                dcc.Dropdown(
                    id='group-dropdown',
                    options=[{'label': g, 'value': g} for g in GROUP_NAMES],
                    placeholder='Select a group'
                ),
                dcc.Dropdown(
                    id='grouping-mode',
                    options=[
                        {'label': 'Project', 'value': 'project'},
                        {'label': 'Employee', 'value': 'employee'},
                        {'label': 'Project and Employee', 'value': 'project_employee'},
                    ],
                    value='project'
                ),
                dcc.DatePickerRange(
                    id='date-range',
                    minimum_nights=0,
                    clearable=True
                ),
                dash_table.DataTable(
                    id='group-workload-table',
                    columns=[
                        {"name": "Project", "id": "Project", "presentation": "markdown"},
                        {"name": "Employee", "id": "Employee"},
                        {"name": "Issues", "id": "Issues", "presentation": "markdown"},
                        {"name": "Workload (hours)", "id": "Workload (hours)"},
                        {"name": "Workload (weeks, days, hours)", "id": "Workload (weeks, days, hours)"},
                    ],
                    data=[],
                    style_as_list_view=True,
                    style_table={"width": "100%"},
                    style_header={"fontWeight": "bold", "textAlign": "center"},
                    style_cell={"textAlign": "center", "padding": "8px"},
                    style_data={"textAlign": "center"},
                    style_data_conditional=[
                        {
                            "if": {"filter_query": '{Project} = "Total"'},
                            "fontWeight": "bold",
                        }
                    ],
                )
            ])
        ])
    ])
])

@app.callback(
    Output('workload-table', 'data'),
    [
        Input('user-dropdown', 'value'),
        Input('user-date-range', 'start_date'),
        Input('user-date-range', 'end_date'),
    ]
)
def update_table(account_id, start_date, end_date):
    if not account_id:
        return []
    issues = get_user_issues_raw(session, account_id, start_due=start_date, end_due=end_date)
    rows = []
    for it in issues:
        f = it.get('fields', {})
        proj = (f.get('project') or {}).get('name')
        proj_key = (f.get('project') or {}).get('key')
        secs = f.get('timeoriginalestimate') or 0
        rows.append([proj, proj_key, it.get('key'), secs])
    if not rows:
        df = pd.DataFrame([["No work assigned in the backlog", "", None, 0]], columns=["Project", "Project Key", "Issue", "Time (seconds)"])
    else:
        df = pd.DataFrame(rows, columns=["Project", "Project Key", "Issue", "Time (seconds)"])
    grouped = df.groupby("Project").agg({
        "Issue": "count",
        "Time (seconds)": "sum",
        "Project Key": "first",
    }).reset_index().rename(columns={"Issue": "Issues"})
    grouped["Workload (hours)"] = (grouped["Time (seconds)"] / 3600).round(2)
    def fmt_weeks_days_hours(seconds: float) -> str:
        total_hours = seconds / 3600
        weeks = int(total_hours // 40)
        rem_hours = total_hours - weeks * 40
        days = int(rem_hours // 8)
        hours = int(round(rem_hours - days * 8))
        w = "week" if weeks == 1 else "weeks"
        d = "day" if days == 1 else "days"
        h = "hour" if hours == 1 else "hours"
        return f"{weeks} {w}, {days} {d}, {hours} {h}"
    grouped["Workload (weeks, days, hours)"] = grouped["Time (seconds)"].apply(fmt_weeks_days_hours)
    total_issues = int(grouped["Issues"].sum())
    total_seconds = float(grouped["Time (seconds)"].sum())
    total_hours = round(total_seconds / 3600, 2)
    total_formatted = fmt_weeks_days_hours(total_seconds)
    def make_project_link(row):
        key = str(row.get("Project Key", "")).strip()
        name = str(row.get("Project", "")).strip()
        if JIRA_URL and key and name:
            return f"[{name}]({JIRA_URL}/browse/{key})"
        return name
    def make_issues_link(row):
        key = str(row.get("Project Key", "")).strip()
        issues_count = row.get("Issues", 0)
        if JIRA_URL and key and issues_count:
            jql_parts = [f"project={key}", f"assignee in (\"{account_id}\")", "statusCategory != Done"]
            if start_date:
                jql_parts.append(f"duedate >= \"{start_date}\"")
            if end_date:
                jql_parts.append(f"duedate <= \"{end_date}\"")
            jql = " AND ".join(jql_parts)
            return f"[{int(issues_count)}]({JIRA_URL}/issues/?jql={quote_plus(jql)})"
        return str(int(issues_count)) if issues_count else "0"
    if "Project Key" in grouped.columns:
        grouped["Project"] = grouped.apply(make_project_link, axis=1)
        grouped["Issues"] = grouped.apply(make_issues_link, axis=1)
    keep_cols = ["Project", "Issues", "Workload (hours)", "Workload (weeks, days, hours)"]
    grouped = grouped[[c for c in keep_cols if c in grouped.columns]]
    records = grouped.to_dict("records")
    records.append({
        "Project": "Total",
        "Issues": str(total_issues),
        "Workload (hours)": total_hours,
        "Workload (weeks, days, hours)": total_formatted,
    })
    return records

@app.callback(
    Output('group-workload-table', 'data'),
    [
        Input('group-dropdown', 'value'),
        Input('grouping-mode', 'value'),
        Input('date-range', 'start_date'),
        Input('date-range', 'end_date'),
    ]
)
def update_group_table(group_name, mode, start_date, end_date):
    if not group_name:
        return []
    group_users = get_users_from_groups(session, [group_name])
    if APPLY_DOMAIN_FILTER:
        def keep(u):
            email = str(u.get("emailAddress", "")).strip().lower()
            return (not email) or email.endswith(EMAIL_DOMAIN)
        group_users = [u for u in group_users if keep(u)]

    rows = []
    for u in group_users:
        acc_id = u.get('accountId')
        disp = normalize_name(u.get('displayName', ''))
        issues = get_user_issues_raw(session, acc_id, start_due=start_date, end_due=end_date)
        for it in issues:
            f = it.get('fields', {})
            proj = (f.get('project') or {}).get('name')
            proj_key = (f.get('project') or {}).get('key')
            secs = f.get('timeoriginalestimate') or 0
            rows.append({
                'Project': proj,
                'Project Key': proj_key,
                'Issue': it.get('key'),
                'Time (seconds)': secs,
                'Employee': disp,
                'AccountId': acc_id,
            })

    if not rows:
        df = pd.DataFrame([{
            'Project': 'No work assigned in the backlog',
            'Employee': '',
            'Issue': None,
            'Time (seconds)': 0,
        }])
    else:
        df = pd.DataFrame(rows)

    if mode == 'employee':
        grp_cols = ['Employee']
        agg_dict = {
            'Issue': 'count',
            'Time (seconds)': 'sum',
            'AccountId': 'first',
        }
    elif mode == 'project_employee':
        grp_cols = ['Project', 'Employee']
        agg_dict = {
            'Issue': 'count',
            'Time (seconds)': 'sum',
            'Project Key': 'first',
            'AccountId': 'first',
        }
    else:
        grp_cols = ['Project']
        agg_dict = {
            'Issue': 'count',
            'Time (seconds)': 'sum',
            'Project Key': 'first',
        }

    grouped = df.groupby(grp_cols, dropna=False).agg(agg_dict).reset_index().rename(columns={'Issue': 'Issues'})

    def fmt_weeks_days_hours(seconds: float) -> str:
        total_hours = seconds / 3600 if seconds else 0
        weeks = int(total_hours // 40)
        rem_hours = total_hours - weeks * 40
        days = int(rem_hours // 8)
        hours = int(round(rem_hours - days * 8))
        w = "week" if weeks == 1 else "weeks"
        d = "day" if days == 1 else "days"
        h = "hour" if hours == 1 else "hours"
        return f"{weeks} {w}, {days} {d}, {hours} {h}"

    grouped['Workload (hours)'] = (grouped['Time (seconds)'] / 3600).round(2)
    grouped['Workload (weeks, days, hours)'] = grouped['Time (seconds)'].apply(fmt_weeks_days_hours)

    total_issues = int(grouped['Issues'].sum())
    total_seconds = float(grouped['Time (seconds)'].sum())
    total_hours = round(total_seconds / 3600, 2)
    total_formatted = fmt_weeks_days_hours(total_seconds)

    for col in ['Project', 'Employee']:
        if col not in grouped.columns:
            grouped[col] = ''

    # Build clickable links for Project and Issues
    def make_project_link(row):
        key = str(row.get('Project Key', '')).strip()
        name = str(row.get('Project', '')).strip()
        if JIRA_URL and key and name:
            return f"[{name}]({JIRA_URL}/browse/{key})"
        return name

    # Build JQL for issues link based on grouping mode
    # Collect all group accountIds for 'project' mode
    all_acc_ids = [u.get('accountId') for u in group_users if u.get('accountId')]

    def make_issues_link(row):
        issues_count = row.get('Issues', 0)
        if not issues_count:
            return '0'
        parts = []
        if mode in ('project', 'project_employee'):
            key = str(row.get('Project Key', '')).strip()
            if key:
                parts.append(f"project={key}")
        if mode == 'employee':
            acc = row.get('AccountId') or ''
            if acc:
                parts.append(f"assignee in (\"{acc}\")")
        elif mode == 'project_employee':
            acc = row.get('AccountId') or ''
            if acc:
                parts.append(f"assignee in (\"{acc}\")")
        else:  # project mode
            if all_acc_ids:
                acc_list = ",".join([f'"{a}"' for a in all_acc_ids])
                parts.append(f"assignee in ({acc_list})")
        parts.append("statusCategory != Done")
        if start_date:
            parts.append(f"duedate >= \"{start_date}\"")
        if end_date:
            parts.append(f"duedate <= \"{end_date}\"")
        jql = " AND ".join(parts)
        return f"[{int(issues_count)}]({JIRA_URL}/issues/?jql={quote_plus(jql)})"

    if 'Project' in grouped.columns:
        grouped['Project'] = grouped.apply(make_project_link, axis=1)
    grouped['Issues'] = grouped.apply(make_issues_link, axis=1)

    keep_cols = [
        'Project',
        'Employee',
        'Issues',
        'Workload (hours)',
        'Workload (weeks, days, hours)'
    ]
    # Drop helper columns before rendering
    drop_helpers = [c for c in ['Project Key', 'AccountId', 'Time (seconds)'] if c in grouped.columns]
    grouped = grouped.drop(columns=drop_helpers, errors='ignore')
    grouped = grouped[[c for c in keep_cols if c in grouped.columns]]

    records = grouped.to_dict('records')
    records.append({
        'Project': 'Total',
        'Employee': '',
        'Issues': str(total_issues),
        'Workload (hours)': total_hours,
        'Workload (weeks, days, hours)': total_formatted,
    })
    return records

if __name__ == "__main__":
    app.run(debug=True)
