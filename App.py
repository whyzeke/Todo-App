import streamlit as st
import sqlite3
import pandas as pd
from datetime import date
from utils import get_connection, fetch_task_tree, fetch_statuses, insert_status_log, get_current_status, get_category_id
import io
import subprocess
import sys

# -----------------------------
# Run DBSettup.py once per session
# -----------------------------
if "db_initialized" not in st.session_state:
    result = subprocess.run(
        [sys.executable, "DBSetup.py"],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        st.error(f"Database setup failed:\n{result.stderr}")
        st.stop()
    st.session_state["db_initialized"] = True

# -----------------------------
# Database Connection
# -----------------------------
def init_db():
    with get_connection() as conn:
        conn.execute("PRAGMA foreign_keys = ON")

init_db()

# -----------------------------
# Helper Functions
# -----------------------------
def fetch_categories():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT id, name, parent_id FROM categories ORDER BY name", conn)

def build_category_hierarchy():
    """Build full path for each category: Grandparent > Parent > Category"""
    categories = fetch_categories()
    if categories.empty:
        return pd.DataFrame(columns=['id', 'full_path'])
    
    cat_map = dict(zip(categories['id'], categories['name']))
    
    def get_full_path(cat_id, visited=None):
        if visited is None:
            visited = set()
        if cat_id is None or cat_id not in cat_map:
            return ""
        if cat_id in visited:
            return "... (cycle)"
        visited.add(cat_id)
        parent_id = categories[categories['id'] == cat_id]['parent_id'].iloc[0]
        parent_path = get_full_path(parent_id, visited)
        name = cat_map[cat_id]
        if parent_path:
            return f"{parent_path} > {name}"
        return name
    
    categories['full_path'] = categories['id'].apply(get_full_path)
    return categories

def fetch_priorities():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT id, level, description, color FROM priorities ORDER BY level", conn)

def fetch_threats():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT id, level, description, color FROM threats ORDER BY id", conn)

def insert_category(name, parent_id=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name.strip(), parent_id))
        conn.commit()
        return cursor.lastrowid

def insert_task(title, description, due_date, parent_id, category_id, priority_id, threat_id):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO tasks (title, description, due_date, parent_id, category_id, priority_id, threat_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (title, description, due_date, parent_id, category_id, priority_id, threat_id))
        conn.commit()
        return cursor.lastrowid

def delete_category(category_id):
    """
    Deletes a category and reassigns its contents.
    - Tasks under this category will become 'Uncategorized'.
    - Sub-categories will become top-level categories.
    Returns a tuple (bool_success, str_message).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        try:
            # Re-parent sub-categories to become top-level categories
            cursor.execute("UPDATE categories SET parent_id = NULL WHERE parent_id = ?", (category_id,))
            
            # Un-categorize tasks belonging to this category
            cursor.execute("UPDATE tasks SET category_id = NULL WHERE category_id = ?", (category_id,))
            
            # Now, delete the category
            cursor.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            
            conn.commit()
            return True, "Category deleted. Its tasks are now uncategorized and its sub-categories are now top-level."
        except sqlite3.Error as e:
            conn.rollback()
            return False, f"Database error: {e}"


# -----------------------------
# Streamlit App
# -----------------------------
st.set_page_config(page_title="Todo List", layout="wide")
st.title("📋 Hierarchical Todo List")

# Load data
category_hierarchy = build_category_hierarchy()
priorities = fetch_priorities()
threats = fetch_threats()
statuses = fetch_statuses()

# Category options with full path
category_full_paths = ["(No Category)"] + category_hierarchy['full_path'].tolist()
category_ids = [None] + category_hierarchy['id'].tolist()
priority_options = priorities['description'].tolist()
priority_ids = priorities['id'].tolist()
threat_options = threats['description'].tolist()
threat_ids = threats['id'].tolist()
status_options = statuses['name'].tolist()
status_colors = {
    "Not Started": "#888888",
    "In Progress": "#FFA500",
    "Blocked": "#FF0000",
    "Ongoing": "#FFFF00",
    "Completed": "#28A745",
    "Cancelled": "#DC3545"
}

status_st_colors={
    "Not Started": "gray",
    "In Progress": "orange",
    "Blocked": "red",
    "Ongoing": "yellow",
    "Completed": "green",
    "Cancelled": "red"
}

status_st_emoji={
    "Not Started": ":o:",
    "In Progress": "",
    "Blocked": ":bangbang:",
    "Ongoing": "",
    "Completed": "",
    "Cancelled": ""
}

# -----------------------------
# Category Management
# -----------------------------
with st.expander("🗂️ Manage Categories", expanded=False):
    # --- Add Category ---
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
    
    # --- Delete Category ---
    with st.form("delete_category"):
        st.subheader("Delete a Category")
        options_to_delete = category_full_paths[1:]  # Exclude "(No Category)"
        category_to_delete_full_path = st.selectbox(
            "Category to Delete",
            options=options_to_delete,
            index=None,
            placeholder="Select a category to delete...",
            disabled=not options_to_delete # Disable if no categories exist
        )
        st.warning("⚠️ **Warning:** Deleting a category will move its tasks to 'Uncategorized' and make its sub-categories top-level categories.")

        if st.form_submit_button("Delete Category", type="primary", disabled=not options_to_delete):
            if not category_to_delete_full_path:
                st.error("Please select a category to delete.")
            else:
                cat_id_to_delete = category_ids[category_full_paths.index(category_to_delete_full_path)]
                success, message = delete_category(cat_id_to_delete)
                if success:
                    st.success(message)
                    st.rerun()
                else:
                    st.error(message)

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

        submitted = st.form_submit_button("Create Main Task")
        if submitted:
            if not title.strip():
                st.error("Title is required!")
            else:
                category_id = category_ids[category_full_paths.index(category_choice)] if category_choice != "(No Category)" else None
                priority_id = priority_ids[priority_options.index(priority_choice)]
                threat_id = threat_ids[threat_options.index(threat_choice)]
                task_id = insert_task(
                    title=title.strip(),
                    description=description or None,
                    due_date=due_date if due_date != date(1970,1,1) else None,
                    parent_id=None,
                    category_id=category_id,
                    priority_id=priority_id,
                    threat_id=threat_id
                )
                insert_status_log(task_id, "Not Started")
                st.success(f"Task '{title}' created!")
                st.rerun()

# -----------------------------
# Recursive Subtask Form
# -----------------------------
def render_subtask_form(parent_task_id, depth=1):
    indent = "    " * depth
    with st.expander(f"{indent}➕ Add Subtask", expanded=False):
        with st.form(key=f"subtask_form_{parent_task_id}_{depth}"):
            sub_title = st.text_input("Subtask Title *")
            sub_desc = st.text_area("Description")
            sub_due = st.date_input("Due Date", value=None, key=f"due_sub_{parent_task_id}_{depth}")
            
            col1, col2 = st.columns(2)
            with col1:
                sub_priority = st.selectbox("Priority", options=priority_options, index=2, key=f"pri_sub_{parent_task_id}_{depth}")
            with col2:
                sub_threat = st.selectbox("Threat Level", options=threat_options, index=0, key=f"thr_sub_{parent_task_id}_{depth}")

            cat_id = get_category_id(parent_task_id)["category_id"].tolist()[0]
            if st.form_submit_button("Create Subtask"):
                if not sub_title.strip():
                    st.error("Title required")
                else:
                    sub_priority_id = priority_ids[priority_options.index(sub_priority)]
                    sub_threat_id = threat_ids[threat_options.index(sub_threat)]
                    sub_task_id = insert_task(
                        title=sub_title.strip(),
                        description=sub_desc or None,
                        due_date=sub_due if sub_due != date(1970,1,1) else None,
                        parent_id=parent_task_id,
                        category_id=cat_id,
                        priority_id=sub_priority_id,
                        threat_id=sub_threat_id
                    )
                    insert_status_log(sub_task_id, "Not Started")
                    st.success(f"Subtask '{sub_title}' created!")
                    st.rerun()

# -----------------------------
# Task Display with Category Headers
# -----------------------------
st.markdown("---")
st.header("Tasks by Category")

# <<< START: EDITED SECTION >>>
# Filters and Sorting
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    selected_full_paths = st.multiselect(
        "Filter by Category",
        options=category_full_paths[1:],
        default=None,
        help="Shows tasks in selected categories only"
    )
    selected_cat_ids = [
        category_ids[category_full_paths.index(path)]
        for path in selected_full_paths
    ] if selected_full_paths else None

with col_f2:
    show_completed = st.checkbox("Show Completed/Cancelled", value=False)

with col_f3:
    sort_by = st.selectbox("Sort by", ["Default Order", "Status", "Priority", "Due Date (Soonest)"])

tasks_df = fetch_task_tree(selected_category_ids=selected_cat_ids, show_completed=show_completed)

# Apply sorting if a sort order is chosen
if not tasks_df.empty and sort_by != "Default Order":
    if sort_by == "Status":
        # Define the desired order for statuses for sorting
        status_order = ["In Progress", "Ongoing", "Blocked", "Not Started", "Completed", "Cancelled"]
        tasks_df['current_status'] = pd.Categorical(tasks_df['current_status'], categories=status_order, ordered=True)
        # Sort by status, then by priority as a secondary factor
        tasks_df = tasks_df.sort_values(by=['current_status', 'priority_level'])

    elif sort_by == "Priority":
        # Sort by priority level (assuming lower level is higher priority), then by due date
        tasks_df = tasks_df.sort_values(by=['priority_level', 'due_date'], ascending=[True, True], na_position='last')

    elif sort_by == "Due Date (Soonest)":
        # Sort by due date, putting tasks without a due date at the end
        tasks_df = tasks_df.sort_values(by='due_date', ascending=True, na_position='last')
# <<< END: EDITED SECTION >>>

uncategorized_tasks = tasks_df[pd.isna(tasks_df['category_id'])] if not tasks_df.empty else pd.DataFrame()

if tasks_df.empty and uncategorized_tasks.empty:
    st.info("No tasks yet or none match the filters.")
else:
    if not tasks_df.empty:
        category_groups = tasks_df.dropna(subset=['category_id']).groupby('category_id')
    else:
        category_groups = []

    def build_children_dict(df_subset):
        children = {}
        for _, row in df_subset.iterrows():
            parent = row['parent_id'] if pd.notna(row['parent_id']) else None
            if parent not in children:
                children[parent] = []
            children[parent].append(row)
        return children
    
    def display_task(row, depth=0, children_dict=None):
        indent = "└─ " * depth
        status = row['current_status']
        num_subs = int(row['num_subtasks'])
        status_color = status_colors.get(status, "#888888")
        text_color = "black" if status == "Ongoing" else "white"


        if pd.isna(row['due_date']):
            due_label = "TBD"
        else:
            due_label = row['due_date'].strftime('%Y-%m-%d')
        
        label = f"{indent}**{row['title']}** | Due: {due_label} | Status: :{status_st_colors[status]}[{status}]{status_st_emoji[status]} | Subtasks: {num_subs}"
        
        with st.expander(label, expanded=False):
            col1, col2, col3 = st.columns([3, 2, 3])
            with col1:
                if row['description']:
                    st.write(f"_{row['description']}_")
                st.write(f"**Due Date:** {due_label}")
            with col2:
                priority_color = row['priority_color'] or "#888888"
                threat_color = row['threat_color'] or "#888888"
                st.markdown(
                    f"<span style='background-color:{priority_color}; padding:3px 10px; border-radius:5px; color:black; font-weight:bold;'>Priority: {row['priority_level']}</span>",
                    unsafe_allow_html=True
                )
                st.markdown(
                    f"<span style='background-color:{threat_color}; padding:3px 10px; border-radius:5px; color:black; font-weight:bold;'>Threat: {row['threat_level'].capitalize() if row['threat_level'] else 'None'}</span>",
                    unsafe_allow_html=True
                )
            with col3:
                st.markdown(
                    f"<span style='background-color:{status_color}; padding:5px 12px; border-radius:6px; color:white; font-weight:bold; font-size:1.1em;'>Status: {status}</span>",
                    unsafe_allow_html=True
                )
            
            with st.expander("📝 Edit Description", expanded=False):
                with st.form(key=f"description_update_{row['id']}"):
                    new_description = st.text_area(
                        "New Description",
                        value=row['description'] if pd.notna(row['description']) else "",
                        key=f"desc_editor_{row['id']}"
                    )
                    
                    if st.form_submit_button("Save Description"):
                        with get_connection() as conn:
                            conn.execute(
                                "UPDATE tasks SET description = ? WHERE id = ?",
                                (new_description.strip() or None, row['id'])
                            )
                            conn.commit()
                        st.success("Description updated!")
                        st.rerun()

            with st.expander("📅 Edit Due Date", expanded=False):
                with st.form(key=f"due_date_update_{row['id']}"):
                    col_d1, col_d2 = st.columns([3, 1])
                    with col_d1:
                        new_due_date = st.date_input(
                            "New Due Date",
                            value=(row['due_date'] if not pd.isna(row['due_date']) else None),
                            key=f"due_picker_{row['id']}"
                        )
                    with col_d2:
                        st.write(" ")
                        clear_btn = st.form_submit_button("Clear (TBD)")
                    
                    update_btn = st.form_submit_button("Save Due Date")

                    if update_btn or clear_btn:
                        due_to_save = None if clear_btn else new_due_date
                        with get_connection() as conn:
                            conn.execute(
                                "UPDATE tasks SET due_date = ? WHERE id = ?",
                                (due_to_save, row['id'])
                            )
                            conn.commit()
                        st.success(f"Due date updated to: **{due_to_save if due_to_save else 'TBD'}**")
                        st.rerun()

            with st.expander("🔄 Update Status", expanded=False):
                with st.form(key=f"status_update_{row['id']}"):
                    col_a, col_b = st.columns([2, 3])
                    with col_a:
                        new_status = st.selectbox(
                            "New Status",
                            options=status_options,
                            index=status_options.index(status),
                            key=f"status_sel_{row['id']}"
                        )
                    with col_b:
                        reason = st.text_input(
                            "Reason (optional)",
                            placeholder="e.g., Waiting on approval",
                            key=f"reason_{row['id']}"
                        )
                    
                    if st.form_submit_button("Update Status"):
                        if new_status != status:
                            insert_status_log(row['id'], new_status, reason or None)
                            st.success(f"Status updated to **{new_status}**")
                            st.rerun()
                        else:
                            st.info("No change made.")

            render_subtask_form(row['id'], depth + 1)
            
            child_rows = children_dict.get(row['id'], [])
            if child_rows:
                st.caption("**Next Steps:**")
                for child_row in child_rows:
                    display_task(child_row, depth + 1, children_dict)

    displayed_any = False
    for cat_id, group_df in category_groups:
        full_path = category_hierarchy[category_hierarchy['id'] == cat_id]['full_path'].iloc[0]
        st.subheader(f"📁 {full_path}")
        children_dict = build_children_dict(group_df)
        root_tasks = [row for _, row in group_df.iterrows() if pd.isna(row['parent_id'])]
        for root_row in root_tasks:
            display_task(root_row, children_dict=children_dict)
        displayed_any = True

    if not uncategorized_tasks.empty and (selected_cat_ids is None or not selected_cat_ids):
        if displayed_any:
            st.markdown("---")
        st.subheader("📌 Uncategorized Tasks")
        children_dict = build_children_dict(uncategorized_tasks)
        root_tasks = [row for _, row in uncategorized_tasks.iterrows() if pd.isna(row['parent_id'])]
        for root_row in root_tasks:
            display_task(root_row, children_dict=children_dict)
    
    if not displayed_any and uncategorized_tasks.empty:
        st.info("No tasks in selected categories.")

st.caption("Categories show full hierarchy (Parent > Child > Subchild). Tasks are grouped under clear category headers.")
st.markdown("---")

# --- Export to Markdown ---
st.subheader("📄 Export Tasks to Markdown")
if st.button("Generate & Download Markdown"):
    tasks_df = fetch_task_tree(selected_category_ids=None, show_completed=True)
    
    if tasks_df.empty:
        st.warning("No tasks to export!")
    else:
        tasks_df['current_status'] = tasks_df['id'].apply(get_current_status)
        
        children = {}
        for _, row in tasks_df.iterrows():
            parent = row['parent_id'] if pd.notna(row['parent_id']) else None
            if parent not in children:
                children[parent] = []
            children[parent].append(row)
        
        active_df = tasks_df[~tasks_df['current_status'].isin(['Completed','Cancelled'])].copy()
        completed_df = tasks_df[tasks_df['current_status'].isin(['Completed','Cancelled'])].copy()
        
        cat_paths = {}
        if not category_hierarchy.empty:
            cat_paths = dict(zip(category_hierarchy['id'], category_hierarchy['full_path']))
        
        md = io.StringIO()
        md.write("""---
title: Todo list
---
<style>
h3 {
    border-bottom: 2px solid #3498db;
    color: #3498db;
}
h4 {
    border-left: 2px solid #F7DC6F;
    padding-left: 4px;
    color: #F7DC6F;
}
</style>\n""")
        md.write(f"# Todo List Export\n\n")
        md.write(f"Generated on: {date.today().strftime('%Y-%m-%d')}\n\n")
        
        md.write("Priority Level | Meaning\n")
        md.write(":--------------: | -------\n")
        for index, row in priorities.iterrows():
            md.write(f"<span style=\"color:{row['color']}\">{row['level']}</span> | {row['description']}\n")

        def write_category_headers(path, level=2):
            parts = [p.strip() for p in path.split('>')]
            for i, part in enumerate(parts, start=level):
                md.write("#" * (i+1) + f" {part}\n")
            md.write("\n")

        def sort_key(row):
            if pd.isna(row['due_date']):
                return date(9999, 12, 31)
            return row['due_date']
        
        def write_task_recursive(row, indent_level=0):
            indent = "  " * indent_level
            checkbox = "[x]" if row['current_status'] == 'Completed' else "[ ]"
            due = "TBD" if pd.isna(row['due_date']) else row['due_date'].strftime('%Y-%m-%d')
            pri = row['priority_level'] or "?"
            thr = row['threat_level'].capitalize() if row['threat_level'] else "None"
            status_note = f" | <span style=\"color:{status_colors[row['current_status']]}\">{row['current_status']}</span>"
            s = "~~" if row['current_status'] == "Cancelled" else ""
            md.write(f"{indent}- {s}{checkbox} **{row['title']}** (Due: {due} | Priority: <span style=\"color:{row['priority_color']}\">{pri}</span> | Threat: <span style=\"color:{row['threat_color']}\">{thr}</span>{status_note}){s}\n")
            
            if row['description'] and str(row['description']).strip():
                desc_lines = str(row['description']).strip().split('\n')
                for line in desc_lines:
                    md.write(f"{indent}- > {line.strip()}\n")
                md.write(f"{indent}\n")
            
            child_rows = children.get(row['id'], [])
            if child_rows:
                child_rows_sorted = sorted(child_rows, key=sort_key)
                md.write(f"{indent}  - *Next Steps*\n")
                for child in child_rows_sorted:
                    write_task_recursive(child, indent_level + 2)
        
        md.write("## Active Tasks\n\n")
        if not active_df.empty:
            for cat_id, group in active_df.groupby('category_id', sort=False):
                group = group.copy()
                if pd.isna(cat_id):
                    md.write("### Uncategorized\n\n")
                else:
                    path = cat_paths.get(cat_id, "Unknown Category")
                    write_category_headers(path)
                
                root_tasks = [r for _, r in group.iterrows() if pd.isna(r['parent_id'])]
                root_tasks_sorted = sorted(root_tasks, key=sort_key)
                
                for root in root_tasks_sorted:
                    write_task_recursive(root)
                md.write("\n")
        
        md.write("## Completed Tasks\n\n")
        if not completed_df.empty:
            for cat_id, group in completed_df.groupby('category_id', sort=False):
                group = group.copy()
                if pd.isna(cat_id):
                    md.write("### Uncategorized\n\n")
                else:
                    path = cat_paths.get(cat_id, "Unknown Category")
                    write_category_headers(path)
                
                root_tasks = [r for _, r in group.iterrows() if pd.isna(r['parent_id'])]
                root_tasks_sorted = sorted(root_tasks, key=sort_key)
                
                for root in root_tasks_sorted:
                    write_task_recursive(root)
                md.write("\n")
        else:
            md.write("_No completed tasks._\n\n")
        
        markdown_content = md.getvalue()
        
        with st.expander("Preview Markdown Export", expanded=True):
            st.code(markdown_content, language="markdown")
        
        st.download_button(
            label="📥 Download Markdown File",
            data=markdown_content,
            file_name=f"todo_export_{date.today().strftime('%Y%m%d')}.md",
            mime="text/markdown"
        )
st.caption("Export includes all tasks, sorted by due date, with descriptions and full category hierarchy.")

