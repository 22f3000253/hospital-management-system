from .auth import auth_bp
from .admin import admin_bp
from .doctor import doctor_bp
from .patient import patient_bp

__all__ = ['auth_bp', 'admin_bp', 'doctor_bp', 'patient_bp']