# backend/tasks.py
"""
Celery background tasks for Hospital Management System.

Three mandatory jobs
────────────────────
1. send_daily_reminders   – Scheduled every morning at 8 AM.
                            Finds all patients with a BOOKED appointment
                            today and emails each one a reminder.

2. send_monthly_reports   – Scheduled 1st of every month at 7 AM.
                            Generates a full HTML activity report for each
                            doctor (previous month) and emails it to them.

3. export_patient_csv     – User-triggered (patient presses "Export" button).
                            Builds a CSV of the patient's complete treatment
                            history and emails it as an attachment.

Email transport: Gmail SMTP over SSL (port 465).
Credentials are read from Flask app config:
    MAIL_USERNAME  →  your Gmail address
    MAIL_PASSWORD  →  your Gmail App Password  (NOT your account password)
"""

import csv
import io
import smtplib
from datetime import date, datetime, timedelta
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from celery.utils.log import get_task_logger

# Imported lazily inside task bodies to avoid circular import at module load
# (app and celery are set up in app.py which imports tasks)
from app import celery, app
from models import (
    db, Appointment, Doctor, Patient, Treatment, Department, User
)

logger = get_task_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  SHARED EMAIL HELPER
# ─────────────────────────────────────────────────────────────────────────────

def _send_email(
    to_email: str,
    subject: str,
    html_body: str,
    attachment_bytes: bytes = None,
    attachment_filename: str = None,
):
    """
    Send an HTML email via Gmail SMTP SSL (port 465).

    Parameters
    ----------
    to_email            : recipient address
    subject             : email subject line
    html_body           : full HTML string for the email body
    attachment_bytes    : raw bytes of any file to attach (optional)
    attachment_filename : filename shown in the attachment (optional)
    """
    with app.app_context():
        mail_user   = app.config['MAIL_USERNAME']
        mail_pass   = app.config['MAIL_PASSWORD']
        mail_from   = app.config.get('MAIL_DEFAULT_SENDER', mail_user)

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From']    = mail_from
    msg['To']      = to_email

    # HTML body part
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    # Optional file attachment
    if attachment_bytes and attachment_filename:
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(attachment_bytes)
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename="{attachment_filename}"',
        )
        msg.attach(part)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(mail_user, mail_pass)
        server.sendmail(mail_from, to_email, msg.as_string())

    logger.info("  Email sent  →  %s  |  %s", to_email, subject)


# ─────────────────────────────────────────────────────────────────────────────
#  JOB 1 — DAILY APPOINTMENT REMINDERS
#  Scheduled: every day at 8:00 AM  (see celery_app.py beat_schedule)
# ─────────────────────────────────────────────────────────────────────────────

@celery.task(name='tasks.send_daily_reminders', bind=True, max_retries=3)
def send_daily_reminders(self):
    """
    Query every BOOKED appointment for today and email the patient a
    personalised reminder with appointment details.
    """
    try:
        with app.app_context():
            today = date.today()

            appointments = (
                Appointment.query
                .filter(
                    Appointment.appointment_date == today,
                    Appointment.status == 'Booked',
                )
                .all()
            )

            if not appointments:
                logger.info("Daily reminders: no booked appointments on %s", today)
                return {'sent': 0, 'date': str(today)}

            sent = 0
            for apt in appointments:
                patient   = apt.patient
                doctor    = apt.doctor
                to_email  = patient.user.email

                patient_id_fmt = f"patient{str(patient.id).zfill(2)}"
                appt_id_fmt    = f"appt{str(apt.id).zfill(2)}"
                doctor_id_fmt  = f"doctor{str(doctor.id).zfill(2)}"
                dept_id_fmt    = f"dept{str(doctor.department_id).zfill(2)}" \
                                 if doctor.department_id else "N/A"

                subject = (
                    f" Appointment Reminder — Today at "
                    f"{apt.appointment_time.strftime('%H:%M')}"
                )

                html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:30px 20px;">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:white;border-radius:12px;overflow:hidden;
              box-shadow:0 4px 20px rgba(0,0,0,0.12);">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
               padding:35px 40px;text-align:center;color:white;">
      <div style="font-size:2.5em;margin-bottom:8px;"></div>
      <h1 style="margin:0;font-size:1.8em;font-weight:700;">Appointment Reminder</h1>
      <p  style="margin:6px 0 0;opacity:.85;font-size:1em;">IITM Hospital</p>
    </td>
  </tr>

  <!-- Body -->
  <tr>
    <td style="padding:35px 40px;">
      <p style="font-size:1.1em;color:#2c3e50;margin-top:0;">
        Dear <strong>{patient.name}</strong>,
      </p>
      <p style="color:#555;line-height:1.6;">
        This is a friendly reminder that you have a scheduled appointment
        <strong>today</strong>. Please review the details below.
      </p>

      <!-- Details card -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#f0f0ff;border-left:4px solid #667eea;
                    border-radius:8px;margin:20px 0;">
        <tr>
          <td style="padding:20px 25px;">
            <table width="100%" cellpadding="4" cellspacing="0"
                   style="color:#2c3e50;font-size:0.95em;">
              <tr>
                <td width="160"><strong> Patient ID</strong></td>
                <td>
                  <span style="background:#667eea;color:white;padding:2px 10px;
                               border-radius:4px;font-family:monospace;
                               font-size:.85em;">{patient_id_fmt}</span>
                </td>
              </tr>
              <tr>
                <td><strong> Appointment ID</strong></td>
                <td>
                  <span style="background:#667eea;color:white;padding:2px 10px;
                               border-radius:4px;font-family:monospace;
                               font-size:.85em;">{appt_id_fmt}</span>
                </td>
              </tr>
              <tr>
                <td><strong> Doctor</strong></td>
                <td>Dr. {doctor.name}
                  &nbsp;<span style="background:#667eea;color:white;padding:2px 8px;
                               border-radius:4px;font-family:monospace;
                               font-size:.8em;">{doctor_id_fmt}</span>
                </td>
              </tr>
              <tr>
                <td><strong> Specialization</strong></td>
                <td>{doctor.specialization}</td>
              </tr>
              <tr>
                <td><strong> Department</strong></td>
                <td>{doctor.department.name if doctor.department else 'N/A'}
                  &nbsp;<span style="background:#667eea;color:white;padding:2px 8px;
                               border-radius:4px;font-family:monospace;
                               font-size:.8em;">{dept_id_fmt}</span>
                </td>
              </tr>
              <tr>
                <td><strong> Date</strong></td>
                <td>{apt.appointment_date.strftime('%d %B %Y')}</td>
              </tr>
              <tr>
                <td><strong> Time</strong></td>
                <td><strong style="color:#667eea;">
                  {apt.appointment_time.strftime('%H:%M')}
                </strong></td>
              </tr>
              {"<tr><td><strong> Reason</strong></td><td>" + apt.reason + "</td></tr>" if apt.reason else ""}
            </table>
          </td>
        </tr>
      </table>

      <p style="color:#555;line-height:1.6;">
         Please arrive <strong>10–15 minutes early</strong> and bring any
        previous prescriptions or medical reports.
      </p>
      <p style="color:#888;font-size:.9em;">
        If you need to cancel, please log in to the patient portal as soon
        as possible.
      </p>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="background:#f8f9fa;padding:18px 40px;text-align:center;
               color:#aaa;font-size:.82em;border-top:1px solid #eee;">
      IITM Hospital &nbsp;•&nbsp; This is an automated reminder.
      &nbsp;•&nbsp; Please do not reply to this email.
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>
                """

                try:
                    _send_email(to_email, subject, html)
                    sent += 1
                except Exception as mail_err:
                    logger.warning(
                        "Reminder failed for %s (%s): %s",
                        patient.name, to_email, mail_err
                    )

            logger.info(
                "Daily reminders: sent %d / %d for %s",
                sent, len(appointments), today
            )
            return {
                'sent':  sent,
                'total': len(appointments),
                'date':  str(today),
            }

    except Exception as exc:
        logger.error("send_daily_reminders failed: %s", exc)
        raise self.retry(exc=exc, countdown=60)


# ─────────────────────────────────────────────────────────────────────────────
#  JOB 2 — MONTHLY ACTIVITY REPORTS
#  Scheduled: 1st of every month at 7:00 AM  (see celery_app.py beat_schedule)
# ─────────────────────────────────────────────────────────────────────────────

@celery.task(name='tasks.send_monthly_reports', bind=True, max_retries=3)
def send_monthly_reports(self):
    """
    On the 1st of every month, generate a full HTML activity report for
    every active doctor covering the previous calendar month and email it.

    The report includes:
      • Summary stats (total / completed / cancelled)
      • Full appointment table with diagnosis, prescription, next-visit
    """
    try:
        with app.app_context():
            today       = date.today()
            # Previous month range
            first_this  = today.replace(day=1)
            last_prev   = first_this - timedelta(days=1)
            first_prev  = last_prev.replace(day=1)
            month_label = first_prev.strftime('%B %Y')

            doctors = (
                Doctor.query
                .join(Doctor.user)
                .filter(User.is_active == True)
                .all()
            )

            if not doctors:
                logger.info("Monthly reports: no active doctors found")
                return {'sent': 0}

            sent = 0
            for doctor in doctors:
                to_email = doctor.user.email

                # All appointments for this doctor last month
                apts = (
                    Appointment.query
                    .filter(
                        Appointment.doctor_id       == doctor.id,
                        Appointment.appointment_date >= first_prev,
                        Appointment.appointment_date <= last_prev,
                    )
                    .order_by(
                        Appointment.appointment_date,
                        Appointment.appointment_time,
                    )
                    .all()
                )

                completed = [a for a in apts if a.status == 'Completed']
                cancelled = [a for a in apts if a.status == 'Cancelled']
                booked    = [a for a in apts if a.status == 'Booked']

                doctor_id_fmt = f"doctor{str(doctor.id).zfill(2)}"
                dept_id_fmt   = (f"dept{str(doctor.department_id).zfill(2)}"
                                 if doctor.department_id else "N/A")

                # Build appointment rows
                rows_html = ''
                for apt in apts:
                    t            = apt.treatment
                    diagnosis    = (t.diagnosis[:70] + '…'
                                    if t and len(t.diagnosis) > 70
                                    else (t.diagnosis if t else '—'))
                    prescription = (t.prescription[:70] + '…'
                                    if t and t.prescription and len(t.prescription) > 70
                                    else (t.prescription if t and t.prescription else '—'))
                    next_visit   = (t.next_visit_date.strftime('%d %b %Y')
                                    if t and t.next_visit_date else '—')
                    status_color = {
                        'Completed': '#27ae60',
                        'Cancelled': '#e74c3c',
                        'Booked':    '#3498db',
                    }.get(apt.status, '#7f8c8d')

                    p_id_fmt   = f"patient{str(apt.patient.id).zfill(2)}"
                    apt_id_fmt = f"appt{str(apt.id).zfill(2)}"

                    rows_html += f"""
                    <tr style="border-bottom:1px solid #f0f0f0;">
                      <td style="padding:10px 12px;">
                        <span style="background:#667eea;color:white;padding:2px 8px;
                                     border-radius:4px;font-family:monospace;
                                     font-size:.8em;">{apt_id_fmt}</span>
                      </td>
                      <td style="padding:10px 12px;">
                        {apt.patient.name}<br>
                        <span style="background:#667eea;color:white;padding:1px 6px;
                                     border-radius:3px;font-family:monospace;
                                     font-size:.75em;">{p_id_fmt}</span>
                      </td>
                      <td style="padding:10px 12px;">
                        {apt.appointment_date.strftime('%d %b')}
                      </td>
                      <td style="padding:10px 12px;">
                        {apt.appointment_time.strftime('%H:%M')}
                      </td>
                      <td style="padding:10px 12px;font-weight:600;
                                 color:{status_color};">{apt.status}</td>
                      <td style="padding:10px 12px;color:#555;">{diagnosis}</td>
                      <td style="padding:10px 12px;color:#555;">{prescription}</td>
                      <td style="padding:10px 12px;color:#555;">{next_visit}</td>
                    </tr>
                    """

                if not apts:
                    rows_html = """
                    <tr>
                      <td colspan="8" style="padding:25px;text-align:center;
                                             color:#aaa;">
                        No appointments recorded this month.
                      </td>
                    </tr>
                    """

                subject = (
                    f" Monthly Activity Report — {month_label} "
                    f"| Dr. {doctor.name}"
                )

                html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:30px 20px;">
<table width="860" cellpadding="0" cellspacing="0"
       style="background:white;border-radius:12px;overflow:hidden;
              box-shadow:0 4px 20px rgba(0,0,0,0.12);">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
               padding:35px 40px;color:white;">
      <div style="font-size:2em;margin-bottom:8px;"></div>
      <h1 style="margin:0;font-size:1.8em;font-weight:700;">
        Monthly Activity Report
      </h1>
      <p style="margin:6px 0 0;opacity:.85;font-size:1.1em;">{month_label}</p>
    </td>
  </tr>

  <!-- Doctor info bar -->
  <tr>
    <td style="padding:22px 40px;background:#fafafa;
               border-bottom:2px solid #eee;">
      <table cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <h2 style="margin:0 0 4px;color:#2c3e50;">Dr. {doctor.name}</h2>
            <p style="margin:0;color:#7f8c8d;font-size:.95em;">
              {doctor.specialization}
              &nbsp;|&nbsp;
              <span style="background:#667eea;color:white;padding:1px 8px;
                           border-radius:4px;font-family:monospace;
                           font-size:.85em;">{doctor_id_fmt}</span>
              &nbsp;|&nbsp;
              {doctor.department.name if doctor.department else 'N/A'}
              &nbsp;
              <span style="background:#667eea;color:white;padding:1px 8px;
                           border-radius:4px;font-family:monospace;
                           font-size:.85em;">{dept_id_fmt}</span>
            </p>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Summary stats -->
  <tr>
    <td>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-bottom:2px solid #eee;">
        <tr>
          <td width="25%" style="padding:22px;text-align:center;
                                  border-right:1px solid #eee;">
            <div style="font-size:2.2em;font-weight:700;color:#667eea;">
              {len(apts)}
            </div>
            <div style="color:#7f8c8d;font-size:.9em;margin-top:4px;">
              Total Appointments
            </div>
          </td>
          <td width="25%" style="padding:22px;text-align:center;
                                  border-right:1px solid #eee;">
            <div style="font-size:2.2em;font-weight:700;color:#27ae60;">
              {len(completed)}
            </div>
            <div style="color:#7f8c8d;font-size:.9em;margin-top:4px;">
              Completed
            </div>
          </td>
          <td width="25%" style="padding:22px;text-align:center;
                                  border-right:1px solid #eee;">
            <div style="font-size:2.2em;font-weight:700;color:#e74c3c;">
              {len(cancelled)}
            </div>
            <div style="color:#7f8c8d;font-size:.9em;margin-top:4px;">
              Cancelled
            </div>
          </td>
          <td width="25%" style="padding:22px;text-align:center;">
            <div style="font-size:2.2em;font-weight:700;color:#3498db;">
              {len(booked)}
            </div>
            <div style="color:#7f8c8d;font-size:.9em;margin-top:4px;">
              Still Booked
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>

  <!-- Appointment details table -->
  <tr>
    <td style="padding:30px 40px;">
      <h3 style="color:#2c3e50;margin:0 0 16px;"> Appointment Details</h3>
      <table width="100%" cellpadding="0" cellspacing="0"
             style="font-size:.88em;border-collapse:collapse;">
        <thead>
          <tr style="background:linear-gradient(135deg,#667eea,#764ba2);
                     color:white;">
            <th style="padding:12px 12px;text-align:left;">Appt ID</th>
            <th style="padding:12px 12px;text-align:left;">Patient</th>
            <th style="padding:12px 12px;text-align:left;">Date</th>
            <th style="padding:12px 12px;text-align:left;">Time</th>
            <th style="padding:12px 12px;text-align:left;">Status</th>
            <th style="padding:12px 12px;text-align:left;">Diagnosis</th>
            <th style="padding:12px 12px;text-align:left;">Prescription</th>
            <th style="padding:12px 12px;text-align:left;">Next Visit</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="background:#f8f9fa;padding:18px 40px;text-align:center;
               color:#aaa;font-size:.82em;border-top:1px solid #eee;">
      IITM  Hospital &nbsp;•&nbsp; Auto-generated for {month_label}
      &nbsp;•&nbsp; Generated on {today.strftime('%d %B %Y')}
      &nbsp;•&nbsp; Please do not reply to this email.
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>
                """

                try:
                    _send_email(to_email, subject, html)
                    sent += 1
                except Exception as mail_err:
                    logger.warning(
                        "Monthly report failed for Dr. %s (%s): %s",
                        doctor.name, to_email, mail_err
                    )

            logger.info(
                "Monthly reports: sent %d / %d for %s",
                sent, len(doctors), month_label
            )
            return {'sent': sent, 'month': month_label}

    except Exception as exc:
        logger.error("send_monthly_reports failed: %s", exc)
        raise self.retry(exc=exc, countdown=120)


# ─────────────────────────────────────────────────────────────────────────────
#  JOB 3 — PATIENT CSV EXPORT  (user-triggered async job)
#  Endpoint: POST /api/patient/export-csv
# ─────────────────────────────────────────────────────────────────────────────

@celery.task(name='tasks.export_patient_csv', bind=True, max_retries=3)
def export_patient_csv(self, patient_id: int):
    """
    Build a CSV of the patient's complete treatment history in-memory
    and email it as an attachment to the patient.

    The patient receives an email with:
      • A summary of how many records were exported
      • The CSV file attached

    CSV columns:
      Patient ID | Patient Name | Appointment ID | Date | Time |
      Doctor ID  | Doctor Name  | Specialization | Dept ID |
      Diagnosis  | Prescription | Notes          | Next Visit Date | Recorded On
    """
    try:
        with app.app_context():
            patient = Patient.query.get(patient_id)
            if not patient:
                logger.error("export_patient_csv: patient %d not found", patient_id)
                return {'error': 'Patient not found'}

            to_email   = patient.user.email
            p_id_fmt   = f"patient{str(patient.id).zfill(2)}"

            # ── Build CSV in memory ───────────────────────────────────────
            output = io.StringIO()
            writer = csv.writer(output)

            # Header
            writer.writerow([
                'Patient ID',
                'Patient Name',
                'Appointment ID',
                'Appointment Date',
                'Appointment Time',
                'Doctor ID',
                'Doctor Name',
                'Doctor Specialization',
                'Department ID',
                'Diagnosis',
                'Prescription',
                'Doctor Notes',
                'Next Visit Date',
                'Treatment Recorded On',
            ])

            # Data rows — only Completed appointments with a Treatment record
            treatments = (
                Treatment.query
                .join(Appointment)
                .filter(
                    Appointment.patient_id == patient_id,
                    Appointment.status     == 'Completed',
                )
                .order_by(Appointment.appointment_date.desc())
                .all()
            )

            for t in treatments:
                apt    = t.appointment
                doctor = apt.doctor
                writer.writerow([
                    p_id_fmt,
                    patient.name,
                    f"appt{str(apt.id).zfill(2)}",
                    apt.appointment_date.strftime('%Y-%m-%d'),
                    apt.appointment_time.strftime('%H:%M'),
                    f"doctor{str(doctor.id).zfill(2)}",
                    f"Dr. {doctor.name}",
                    doctor.specialization,
                    f"dept{str(doctor.department_id).zfill(2)}" if doctor.department_id else 'N/A',
                    t.diagnosis    or '',
                    t.prescription or '',
                    t.notes        or '',
                    t.next_visit_date.strftime('%Y-%m-%d') if t.next_visit_date else '',
                    t.created_at.strftime('%Y-%m-%d %H:%M') if t.created_at else '',
                ])

            if not treatments:
                writer.writerow(['No completed treatment records found.'])

            csv_bytes    = output.getvalue().encode('utf-8')
            csv_filename = (
                f"treatment_history_{patient.user.username}"
                f"_{date.today()}.csv"
            )
            record_count = len(treatments)

            # ── Notification email with CSV attached ──────────────────────
            subject = (
                f" Your Treatment History Export is Ready "
                f"— {record_count} record(s)"
            )

            html = f"""
<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f5f7fa;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0">
<tr><td align="center" style="padding:30px 20px;">
<table width="600" cellpadding="0" cellspacing="0"
       style="background:white;border-radius:12px;overflow:hidden;
              box-shadow:0 4px 20px rgba(0,0,0,0.12);">

  <!-- Header -->
  <tr>
    <td style="background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);
               padding:35px 40px;text-align:center;color:white;">
      <div style="font-size:2.5em;margin-bottom:8px;"></div>
      <h1 style="margin:0;font-size:1.8em;font-weight:700;">Export Ready</h1>
      <p  style="margin:6px 0 0;opacity:.85;">IITM Hospital</p>
    </td>
  </tr>

  <!-- Body -->
  <tr>
    <td style="padding:35px 40px;">
      <p style="font-size:1.1em;color:#2c3e50;margin-top:0;">
        Dear <strong>{patient.name}</strong>,
      </p>
      <p style="color:#555;line-height:1.6;">
        Your treatment history export has been completed. Please find the
        CSV file attached to this email.
      </p>

      <!-- Details card -->
      <table width="100%" cellpadding="0" cellspacing="0"
             style="background:#f0f0ff;border-left:4px solid #667eea;
                    border-radius:8px;margin:20px 0;">
        <tr>
          <td style="padding:20px 25px;">
            <table cellpadding="5" cellspacing="0"
                   style="color:#2c3e50;font-size:.95em;">
              <tr>
                <td width="175"><strong> Patient ID</strong></td>
                <td>
                  <span style="background:#667eea;color:white;padding:2px 10px;
                               border-radius:4px;font-family:monospace;
                               font-size:.85em;">{p_id_fmt}</span>
                </td>
              </tr>
              <tr>
                <td><strong> File</strong></td>
                <td style="color:#555;">{csv_filename}</td>
              </tr>
              <tr>
                <td><strong> Records</strong></td>
                <td style="color:#555;">
                  <strong>{record_count}</strong> treatment record(s)
                </td>
              </tr>
              <tr>
                <td><strong> Generated</strong></td>
                <td style="color:#555;">
                  {datetime.now().strftime('%d %B %Y at %H:%M')}
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>

      

      <p style="color:#aaa;font-size:.88em;margin-top:24px;">
        If you did not request this export, please contact hospital
        administration immediately.
      </p>
    </td>
  </tr>

  <!-- Footer -->
  <tr>
    <td style="background:#f8f9fa;padding:18px 40px;text-align:center;
               color:#aaa;font-size:.82em;border-top:1px solid #eee;">
               IITM Hospital &nbsp;•&nbsp; Automated notification.
      &nbsp;•&nbsp; Please do not reply to this email.
    </td>
  </tr>

</table>
</td></tr>
</table>
</body>
</html>
            """

            _send_email(
                to_email,
                subject,
                html,
                attachment_bytes=csv_bytes,
                attachment_filename=csv_filename,
            )

            logger.info(
                "CSV export emailed to %s  (%d records)", to_email, record_count
            )
            return {
                'status':     'success',
                'patient_id': patient_id,
                'records':    record_count,
                'email':      to_email,
            }

    except Exception as exc:
        logger.error(
            "export_patient_csv failed for patient %d: %s", patient_id, exc
        )
        raise self.retry(exc=exc, countdown=30)