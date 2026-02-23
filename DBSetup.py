import sqlite3
from datetime import date


def setup_database(db_path="todo.db"):
    # Connect to the SQLite database
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # -----------------------------
    # 1. Priorities table
    # -----------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS priorities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level INTEGER UNIQUE NOT NULL,
        description TEXT NOT NULL,
        color TEXT NOT NULL
    )
    ''')

    cursor.executemany('''
    INSERT OR IGNORE INTO priorities (level, description, color) VALUES (?, ?, ?)
    ''', [
        (1, 'Very Low - No potential to cause raod blocks if not completed', '#00FF00'),    # Green
        (2, 'Low - Unlikely to cause road blocks if not completed', '#99FF00'),
        (3, 'Medium - Has low potential to cause road blocks if not completed', '#FFFF00'),     # Yellow
        (4, 'High - can cause road blocks if not finished', '#FF9900'),       # Orange
        (5, 'Very High - Will cause road blocks if not finished', '#FF0000')   # Red
    ])

    # -----------------------------
    # 2. Threats table
    # -----------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS threats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        level TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        color TEXT NOT NULL
    )
    ''')

    cursor.executemany('''
    INSERT OR IGNORE INTO threats (level, description, color) VALUES (?, ?, ?)
    ''', [
        ('low', 'Low Threat', '#00FF00'),
        ('medium', 'Medium Threat', '#FFFF00'),
        ('high', 'High Threat', '#FF0000')
    ])

    # -----------------------------
    # 3. Statuses table (lookup)
    # -----------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS statuses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT
    )
    ''')

    cursor.executemany('''
    INSERT OR IGNORE INTO statuses (name, description) VALUES (?,?)
    ''', [
        ('Not Started','Task has not been started'),
        ('In Progress','Task is currently being worked on'),
        ('Blocked','Task is waiting on dependencies'),
        ('Ongoing','Reoccuring task that will not complete'),
        ('Completed','Task has been successfully completed'),
        ('Cancelled','Task has been abandoned and will not be completed')
    ])

    # -----------------------------
    # 4. Categories table (recursive for sub-categories)
    # -----------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        parent_id INTEGER,
        FOREIGN KEY (parent_id) REFERENCES categories (id) ON DELETE SET NULL
    )
    ''')

    # Optional: Insert some example categories (uncomment if you want starters)
    """
    cursor.executemany('''
    INSERT OR IGNORE INTO categories (name, parent_id) VALUES (?, ?)
    ''', [
        ('Work', None),
        ('Personal', None),
        ('Health', None),
        ('Projects', None),
        ('Home', None),
    ])
    # Example sub-categories
    # cursor.execute("INSERT OR IGNORE INTO categories (name, parent_id) VALUES ('Meetings', (SELECT id FROM categories WHERE name='Work'))")
    """

    # -----------------------------
    # 5. Tasks table (now with category_id)
    # -----------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        due_date DATE,
        parent_id INTEGER,          -- for sub-tasks
        category_id INTEGER,        -- link to category (nullable)
        priority_id INTEGER,
        threat_id INTEGER,
        FOREIGN KEY (parent_id) REFERENCES tasks (id) ON DELETE CASCADE,
        FOREIGN KEY (category_id) REFERENCES categories (id) ON DELETE SET NULL,
        FOREIGN KEY (priority_id) REFERENCES priorities (id),
        FOREIGN KEY (threat_id) REFERENCES threats (id)
    )
    ''')

    # -----------------------------
    # 6. Task status history log
    # -----------------------------
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS task_status_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id INTEGER NOT NULL,
        status_id INTEGER NOT NULL,
        reason TEXT,
        extra_info TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE,
        FOREIGN KEY (status_id) REFERENCES statuses (id)
    )
    ''')

    # Commit and close
    conn.commit()
    conn.close()

    print("SQLite database 'todo.db' has been updated successfully!")
    print("Now includes a recursive 'categories' table and tasks can be assigned to a category.")

if __name__ == "__main__":
    setup_database()