## Project Structure

```text
project/
├── app.py
├── templates/
│   └── index.html
├── requirements.txt
└── README.md
```

---

## `app.py`

```python
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, g

DATABASE = 'todos.db'

app = Flask(__name__)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('CREATE TABLE IF NOT EXISTS todos (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0)')
        db.commit()

@app.route('/')
def index():
    db = get_db()
    todos = db.execute('SELECT * FROM todos ORDER BY id DESC').fetchall()
    return render_template('index.html', todos=todos)

@app.route('/add', methods=['POST'])
def add():
    title = request.form.get('title', '').strip()
    db = get_db()
    if title:
        db.execute('INSERT INTO todos (title, completed) VALUES (?, 0)', (title,))
        db.commit()
    return redirect(url_for('index'))

@app.route('/complete/<int:todo_id>', methods=['POST'])
def complete(todo_id):
    db = get_db()
    db.execute('UPDATE todos SET completed = CASE WHEN completed = 0 THEN 1 ELSE 0 END WHERE id = ?', (todo_id,))
    db.commit()
    return redirect(url_for('index'))

@app.route('/delete/<int:todo_id>', methods=['POST'])
def delete(todo_id):
    db = get_db()
    db.execute('DELETE FROM todos WHERE id = ?', (todo_id,))
    db.commit()
    return redirect(url_for('index'))

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
```

---

## `templates/index.html`

```html
<!DOCTYPE html>
<html lang='en'>
<head>
  <meta charset='UTF-8'>
  <meta name='viewport' content='width=device-width, initial-scale=1.0'>
  <title>Flask TODO</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: #f4f4f4;
      margin: 0;
      padding: 40px 16px;
    }
    .container {
      max-width: 560px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 12px;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
      padding: 24px;
    }
    h1 {
      margin-top: 0;
      text-align: center;
      color: #333333;
    }
    .add-form {
      display: flex;
      gap: 8px;
      margin-bottom: 24px;
    }
    input[type='text'] {
      flex: 1;
      padding: 10px 14px;
      border: 1px solid #dddddd;
      border-radius: 8px;
      font-size: 16px;
    }
    button {
      padding: 10px 16px;
      border: none;
      border-radius: 8px;
      background: #007bff;
      color: #ffffff;
      font-size: 16px;
      cursor: pointer;
    }
    button:hover {
      opacity: 0.9;
    }
    ul {
      list-style: none;
      padding: 0;
      margin: 0;
    }
    li {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px 8px;
      border-bottom: 1px solid #f0f0f0;
    }
    li:last-child {
      border-bottom: none;
    }
    li.completed .todo-title {
      text-decoration: line-through;
      color: #999999;
    }
    .todo-title {
      flex: 1;
      font-size: 18px;
      color: #333333;
      word-break: break-word;
    }
    form.inline {
      display: inline;
    }
    button.complete {
      background: #28a745;
    }
    button.delete {
      background: #dc3545;
    }
    .empty {
      text-align: center;
      color: #999999;
      padding: 20px 0;
    }
  </style>
</head>
<body>
  <div class='container'>
    <h1>TODO</h1>

    <form action='{{ url_for('add') }}' method='post' class='add-form'>
      <input type='text' name='title' placeholder='What needs to be done?' required autocomplete='off'>
      <button type='submit'>Add</button>
    </form>

    {% if todos %}
      <ul>
        {% for todo in todos %}
        <li class='{{ 'completed' if todo['completed'] else '' }}'>
          <span class='todo-title'>{{ todo['title'] }}</span>
          <form action='{{ url_for('complete', todo_id=todo['id']) }}' method='post' class='inline'>
            <button type='submit' class='complete'>{{ 'Undo' if todo['completed'] else 'Complete' }}</button>
          </form>
          <form action='{{ url_for('delete', todo_id=todo['id']) }}' method='post' class='inline' onsubmit="return confirm('Delete this todo?');">
            <button type='submit' class='delete'>Delete</button>
          </form>
        </li>
        {% endfor %}
      </ul>
    {% else %}
      <p class='empty'>No todos yet. Add one above!</p>
    {% endif %}
  </div>
</body>
</html>
```

---

## `requirements.txt`

```text
Flask==3.0.3
```

---

## `README.md`

````markdown
# Flask TODO App

A minimal Flask web application for managing a TODO list with SQLite persistence.

## Features

- Add new todos
- Mark todos complete / incomplete
- Delete todos
- Persistent storage using SQLite
- Clean, minimal, responsive UI

## Project Structure

```
.
├── app.py
├── templates/
│   └── index.html
├── requirements.txt
└── README.md
```

## Setup

1. Create and activate a virtual environment (optional but recommended):

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:

   ```bash
   python app.py
   ```

4. Open http://127.0.0.1:5000 in your browser.

## Database

The SQLite database file `todos.db` is created automatically on first run. The `todos` table contains `id`, `title`, and `completed` columns.
````