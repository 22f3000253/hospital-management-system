# backend/routes/auth.py
from flask import Blueprint, request, jsonify, session
from models import db, User, Doctor, Patient, Admin
from functools import wraps
from datetime import datetime

auth_bp = Blueprint('auth', __name__)

# Decorator for login required
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized access'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Decorator for role-based access
def role_required(roles):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                return jsonify({'error': 'Unauthorized access'}), 401
            
            user = User.query.get(session['user_id'])
            if not user or user.role not in roles:
                return jsonify({'error': 'Forbidden: Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Register endpoint for patients
@auth_bp.route('/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['username', 'email', 'password', 'name', 'phone']
        for field in required_fields:
            if field not in data or not data[field]:
                return jsonify({'error': f'{field} is required'}), 400
        
        # Check if username already exists
        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 400
        
        # Check if email already exists
        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 400
        
        # Create user
        user = User(
            username=data['username'],
            email=data['email'],
            role='patient'
        )
        user.set_password(data['password'])
        db.session.add(user)
        db.session.flush()  # Get user.id
        
        # Create patient profile
        patient = Patient(
            user_id=user.id,
            name=data['name'],
            phone=data['phone'],
            age=data.get('age'),
            gender=data.get('gender'),
            address=data.get('address'),
            blood_group=data.get('blood_group'),
            emergency_contact=data.get('emergency_contact')
        )
        db.session.add(patient)
        db.session.commit()
        
        return jsonify({
            'message': 'Registration successful',
            'user': user.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Login endpoint
@auth_bp.route('/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        
        # Validate required fields
        if not data.get('username') or not data.get('password'):
            return jsonify({'error': 'Username and password are required'}), 400
        
        # Find user
        user = User.query.filter_by(username=data['username']).first()
        
        # Verify user and password
        if not user or not user.check_password(data['password']):
            return jsonify({'error': 'Invalid username or password'}), 401
        
        # Check if user is active
        if not user.is_active:
            return jsonify({'error': 'Account is deactivated. Please contact admin.'}), 403
        
        # Create session
        session['user_id'] = user.id
        session['username'] = user.username
        session['role'] = user.role
        
        # Get profile data based on role
        profile_data = None
        if user.role == 'admin':
            admin = Admin.query.filter_by(user_id=user.id).first()
            profile_data = admin.to_dict() if admin else None
        elif user.role == 'doctor':
            doctor = Doctor.query.filter_by(user_id=user.id).first()
            profile_data = doctor.to_dict() if doctor else None
        elif user.role == 'patient':
            patient = Patient.query.filter_by(user_id=user.id).first()
            profile_data = patient.to_dict() if patient else None
        
        return jsonify({
            'message': 'Login successful',
            'user': user.to_dict(),
            'profile': profile_data
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Logout endpoint
@auth_bp.route('/logout', methods=['POST'])
@login_required
def logout():
    session.clear()
    return jsonify({'message': 'Logout successful'}), 200

# Get current user endpoint
@auth_bp.route('/me', methods=['GET'])
@login_required
def get_current_user():
    try:
        user = User.query.get(session['user_id'])
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get profile data based on role
        profile_data = None
        if user.role == 'admin':
            admin = Admin.query.filter_by(user_id=user.id).first()
            profile_data = admin.to_dict() if admin else None
        elif user.role == 'doctor':
            doctor = Doctor.query.filter_by(user_id=user.id).first()
            profile_data = doctor.to_dict() if doctor else None
        elif user.role == 'patient':
            patient = Patient.query.filter_by(user_id=user.id).first()
            profile_data = patient.to_dict() if patient else None
        
        return jsonify({
            'user': user.to_dict(),
            'profile': profile_data
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Check authentication status
@auth_bp.route('/check', methods=['GET'])
def check_auth():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            return jsonify({
                'authenticated': True,
                'user': user.to_dict()
            }), 200
    
    return jsonify({'authenticated': False}), 200