from flask import Flask, render_template, request, jsonify, session, g
import sqlite3
import os
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
import logging

# --- Configuration ---
BASE_DIR = Path(__file__).resolve().parent
DATABASE = os.path.join(BASE_DIR, 'finance.db')
app = Flask(__name__, static_folder='static', template_folder='templates')

# IMPORTANT: Change this to a strong, random secret key in production!
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'your_super_secret_key_here_replace_me_in_prod')
app.permanent_session_lifetime = timedelta(days=7)

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO)

# --- Database Functions ---
def get_db():
    """Establishes a database connection or returns the existing one."""
    try:
        db = getattr(g, '_database', None)
        if db is None:
            db = g._database = sqlite3.connect(DATABASE, check_same_thread=False)
            db.row_factory = sqlite3.Row  # This makes rows behave like dictionaries
        return db
    except sqlite3.Error as e:
        logging.error(f"Database connection error: {e}")
        return None  # Or handle it as needed

def init_db():
    """Initializes the database schema."""
    with app.app_context():  # Ensure we are in app context for db operations
        db = get_db()
        cur = db.cursor()
        # Create users table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
        ''')
        # Create transactions table
        cur.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            type TEXT NOT NULL,
            date TEXT NOT NULL,
            amount REAL NOT NULL,
            category TEXT NOT NULL,
            categoryName TEXT,
            FOREIGN KEY (user_email) REFERENCES users (email)
        );
        ''')
        db.commit()
    logging.info("Database initialized successfully.")

@app.teardown_appcontext
def close_connection(exception):
    """Closes the database connection at the end of the request."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

# --- Helper for Authentication ---
def require_user():
    """
    Checks if a user is authenticated via session.
    Returns the user's email if authenticated, otherwise None.
    """
    user_email = session.get('user_email')
    if not user_email:
        return None  # Return None if user is not authenticated
    return user_email

# --- Frontend Route ---
@app.route('/')
def index():
    """Serves the main HTML page."""
    return render_template('index.html')

# --- API Endpoints ---

@app.route('/api/register', methods=['POST'])
def register():
    """Handles user registration."""
    data = request.json
    if not data:
        return jsonify({'error': 'Request must be JSON'}), 400

    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    db = get_db()
    try:
        hashed_password = generate_password_hash(password)
        db.execute('INSERT INTO users (email, password) VALUES (?, ?)', (email, hashed_password))
        db.commit()
        session.permanent = True
        session['user_email'] = email
        logging.info(f"User  registered: {email}")
        return jsonify({'ok': True, 'email': email}), 201  # 201 Created
    except sqlite3.IntegrityError:
        return jsonify({'error': 'User  with this email already exists'}), 409  # 409 Conflict
    except Exception as e:
        logging.error(f"Error during registration: {e}")
        return jsonify({'error': 'An unexpected error occurred during registration'}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """Handles user login."""
    data = request.json
    if not data:
        return jsonify({'error': 'Request must be JSON'}), 400

    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'error': 'Email and password are required'}), 400

    db = get_db()
    user = db.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()

    if user and check_password_hash(user['password'], password):
        session.permanent = True
        session['user_email'] = email
        logging.info(f"User  logged in: {email}")
        return jsonify({'ok': True, 'email': email}), 200  # 200 OK
    else:
        return jsonify({'error': 'Invalid email or password'}), 401  # 401 Unauthorized

@app.route('/api/logout', methods=['POST'])
def logout():
    """Handles user logout."""
    session.pop('user_email', None)
    logging.info("User  logged out.")
    return jsonify({'ok': True}), 200

@app.route('/api/transactions', methods=['GET', 'POST'])
def transactions():
    """
    Handles fetching all transactions for the authenticated user (GET)
    and adding a new transaction (POST).
    """
    user_email = require_user()
    if user_email is None:
        return jsonify({'error': 'Not authenticated'}), 401

    db = get_db()

    if request.method == 'GET':
        rows = db.execute(
            'SELECT id, user_email, type, date, amount, category, categoryName FROM transactions WHERE user_email = ? ORDER BY date DESC',
            (user_email,)
        ).fetchall()
        transactions_list = [dict(row) for row in rows]
        return jsonify(transactions_list), 200

    elif request.method == 'POST':
        data = request.json
        if not data:
            return jsonify({'error': 'Request must be JSON'}), 400

        ttype = data.get('type')
        date = data.get('date')
        amount = data.get('amount')
        category = data.get('category')
        category_name = data.get('categoryName')  # HTML sends categoryName, use it directly

        if not all([ttype, date, amount, category]):
            return jsonify({'error': 'Missing required transaction fields'}), 400

        try:
            amount = float(amount)  # Ensure amount is a float
        except ValueError:
            return jsonify({'error': 'Amount must be a valid number'}), 400

        try:
            cursor = db.execute(
                'INSERT INTO transactions (user_email, type, date, amount, category, categoryName) VALUES (?, ?, ?, ?, ?, ?)',
                (user_email, ttype, date, amount, category, category_name)
            )
            db.commit()
            new_id = cursor.lastrowid
            return jsonify({'ok': True, 'id': new_id}), 201  # 201 Created
        except Exception as e:
            logging.error(f"Error adding transaction: {e}")
            return jsonify({'error': 'An unexpected error occurred while adding transaction'}), 500

@app.route('/api/transactions/<int:tx_id>', methods=['DELETE'])
def delete_transaction(tx_id):
    """Handles deleting a specific transaction by ID."""
    user_email = require_user()
    if not user_email:
        return jsonify({'error': 'Not authenticated'}), 401

    db = get_db()
    cursor = db.execute('DELETE FROM transactions WHERE id = ? AND user_email = ?', (tx_id, user_email))
    db.commit()

    if cursor.rowcount == 0:
        return jsonify({'error': 'Transaction not found or not authorized to delete'}), 404  # 404 Not Found
    else:
        return jsonify({'ok': True}), 200

@app.route('/api/setup_demo', methods=['POST'])
def setup_demo():
    """
    Sets up a demo user and some initial transactions.
    This is for convenience and should be removed or protected in production.
    """
    db = get_db()
    try:
        # Add demo user 'harika' if not exists
        hashed_password = generate_password_hash('1234')
        db.execute('INSERT INTO users (email, password) VALUES (?, ?)', ('harika', hashed_password))
        db.commit()
    except sqlite3.IntegrityError:
        # User 'harika' already exists
        pass

    # Add demo transactions for 'harika' if none exist
    cur = db.execute('SELECT COUNT(*) as c FROM transactions WHERE user_email = ?', ('harika',)).fetchone()
    if cur['c'] == 0:
        demo_transactions = [
            { "type": "income", "date": "2020-01-10", "amount": "52000.00", "category": "salary", "categoryName": "Salary" },
            { "type": "expense", "date": "2020-03-15", "amount": "1800.00", "category": "transport", "categoryName": "Transport" },
            { "type": "income", "date": "2021-06-18", "amount": "15000.00", "category": "business", "categoryName": "Business" },
            { "type": "expense", "date": "2022-02-08", "amount": "7000.00", "category": "housing", "categoryName": "Housing" },
            { "type": "expense", "date": "2023-08-12", "amount": "1200.00", "category": "food", "categoryName": "Food" },
            { "type": "income", "date": "2024-11-25", "amount": "10000.00", "category": "investment", "categoryName": "Investment" },
            { "type": "expense", "date": "2025-01-05", "amount": "900.00", "category": "entertainment", "categoryName": "Entertainment" },
            { "type": "income", "date": "2025-02-14", "amount": "48000.00", "category": "salary", "categoryName": "Salary" },
            { "type": "expense", "date": "2025-03-22", "amount": "650.00", "category": "shopping", "categoryName": "Shopping" },
            { "type": "expense", "date": "2025-04-11", "amount": "2000.00", "category": "health", "categoryName": "Health" },
            { "type": "income", "date": "2025-05-19", "amount": "56000.00", "category": "business", "categoryName": "Business" },
            { "type": "expense", "date": "2025-06-27", "amount": "1200.00", "category": "education", "categoryName": "Education" },
            { "type": "expense", "date": "2025-07-04", "amount": "1700.00", "category": "food", "categoryName": "Food" },
            { "type": "income", "date": "2025-08-01", "amount": "4000.00", "category": "gifts", "categoryName": "Gifts" },
            { "type": "expense", "date": "2025-06-17", "amount": "1300.00", "category": "shopping", "categoryName": "Shopping" },
            { "type": "income", "date": "2025-06-24", "amount": "52000.00", "category": "salary", "categoryName": "Salary" },
            { "type": "expense", "date": "2025-07-01", "amount": "3000.00", "category": "health", "categoryName": "Health" },
            { "type": "expense", "date": "2025-07-08", "amount": "1800.00", "category": "education", "categoryName": "Education" },
            { "type": "income", "date": "2025-07-15", "amount": "6000.00", "category": "gifts", "categoryName": "Gifts" },
            { "type": "expense", "date": "2025-07-22", "amount": "950.00", "category": "transport", "categoryName": "Transport" },
            { "type": "income", "date": "2025-07-29", "amount": "10000.00", "category": "other-income", "categoryName": "Other" },
            { "type": "expense", "date": "2025-08-05", "amount": "1350.00", "category": "entertainment", "categoryName": "Entertainment" }
        ]

        for transaction in demo_transactions:
            db.execute(
                'INSERT INTO transactions (user_email, type, date, amount, category, categoryName) VALUES (?, ?, ?, ?, ?, ?)',
                ('harika', transaction['type'], transaction['date'], transaction['amount'], transaction['category'], transaction['categoryName'])
            )
        db.commit()
        logging.info("Demo data for 'harika' added.")
    else:
        logging.info("Demo data for 'harika' already exists.")

    return jsonify({'ok': True}), 200

# --- Main Execution ---
if __name__ == '__main__':
    # Initialize the database if it doesn't exist
    if not os.path.exists(DATABASE):
        logging.info(f"Database file '{DATABASE}' not found. Creating and initializing...")
        # Create an empty file first
        open(DATABASE, 'a').close()
        init_db()
    else:
        logging.info(f"Database file '{DATABASE}' found. Ensuring schema is up-to-date...")
        init_db()  # Still run init_db to ensure tables exist if db file was empty

    # Run the Flask app
    app.run(host='0.0.0.0', port=5000, debug=True)
