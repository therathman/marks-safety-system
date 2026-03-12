import os
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client
import smtplib
from email.mime.text import MIMEText
import pytz

# ── Configuration ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///checkins.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-in-production')

db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Settings (from environment variables) ─────────────────────────────────────
TWILIO_SID          = os.environ.get('TWILIO_SID')
TWILIO_AUTH         = os.environ.get('TWILIO_AUTH')
TWILIO_FROM         = os.environ.get('TWILIO_FROM')        # Your Twilio phone number
MY_PHONE            = os.environ.get('MY_PHONE')            # Mark's phone number
EMERGENCY_PHONE     = os.environ.get('EMERGENCY_PHONE')     # Emergency contact phone
MY_EMAIL            = os.environ.get('MY_EMAIL')            # Mark's email
EMERGENCY_EMAIL     = os.environ.get('EMERGENCY_EMAIL')     # Emergency contact email
EMAIL_SMTP          = os.environ.get('EMAIL_SMTP', 'smtp.gmail.com')
EMAIL_PORT          = int(os.environ.get('EMAIL_PORT', 587))
EMAIL_USER          = os.environ.get('EMAIL_USER')          # Gmail address for sending
EMAIL_PASS          = os.environ.get('EMAIL_PASS')          # Gmail app password
CHECKIN_HOUR        = int(os.environ.get('CHECKIN_HOUR', 10))   # 10am
TIMEZONE            = os.environ.get('TIMEZONE', 'America/New_York')
CHECKIN_TOKEN       = os.environ.get('CHECKIN_TOKEN', 'markscheckin2024')  # Secret URL token

EMERGENCY_MESSAGE = (
    "SAFETY ALERT: Mark Rath has not responded to automated check-ins for 48 hours. "
    "Please immediately check his residence or last known GPS location and ensure the welfare "
    "of his Service Dogs, Angel and Scout. This is an automated message — not a test."
)

# ── Database Model ─────────────────────────────────────────────────────────────
class CheckIn(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)
    method       = db.Column(db.String(50))   # 'sms_reply', 'web', 'email_reply'
    note         = db.Column(db.String(200))

class AlertLog(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    timestamp    = db.Column(db.DateTime, default=datetime.utcnow)
    alert_type   = db.Column(db.String(50))   # 'daily_sms','followup_email','emergency'
    success      = db.Column(db.Boolean)
    message      = db.Column(db.String(500))

# ── Helpers ────────────────────────────────────────────────────────────────────
def send_sms(to, body):
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH)
        client.messages.create(to=to, from_=TWILIO_FROM, body=body)
        logger.info(f"SMS sent to {to}")
        return True
    except Exception as e:
        logger.error(f"SMS failed: {e}")
        return False

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
        logger.error(f"Email failed: {e}")
        return False

def hours_since_last_checkin():
    last = CheckIn.query.order_by(CheckIn.timestamp.desc()).first()
    if not last:
        return 999
    delta = datetime.utcnow() - last.timestamp
    return delta.total_seconds() / 3600

def log_alert(alert_type, success, message):
    with app.app_context():
        entry = AlertLog(alert_type=alert_type, success=success, message=message)
        db.session.add(entry)
        db.session.commit()

# ── Scheduled Jobs ─────────────────────────────────────────────────────────────
def send_daily_ping():
    """10am daily: SMS check-in request to Mark."""
    with app.app_context():
        checkin_url = os.environ.get('APP_URL', 'https://your-app.railway.app')
        msg = (
            f"Good morning, Mark! Your daily safety check-in. "
            f"Reply YES to this message OR tap: {checkin_url}/checkin/{CHECKIN_TOKEN} "
            f"Angel and Scout are counting on you! 🐾"
        )
        ok = send_sms(MY_PHONE, msg)
        log_alert('daily_sms', ok, msg)
        logger.info("Daily ping sent.")

def check_and_escalate():
    """Runs every 30 min — sends email at 4hr silence, emergency alert at 48hr silence."""
    with app.app_context():
        hours = hours_since_last_checkin()
        logger.info(f"Hours since last check-in: {hours:.1f}")

        # 4-hour follow-up email
        if 4 <= hours < 5:
            already_sent = AlertLog.query.filter(
                AlertLog.alert_type == 'followup_email',
                AlertLog.timestamp >= datetime.utcnow() - timedelta(hours=6)
            ).first()
            if not already_sent:
                subject = "Safety Check-In Reminder — Mark Rath"
                body = (
                    f"Hi Mark,\n\nWe haven't received your check-in yet today "
                    f"({hours:.0f} hours since last response).\n\n"
                    f"Please click to check in: "
                    f"{os.environ.get('APP_URL','')}/checkin/{CHECKIN_TOKEN}\n\n"
                    f"Or simply reply to this email with 'OK'.\n\n"
                    f"— Your Safety System"
                )
                ok = send_email(MY_EMAIL, subject, body)
                log_alert('followup_email', ok, body)

        # 48-hour emergency alert
        if hours >= 48:
            already_sent = AlertLog.query.filter(
                AlertLog.alert_type == 'emergency',
                AlertLog.timestamp >= datetime.utcnow() - timedelta(hours=12)
            ).first()
            if not already_sent:
                # SMS to emergency contact
                sms_ok = send_sms(EMERGENCY_PHONE, EMERGENCY_MESSAGE)
                # Email to emergency contact
                email_ok = send_email(
                    EMERGENCY_EMAIL,
                    "⚠️ SAFETY ALERT — Mark Rath — Immediate Attention Required",
                    EMERGENCY_MESSAGE
                )
                log_alert('emergency', sms_ok or email_ok, EMERGENCY_MESSAGE)
                logger.warning("EMERGENCY ALERT SENT.")

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    last = CheckIn.query.order_by(CheckIn.timestamp.desc()).first()
    hours = hours_since_last_checkin()
    recent_alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all()
    return render_template('index.html',
                           last_checkin=last,
                           hours_since=round(hours, 1),
                           alerts=recent_alerts,
                           token=CHECKIN_TOKEN)

@app.route('/checkin/<token>')
def checkin(token):
    if token != CHECKIN_TOKEN:
        return "Invalid link.", 403
    entry = CheckIn(method='web', note='Check-in via link')
    db.session.add(entry)
    db.session.commit()
    logger.info("Web check-in recorded.")
    now_str = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')
    return render_template('confirmed.html', now=now_str)

@app.route('/sms', methods=['POST'])
def sms_webhook():
    """Twilio webhook — any reply from Mark's number counts as a check-in."""
    from_number = request.form.get('From', '')
    body        = request.form.get('Body', '').strip().upper()
    if from_number == MY_PHONE:
        entry = CheckIn(method='sms_reply', note=f"SMS reply: {body[:100]}")
        db.session.add(entry)
        db.session.commit()
        logger.info("SMS check-in recorded.")
        return '<?xml version="1.0"?><Response><Message>✅ Check-in received! Angel and Scout say hi. 🐾</Message></Response>', 200, {'Content-Type': 'text/xml'}
    return '<?xml version="1.0"?><Response></Response>', 200, {'Content-Type': 'text/xml'}

@app.route('/status')
def status():
    hours = hours_since_last_checkin()
    return jsonify({
        'hours_since_checkin': round(hours, 1),
        'status': 'OK' if hours < 24 else ('WARNING' if hours < 48 else 'EMERGENCY_SENT')
    })

# ── Startup ────────────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

tz = pytz.timezone(TIMEZONE)
scheduler = BackgroundScheduler(timezone=tz)
scheduler.add_job(send_daily_ping,    'cron', hour=CHECKIN_HOUR, minute=0)
scheduler.add_job(check_and_escalate, 'interval', minutes=30)
scheduler.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
