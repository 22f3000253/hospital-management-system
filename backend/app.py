# backend/app.py
from flask import Flask, render_template, jsonify, session
from flask_cors import CORS
from flask_caching import Cache
from models import db, User, Doctor, Patient, Admin, Appointment, Treatment, Department
from config import get_config
from celery_app import make_celery
import os

# ── Create Flask app ───────────────────────────────────────────────────────
app = Flask(__name__,
            template_folder='../frontend',
            static_folder='../frontend/src')

app.config.from_object(get_config())

# ── Flask-Caching  (SimpleCache — in-process, no Redis needed for caching) ─
cache = Cache(app, config={
    'CACHE_TYPE':            'SimpleCache',
    'CACHE_DEFAULT_TIMEOUT': 300,   # 5-minute default TTL
})
app.cache = cache   # expose to blueprints via current_app.cache

# ── SQLAlchemy ─────────────────────────────────────────────────────────────
db.init_app(app)

# ── CORS ───────────────────────────────────────────────────────────────────
CORS(app, supports_credentials=True, origins=['http://localhost:5000'])

# ── Celery  (uses Redis as broker + result backend) ────────────────────────
celery = make_celery(app)
app.celery = celery   # expose to tasks module

# ── Blueprints ─────────────────────────────────────────────────────────────
from routes.auth    import auth_bp
from routes.admin   import admin_bp
from routes.doctor  import doctor_bp
from routes.patient import patient_bp

app.register_blueprint(auth_bp,    url_prefix='/api/auth')
app.register_blueprint(admin_bp,   url_prefix='/api/admin')
app.register_blueprint(doctor_bp,  url_prefix='/api/doctor')
app.register_blueprint(patient_bp, url_prefix='/api/patient')

# ── Frontend entry point ───────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('index.html')

# ── Initial seed data ──────────────────────────────────────────────────────
def create_initial_data():
    with app.app_context():
        db.create_all()
        print("✓ Database tables ready")

        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', email='admin@hospital.com', role='admin')
            admin_user.set_password('admin123')
            db.session.add(admin_user)
            db.session.commit()

            db.session.add(Admin(user_id=admin_user.id,
                                 name='System Administrator',
                                 phone='+1234567890'))

            for dept in [
                Department(name='Cardiology',      description='Heart and cardiovascular system'),
                Department(name='Neurology',        description='Brain and nervous system'),
                Department(name='Orthopedics',      description='Bones, joints, and muscles'),
                Department(name='Pediatrics',       description='Medical care for children'),
                Department(name='Dermatology',      description='Skin, hair, and nails'),
                Department(name='General Medicine', description='General health and wellness'),
            ]:
                db.session.add(dept)

            db.session.commit()
            print("=" * 60)
            print("✓ Admin created  →  admin / admin123")
            print("✓ 6 departments seeded")
            print("  Access: http://localhost:5000")
            print("=" * 60)
        else:
            print("✓ Database already initialised")

# ── Health check ───────────────────────────────────────────────────────────
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'ok', 'version': '2.0.0',
                    'message': 'Hospital Management System API is running'}), 200

# ── Cache management ───────────────────────────────────────────────────────
@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    cache.clear()
    return jsonify({'message': 'Cache cleared'}), 200

# ── Manual job triggers  (useful for testing without waiting for schedule) ─
@app.route('/api/jobs/trigger-reminders', methods=['POST'])
def trigger_reminders():
    """Fire the daily reminders task immediately (for testing)."""
    from tasks import send_daily_reminders
    task = send_daily_reminders.delay()
    return jsonify({'message': 'Daily reminders triggered', 'task_id': task.id}), 202

@app.route('/api/jobs/trigger-monthly-reports', methods=['POST'])
def trigger_monthly_reports():
    """Fire the monthly reports task immediately (for testing)."""
    from tasks import send_monthly_reports
    task = send_monthly_reports.delay()
    return jsonify({'message': 'Monthly reports triggered', 'task_id': task.id}), 202

@app.route('/api/jobs/status/<task_id>', methods=['GET'])
def job_status(task_id):
    """Poll the status/result of any Celery task."""
    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery)
    response = {'task_id': task_id, 'status': result.status}
    if result.ready():
        response['result'] = (result.result
                               if not isinstance(result.result, Exception)
                               else str(result.result))
    return jsonify(response), 200

# ── Error handlers ─────────────────────────────────────────────────────────
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    db.session.rollback()
    return jsonify({'error': 'Internal server error'}), 500

@app.errorhandler(403)
def forbidden(e):
    return jsonify({'error': 'Forbidden: access denied'}), 403

@app.errorhandler(401)
def unauthorized(e):
    return jsonify({'error': 'Unauthorized'}), 401

@app.before_request
def make_session_permanent():
    session.permanent = True

# ── Entry point ────────────────────────────────────────────────────────────
if __name__ == '__main__':
    create_initial_data()
    print("\n🏥  Hospital Management System  v2.0.0")
    print("━" * 50)
    print("⚡  Caching    : SimpleCache (5 min TTL)")
    print("📨  Email      : Gmail SMTP SSL (port 465)")
    print("🔄  Celery     : Redis broker — start separately:")
    print("      celery -A tasks worker --loglevel=info")
    print("      celery -A tasks beat   --loglevel=info")
    print("━" * 50)
    print("   Access → http://localhost:5000\n")
    app.run(debug=app.config.get('DEBUG', True), host='0.0.0.0', port=5000)