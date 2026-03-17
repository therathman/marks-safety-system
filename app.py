import os
import logging
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
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
BREVO_API_KEY   = os.environ.get('BREVO_API_KEY', '')
SENDER_EMAIL    = os.environ.get('SENDER_EMAIL', '')
CHECKIN_HOUR    = int(os.environ.get('CHECKIN_HOUR', 21))
TIMEZONE        = os.environ.get('TIMEZONE', 'America/New_York')
CHECKIN_TOKEN   = os.environ.get('CHECKIN_TOKEN', 'markscheckin2024')
STOP_WORD       = os.environ.get('STOP_WORD', 'BOTHGONE')

MY_SMS_EMAIL        = f"{MY_PHONE}@tmomail.net"
EMERGENCY_SMS_EMAIL = f"{EMERGENCY_PHONE}@vtext.com"

EMERGENCY_MESSAGE = (
    "SAFETY ALERT: Mark Rath has not responded to automated check-ins for 48 hours. "
    "Please immediately check his residence or last known GPS location and ensure the "
    "welfare of his Service Dogs, Angel and Scout. This is an automated message — not a test."
)

# ── Database Models ────────────────────────────────────────────────────────────
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

class SystemState(db.Model):
    id          = db.Column(db.Integer, primary_key=True)
    state       = db.Column(db.String(20), default='active')
    pause_until = db.Column(db.DateTime, nullable=True)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow)
    note        = db.Column(db.String(200), nullable=True)

def get_state():
    state = SystemState.query.first()
    if not state:
        state = SystemState(state='active')
        db.session.add(state)
        db.session.commit()
    if state.state == 'paused' and state.pause_until and datetime.utcnow() > state.pause_until:
        state.state = 'active'
        state.pause_until = None
        state.note = 'Auto-resumed after pause period'
        state.updated_at = datetime.utcnow()
        db.session.commit()
    return state

# ── Brevo HTTP API Email ───────────────────────────────────────────────────────
def send_email(to_email, subject, body):
    """Send email via Brevo HTTP API — bypasses Railway SMTP block."""
    try:
        url = "https://api.brevo.com/v3/smtp/email"
        headers = {
            "accept": "application/json",
            "api-key": BREVO_API_KEY,
            "content-type": "application/json"
        }
        payload = {
            "sender": {"name": "Mark's Safety System", "email": SENDER_EMAIL},
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": body
        }
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code in (200, 201):
            logger.info(f"Email sent via Brevo API to {to_email}")
            return True
        else:
            logger.error(f"Brevo API error {response.status_code}: {response.text}")
            return False
    except Exception as e:
        logger.error(f"Brevo API failed: {e}")
        return False

def send_sms(to_sms_email, body):
    """Send SMS via carrier email gateway using Brevo HTTP API."""
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

# ── Scheduled Jobs ─────────────────────────────────────────────────────────────
def send_daily_ping():
    with app.app_context():
        state = get_state()
        if state.state != 'active':
            logger.info(f"Daily ping skipped — system is {state.state}")
            return
        app_url = os.environ.get('APP_URL', 'https://marks-safety-system-production.up.railway.app')
        msg = (
            f"Good morning Mark! Daily safety check-in. "
            f"Tap to check in: {app_url}/checkin/{CHECKIN_TOKEN} "
            f"Angel & Scout are counting on you!"
        )
        ok = send_sms(MY_SMS_EMAIL, msg)
        log_alert('daily_sms', ok, msg)
        logger.info(f"Daily ping sent: {ok}")

def check_and_escalate():
    with app.app_context():
        state = get_state()
        if state.state != 'active':
            logger.info(f"Escalation check skipped — system is {state.state}")
            return
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

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.route('/')
def index():
    last   = CheckIn.query.order_by(CheckIn.timestamp.desc()).first()
    hours  = hours_since_last_checkin()
    alerts = AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all()
    state  = get_state()
    pause_until_str = None
    if state.pause_until:
        pause_until_str = state.pause_until.strftime('%B %d, %Y at %I:%M %p UTC')
    return render_template('index.html',
                           last_checkin=last,
                           hours_since=round(hours, 1),
                           alerts=alerts,
                           token=CHECKIN_TOKEN,
                           system_state=state.state,
                           pause_until=pause_until_str)

@app.route('/checkin/<token>')
def checkin(token):
    if token != CHECKIN_TOKEN:
        return "Invalid link.", 403
    db.session.add(CheckIn(method='web', note='Check-in via link'))
    db.session.commit()
    now_str = datetime.utcnow().strftime('%B %d, %Y at %I:%M %p UTC')
    return render_template('confirmed.html', now=now_str)

@app.route('/pause', methods=['POST'])
def pause():
    days = int(request.form.get('days', 7))
    state = get_state()
    if state.state == 'stopped':
        return jsonify({'error': 'System is stopped'}), 400
    state.state       = 'paused'
    state.pause_until = datetime.utcnow() + timedelta(days=days)
    state.updated_at  = datetime.utcnow()
    state.note        = f'Paused for {days} days'
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/resume', methods=['POST'])
def resume():
    state = get_state()
    if state.state == 'stopped':
        return jsonify({'error': 'System is stopped'}), 400
    state.state       = 'active'
    state.pause_until = None
    state.updated_at  = datetime.utcnow()
    state.note        = 'Manually resumed'
    db.session.commit()
    db.session.add(CheckIn(method='resume', note='System resumed'))
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/stop', methods=['POST'])
def stop():
    confirm = request.form.get('confirm_word', '').strip().upper()
    if confirm != STOP_WORD.upper():
        return render_template('index.html',
                               error='Incorrect confirmation word. System NOT stopped.',
                               last_checkin=CheckIn.query.order_by(CheckIn.timestamp.desc()).first(),
                               hours_since=round(hours_since_last_checkin(), 1),
                               alerts=AlertLog.query.order_by(AlertLog.timestamp.desc()).limit(10).all(),
                               token=CHECKIN_TOKEN,
                               system_state=get_state().state,
                               pause_until=None)
    state = get_state()
    state.state       = 'stopped'
    state.pause_until = None
    state.updated_at  = datetime.utcnow()
    state.note        = 'System permanently stopped by user'
    db.session.commit()
    return render_template('stopped.html')

@app.route('/status')
def status():
    hours = hours_since_last_checkin()
    state = get_state()
    return jsonify({
        'hours_since_checkin': round(hours, 1),
        'system_state': state.state,
        'status': 'STOPPED'  if state.state == 'stopped' else
                  'PAUSED'   if state.state == 'paused'  else
                  'OK'       if hours < 24 else
                  'WARNING'  if hours < 48 else 'EMERGENCY_SENT'
    })

@app.route('/health')
def health():
    return 'OK', 200

# ── Startup ────────────────────────────────────────────────────────────────────
with app.app_context():
    db.create_all()

tz = pytz.timezone(TIMEZONE)
scheduler = BackgroundScheduler(timezone=tz)
scheduler.add_job(send_daily_ping,    'cron',     hour=CHECKIN_HOUR, minute=0)
scheduler.add_job(check_and_escalate, 'interval', minutes=30)
scheduler.start()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
