# backend/routes/doctor.py
from flask import Blueprint, request, jsonify, session, current_app
from models import db, Doctor, Patient, Appointment, Treatment, DoctorAvailability
from routes.auth import login_required, role_required
from datetime import datetime, date, time, timedelta
from sqlalchemy import func

doctor_bp = Blueprint('doctor', __name__)

def get_cache():
    return current_app.cache

# ─── Dashboard ────────────────────────────────────────────────────────────────

@doctor_bp.route('/dashboard', methods=['GET'])
@login_required
@role_required(['doctor'])
def get_dashboard():
    cache = get_cache()
    cache_key = f'doctor_dashboard_{session["user_id"]}'
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        today_appointments = Appointment.query.filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date == today
        ).order_by(Appointment.appointment_time).all()

        today_count = len(today_appointments)

        week_count = Appointment.query.filter(
            Appointment.doctor_id == doctor.id,
            Appointment.appointment_date >= week_start,
            Appointment.appointment_date <= week_end
        ).count()

        total_patients = db.session.query(func.count(func.distinct(Appointment.patient_id))).filter(
            Appointment.doctor_id == doctor.id
        ).scalar()

        result = {
            'today_appointments': today_count,
            'week_appointments': week_count,
            'total_patients': total_patients or 0,
            'appointments': [apt.to_dict() for apt in today_appointments]
        }

        cache.set(cache_key, result, timeout=60)  # 1 min - appointment status changes
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── Appointments ─────────────────────────────────────────────────────────────

@doctor_bp.route('/appointments', methods=['GET'])
@login_required
@role_required(['doctor'])
def get_appointments():
    cache = get_cache()
    status = request.args.get('status', 'all')
    cache_key = f'doctor_appointments_{session["user_id"]}_{status}'
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        query = Appointment.query.filter_by(doctor_id=doctor.id)

        if status and status != 'all':
            query = query.filter_by(status=status)

        appointments = query.order_by(
            Appointment.appointment_date.desc(),
            Appointment.appointment_time.desc()
        ).all()

        result = {'appointments': [apt.to_dict() for apt in appointments]}
        cache.set(cache_key, result, timeout=60)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@doctor_bp.route('/appointments/<int:appointment_id>/treatment', methods=['POST'])
@login_required
@role_required(['doctor'])
def add_treatment(appointment_id):
    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        appointment = Appointment.query.get(appointment_id)
        if not appointment or appointment.doctor_id != doctor.id:
            return jsonify({'error': 'Appointment not found'}), 404

        if appointment.status != 'Booked':
            return jsonify({'error': 'Only booked appointments can be completed'}), 400

        data = request.get_json()

        if 'diagnosis' not in data or not data['diagnosis']:
            return jsonify({'error': 'Diagnosis is required'}), 400

        treatment = Treatment(
            appointment_id=appointment_id,
            diagnosis=data['diagnosis'],
            prescription=data.get('prescription', ''),
            notes=data.get('notes', ''),
            next_visit_date=datetime.strptime(data['next_visit_date'], '%Y-%m-%d').date() if data.get('next_visit_date') else None
        )

        # Update appointment status: Booked → Completed
        appointment.status = 'Completed'
        appointment.updated_at = datetime.utcnow()

        db.session.add(treatment)
        db.session.commit()

        # Invalidate relevant caches
        cache = get_cache()
        cache.delete_many(
            f'doctor_dashboard_{session["user_id"]}',
            f'doctor_appointments_{session["user_id"]}_all',
            f'doctor_appointments_{session["user_id"]}_Booked',
            f'doctor_appointments_{session["user_id"]}_Completed',
            f'patient_treatment_{appointment.patient_id}',
            f'patient_appointments_{appointment.patient.user_id}',
            'admin_appointments_list',
            'admin_dashboard'
        )

        return jsonify({
            'message': 'Treatment added and appointment completed successfully',
            'treatment': treatment.to_dict()
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@doctor_bp.route('/appointments/<int:appointment_id>/cancel', methods=['PUT'])
@login_required
@role_required(['doctor'])
def cancel_appointment(appointment_id):
    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        appointment = Appointment.query.get(appointment_id)

        if not appointment or appointment.doctor_id != doctor.id:
            return jsonify({'error': 'Appointment not found'}), 404

        if appointment.status != 'Booked':
            return jsonify({'error': 'Only booked appointments can be cancelled'}), 400

        # Update appointment status: Booked → Cancelled
        appointment.status = 'Cancelled'
        appointment.updated_at = datetime.utcnow()
        db.session.commit()

        # Invalidate caches
        cache = get_cache()
        cache.delete_many(
            f'doctor_dashboard_{session["user_id"]}',
            f'doctor_appointments_{session["user_id"]}_all',
            f'doctor_appointments_{session["user_id"]}_Booked',
            f'doctor_appointments_{session["user_id"]}_Cancelled',
            f'patient_appointments_{appointment.patient.user_id}',
            'admin_appointments_list',
            'admin_dashboard'
        )

        return jsonify({
            'message': 'Appointment cancelled successfully',
            'appointment': appointment.to_dict()
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# ─── Patients ─────────────────────────────────────────────────────────────────

@doctor_bp.route('/patients', methods=['GET'])
@login_required
@role_required(['doctor'])
def get_patients():
    cache = get_cache()
    cache_key = f'doctor_patients_{session["user_id"]}'
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        patients = db.session.query(Patient).join(Appointment).filter(
            Appointment.doctor_id == doctor.id
        ).distinct().all()

        patients_data = []
        for patient in patients:
            patient_dict = patient.to_dict()
            appointment_count = Appointment.query.filter_by(
                patient_id=patient.id,
                doctor_id=doctor.id
            ).count()
            patient_dict['appointment_count'] = appointment_count
            patients_data.append(patient_dict)

        result = {'patients': patients_data}
        cache.set(cache_key, result, timeout=120)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@doctor_bp.route('/patients/<int:patient_id>/history', methods=['GET'])
@login_required
@role_required(['doctor'])
def get_patient_history(patient_id):
    """
    Full treatment history of a patient (all doctors) for informed consultation.
    """
    cache = get_cache()
    cache_key = f'doctor_patient_full_history_{patient_id}'
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        patient = Patient.query.get(patient_id)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404

        # Get ALL completed appointments with treatments for this patient (from all doctors)
        treatments = Treatment.query.join(Appointment).filter(
            Appointment.patient_id == patient_id,
            Appointment.status == 'Completed'
        ).order_by(Appointment.appointment_date.desc()).all()

        result = {
            'patient': patient.to_dict(),
            'treatments': [t.to_dict() for t in treatments]
        }
        cache.set(cache_key, result, timeout=120)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@doctor_bp.route('/patients/<int:patient_id>/history-view', methods=['GET'])
@login_required
@role_required(['doctor'])
def view_patient_history(patient_id):
    """
    Treatment history of a patient from this doctor only.
    """
    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        patient = Patient.query.get(patient_id)
        if not patient:
            return jsonify({'error': 'Patient not found'}), 404

        treatments = Treatment.query.join(Appointment).filter(
            Appointment.patient_id == patient_id,
            Appointment.doctor_id == doctor.id,
            Appointment.status == 'Completed'
        ).order_by(Appointment.appointment_date.desc()).all()

        return jsonify({
            'patient': patient.to_dict(),
            'treatments': [t.to_dict() for t in treatments]
        }), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ─── Availability ─────────────────────────────────────────────────────────────

@doctor_bp.route('/availability', methods=['POST'])
@login_required
@role_required(['doctor'])
def set_availability():
    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        data = request.get_json()

        required_fields = ['date', 'start_time', 'end_time']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400

        availability_date = datetime.strptime(data['date'], '%Y-%m-%d').date()
        start_time = datetime.strptime(data['start_time'], '%H:%M').time()
        end_time = datetime.strptime(data['end_time'], '%H:%M').time()

        if availability_date < date.today():
            return jsonify({'error': 'Cannot set availability for past dates'}), 400

        if start_time >= end_time:
            return jsonify({'error': 'Start time must be before end time'}), 400

        existing = DoctorAvailability.query.filter_by(
            doctor_id=doctor.id,
            date=availability_date
        ).first()

        if existing:
            existing.start_time = start_time
            existing.end_time = end_time
            existing.is_available = True
        else:
            availability = DoctorAvailability(
                doctor_id=doctor.id,
                date=availability_date,
                start_time=start_time,
                end_time=end_time,
                is_available=True
            )
            db.session.add(availability)

        db.session.commit()

        # Invalidate availability caches
        get_cache().delete_many(
            f'doctor_availability_{session["user_id"]}',
            f'doctor_detail_{doctor.id}'
        )

        return jsonify({'message': 'Availability set successfully'}), 201

    except ValueError:
        return jsonify({'error': 'Invalid date or time format'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@doctor_bp.route('/availability', methods=['GET'])
@login_required
@role_required(['doctor'])
def get_availability():
    cache = get_cache()
    cache_key = f'doctor_availability_{session["user_id"]}'
    cached = cache.get(cache_key)
    if cached:
        return jsonify(cached), 200

    try:
        doctor = Doctor.query.filter_by(user_id=session['user_id']).first()
        if not doctor:
            return jsonify({'error': 'Doctor profile not found'}), 404

        today = date.today()
        end_date = today + timedelta(days=7)

        availability = DoctorAvailability.query.filter(
            DoctorAvailability.doctor_id == doctor.id,
            DoctorAvailability.date >= today,
            DoctorAvailability.date <= end_date
        ).order_by(DoctorAvailability.date).all()

        result = {'availability': [avail.to_dict() for avail in availability]}
        cache.set(cache_key, result, timeout=300)
        return jsonify(result), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500