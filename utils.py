import streamlit as st
import pandas as pd
from datetime import date
from supabase import create_client, Client


# -----------------------------
# Supabase Client (cached)
# -----------------------------
@st.cache_resource
def get_client() -> Client:
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)


def get_profile_id() -> int:
    return st.session_state["profile_id"]


# -----------------------------
# Profiles
# -----------------------------
def fetch_profiles() -> pd.DataFrame:
    client = get_client()
    response = client.table("profiles").select("id, name").order("name").execute()
    data = response.data or []
    return pd.DataFrame(data, columns=["id", "name"]) if not data else pd.DataFrame(data)


def create_profile(name: str) -> int:
    client = get_client()
    response = client.table("profiles").insert({"name": name}).execute()
    return response.data[0]["id"]


# -----------------------------
# Lookup tables
# -----------------------------
def fetch_statuses() -> pd.DataFrame:
    client = get_client()
    response = client.table("statuses").select("id, name").order("id").execute()
    return pd.DataFrame(response.data or [])


def fetch_priorities() -> pd.DataFrame:
    client = get_client()
    response = client.table("priorities").select("id, level, description, color").order("level").execute()
    return pd.DataFrame(response.data or [])


def fetch_threats() -> pd.DataFrame:
    client = get_client()
    response = client.table("threats").select("id, level, description, color").order("id").execute()
    return pd.DataFrame(response.data or [])


# -----------------------------
# Categories
# -----------------------------
def fetch_categories() -> pd.DataFrame:
    client = get_client()
    profile_id = get_profile_id()
    response = (
        client.table("categories")
        .select("id, name, parent_id")
        .eq("profile_id", profile_id)
        .order("name")
        .execute()
    )
    return pd.DataFrame(response.data or [])


def insert_category(name: str, parent_id=None) -> int:
    client = get_client()
    response = client.table("categories").insert({
        "profile_id": get_profile_id(),
        "name":       name.strip(),
        "parent_id":  parent_id,
    }).execute()
    return response.data[0]["id"]


def delete_category(category_id: int):
    client = get_client()
    client.table("categories").update({"parent_id": None}).eq("parent_id", category_id).execute()
    client.table("tasks").update({"category_id": None}).eq("category_id", category_id).execute()
    client.table("categories").delete().eq("id", category_id).execute()
    return True, "Category deleted. Tasks are now uncategorized and sub-categories are now top-level."


# -----------------------------
# Tasks
# -----------------------------
def insert_task(title, description, due_date, parent_id, category_id, priority_id, threat_id) -> int:
    client = get_client()
    response = client.table("tasks").insert({
        "profile_id":  get_profile_id(),
        "title":       title,
        "description": description,
        "due_date":    due_date.isoformat() if isinstance(due_date, date) else due_date,
        "parent_id":   parent_id,
        "category_id": category_id,
        "priority_id": priority_id,
        "threat_id":   threat_id,
    }).execute()
    return response.data[0]["id"]


def update_task_description(task_id: int, description):
    get_client().table("tasks").update({"description": description or None}).eq("id", task_id).execute()


def update_task_due_date(task_id: int, due_date):
    value = due_date.isoformat() if isinstance(due_date, date) else due_date
    get_client().table("tasks").update({"due_date": value}).eq("id", task_id).execute()


def get_category_id(task_id: int):
    response = get_client().table("tasks").select("category_id").eq("id", task_id).single().execute()
    return (response.data or {}).get("category_id")


# -----------------------------
# Status logs
# -----------------------------
def insert_status_log(task_id: int, status_name: str, reason=None, extra_info=None):
    client = get_client()
    status_resp = client.table("statuses").select("id").eq("name", status_name).single().execute()
    status_id = status_resp.data["id"]
    client.table("task_status_logs").insert({
        "task_id":    task_id,
        "status_id":  status_id,
        "reason":     reason,
        "extra_info": extra_info,
    }).execute()


def get_current_status(task_id: int) -> str:
    """Single task lookup — only use this outside of fetch_task_tree."""
    response = (
        get_client().table("task_status_logs")
        .select("statuses(name)")
        .eq("task_id", task_id)
        .order("id", desc=True)
        .limit(1)
        .execute()
    )
    if response.data:
        return (response.data[0].get("statuses") or {}).get("name", "Pending")
    return "Pending"


def fetch_all_current_statuses(task_ids: list) -> dict:
    """Fetch the latest status for ALL tasks in ONE single query.
    Returns {task_id: status_name} — eliminates the N+1 query problem."""
    if not task_ids:
        return {}
    response = (
        get_client().table("task_status_logs")
        .select("task_id, id, statuses(name)")
        .in_("task_id", task_ids)
        .order("id", desc=True)
        .execute()
    )
    rows = response.data or []
    # Keep only the first (highest id = latest) row seen per task
    seen = {}
    for row in rows:
        tid = row["task_id"]
        if tid not in seen:
            seen[tid] = (row.get("statuses") or {}).get("name", "Pending")
    # Tasks with no log entry default to Pending
    for tid in task_ids:
        if tid not in seen:
            seen[tid] = "Pending"
    return seen


def fetch_status_history(task_id: int) -> pd.DataFrame:
    response = (
        get_client().table("task_status_logs")
        .select("timestamp, reason, extra_info, statuses(name)")
        .eq("task_id", task_id)
        .order("timestamp", desc=True)
        .execute()
    )
    rows = response.data or []
    return pd.DataFrame([{
        "timestamp":  r["timestamp"],
        "status":     (r.get("statuses") or {}).get("name"),
        "reason":     r["reason"],
        "extra_info": r["extra_info"],
    } for r in rows])


# -----------------------------
# Task tree (main fetch)
# -----------------------------
def fetch_task_tree(selected_category_ids=None, show_completed=False) -> pd.DataFrame:
    client = get_client()
    profile_id = get_profile_id()

    query = (
        client.table("tasks")
        .select(
            "id, title, description, due_date, parent_id, category_id, "
            "categories(name), priorities(level, color), threats(level, color)"
        )
        .eq("profile_id", profile_id)
    )
    if selected_category_ids:
        query = query.in_("category_id", selected_category_ids)

    rows = query.order("id").execute().data or []

    if not rows:
        return pd.DataFrame()

    records = []
    for r in rows:
        records.append({
            "id":             r["id"],
            "title":          r["title"],
            "description":    r["description"],
            "due_date":       pd.to_datetime(r["due_date"]).date() if r["due_date"] else None,
            "parent_id":      r["parent_id"],
            "category_id":    r["category_id"],
            "category_name":  (r.get("categories") or {}).get("name"),
            "priority_level": (r.get("priorities") or {}).get("level"),
            "priority_color": (r.get("priorities") or {}).get("color"),
            "threat_level":   (r.get("threats") or {}).get("level"),
            "threat_color":   (r.get("threats") or {}).get("color"),
        })

    df = pd.DataFrame(records)

    # ONE bulk query for all statuses instead of one query per task
    task_ids = df["id"].tolist()
    status_map = fetch_all_current_statuses(task_ids)
    df["current_status"] = df["id"].map(status_map)

    df["num_subtasks"] = df["id"].apply(
        lambda tid: sum(1 for rec in records if rec["parent_id"] == tid)
    )

    if not show_completed:
        df = df[~df["current_status"].isin(["Completed", "Cancelled"])]

    return df
