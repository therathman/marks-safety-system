import os
import logging
import pytz
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from twilio.rest import Client

app = Flask(__name__)

# Use /data/ to ensure Railway Volume saves your data permanently
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///checkins.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = os.environ.get('SECRET_KEY', 'angel-scout-safety-2024')

db = SQLAlchemy(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Variables ---
MY_PHONE        = os.environ.get('MY_PHONE', '')
EMERGENCY_PHONE = os.environ.get('EMERGENCY_PHONE', '')
MY_EMAIL        = os.environ.get('MY_EMAIL', '')
EMERGENCY_EMAIL = os.environ.get('EMERGENCY_EMAIL', '')
TWILIO_SID      = os.environ.get('TWILIO_SID', '')
TWILIO_AUTH     = os.environ.get('TWILIO_AUTH', '')
TWILIO_FROM     = os.environ.get('TWILIO_FROM', '')
CHECKIN_HOUR    = int(os.environ.get('CHECKIN_HOUR', 10))
TIMEZONE        = os.environ.get('TZ', 'America/New_York')
CHECKIN_TOKEN   = os.environ.get('CHECKIN_TOKEN', 'AngelAndScout2024')
STOP_WORD       = os.environ.get('STOP_WORD', 'BOTHGONE')

# --- Database Models ---
class CheckIn(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    method = db.Column(db.String(50))

class AlertLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda:datetime.now(pytz.timezone(TIMEZONE)))
    alert_type = db.Column(db.String(50))
    success = db.Column(db.Boolean)

class SystemState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    state = db.Column(db.String(20), default='active') # active, paused, stopped
    pause_until = db.Column(db.DateTime, nullable=True)

# --- Helper Functions ---
def send_sms(to_number, body):
    try:
        client = Client(TWILIO_SID, TWILIO_AUTH)
        client.messages.create(body=body, from_=TWILIO_FROM, to=to_number)
        return True
    except Exception as e:
        logger.error(f"Twilio Error: {e}")
        return False

import requests

def send_email(to_email, subject, body):
    try:
        api_key = os.environ.get("BREVO_API_KEY")
        url = "https://api.brevo.com/v3/smtp/email"

        headers = {
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json"
        }

        data = {
            "sender": {
                "name": "Safety System",
                "email": "alerts@servicedogsafety.com"
            },
            "to": [{"email": to_email}],
            "subject": subject,
            "textContent": body
        }

        response = requests.post(url, headers=headers, json=data)

        logger.info(f"Brevo Email Response: {response.status_code}")
        return response.status_code in [200, 201]

    except Exception as e:
        logger.error(f"Brevo Email Error: {e}")
        return False
        
def get_current_state():
    state = SystemState.query.first()
    if not state:
        state = SystemState(state='active')
        db.session.add(state)
        db.session.commit()
    return state

# --- Routes ---
@app.route('/')
def index():
    state = get_current_state()
    last = CheckIn.query.order_by(CheckIn.id.desc()).first()
    hours = 0
    if last:
        hours = (datetime.utcnow() - last.timestamp).total_seconds() / 3600
    
    alerts = AlertLog.query.order_by(AlertLog.id.desc()).limit(5).all()
    return render_template('index.html', 
                           system_state=state.state, 
                           token=CHECKIN_TOKEN, 
                           hours_since=round(hours, 1), 
                           last_checkin=last,
                           alerts=alerts)

@app.route('/checkin/<token>')
def checkin(token):
    if token != CHECKIN_TOKEN:
        return "Invalid Link", 403
    db.session.add(CheckIn(method='Web Link'))
    db.session.commit()
    return render_template('confirmed.html', now=datetime.now().strftime('%Y-%m-%d %H:%M'))

@app.route('/sms', methods=['POST'])
def sms_reply():
    # This records a check-in when you reply to a text
    db.session.add(CheckIn(method='SMS Reply'))
    db.session.commit()
    return "<Response></Response>", 200

@app.route('/pause', methods=['POST'])
def pause():
    days = int(request.form.get('days', 7))
    state = get_current_state()
    state.state = 'paused'
    state.pause_until = datetime.utcnow() + timedelta(days=days)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/resume', methods=['POST'])
def resume():
    state = get_current_state()
    state.state = 'active'
    state.pause_until = None
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/test-email')
def test_email():
    subject = "Safety System Test Email"
    body = "This is a manual test of the Brevo email system."
    success = send_email(MY_EMAIL, subject, body)
    return f"Email sent: {success}", 200
    
# --- Scheduler Jobs ---
def daily_ping():
    with app.app_context():
        state = get_current_state()
        if state.state == 'active':
            msg = f"Good morning! Safety check-in for Angel & Scout. Tap: {os.environ.get('APP_URL')}/checkin/{CHECKIN_TOKEN}"
            success = send_sms(MY_PHONE, msg)
            db.session.add(AlertLog(alert_type='Daily Ping', success=success))
            db.session.commit()

# --- Initialize ---
with app.app_context():
    db.create_all()

scheduler = BackgroundScheduler(timezone=pytz.timezone(TIMEZONE))
scheduler.add_job(daily_ping, 'cron', hour=CHECKIN_HOUR, minute='0,5,20')
scheduler.start()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
