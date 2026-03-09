from flask import Blueprint, request, jsonify, session, current_app
from models import db, User, Doctor, Patient, Appointment, Department
from routes.auth import login_required, role_required
from datetime import datetime
from sqlalchemy import or_

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/dashboard', methods=['GET'])
@login_required
@role_required(['admin'])
def get_dashboard():
    try:
        cache = current_app.cache
        data = cache.get('admin_dashboard')
        if data:
            return jsonify(data), 200

        total_doctors = Doctor.query.join(Doctor.user).filter(User.is_active == True).count()
        total_patients = Patient.query.join(Patient.user).filter(User.is_active == True).count()
        total_appointments = Appointment.query.count()
        total_departments = Department.query.count()

        recent_appointments = Appointment.query.order_by(
            Appointment.appointment_date.desc(),
            Appointment.appointment_time.desc()
        ).limit(10).all()

        active_doctors = Doctor.query.join(Doctor.user).filter(
            User.is_active == True
        ).limit(10).all()

        data = {
            'total_doctors': total_doctors,
            'total_patients': total_patients,
            'total_appointments': total_appointments,
            'total_departments': total_departments,
            'recent_appointments': [apt.to_dict() for apt in recent_appointments],
            'active_doctors': [doc.to_dict() for doc in active_doctors]
        }
        cache.set('admin_dashboard', data, timeout=120)
        return jsonify(data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/doctors', methods=['GET'])
@login_required
@role_required(['admin'])
def get_doctors():
    try:
        cache = current_app.cache
        data = cache.get('admin_doctors')
        if data:
            return jsonify(data), 200
        doctors = Doctor.query.join(Doctor.user).filter(User.is_active == True).all()
        data = {'doctors': [d.to_dict() for d in doctors]}
        cache.set('admin_doctors', data, timeout=180)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/doctors', methods=['POST'])
@login_required
@role_required(['admin'])
def add_doctor():
    try:
        data = request.get_json()
        required_fields = ['username', 'email', 'password', 'name', 'specialization', 'department_id', 'phone']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        if User.query.filter_by(username=data['username']).first():
            return jsonify({'error': 'Username already exists'}), 400

        if User.query.filter_by(email=data['email']).first():
            return jsonify({'error': 'Email already exists'}), 400

        if not Department.query.get(data['department_id']):
            return jsonify({'error': 'Department not found'}), 404

        user = User(username=data['username'], email=data['email'], role='doctor', is_active=True)
        user.set_password(data['password'])
        db.session.add(user)
        db.session.flush()

        doctor = Doctor(
            user_id=user.id,
            name=data['name'],
            specialization=data['specialization'],
            department_id=data['department_id'],
            phone=data['phone'],
            qualification=data.get('qualification', ''),
            experience_years=data.get('experience_years', 0),
            consultation_fee=data.get('consultation_fee', 0.0)
        )
        db.session.add(doctor)
        db.session.commit()

        current_app.cache.delete('admin_doctors')
        current_app.cache.delete('admin_dashboard')

        return jsonify({'message': 'Doctor added successfully', 'doctor': doctor.to_dict()}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/doctors/<int:doctor_id>', methods=['PUT'])
@login_required
@role_required(['admin'])
def update_doctor(doctor_id):
    try:
        doctor = Doctor.query.get(doctor_id)
        if not doctor:
            return jsonify({'error': 'Doctor not found'}), 404

        data = request.get_json()

        if 'name' in data:
            doctor.name = data['name']
        if 'specialization' in data:
            doctor.specialization = data['specialization']
        if 'department_id' in data:
            if not Department.query.get(data['department_id']):
                return jsonify({'error': 'Department not found'}), 404
            doctor.department_id = data['department_id']
        if 'phone' in data:
            doctor.phone = data['phone']
        if 'qualification' in data:
            doctor.qualification = data['qualification']
        if 'experience_years' in data:
            doctor.experience_years = data['experience_years']
        if 'consultation_fee' in data:
            doctor.consultation_fee = data['consultation_fee']

        if 'email' in data and data['email'] != doctor.user.email:
            existing = User.query.filter_by(email=data['email']).first()
            if existing and existing.id != doctor.user_id:
                return jsonify({'error': 'Email already in use'}), 400
            doctor.user.email = data['email']

        db.session.commit()
        current_app.cache.delete('admin_doctors')
        current_app.cache.delete('admin_dashboard')

        return jsonify({'message': 'Doctor updated successfully', 'doctor': doctor.to_dict()}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/doctors/<int:doctor_id>', methods=['DELETE'])
@login_required
@role_required(['admin'])
def delete_doctor(doctor_id):
    try:
        doctor = Doctor.query.get(doctor_id)
        if not doctor:
            return jsonify({'error': 'Doctor not found'}), 404

        doctor.user.is_active = False
        db.session.commit()
        current_app.cache.delete('admin_doctors')
        current_app.cache.delete('admin_dashboard')

        return jsonify({'message': 'Doctor deactivated successfully'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/patients', methods=['GET'])
@login_required
@role_required(['admin'])
def get_patients():
    try:
        cache = current_app.cache
        data = cache.get('admin_patients')
        if data:
            return jsonify(data), 200
        patients = Patient.query.join(Patient.user).filter(User.is_active == True).all()
        data = {'patients': [p.to_dict() for p in patients]}
        cache.set('admin_patients', data, timeout=180)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/patients/<int:patient_id>', methods=['PUT'])
@login_required
@role_required(['admin'])
def update_patient(patient_id):
    try:
        patient = Patient.query.get(patient_id)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404

        data = request.get_json()

        if 'name' in data:
            patient.name = data['name']
        if 'age' in data:
            patient.age = data['age']
        if 'gender' in data:
            patient.gender = data['gender']
        if 'phone' in data:
            patient.phone = data['phone']
        if 'address' in data:
            patient.address = data['address']
        if 'blood_group' in data:
            patient.blood_group = data['blood_group']
        if 'emergency_contact' in data:
            patient.emergency_contact = data['emergency_contact']

        if 'email' in data and data['email'] != patient.user.email:
            existing = User.query.filter_by(email=data['email']).first()
            if existing and existing.id != patient.user_id:
                return jsonify({'error': 'Email already in use'}), 400
            patient.user.email = data['email']

        db.session.commit()
        current_app.cache.delete('admin_patients')

        return jsonify({'message': 'Patient updated successfully', 'patient': patient.to_dict()}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/patients/<int:patient_id>', methods=['DELETE'])
@login_required
@role_required(['admin'])
def delete_patient(patient_id):
    try:
        patient = Patient.query.get(patient_id)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404

        patient.user.is_active = False
        db.session.commit()
        current_app.cache.delete('admin_patients')
        current_app.cache.delete('admin_dashboard')

        return jsonify({'message': 'Patient deactivated successfully'}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/appointments', methods=['GET'])
@login_required
@role_required(['admin'])
def get_appointments():
    try:
        appointments = Appointment.query.order_by(
            Appointment.appointment_date.desc(),
            Appointment.appointment_time.desc()
        ).all()
        return jsonify({'appointments': [apt.to_dict() for apt in appointments]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/departments', methods=['GET'])
@login_required
@role_required(['admin'])
def get_departments():
    try:
        departments = Department.query.all()
        departments_data = []
        for dept in departments:
            d = dept.to_dict()
            d['doctors_count'] = Doctor.query.join(Doctor.user).filter(
                Doctor.department_id == dept.id,
                User.is_active == True
            ).count()
            departments_data.append(d)
        return jsonify({'departments': departments_data}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/departments', methods=['POST'])
@login_required
@role_required(['admin'])
def add_department():
    try:
        data = request.get_json()
        if 'name' not in data:
            return jsonify({'error': 'Department name is required'}), 400

        if Department.query.filter_by(name=data['name']).first():
            return jsonify({'error': 'Department already exists'}), 400

        department = Department(name=data['name'], description=data.get('description', ''))
        db.session.add(department)
        db.session.commit()
        current_app.cache.delete('admin_departments')
        current_app.cache.delete('admin_dashboard')

        return jsonify({'message': 'Department added successfully', 'department': department.to_dict()}), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/search/doctors', methods=['GET'])
@login_required
@role_required(['admin'])
def search_doctors():
    try:
        query = request.args.get('q', '').strip()
        if not query:
            doctors = Doctor.query.join(Doctor.user).filter(User.is_active == True).all()
        else:
            doctors = Doctor.query.join(Doctor.user).filter(
                User.is_active == True,
                or_(
                    Doctor.name.ilike(f'%{query}%'),
                    Doctor.specialization.ilike(f'%{query}%')
                )
            ).all()
        return jsonify({'doctors': [d.to_dict() for d in doctors]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/search/patients', methods=['GET'])
@login_required
@role_required(['admin'])
def search_patients():
    try:
        query = request.args.get('q', '').strip()
        if not query:
            patients = Patient.query.join(Patient.user).filter(User.is_active == True).all()
        else:
            patients = Patient.query.join(Patient.user).filter(
                User.is_active == True,
                or_(
                    Patient.name.ilike(f'%{query}%'),
                    Patient.phone.ilike(f'%{query}%'),
                    User.email.ilike(f'%{query}%'),
                    Patient.id == (int(query) if query.isdigit() else -1)
                )
            ).all()
        return jsonify({'patients': [p.to_dict() for p in patients]}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500