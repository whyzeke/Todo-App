import sqlite3
import pandas as pd
from datetime import datetime, date
import streamlit as st

def get_db_path():
    """Return the current profile's DB path from session state."""
    return st.session_state.get("db_path", "todo.db")

def get_connection():
    db_path = get_db_path()

    def adapt_datetime_iso(val):
        return val.isoformat()

    def convert_datetime_iso(val):
        try:
            return datetime.fromisoformat(val.decode('utf-8'))
        except ValueError:
            return datetime.strptime(val.decode('utf-8'), '%Y-%m-%d %H:%M:%S')

    def adapt_date_iso(val):
        return val.isoformat()

    def convert_date_iso(val):
        return date.fromisoformat(val.decode('utf-8'))

    sqlite3.register_adapter(datetime, adapt_datetime_iso)
    sqlite3.register_adapter(date, adapt_date_iso)
    sqlite3.register_converter("timestamp", convert_datetime_iso)
    sqlite3.register_converter("datetime", convert_datetime_iso)
    sqlite3.register_converter("date", convert_date_iso)

    return sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)

def fetch_task_tree(selected_category_ids=None, show_completed=False):
    with get_connection() as conn:
        query = """
            SELECT 
                t.id, t.title, t.description, t.due_date, t.parent_id, t.category_id,
                c.name AS category_name,
                p.level AS priority_level, p.color AS priority_color,
                th.level AS threat_level, th.color AS threat_color
            FROM tasks t
            LEFT JOIN categories c ON t.category_id = c.id
            LEFT JOIN priorities p ON t.priority_id = p.id
            LEFT JOIN threats th ON t.threat_id = th.id
        """
        params = []
        conditions = []
        
        if selected_category_ids:
            placeholders = ','.join('?' for _ in selected_category_ids)
            conditions.append(f"t.category_id IN ({placeholders})")
            params.extend(selected_category_ids)
        
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        
        query += " ORDER BY t.id"
        
        df = pd.read_sql_query(query, conn, params=params)
    
    if not df.empty:
        df['current_status'] = df['id'].apply(get_current_status)
        df['num_subtasks'] = df['id'].apply(lambda tid: sum(1 for _, row in df.iterrows() if row['parent_id'] == tid))
        
        if not show_completed:
            df = df[(df['current_status'] != 'Completed') & (df['current_status'] != 'Cancelled')]
    
    return df

def get_current_status(task_id):
    with get_connection() as conn:
        result = conn.execute("""
            SELECT s.name 
            FROM task_status_logs tsl
            JOIN statuses s ON tsl.status_id = s.id
            WHERE tsl.task_id = ?
            ORDER BY tsl.timestamp DESC, tsl.id DESC
            LIMIT 1
        """, (task_id,)).fetchone()
        return result[0] if result else "Pending"

def fetch_status_history(task_id):
    with get_connection() as conn:
        return pd.read_sql_query("""
            SELECT 
                tsl.timestamp,
                s.name AS status,
                tsl.reason,
                tsl.extra_info
            FROM task_status_logs tsl
            JOIN statuses s ON tsl.status_id = s.id
            WHERE tsl.task_id = ?
            ORDER BY tsl.timestamp DESC
        """, conn, params=(task_id,))

def fetch_task_basics(task_id):
    with get_connection() as conn:
        return pd.read_sql_query("""
            SELECT 
                t.title,
                t.description,
                t.due_date,
                c.full_path AS category_path
            FROM tasks t
            LEFT JOIN (
                SELECT id, full_path FROM (
                    SELECT 
                        c.id,
                        GROUP_CONCAT(c2.name, ' > ') AS full_path
                    FROM categories c
                    LEFT JOIN categories c2 ON c2.id IN (
                        WITH RECURSIVE parents AS (
                            SELECT id, parent_id, name
                            FROM categories
                            WHERE id = c.id
                            UNION ALL
                            SELECT c3.id, c3.parent_id, c3.name
                            FROM categories c3
                            JOIN parents p ON c3.id = p.parent_id
                        )
                        SELECT id FROM parents
                    )
                    GROUP BY c.id
                )
            ) c ON t.category_id = c.id
            WHERE t.id = ?
        """, conn, params=(task_id,))

def insert_status_log(task_id, status_name, reason=None, extra_info=None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO task_status_logs (task_id, status_id, reason, extra_info)
            VALUES (?, (SELECT id FROM statuses WHERE name=?), ?, ?)
        """, (task_id, status_name, reason, extra_info))
        conn.commit()

def get_category_id(task_id):
    with get_connection() as conn:
        return pd.read_sql_query("SELECT t.category_id AS category_id FROM tasks t WHERE t.id == ?",conn, params=(task_id,))

def fetch_statuses():
    with get_connection() as conn:
        return pd.read_sql_query("SELECT id, name FROM statuses ORDER BY id", conn)

def build_task_hierarchy_for_tree(show_completed=False):
    """Fetch tasks for the tree, optionally filtering out Completed/Cancelled"""
    with get_connection() as conn:
        include_all = 1 if show_completed else 0
        
        query = """
        WITH latest_status AS (
            SELECT 
                tsl.task_id,
                COALESCE(s.name, 'Pending') AS status
            FROM (
                SELECT task_id, MAX(id) AS max_id 
                FROM task_status_logs 
                GROUP BY task_id
            ) latest_log
            LEFT JOIN task_status_logs tsl ON tsl.id = latest_log.max_id
            LEFT JOIN statuses s ON tsl.status_id = s.id
            UNION ALL
            SELECT t.id AS task_id, 'Pending' AS status
            FROM tasks t
            WHERE NOT EXISTS (SELECT 1 FROM task_status_logs WHERE task_id = t.id)
        )
        SELECT 
            t.id,
            t.title,
            t.parent_id,
            t.due_date,
            p.level AS priority_level,
            th.level AS threat_level
        FROM tasks t
        JOIN latest_status ls ON t.id = ls.task_id
        LEFT JOIN priorities p ON t.priority_id = p.id
        LEFT JOIN threats th ON t.threat_id = th.id
        WHERE ? = 1 OR ls.status NOT IN ('Completed', 'Cancelled')
        ORDER BY t.id
        """
        
        df = pd.read_sql_query(query, conn, params=(include_all,))
    
    if df.empty:
        return []
    
    children_map = {}
    for _, row in df.iterrows():
        parent = row['parent_id'] if pd.notna(row['parent_id']) else None
        if parent not in children_map:
            children_map[parent] = []
        children_map[parent].append(row.to_dict())
    
    def build_node(task_dict):
        task_id = task_dict['id']
        due = "TBD" if pd.isna(task_dict['due_date']) else task_dict['due_date'].strftime('%Y-%m-%d')
        pri = task_dict['priority_level'] or "?"
        thr = task_dict['threat_level'].capitalize() if task_dict['threat_level'] else "?"
        
        label = f"{task_dict['title']} | Due: {due} | P:{pri} | T:{thr}"
        
        node = {
            "id": str(task_id),
            "name": label
        }
        
        child_tasks = children_map.get(task_id, [])
        for child in child_tasks:
            if("children" not in node):
                node["children"] = [{"id": str(task_id),"name": "^This task"}]
            node["children"].append(build_node(child))
        
        return node
    
    root_tasks = children_map.get(None, [])
    tree_data = [build_node(task) for task in root_tasks]
    
    return tree_data

def get_task_details(task_id):
    """Fetch full details for quick actions"""
    with get_connection() as conn:
        df = pd.read_sql_query("""
            SELECT 
                t.*,
                p.level AS priority_level, p.description AS priority_desc, p.color AS priority_color,
                th.level AS threat_level, th.description AS threat_desc, th.color AS threat_color
            FROM tasks t
            LEFT JOIN priorities p ON t.priority_id = p.id
            LEFT JOIN threats th ON t.threat_id = th.id
            WHERE t.id = ?
        """, conn, params=(task_id,))
        if df.empty:
            return None
        return df.iloc[0]
