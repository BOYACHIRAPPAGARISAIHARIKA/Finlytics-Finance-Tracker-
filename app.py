from flask import Flask, render_template, request, jsonify, session, g
import sqlite3
import os
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta

BASE_DIR = Path(__file__).resolve().parent
DATABASE = os.path.join(BASE_DIR, 'finance.db')
app = Flask(__name__, static_folder='static', template_folder='templates')
app.secret_key = os.environ.get('FLASK_SECRET', 'change-me-in-prod')
app.permanent_session_lifetime = timedelta(days=7)

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
        db.row_factory = sqlite3.Row
    return db

def init_db():
    db = get_db()
    cur = db.cursor()
    cur.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );
    ''')
    cur.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_email TEXT NOT NULL,
        type TEXT NOT NULL,
        date TEXT NOT NULL,
        amount REAL NOT NULL,
        category TEXT NOT NULL,
        categoryName TEXT
    );
    ''')
    db.commit()

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# Serve frontend
@app.route('/')
def index():
    return render_template('index.html')

# Auth endpoints
@app.route('/api/register', methods=['POST'])
def register():
    data = request.json or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error':'missing fields'}), 400
    db = get_db()
    try:
        hashed = generate_password_hash(password)
        db.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, hashed))
        db.commit()
    except sqlite3.IntegrityError:
        return jsonify({'error':'user exists'}), 400
    session.permanent = True
    session['user_email'] = email
    return jsonify({'ok': True, 'email': email})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error':'missing fields'}), 400
    db = get_db()
    row = db.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
    if not row or not check_password_hash(row['password'], password):
        return jsonify({'error':'invalid credentials'}), 401
    session.permanent = True
    session['user_email'] = email
    return jsonify({'ok': True, 'email': email})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_email', None)
    return jsonify({'ok': True})

def require_user():
    user_email = session.get('user_email') or request.args.get('user_email')
    return user_email

@app.route('/api/transactions', methods=['GET', 'POST'])
def transactions():
    user_email = require_user()
    if not user_email:
        return jsonify({'error':'not authenticated'}), 401
    db = get_db()
    if request.method == 'GET':
        rows = db.execute('SELECT id, user_email, type, date, amount, category, categoryName FROM transactions WHERE user_email=? ORDER BY date DESC', (user_email,)).fetchall()
        txs = [dict(r) for r in rows]
        return jsonify(txs)
    else:
        data = request.json or {}
        ttype = data.get('type')
        date = data.get('date')
        amount = data.get('amount')
        category = data.get('category')
        categoryName = data.get('categoryName') or category
        if not all([ttype, date, amount, category]):
            return jsonify({'error':'missing fields'}), 400
        cur = db.execute('INSERT INTO transactions (user_email, type, date, amount, category, categoryName) VALUES (?,?,?,?,?,?)',
                   (user_email, ttype, date, float(amount), category, categoryName))
        db.commit()
        new_id = cur.lastrowid
        return jsonify({'ok': True, 'id': new_id})

@app.route('/api/transactions/<int:tx_id>', methods=['DELETE'])
def delete_transaction(tx_id):
    user_email = require_user()
    if not user_email:
        return jsonify({'error':'not authenticated'}), 401
    db = get_db()
    db.execute('DELETE FROM transactions WHERE id=? AND user_email=?', (tx_id, user_email))
    db.commit()
    return jsonify({'ok': True})

@app.route('/api/setup_demo', methods=['POST'])
def setup_demo():
    db = get_db()
    try:
        hashed = generate_password_hash('1234')
        db.execute('INSERT INTO users (email, password) VALUES (?, ?)', ('harika', hashed))
    except sqlite3.IntegrityError:
        pass
    cur = db.execute('SELECT COUNT(*) as c FROM transactions WHERE user_email=?', ('harika',))
    if cur.fetchone()['c'] == 0:
        demo = [
            ('harika','income','2025-08-01',4000.00,'gifts','Gifts'),
            ('harika','expense','2025-07-04',1700.00,'food','Food'),
            ('harika','income','2025-05-19',56000.00,'business','Business'),
        ]
        db.executemany('INSERT INTO transactions (user_email, type, date, amount, category, categoryName) VALUES (?,?,?,?,?,?)', demo)
        db.commit()
    return jsonify({'ok': True})

if __name__ == '__main__':
    if not os.path.exists(os.path.join(os.path.dirname(__file__), 'finance.db')):
        open(os.path.join(os.path.dirname(__file__), 'finance.db'), 'a').close()
    with app.app_context():
        init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
