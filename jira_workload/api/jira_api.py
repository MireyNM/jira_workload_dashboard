import requests
from requests.auth import HTTPBasicAuth
import pandas as pd

import os
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv())

# ==== Env Variables ====
JIRA_URL = os.getenv("JIRA_URL")
JIRA_USER_EMAIL = os.getenv("JIRA_USER_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")
if not all([JIRA_URL, JIRA_USER_EMAIL, JIRA_API_TOKEN]): raise RuntimeError("Jira env vars not set")

# ==== CONNECTION ====
def connect_to_jira():
    """Return a requests.Session() with Jira Cloud authentication"""
    session = requests.Session()
    session.auth = HTTPBasicAuth(JIRA_USER_EMAIL, JIRA_API_TOKEN)
    session.headers.update({
        "Accept": "application/json",
        "Content-Type": "application/json"
    })
    return session

# ==== ISSUE COUNT ====
def count_issues(session, jql):
    """Count issues based on JQL (v3 REST API)"""
    url = f"{JIRA_URL}/rest/api/3/search"
    params = {"jql": jql, "maxResults": 0}
    response = session.get(url, params=params)

    if response.status_code != 200:
        raise Exception(f"❌ Jira API error {response.status_code}: {response.text}")

    data = response.json()
    return data.get("total", 0)

# ==== PROJECT COUNT ====
def get_project_count(session):
    """Count number of projects (v3 REST API)"""
    url = f"{JIRA_URL}/rest/api/3/project/search"
    response = session.get(url)
    if response.status_code != 200:
        raise Exception(f"❌ Jira API error {response.status_code}: {response.text}")
    data = response.json()
    return data.get("total", 0)

# ==== USER LIST ====
# def get_all_jira_users(session):
#     """Fetch all users using Jira REST API v3 with pagination"""
#     all_users = []
#     start_at = 0
#     max_results = 80

#     while True:
#         url = f"{JIRA_URL}/rest/api/3/users/search"
#         response = session.get(url, params={"startAt": start_at, "maxResults": max_results})
#         if response.status_code != 200:
#             raise Exception(f"❌ Jira API error {response.status_code}: {response.text}")

#         users = response.json()
#         if not users:
#             break

#         all_users.extend(users)
#         start_at += max_results

#     print(f"✅ Retrieved {len(all_users)} users from Jira")
#     return all_users

def get_group_members(session, group_name, max_results=100):
    """Return members of a Jira group by name (paginated)."""
    members = []
    start_at = 0
    while True:
        url = f"{JIRA_URL}/rest/api/3/group/member"
        resp = session.get(url, params={"groupname": group_name, "startAt": start_at, "maxResults": max_results})
        if resp.status_code == 404:
            try:
                details = resp.json().get("errorMessages", [])
            except Exception:
                details = []
            print(f"⚠️ Jira group not found, skipping: '{group_name}'. Details: {details}")
            return []
        if resp.status_code != 200:
            raise Exception(f"❌ Jira API error {resp.status_code}: {resp.text}")

        data = resp.json()
        values = data.get("values", [])
        if not values:
            break

        members.extend(values)
        if data.get("isLast", False) or (start_at + len(values)) >= data.get("total", 0):
            break
        start_at += max_results

    return members

def get_users_from_groups(session, group_names):
    """Fetch active human users from multiple groups, dedupe and sort."""
    all_users = []
    for name in group_names:
        grp_members = get_group_members(session, name)
        filtered = [
            u for u in grp_members
            if u.get("accountType") == "atlassian" and bool(u.get("active"))
        ]
        all_users.extend(filtered)

    # Dedupe by accountId
    dedup = {u.get("accountId"): u for u in all_users}.values()
    users = sorted(dedup, key=lambda u: (u.get("displayName") or "").lower())
    return list(users) 

# === Function to query Jira ===
def get_issues(jql):
    url = f"{JIRA_URL}/rest/api/3/search"
    response = requests.post(
        url,
        json={
            "jql": jql,
            "maxResults": 500,
            "fields": ["summary", "status", "assignee", "project", "duedate"]
        },
        auth=HTTPBasicAuth(JIRA_USER_EMAIL, JIRA_API_TOKEN),
        headers={"Accept": "application/json", "Content-Type": "application/json"}
    )

    if response.status_code != 200:
        raise Exception(f"❌ Jira API error {response.status_code}: {response.text}")

    return response.json().get("issues", [])

def get_user_workload(session, account_id):
    # Exclude completed work
    jql = f"assignee in (\"{account_id}\") AND statusCategory NOT IN ('Done','Cancelled')"
    url = f"{JIRA_URL}/rest/api/3/search/jql"
    payload = {
        "jql": jql,
        "maxResults": 1000,
        "fields": ["project", "timeoriginalestimate"]
    }
    response = session.post(url, json=payload)
    # Debug after sending the request
    try:
        print("[DEBUG] JQL:", jql)
        print("[DEBUG] URL:", url)
        print("[DEBUG] Status:", response.status_code)
        body_preview = response.text[:400] if hasattr(response, 'text') else '<no body>'
        print("[DEBUG] Body:", body_preview)
    except Exception:
        pass
    if response.status_code != 200:
        raise Exception(f"❌ Jira API error {response.status_code}: {response.text}")

    issues = response.json().get("issues", [])
    data = []
    for issue in issues:
        fields = issue.get("fields", {})
        project = (fields.get("project") or {}).get("name")
        time_estimate = fields.get("timeoriginalestimate") or 0
        data.append([project, issue.get("key"), time_estimate])

    df = pd.DataFrame(data, columns=["Project", "Issue", "Time (seconds)"])
    grouped = df.groupby("Project").agg({
        "Issue": "count",
        "Time (seconds)": "sum"
    }).reset_index().rename(columns={"Issue": "Issues"})
    return grouped