import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.text import MIMEText
import pytz

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///checkins.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MY_PHONE        = os.environ.get('MY_PHONE', '')
EMERGENCY_PHONE = os.environ.get('EMERGENCY_PHONE', '')
MY_EMAIL        = os.environ.get('MY_EMAIL', '')
EMERGENCY_EMAIL = os.environ.get('EMERGENCY_EMAIL', '')
EMAIL_USER      = os.environ.get('EMAIL_USER', '')
EMAIL_PASS      = os.environ.get('EMAIL_PASS', '')
EMAIL_SMTP      = os.environ.get('EMAIL_SMTP', 'smtp.gmail.com')
EMAIL_PORT      = int(os.environ.get('EMAIL_PORT', 587))
CHECKIN_HOUR    = int(os.environ.get('CHECKIN_HOUR', 10))
TIMEZONE        = os.environ.get('TIMEZONE', 'America/New_York')
CHECKIN_TOKEN   = os.environ.get('CHECKIN_TOKEN', 'markscheckin2024')

MY_SMS_EMAIL        = f"{MY_PHONE}@tmomail.net"
EMERGENCY_SMS_EMAIL = f"{EMERGENCY_PHONE}@vtext.com"

EMERGENCY_MESSAGE = (
    "SAFETY ALERT: Mark Rath has not responded to automated check-ins for 48 hours. "
    "Please immediately check his residence or last known GPS location and ensure the "
    "welfare of his Service Dogs, Angel and Scout. This is an automated message — not a test."
)

class CheckIn(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    method    = db.Column(db.String(50))
    note      = db.Column(db.String(200))

class AlertLog(db.Model):
    id         = db.Column(db.Integer, primary_key=True)
    timestamp  = db.Column(db.DateTime, default=datetime.utcnow)
    alert_type = db.Column(db.String(50))
    success    = db.Column(db.Boolean)
    message    = db.Column(db.String(500))

def send_email(to, subject, body):
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From']    = EMAIL_USER
        msg['To']      = to
        with smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT) as server:
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASS)
            server.send_message(msg)
        logger.info(f"Email sent to {to}")
        return True
    except Exception as e:
        logger.error(f"Email failed to {to}: {e}")
        return False

def send_sms(to_sms_email, body):
    return send_email(to_sms_email, '', body)

def hours_since_last_checkin():
    last = CheckIn.query.order_by(CheckIn.timestamp.desc()).first()
    if not last:
        return 999
    return (datetime.utcnow() - last.timestamp).total_seconds() / 3600

def log_alert(alert_type, success, message):
    with app.app_context():
        db.session.add(AlertLog(alert_type=alert_type, success=success, message=message[:500]))
        db.session.commit()

def send_daily_ping():
    with app.app_context():
        app_url = os.environ.get('APP_URL', 'https://marks-safety-system-production.up.railway.app')
        msg = (
            f"Good morning Mark! Daily safety check-in. "
            f"Tap to check in: {app_url}/checkin/{CHECKIN_TOKEN} "
            f"Angel & Scout are counting on you!"
        )
        ok = send_sms(MY_SMS_EMAIL, msg)
        log_alert('daily_sms', ok, msg)

def check_and_escalate():
    with app.app_context():
        hours = hours_since_last_checkin()
        app_url = os.environ.get('APP_URL', 'https://marks-safety-system-production.up.railway.app')

        if 4 <= hours < 5:
            recent = AlertLog.query.filter(
                AlertLog.alert_type == 'followup_email',
                AlertLog.timestamp >= datetime.utcnow() - timedelta(hours=6)
            ).first()
            if not recent:
                body = (
                    f"Hi Mark,\n\nNo check-in received yet today "
                    f"({hours:.0f} hours since last response).\n\n"
                    f"Please check in: {app_url}/checkin/{CHECKIN_TOKEN}\n\n"
                    f"Angel and Scout need you!\n\n— Your Safety System"
                )
                ok = send_email(MY_EMAIL, "Safety Check-In Reminder", body)
                log_alert('followup_email', ok, body)

        if hours >= 48:
            recent = AlertLog.query.filter(
                AlertLog.alert_type == 'emergency',
                AlertLog.timestamp >= datetime.utcnow() - timedelta(hours=12)
            ).first()
            if not recent:
                sms_ok   = send_sms(EMERGENCY_SMS_EMAIL, EMERGENCY_MESSAGE)
                email_ok = send_email(
                    EMERGENCY_EMAIL,
                    "SAFETY ALERT — Mark Rath — Immediate Action Required",
                    EMERGENCY_MESSAGE
                )
                log_alert('emergency', sms_ok or email_ok, EMERGENCY_MESSAGE)
                logger.warning("EMERGENCY ALERT SENT.")

@app.route('/')
def index():
    last   = CheckIn.query.order_by(CheckIn.timestamp.desc()).first()
    hours  = hours_since_last_checkin()
    alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all()
    return render_template('index.html',
                           last_checkin=last,
                           hours_since=round(hours, 1),
                           alerts=alerts,
                           token=CHECKIN_TOKEN)

@app.route('/checkin/<token>')
def checkin(token):
    if token != CHECKIN_TOKEN:
        return "Invalid link.", 403
    db.session.add(CheckIn(method='web', note='Check-in via link'))
    db.session.commit()
    now_str = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')
    return render_template('confirmed.html', now=now_str)

@app.route('/status')
def status():
    hours = hours_since_last_checkin()
    return jsonify({
        'hours_since_checkin': round(hours, 1),
        'status': 'OK' if hours < 24 else ('WARNING' if hours < 48 else 'EMERGENCY_SENT')
    })

@app.route('/health')
def health():
    return 'OK', 200

with app.app_context():
    db.create_all()

tz = pytz.timezone(TIMEZONE)
scheduler = BackgroundScheduler(timezone=tz)
scheduler.add_job(send_daily_ping,    'cron',     hour=CHECKIN_HOUR, minute=0)
scheduler.add_job(check_and_escalate, 'interval', minutes=30)
scheduler.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
