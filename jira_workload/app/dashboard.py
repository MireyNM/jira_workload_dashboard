# Activate env: .\jira_env\Scripts\Activate.ps1 
# Navigate to project root: cd .\jira_workload_dashboard 
# Run app: python -m jira_workload.app.dashboard

import os
import sys
from urllib.parse import quote_plus
import pandas as pd


from dotenv import load_dotenv
from dash import Dash, html, dcc, Input, Output, dash_table
from jira_workload.api.jira_api import connect_to_jira, get_users_from_groups, get_user_workload, get_group_members

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
    html.H2("User Workload Dashboard"),
    dcc.Dropdown(
        id='user-dropdown',
        options=[{'label': normalize_name(u.get('displayName', '')), 'value': u['accountId']} for u in users],
        placeholder='Select a user'
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

@app.callback(
    Output('workload-table', 'data'),
    Input('user-dropdown', 'value')
)
def update_table(account_id):
    if not account_id:
        return []
    df = get_user_workload(session, account_id)  # columns: Project, Issues, Time (seconds), Project Key

    # Compute hours from seconds
    df["Workload (hours)"] = (df["Time (seconds)"] / 3600).round(2)

    # Format as "X weeks, Y day(s), Z hour(s)" assuming 40h/week and 8h/day
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

    df["Workload (weeks, days, hours)"] = df["Time (seconds)"].apply(fmt_weeks_days_hours)

    # Compute totals before dropping seconds
    total_issues = int(df["Issues"].sum())
    total_seconds = float(df["Time (seconds)"].sum())
    total_hours = round(total_seconds / 3600, 2)
    total_formatted = fmt_weeks_days_hours(total_seconds)

    # Build clickable links
    def make_project_link(row):
        key = str(row.get("Project Key", "")).strip()
        name = str(row.get("Project", "")).strip()
        if JIRA_URL and key and name:
            # Link to the main project page (browse)
            return f"[{name}]({JIRA_URL}/browse/{key})"
        return name

    def make_issues_link(row):
        key = str(row.get("Project Key", "")).strip()
        issues_count = row.get("Issues", 0)
        if JIRA_URL and key and issues_count:
            # Link to issues for the selected assignee within this project, excluding Done items
            jql = f"project={key} AND assignee in (\"{account_id}\") AND statusCategory != Done"
            return f"[{int(issues_count)}]({JIRA_URL}/issues/?jql={quote_plus(jql)})"
        return str(int(issues_count)) if issues_count else "0"

    if "Project Key" in df.columns:
        df["Project"] = df.apply(make_project_link, axis=1)
        df["Issues"] = df.apply(make_issues_link, axis=1)

    # Drop helper columns and select final columns
    keep_cols = ["Project", "Issues", "Workload (hours)", "Workload (weeks, days, hours)"]
    df = df[[c for c in keep_cols if c in df.columns]]

    records = df.to_dict("records")
    records.append({
        "Project": "Total",
        "Issues": str(total_issues),  # keep plain text for total row
        "Workload (hours)": total_hours,
        "Workload (weeks, days, hours)": total_formatted,
    })

    return records

if __name__ == "__main__":
    app.run(debug=True)
