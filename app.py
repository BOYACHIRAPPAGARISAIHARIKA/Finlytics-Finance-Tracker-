import os
from flask import Flask, render_template, request, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta, datetime
from flask_cors import CORS
import random
from marshmallow import Schema, fields, validate

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app, supports_credentials=True)  # Enable CORS with cookie/session support

# Secret key for sessions
app.secret_key = os.environ.get('FLASK_SECRET', 'change-me-in-prod')
app.permanent_session_lifetime = timedelta(days=7)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Configure database URI (Postgres on Render or SQLite locally)
DATABASE_URL = os.getenv('DATABASE_URL')
if DATABASE_URL:
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'finance.db')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(256), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_email = db.Column(db.String(256), db.ForeignKey('user.email'), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    date = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    category = db.Column(db.String(100), nullable=False)
    categoryName = db.Column(db.String(100))

# Input validation schema
class TransactionSchema(Schema):
    type = fields.Str(required=True, validate=validate.OneOf(["income", "expense"]))
    date = fields.Str(required=True)
    amount = fields.Float(required=True, validate=validate.Range(min=0))
    category = fields.Str(required=True)
    categoryName = fields.Str()

# Helper: get user email from session or query param
def require_user():
    user_email = session.get('user_email') or request.args.get('user_email')
    return user_email

# Custom error handler for 404 errors
@app.errorhandler(404)
def not_found(error):
    return jsonify({'error': 'not found'}), 404

# Routes

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'missing fields'}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'user exists'}), 400

    hashed = generate_password_hash(password)
    user = User(email=email, password=hashed)
    db.session.add(user)
    db.session.commit()

    session.permanent = True
    session['user_email'] = email
    return jsonify({'ok': True, 'email': email})

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''
    if not email or not password:
        return jsonify({'error': 'missing fields'}), 400

    user = User.query.filter_by(email=email).first()
    if not user or not check_password_hash(user.password, password):
        return jsonify({'error': 'invalid credentials'}), 401

    session.permanent = True
    session['user_email'] = email
    return jsonify({'ok': True, 'email': email})

@app.route('/api/logout', methods=['POST'])
def logout():
    session.pop('user_email', None)
    return jsonify({'ok': True})

@app.route('/api/transactions', methods=['GET', 'POST'])
def transactions():
    user_email = require_user()
    if not user_email:
        return jsonify({'error': 'not authenticated'}), 401

    if request.method == 'GET':
        txs = Transaction.query.filter_by(user_email=user_email).order_by(Transaction.date.desc()).all()
        result = [{
            'id': tx.id,
            'user_email': tx.user_email,
            'type': tx.type,
            'date': tx.date,
            'amount': tx.amount,
            'category': tx.category,
            'categoryName': tx.categoryName or tx.category
        } for tx in txs]
        return jsonify(result)

    # POST to add transaction
    schema = TransactionSchema()
    errors = schema.validate(request.json)
    if errors:
        return jsonify(errors), 400

    data = request.json
    ttype = data['type']
    date = data['date']
    amount = data['amount']
    category = data['category']
    categoryName = data.get('categoryName') or category

    tx = Transaction(
        user_email=user_email,
        type=ttype,
        date=date,
        amount=amount,
        category=category,
        categoryName=categoryName
    )
    db.session.add(tx)
    db.session.commit()

    return jsonify({'ok': True, 'id': tx.id})

@app.route('/api/transactions/<int:tx_id>', methods=['DELETE'])
def delete_transaction(tx_id):
    user_email = require_user()
    if not user_email:
        return jsonify({'error': 'not authenticated'}), 401

    tx = Transaction.query.filter_by(id=tx_id, user_email=user_email).first()
    if not tx:
        return jsonify({'error': 'transaction not found'}), 404

    db.session.delete(tx)
    db.session.commit()
    return jsonify({'ok': True})

@app.route('/api/setup_demo', methods=['POST'])
def setup_demo():
    demo_email = 'harika'
    demo_password = '1234'

    if not User.query.filter_by(email=demo_email).first():
        user = User(email=demo_email, password=generate_password_hash(demo_password))
        db.session.add(user)
        db.session.commit()

    tx_count = Transaction.query.filter_by(user_email=demo_email).count()
    if tx_count == 0:
        demo_data = []
        start_date = datetime(2020, 6, 1)  # Around week 24 of 2020
        end_date = datetime(2025, 8, 31)
        categories = ['food', 'rent', 'salary', 'investment', 'shopping', 'travel', 'gifts', 'business', 'utilities']
        types = ['income', 'expense']

        for _ in range(45):
            # Generate a random date between start_date and end_date but only within weeks 24-32
            while True:
                random_days = random.randint(0, (end_date - start_date).days)
                random_date = start_date + timedelta(days=random_days)
                week_number = random_date.isocalendar()[1]
                if 24 <= week_number <= 32:
                    break

            tx_date = random_date.strftime('%Y-%m-%d')
            tx_type = random.choice(types)
            amount = round(random.uniform(10, 5000), 2)
            category = random.choice(categories)

            demo_data.append(Transaction(
                user_email=demo_email,
                type=tx_type,
                date=tx_date,
                amount=amount,
                category=category,
                categoryName=category.capitalize()
            ))

        db.session.bulk_save_objects(demo_data)
        db.session.commit()

    return jsonify({'ok': True})

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(host='0.0.0.0', port=5000, debug=True)
