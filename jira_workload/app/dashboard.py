# Activate env: .\jira_env\Scripts\Activate.ps1 

import os
import sys
import pandas as pd


from dotenv import load_dotenv
from dash import Dash, html, dcc, Input, Output, dash_table
from jira_workload.api.jira_api import connect_to_jira, get_users_from_groups, get_user_workload

load_dotenv()

app = Dash(__name__)

session = connect_to_jira()

# Get users from specific Jira groups (comma-separated in .env as JIRA_GROUP_NAMES)
GROUP_NAMES = [g.strip() for g in os.getenv("JIRA_GROUP_NAMES", "").split(",") if g.strip()] 
print("GROUP_NAMES from env:", GROUP_NAMES)
users = get_users_from_groups(session, GROUP_NAMES)

# Optional: further restrict by company email domain
users = [u for u in users if str(u.get("emailAddress", "")).lower().endswith("@apscorp.ca")]

app.layout = html.Div([
    html.H2("User Workload Dashboard"),
    dcc.Dropdown(
        id='user-dropdown',
        options=[{'label': u['displayName'], 'value': u['accountId']} for u in users],
        placeholder='Select a user'
    ),
    dash_table.DataTable(
    id='workload-table',
    columns=[
        {"name": "Project", "id": "Project"},
        {"name": "Issues", "id": "Issues"},
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
    df = get_user_workload(session, account_id)  # columns: Project, Issues, Time (seconds)

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

    # Drop raw seconds column and select final columns
    df = df[["Project", "Issues", "Workload (hours)", "Workload (weeks, days, hours)"]]

    # Drop raw seconds column and select final columns
    df = df[["Project", "Issues", "Workload (hours)", "Workload (weeks, days, hours)"]]

    records = df.to_dict("records")
    records.append({
        "Project": "Total",
        "Issues": total_issues,
        "Workload (hours)": total_hours,
        "Workload (weeks, days, hours)": total_formatted,
    })

    return records

if __name__ == "__main__":
    app.run(debug=True)
