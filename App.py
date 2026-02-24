import streamlit as st
import pandas as pd
from datetime import date
from utils import (
    get_client,
    fetch_profiles, create_profile,
    fetch_categories, insert_category, delete_category,
    fetch_priorities, fetch_threats, fetch_statuses,
    insert_task, update_task_description, update_task_due_date,
    insert_status_log, get_current_status, get_category_id,
    fetch_task_tree,
)
import io

st.set_page_config(page_title="Family Todo", layout="wide")

# -----------------------------
# Profile Selection Screen
# -----------------------------
if "profile_id" not in st.session_state:
    st.title("👨‍👩‍👧‍👦 Family Todo List")
    st.subheader("Who are you?")

    profiles_df = fetch_profiles()

    col_select, col_create = st.columns([2, 1])

    with col_select:
        if not profiles_df.empty:
            chosen_name = st.selectbox(
                "Select your profile",
                options=profiles_df["name"].tolist(),
                index=None,
                placeholder="Pick a family member..."
            )
            if st.button("➡️ Open My Tasks", disabled=chosen_name is None, use_container_width=True):
                row = profiles_df[profiles_df["name"] == chosen_name].iloc[0]
                st.session_state["profile_id"] = int(row["id"])
                st.session_state["profile_name"] = chosen_name
                st.rerun()
        else:
            st.info("No profiles yet — create one on the right!")

    with col_create:
        with st.form("create_profile"):
            st.markdown("**Create a new profile**")
            new_name = st.text_input("Your name", placeholder="e.g. Mum, Dad, Lily…")
            if st.form_submit_button("Create Profile"):
                new_name = new_name.strip()
                if not new_name:
                    st.error("Please enter a name.")
                elif new_name in profiles_df["name"].tolist():
                    st.error("A profile with that name already exists.")
                else:
                    create_profile(new_name)
                    st.success(f"Profile '{new_name}' created! Select it on the left.")
                    st.rerun()

    if not profiles_df.empty:
        st.markdown("---")
        st.markdown("**Family members:**")
        cols = st.columns(min(len(profiles_df), 5))
        for i, name in enumerate(profiles_df["name"].tolist()):
            with cols[i % 5]:
                st.markdown(f"**👤 {name}**")

    st.stop()

# ---- Profile active ----
profile_name = st.session_state["profile_name"]

col_title, col_logout = st.columns([5, 1])
with col_title:
    st.title(f"📋 {profile_name}'s Todo List")
with col_logout:
    st.write("")
    if st.button("🔄 Switch Profile"):
        st.session_state.pop("profile_id", None)
        st.session_state.pop("profile_name", None)
        st.rerun()

# -----------------------------
# Load lookup data
# -----------------------------
def build_category_hierarchy():
    categories = fetch_categories()
    if categories.empty:
        return pd.DataFrame(columns=["id", "full_path"])
    cat_map = dict(zip(categories["id"], categories["name"]))
    parent_map = dict(zip(categories["id"], categories["parent_id"]))

    def get_full_path(cat_id, visited=None):
        if visited is None:
            visited = set()
        if cat_id is None or cat_id not in cat_map:
            return ""
        if cat_id in visited:
            return "... (cycle)"
        visited.add(cat_id)
        parent_id = parent_map.get(cat_id)
        parent_path = get_full_path(parent_id, visited)
        name = cat_map[cat_id]
        return f"{parent_path} > {name}" if parent_path else name

    categories["full_path"] = categories["id"].apply(get_full_path)
    return categories

category_hierarchy = build_category_hierarchy()
priorities = fetch_priorities()
threats = fetch_threats()
statuses = fetch_statuses()

category_full_paths = ["(No Category)"] + category_hierarchy["full_path"].tolist()
category_ids = [None] + category_hierarchy["id"].tolist()
priority_options = priorities["description"].tolist()
priority_ids = priorities["id"].tolist()
threat_options = threats["description"].tolist()
threat_ids = threats["id"].tolist()
status_options = statuses["name"].tolist()

status_colors = {
    "Not Started": "#888888", "In Progress": "#FFA500", "Blocked": "#FF0000",
    "Ongoing": "#FFFF00",     "Completed":   "#28A745", "Cancelled": "#DC3545"
}
status_st_colors = {
    "Not Started": "gray", "In Progress": "orange", "Blocked": "red",
    "Ongoing": "yellow",   "Completed":   "green",   "Cancelled": "red"
}
status_st_emoji = {
    "Not Started": ":o:", "In Progress": "", "Blocked": ":bangbang:",
    "Ongoing": "",        "Completed":   "", "Cancelled": ""
}

# -----------------------------
# Category Management
# -----------------------------
with st.expander("🗂️ Manage Categories", expanded=False):
    with st.form("new_category"):
        st.subheader("Add a New Category")
        cat_name = st.text_input("Category Name *")
        parent_full_path = st.selectbox("Parent Category (optional)", options=category_full_paths, index=0)
        if st.form_submit_button("Add Category"):
            if not cat_name.strip():
                st.error("Name required!")
            else:
                parent_id = category_ids[category_full_paths.index(parent_full_path)] if parent_full_path != "(No Category)" else None
                insert_category(cat_name, parent_id)
                st.success(f"Category '{cat_name}' added!")
                st.rerun()

    st.markdown("---")

    with st.form("delete_category"):
        st.subheader("Delete a Category")
        options_to_delete = category_full_paths[1:]
        category_to_delete = st.selectbox(
            "Category to Delete", options=options_to_delete, index=None,
            placeholder="Select a category to delete...", disabled=not options_to_delete
        )
        st.warning("⚠️ Deleting a category moves its tasks to 'Uncategorized' and makes sub-categories top-level.")
        if st.form_submit_button("Delete Category", type="primary", disabled=not options_to_delete):
            if not category_to_delete:
                st.error("Please select a category.")
            else:
                cat_id_to_delete = category_ids[category_full_paths.index(category_to_delete)]
                success, message = delete_category(cat_id_to_delete)
                if success:
                    st.success(message)
                    st.rerun()

# -----------------------------
# Task Creation Form
# -----------------------------
with st.expander("➕ Add New Main Task", expanded=False):
    with st.form("new_main_task"):
        title = st.text_input("Task Title *")
        description = st.text_area("Description")
        due_date = st.date_input("Due Date", value=None)
        col1, col2, col3 = st.columns(3)
        with col1:
            category_choice = st.selectbox("Category", options=category_full_paths, index=0)
        with col2:
            priority_choice = st.selectbox("Priority", options=priority_options, index=2)
        with col3:
            threat_choice = st.selectbox("Threat Level", options=threat_options, index=0)

        if st.form_submit_button("Create Main Task"):
            if not title.strip():
                st.error("Title is required!")
            else:
                cat_id = category_ids[category_full_paths.index(category_choice)] if category_choice != "(No Category)" else None
                pri_id = priority_ids[priority_options.index(priority_choice)]
                thr_id = threat_ids[threat_options.index(threat_choice)]
                task_id = insert_task(
                    title=title.strip(), description=description or None,
                    due_date=due_date if due_date != date(1970, 1, 1) else None,
                    parent_id=None, category_id=cat_id,
                    priority_id=pri_id, threat_id=thr_id
                )
                insert_status_log(task_id, "Not Started")
                st.success(f"Task '{title}' created!")
                st.rerun()

# -----------------------------
# Subtask Form
# -----------------------------
def render_subtask_form(parent_task_id, depth=1):
    indent = "    " * depth
    with st.expander(f"{indent}➕ Add Subtask", expanded=False):
        with st.form(key=f"subtask_form_{parent_task_id}_{depth}"):
            sub_title = st.text_input("Subtask Title *")
            sub_desc  = st.text_area("Description")
            sub_due   = st.date_input("Due Date", value=None, key=f"due_sub_{parent_task_id}_{depth}")
            col1, col2 = st.columns(2)
            with col1:
                sub_priority = st.selectbox("Priority", options=priority_options, index=2, key=f"pri_sub_{parent_task_id}_{depth}")
            with col2:
                sub_threat = st.selectbox("Threat Level", options=threat_options, index=0, key=f"thr_sub_{parent_task_id}_{depth}")

            cat_id = get_category_id(parent_task_id)
            if st.form_submit_button("Create Subtask"):
                if not sub_title.strip():
                    st.error("Title required")
                else:
                    sub_task_id = insert_task(
                        title=sub_title.strip(), description=sub_desc or None,
                        due_date=sub_due if sub_due != date(1970, 1, 1) else None,
                        parent_id=parent_task_id, category_id=cat_id,
                        priority_id=priority_ids[priority_options.index(sub_priority)],
                        threat_id=threat_ids[threat_options.index(sub_threat)]
                    )
                    insert_status_log(sub_task_id, "Not Started")
                    st.success(f"Subtask '{sub_title}' created!")
                    st.rerun()

# -----------------------------
# Task Display
# -----------------------------
st.markdown("---")
st.header("Tasks by Category")

col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    selected_full_paths = st.multiselect("Filter by Category", options=category_full_paths[1:], default=None)
    selected_cat_ids = [category_ids[category_full_paths.index(p)] for p in selected_full_paths] if selected_full_paths else None
with col_f2:
    show_completed = st.checkbox("Show Completed/Cancelled", value=False)
with col_f3:
    sort_by = st.selectbox("Sort by", ["Default Order", "Status", "Priority", "Due Date (Soonest)"])

tasks_df = fetch_task_tree(selected_category_ids=selected_cat_ids, show_completed=show_completed)

if not tasks_df.empty and sort_by != "Default Order":
    if sort_by == "Status":
        order = ["In Progress", "Ongoing", "Blocked", "Not Started", "Completed", "Cancelled"]
        tasks_df["current_status"] = pd.Categorical(tasks_df["current_status"], categories=order, ordered=True)
        tasks_df = tasks_df.sort_values(by=["current_status", "priority_level"])
    elif sort_by == "Priority":
        tasks_df = tasks_df.sort_values(by=["priority_level", "due_date"], ascending=[True, True], na_position="last")
    elif sort_by == "Due Date (Soonest)":
        tasks_df = tasks_df.sort_values(by="due_date", ascending=True, na_position="last")

uncategorized_tasks = tasks_df[pd.isna(tasks_df["category_id"])] if not tasks_df.empty else pd.DataFrame()

def build_children_dict(df_subset):
    children = {}
    for _, row in df_subset.iterrows():
        parent = row["parent_id"] if pd.notna(row["parent_id"]) else None
        children.setdefault(parent, []).append(row)
    return children

def display_task(row, depth=0, children_dict=None):
    indent = "└─ " * depth
    status = row["current_status"]
    num_subs = int(row["num_subtasks"])
    due_label = "TBD" if pd.isna(row["due_date"]) else row["due_date"].strftime("%Y-%m-%d")
    label = f"{indent}**{row['title']}** | Due: {due_label} | Status: :{status_st_colors[status]}[{status}]{status_st_emoji[status]} | Subtasks: {num_subs}"

    with st.expander(label, expanded=False):
        col1, col2, col3 = st.columns([3, 2, 3])
        with col1:
            if row["description"]:
                st.write(f"_{row['description']}_")
            st.write(f"**Due Date:** {due_label}")
        with col2:
            st.markdown(
                f"<span style='background-color:{row['priority_color'] or '#888'}; padding:3px 10px; border-radius:5px; color:black; font-weight:bold;'>Priority: {row['priority_level']}</span>",
                unsafe_allow_html=True
            )
            st.markdown(
                f"<span style='background-color:{row['threat_color'] or '#888'}; padding:3px 10px; border-radius:5px; color:black; font-weight:bold;'>Threat: {str(row['threat_level']).capitalize() if row['threat_level'] else 'None'}</span>",
                unsafe_allow_html=True
            )
        with col3:
            st.markdown(
                f"<span style='background-color:{status_colors[status]}; padding:5px 12px; border-radius:6px; color:white; font-weight:bold; font-size:1.1em;'>Status: {status}</span>",
                unsafe_allow_html=True
            )

        with st.expander("📝 Edit Description", expanded=False):
            with st.form(key=f"desc_{row['id']}"):
                new_desc = st.text_area("New Description", value=row["description"] if pd.notna(row["description"]) else "")
                if st.form_submit_button("Save Description"):
                    update_task_description(row["id"], new_desc.strip() or None)
                    st.success("Description updated!")
                    st.rerun()

        with st.expander("📅 Edit Due Date", expanded=False):
            with st.form(key=f"due_{row['id']}"):
                col_d1, col_d2 = st.columns([3, 1])
                with col_d1:
                    new_due = st.date_input("New Due Date", value=(row["due_date"] if not pd.isna(row["due_date"]) else None))
                with col_d2:
                    st.write(" ")
                    clear_btn = st.form_submit_button("Clear (TBD)")
                update_btn = st.form_submit_button("Save Due Date")
                if update_btn or clear_btn:
                    due_to_save = None if clear_btn else new_due
                    update_task_due_date(row["id"], due_to_save)
                    st.success(f"Due date updated to: **{due_to_save if due_to_save else 'TBD'}**")
                    st.rerun()

        with st.expander("🔄 Update Status", expanded=False):
            with st.form(key=f"status_{row['id']}"):
                col_a, col_b = st.columns([2, 3])
                with col_a:
                    new_status = st.selectbox("New Status", options=status_options, index=status_options.index(status))
                with col_b:
                    reason = st.text_input("Reason (optional)", placeholder="e.g., Waiting on approval")
                if st.form_submit_button("Update Status"):
                    if new_status != status:
                        insert_status_log(row["id"], new_status, reason or None)
                        st.success(f"Status updated to **{new_status}**")
                        st.rerun()
                    else:
                        st.info("No change made.")

        render_subtask_form(row["id"], depth + 1)

        child_rows = (children_dict or {}).get(row["id"], [])
        if child_rows:
            st.caption("**Next Steps:**")
            for child_row in child_rows:
                display_task(child_row, depth + 1, children_dict)

if tasks_df.empty and uncategorized_tasks.empty:
    st.info("No tasks yet or none match the filters.")
else:
    displayed_any = False
    if not tasks_df.empty:
        for cat_id, group_df in tasks_df.dropna(subset=["category_id"]).groupby("category_id"):
            full_path = category_hierarchy[category_hierarchy["id"] == cat_id]["full_path"].iloc[0]
            st.subheader(f"📁 {full_path}")
            cd = build_children_dict(group_df)
            for _, root_row in group_df[pd.isna(group_df["parent_id"])].iterrows():
                display_task(root_row, children_dict=cd)
            displayed_any = True

    if not uncategorized_tasks.empty and not selected_cat_ids:
        if displayed_any:
            st.markdown("---")
        st.subheader("📌 Uncategorized Tasks")
        cd = build_children_dict(uncategorized_tasks)
        for _, root_row in uncategorized_tasks[pd.isna(uncategorized_tasks["parent_id"])].iterrows():
            display_task(root_row, children_dict=cd)

    if not displayed_any and uncategorized_tasks.empty:
        st.info("No tasks in selected categories.")

st.caption("Categories show full hierarchy. Tasks grouped under category headers.")
st.markdown("---")

# -----------------------------
# Export to Markdown
# -----------------------------
st.subheader("📄 Export Tasks to Markdown")
if st.button("Generate & Download Markdown"):
    tasks_df_full = fetch_task_tree(selected_category_ids=None, show_completed=True)
    if tasks_df_full.empty:
        st.warning("No tasks to export!")
    else:
        children_map = {}
        for _, row in tasks_df_full.iterrows():
            parent = row["parent_id"] if pd.notna(row["parent_id"]) else None
            children_map.setdefault(parent, []).append(row)

        active_df    = tasks_df_full[~tasks_df_full["current_status"].isin(["Completed", "Cancelled"])].copy()
        completed_df = tasks_df_full[tasks_df_full["current_status"].isin(["Completed", "Cancelled"])].copy()
        cat_paths = dict(zip(category_hierarchy["id"], category_hierarchy["full_path"])) if not category_hierarchy.empty else {}

        md = io.StringIO()
        md.write(f"# {profile_name}'s Todo List\n\nGenerated: {date.today()}\n\n")

        def sort_key(r):
            return r["due_date"] if not pd.isna(r["due_date"]) else date(9999, 12, 31)

        def write_task_recursive(row, indent_level=0):
            indent   = "  " * indent_level
            checkbox = "[x]" if row["current_status"] == "Completed" else "[ ]"
            due      = "TBD" if pd.isna(row["due_date"]) else row["due_date"].strftime("%Y-%m-%d")
            pri      = row["priority_level"] or "?"
            thr      = str(row["threat_level"]).capitalize() if row["threat_level"] else "None"
            s        = "~~" if row["current_status"] == "Cancelled" else ""
            md.write(f"{indent}- {s}{checkbox} **{row['title']}** (Due: {due} | P:{pri} | T:{thr} | {row['current_status']}){s}\n")
            if row["description"] and str(row["description"]).strip():
                for line in str(row["description"]).strip().split("\n"):
                    md.write(f"{indent}  > {line.strip()}\n")
            child_rows = children_map.get(row["id"], [])
            if child_rows:
                md.write(f"{indent}  - *Next Steps*\n")
                for child in sorted(child_rows, key=sort_key):
                    write_task_recursive(child, indent_level + 2)

        for section_label, section_df in [("Active Tasks", active_df), ("Completed Tasks", completed_df)]:
            md.write(f"## {section_label}\n\n")
            if section_df.empty:
                md.write("_None._\n\n")
                continue
            for cat_id, group in section_df.groupby("category_id", sort=False):
                md.write(f"### {'Uncategorized' if pd.isna(cat_id) else cat_paths.get(cat_id, 'Unknown')}\n\n")
                for root in sorted([r for _, r in group.iterrows() if pd.isna(r["parent_id"])], key=sort_key):
                    write_task_recursive(root)
                md.write("\n")

        content = md.getvalue()
        with st.expander("Preview", expanded=True):
            st.code(content, language="markdown")
        st.download_button("📥 Download Markdown", data=content,
            file_name=f"{profile_name}_todo_{date.today()}.md", mime="text/markdown")
