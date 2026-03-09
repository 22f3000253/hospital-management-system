from flask import Blueprint, request, jsonify, session, current_app
from models import db, User, Doctor, Patient, Appointment, Treatment, Department, DoctorAvailability
from routes.auth import login_required, role_required
from datetime import datetime, date, timedelta
from sqlalchemy import or_

patient_bp = Blueprint('patient', __name__)


@patient_bp.route('/dashboard', methods=['GET'])
@login_required
@role_required(['patient'])
def get_dashboard():
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

        upcoming_appointments = Appointment.query.filter(
            Appointment.patient_id == patient.id,
            Appointment.status == 'Booked',
            Appointment.appointment_date >= date.today()
        ).order_by(Appointment.appointment_date, Appointment.appointment_time).limit(5).all()

        recent_appointments = Appointment.query.filter(
            Appointment.patient_id == patient.id
        ).order_by(Appointment.appointment_date.desc()).limit(5).all()

        departments_count = Department.query.count()
        total_appointments = Appointment.query.filter_by(patient_id=patient.id).count()

        return jsonify({
            'patient': patient.to_dict(),
            'upcoming_appointments': [apt.to_dict() for apt in upcoming_appointments],
            'recent_appointments': [apt.to_dict() for apt in recent_appointments],
            'departments_count': departments_count,
            'total_appointments': total_appointments
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/departments', methods=['GET'])
@login_required
@role_required(['patient'])
def get_departments():
    try:
        departments = Department.query.all()
        dept_list = []
        for dept in departments:
            d = dept.to_dict()
            d['doctors_count'] = Doctor.query.join(Doctor.user).filter(
                Doctor.department_id == dept.id,
                User.is_active == True
            ).count()
            dept_list.append(d)
        return jsonify({'departments': dept_list}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/doctors', methods=['GET'])
@login_required
@role_required(['patient'])
def get_doctors():
    try:
        department_id = request.args.get('department_id')
        cache_key = f'patient_doctors_{department_id or "all"}'
        cache = current_app.cache

        data = cache.get(cache_key)
        if data:
            return jsonify(data), 200

        query = Doctor.query.join(Doctor.user).filter(User.is_active == True)
        if department_id:
            query = query.filter(Doctor.department_id == department_id)

        doctors = query.all()
        data = {'doctors': [d.to_dict() for d in doctors]}
        cache.set(cache_key, data, timeout=180)
        return jsonify(data), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/doctors/search', methods=['GET'])
@login_required
@role_required(['patient'])
def search_doctors():
    try:
        query = request.args.get('q', '').strip()
        department_id = request.args.get('department_id')

        if not query and not department_id:
            return jsonify({'doctors': []}), 200

        doctor_query = Doctor.query.join(Doctor.user).filter(User.is_active == True)

        if query:
            doctor_query = doctor_query.filter(
                or_(
                    Doctor.name.ilike(f'%{query}%'),
                    Doctor.specialization.ilike(f'%{query}%')
                )
            )
        if department_id:
            doctor_query = doctor_query.filter(Doctor.department_id == department_id)

        doctors = doctor_query.all()
        return jsonify({'doctors': [d.to_dict() for d in doctors]}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/doctors/<int:doctor_id>', methods=['GET'])
@login_required
@role_required(['patient'])
def get_doctor_details(doctor_id):
    try:
        doctor = Doctor.query.get(doctor_id)
        if not doctor:
            return jsonify({'error': 'Doctor not found'}), 404

        today = date.today()
        availability = DoctorAvailability.query.filter(
            DoctorAvailability.doctor_id == doctor_id,
            DoctorAvailability.date >= today,
            DoctorAvailability.date <= today + timedelta(days=7),
            DoctorAvailability.is_available == True
        ).order_by(DoctorAvailability.date).all()

        return jsonify({
            'doctor': doctor.to_dict(),
            'availability': [a.to_dict() for a in availability]
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/appointments', methods=['POST'])
@login_required
@role_required(['patient'])
def book_appointment():
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

        data = request.get_json()
        required_fields = ['doctor_id', 'appointment_date', 'appointment_time']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        appointment_date = datetime.strptime(data['appointment_date'], '%Y-%m-%d').date()
        appointment_time = datetime.strptime(data['appointment_time'], '%H:%M').time()

        if appointment_date < date.today():
            return jsonify({'error': 'Cannot book appointments in the past'}), 400

        if appointment_date == date.today():
            if appointment_time <= datetime.now().time():
                return jsonify({
                    'error': f'Cannot book a past time slot. Current time is {datetime.now().strftime("%H:%M")}. Please choose a future time.'
                }), 400

        doctor = Doctor.query.get(data['doctor_id'])
        if not doctor or not doctor.user.is_active:
            return jsonify({'error': 'Doctor not found or inactive'}), 404

        existing = Appointment.query.filter(
            Appointment.doctor_id == data['doctor_id'],
            Appointment.appointment_date == appointment_date,
            Appointment.appointment_time == appointment_time,
            Appointment.status.in_(['Booked', 'Completed'])
        ).first()
        if existing:
            return jsonify({'error': 'This time slot is already booked'}), 400

        availability = DoctorAvailability.query.filter(
            DoctorAvailability.doctor_id == data['doctor_id'],
            DoctorAvailability.date == appointment_date,
            DoctorAvailability.is_available == True
        ).first()
        if not availability:
            return jsonify({'error': 'Doctor is not available on this date'}), 400

        if appointment_time < availability.start_time or appointment_time >= availability.end_time:
            return jsonify({
                'error': f'Selected time is outside doctor\'s availability ({availability.start_time.strftime("%H:%M")} - {availability.end_time.strftime("%H:%M")})'
            }), 400

        appointment = Appointment(
            patient_id=patient.id,
            doctor_id=data['doctor_id'],
            appointment_date=appointment_date,
            appointment_time=appointment_time,
            reason=data.get('reason', ''),
            status='Booked'
        )
        db.session.add(appointment)
        db.session.commit()

        return jsonify({'message': 'Appointment booked successfully', 'appointment': appointment.to_dict()}), 201

    except ValueError:
        return jsonify({'error': 'Invalid date or time format'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/appointments', methods=['GET'])
@login_required
@role_required(['patient'])
def get_appointments():
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

        status = request.args.get('status')
        query = Appointment.query.filter_by(patient_id=patient.id)
        if status:
            query = query.filter_by(status=status)

        appointments = query.order_by(
            Appointment.appointment_date.desc(),
            Appointment.appointment_time.desc()
        ).all()

        return jsonify({'appointments': [apt.to_dict() for apt in appointments]}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/appointments/<int:appointment_id>/reschedule', methods=['PUT'])
@login_required
@role_required(['patient'])
def reschedule_appointment(appointment_id):
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        appointment = Appointment.query.get(appointment_id)

        if not appointment or appointment.patient_id != patient.id:
            return jsonify({'error': 'Appointment not found'}), 404

        if appointment.status != 'Booked':
            return jsonify({'error': 'Only booked appointments can be rescheduled'}), 400

        data = request.get_json()
        new_date = datetime.strptime(data['appointment_date'], '%Y-%m-%d').date()
        new_time = datetime.strptime(data['appointment_time'], '%H:%M').time()

        if new_date < date.today():
            return jsonify({'error': 'Cannot reschedule to a past date'}), 400

        if new_date == date.today():
            if new_time <= datetime.now().time():
                return jsonify({
                    'error': f'Cannot reschedule to a past time. Current time is {datetime.now().strftime("%H:%M")}.'
                }), 400

        availability = DoctorAvailability.query.filter(
            DoctorAvailability.doctor_id == appointment.doctor_id,
            DoctorAvailability.date == new_date,
            DoctorAvailability.is_available == True
        ).first()
        if not availability:
            return jsonify({'error': 'Doctor is not available on this date. Please choose another date.'}), 400

        if new_time < availability.start_time or new_time >= availability.end_time:
            return jsonify({
                'error': f'Selected time is outside doctor\'s available hours ({availability.start_time.strftime("%H:%M")} - {availability.end_time.strftime("%H:%M")}).'
            }), 400

        conflict = Appointment.query.filter(
            Appointment.doctor_id == appointment.doctor_id,
            Appointment.appointment_date == new_date,
            Appointment.appointment_time == new_time,
            Appointment.id != appointment_id,
            Appointment.status.in_(['Booked', 'Completed'])
        ).first()
        if conflict:
            return jsonify({'error': 'This time slot is already booked by another patient.'}), 400

        appointment.appointment_date = new_date
        appointment.appointment_time = new_time
        appointment.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'message': 'Appointment rescheduled successfully', 'appointment': appointment.to_dict()}), 200

    except ValueError:
        return jsonify({'error': 'Invalid date or time format'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/appointments/<int:appointment_id>/cancel', methods=['PUT'])
@login_required
@role_required(['patient'])
def cancel_appointment(appointment_id):
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        appointment = Appointment.query.get(appointment_id)

        if not appointment or appointment.patient_id != patient.id:
            return jsonify({'error': 'Appointment not found'}), 404

        if appointment.status != 'Booked':
            return jsonify({'error': 'Only booked appointments can be cancelled'}), 400

        appointment.status = 'Cancelled'
        appointment.updated_at = datetime.utcnow()
        db.session.commit()

        return jsonify({'message': 'Appointment cancelled successfully', 'appointment': appointment.to_dict()}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/treatment-history', methods=['GET'])
@login_required
@role_required(['patient'])
def get_treatment_history():
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

        treatments = Treatment.query.join(Appointment).filter(
            Appointment.patient_id == patient.id,
            Appointment.status == 'Completed'
        ).order_by(Appointment.appointment_date.desc()).all()

        return jsonify({'treatments': [t.to_dict() for t in treatments]}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/treatments/<int:treatment_id>', methods=['GET'])
@login_required
@role_required(['patient'])
def get_treatment_details(treatment_id):
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

        treatment = Treatment.query.join(Appointment).filter(
            Treatment.id == treatment_id,
            Appointment.patient_id == patient.id
        ).first()

        if not treatment:
            return jsonify({'error': 'Treatment not found'}), 404

        return jsonify({'treatment': treatment.to_dict()}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/profile', methods=['PUT'])
@login_required
@role_required(['patient'])
def update_profile():
    try:
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

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
        return jsonify({'message': 'Profile updated successfully', 'patient': patient.to_dict()}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/export-csv', methods=['POST'])
@login_required
@role_required(['patient'])
def export_csv():
    try:
        from tasks import export_patient_csv
        patient = Patient.query.filter_by(user_id=session['user_id']).first()
        if not patient:
            return jsonify({'error': 'Patient profile not found'}), 404

        task = export_patient_csv.delay(patient.id)
        return jsonify({
            'message': 'Export started. You will receive an email once ready.',
            'task_id': task.id,
            'email': patient.user.email
        }), 202

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@patient_bp.route('/export-csv/status/<task_id>', methods=['GET'])
@login_required
@role_required(['patient'])
def export_csv_status(task_id):
    try:
        from celery.result import AsyncResult
        from celery_app import make_celery
        from flask import current_app
        result = AsyncResult(task_id, app=current_app.celery)
        return jsonify({'status': result.status}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500