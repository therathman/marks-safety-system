# 🐾 Mark's Safety System — Setup Guide
## Complete setup takes about 30–45 minutes, one time only.

---

## WHAT THIS SYSTEM DOES

- Every day at **10:00 AM**, you get a text: "Are you okay? Tap this link or reply YES."
- If you don't respond within **4 hours**, a backup email goes to YOU as a reminder.
- If you go **48 hours without any response**, your emergency contact automatically
  receives a text AND email:

> "SAFETY ALERT: Mark Rath has not responded to automated check-ins for 48 hours.
> Please immediately check his residence or last known GPS location and ensure the
> welfare of his Service Dogs, Angel and Scout. This is an automated message — not a test."

---

## STEP 1 — Create a Free Twilio Account (for SMS)

1. Go to **twilio.com** and click "Sign Up Free"
2. Verify your phone number and email
3. Go to your **Console Dashboard** — you'll see:
   - **Account SID** (looks like ACxxxxxxxx) — copy this
   - **Auth Token** — copy this
4. Click "Get a Trial Number" — this gives you a free phone number
   - Copy this number (format: +15551234567)

> 💡 Twilio free trial gives you ~$15 credit. At roughly $0.01/text, that's
> 1,500 texts — about 4 years of daily pings. After that, you'd add a payment
> method for pennies per month.

---

## STEP 2 — Set Up Gmail App Password (for email backup)

1. Go to **myaccount.google.com**
2. Click **Security** → **2-Step Verification** (must be turned on)
3. Scroll down to **App Passwords**
4. Click "Create app password" → name it "Safety System"
5. Google gives you a **16-character password** — copy it exactly

---

## STEP 3 — Deploy to Railway (free hosting, runs 24/7)

1. Go to **railway.app** and sign up (free)
2. Click **"New Project"** → **"Deploy from GitHub repo"**
   - If you haven't used GitHub: go to **github.com**, create a free account,
     then create a new repository named "marks-safety-system"
   - Upload all the files from this folder to that repository
3. Railway will detect the app and start building it
4. Click your project → **"Variables"** tab → Add each variable from the list below

---

## STEP 4 — Fill In Your Variables (in Railway's Variables tab)

Copy these in one by one — replace the example values with yours:

```
TWILIO_SID          = ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH         = your_twilio_auth_token
TWILIO_FROM         = +15551234567     ← your Twilio number
MY_PHONE            = +15559876543     ← YOUR cell phone (with country code)
EMERGENCY_PHONE     = +15551112222     ← your emergency contact's phone
MY_EMAIL            = mark@gmail.com
EMERGENCY_EMAIL     = contact@gmail.com
EMAIL_USER          = yourgmail@gmail.com
EMAIL_PASS          = xxxx xxxx xxxx xxxx   ← your 16-char app password
CHECKIN_HOUR        = 10
TIMEZONE            = America/Chicago   ← change to your timezone if needed
CHECKIN_TOKEN       = AngelAndScout2024
SECRET_KEY          = mark-safety-random-key-2024
```

After adding variables, Railway restarts the app automatically.

---

## STEP 5 — Get Your App URL + Set Up SMS Replies

1. In Railway, click your project → **Settings** → copy your public URL
   (looks like: `https://marks-safety-abc123.railway.app`)
2. Add this as a variable: `APP_URL = https://marks-safety-abc123.railway.app`
3. Go to **Twilio Console** → **Phone Numbers** → click your number
4. Under **"A Message Comes In"**, paste:
   `https://marks-safety-abc123.railway.app/sms`
5. Save

Now when you reply "YES" to the daily text, it counts as your check-in automatically.

---

## STEP 6 — Test It

1. Visit your app URL in a browser — you'll see the dashboard
2. Click the big blue **"I'm OK — Check In Now"** button
3. You should see "Check-In Received!" — that's your manual check-in working
4. The dashboard shows hours since last check-in and the alert log

---

## YOUR THREE WAYS TO CHECK IN

Every day, you have three options — any one of them resets the 48-hour clock:

| Method | How |
|--------|-----|
| **Reply to the text** | Reply anything to the 10am SMS — "YES", "K", anything |
| **Tap the link** | Tap the link in the SMS (big blue button) |
| **Visit the dashboard** | Go to your app URL and hit the check-in button |

---

## TIMEZONES REFERENCE

Use one of these for your TIMEZONE variable:
- `America/New_York` — Eastern
- `America/Chicago` — Central
- `America/Denver` — Mountain
- `America/Los_Angeles` — Pacific
- `America/Phoenix` — Arizona (no daylight saving)

---

## IF SOMETHING GOES WRONG

- **No daily text arriving?** Check that MY_PHONE has the +1 country code
- **SMS replies not registering?** Verify the Twilio webhook URL is set correctly (Step 5)
- **Email not sending?** Double-check your 16-character Gmail App Password (no spaces)
- **App not loading?** Check Railway logs under your project → "Deployments"

---

## QUESTIONS?

The app runs silently 24/7 in the cloud. Your computer can be off, your phone can be off —
the system keeps running. The only thing it needs is for you to tap one button
(or reply to one text) once a day.

Angel 🐾 and Scout 🐾 are worth 30 seconds a day.
