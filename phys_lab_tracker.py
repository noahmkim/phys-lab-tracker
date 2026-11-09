#!/usr/bin/env python3
"""
PHYS 135A lab seat tracker (Spring 2027) for Noah's schedule.

Every few minutes it checks USC's public Schedule of Classes feed. If a
PHYS 135A lab with an open seat fits around your schedule (Chabok lecture,
QBIO 310, QBIO 465, AMST 135), it emails you and pops up a Mac notification.
It also catches brand-new lab sections the department adds later.

Run:   python3 phys_lab_tracker.py
Test:  python3 phys_lab_tracker.py --test   (sends one test alert, then exits)
Keep the laptop awake while it runs:  caffeinate -i python3 phys_lab_tracker.py
No installs needed (standard library only).
"""
import json, os, subprocess, sys, time, urllib.request
from datetime import datetime

# ---------- settings ----------
# On GitHub these come from repo secrets, so they aren't visible in the public repo.
EMAIL = os.environ.get("ALERT_EMAIL", "noahkim07@gmail.com")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "noah-usc-phys135a-k7q2")  # subscribe in the free ntfy app for phone push
CHECK_EVERY_MIN = 3
TERM = "20271"                          # Spring 2027
COURSE = "PHYS135A"
LECTURE_SECTION = "50340"               # Chabok WF 10-11:50

# Your classes (24h). A lab fits if it doesn't overlap any of these.
BUSY = {
    "Mon": [("14:00", "15:20")],                                    # QBIO 310
    "Tue": [("11:00", "12:20"), ("12:30", "13:50"),                 # AMST 135, QBIO 465
            ("14:00", "14:50"), ("17:00", "18:20")],                # QBIO 310 dis, PHYS dis
    "Wed": [("10:00", "11:50"), ("13:00", "13:50"),                 # PHYS lec, AMST 135 dis
            ("14:00", "15:20")],                                    # QBIO 310
    "Thu": [("11:00", "12:20"), ("12:30", "13:50")],                # AMST 135, QBIO 465
    "Fri": [("10:00", "11:50"), ("14:00", "14:50")],                # PHYS lec, QBIO 465 dis
}
# ------------------------------

API = f"https://classes.usc.edu/api/Search/Basic?termCode={TERM}&searchTerm=PHYS"

def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)

def fits(section):
    for block in section.get("schedule") or []:
        start, end = block.get("startTime"), block.get("endTime")
        if not start or not end:          # TBA time: can't judge, treat as not fitting
            return False
        for day in block.get("days") or []:
            for b_start, b_end in BUSY.get(day, []):
                if mins(start) < mins(b_end) and mins(b_start) < mins(end):
                    return False
    return True

def describe(s):
    times = "; ".join(f"{''.join(b.get('days') or [])} {b.get('startTime')}-{b.get('endTime')}"
                      for b in s.get("schedule") or [])
    return f"Lab {s['sisSectionId']}  {times}  ({s['registeredSeats']}/{s['totalSeats']} taken)"

def find_course(data):
    for c in data.get("courses", []):
        names = [c.get("fullCourseName", "")]
        for key in ("publishedCourseCode", "scheduledCourseCode"):
            cc = c.get(key) or {}
            names.append(f"{cc.get('prefix','')}{cc.get('number','')}{cc.get('suffix','')}")
        if any(n.replace(" ", "").replace("-", "").upper() == COURSE for n in names):
            return c
    return None

def check(data):
    """Returns (open fitting labs, lecture-still-open flag)."""
    course = find_course(data)
    if not course:
        raise RuntimeError("PHYS 135A not found in feed")
    labs, lecture_open = [], True
    for s in course.get("sections", []):
        if s.get("isCancelled"):
            continue
        has_seat = (s.get("registeredSeats") or 0) < (s.get("totalSeats") or 0)
        if s.get("sisSectionId") == LECTURE_SECTION:
            lecture_open = has_seat
        if s.get("rnrMode") == "Lab" and has_seat and fits(s):
            labs.append(s)
    return labs, lecture_open

def notify(title, body):
    # Email + phone push via ntfy.sh (free, no account or password needed)
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{NTFY_TOPIC}", data=body.encode(),
                                     headers={"Title": title, "Email": EMAIL, "Priority": "high",
                                              "Click": "https://webreg.usc.edu"})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print("  (email/push failed:", e, ")")
    # Mac pop-up with sound
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification {json.dumps(body[:200])} with title {json.dumps(title)} sound name "Glass"'],
                       check=False)
    except FileNotFoundError:
        pass

def main():
    if "--test" in sys.argv:
        notify("PHYS 135A tracker test", "If you got this, alerts work. Go to webreg.usc.edu when a real one arrives.")
        print("Test alert sent. Check your email (and spam folder).")
        return
    if "--once" in sys.argv:   # used by GitHub Actions: one check, alert if anything fits
        data = json.load(urllib.request.urlopen(urllib.request.Request(
            API, headers={"User-Agent": "seat-tracker"}), timeout=30))
        labs, lecture_open = check(data)
        if labs:
            body = "\n".join(describe(s) for s in labs)
            if not lecture_open:
                body += "\n\nHeads up: Chabok's lecture (50340) shows full right now."
            notify("PHYS 135A lab open! Register now", body + "\n\nwebreg.usc.edu")
            print("ALERT:\n" + body)
        else:
            print("no fitting lab open")
        return
    print(f"Watching PHYS 135A labs every {CHECK_EVERY_MIN} min. Ctrl+C to stop.")
    alerted = set()
    while True:
        now = datetime.now().strftime("%H:%M:%S")
        try:
            data = json.load(urllib.request.urlopen(urllib.request.Request(
                API, headers={"User-Agent": "seat-tracker"}), timeout=30))
            labs, lecture_open = check(data)
            new = [s for s in labs if s["sisSectionId"] not in alerted]
            if new:
                body = "\n".join(describe(s) for s in new)
                if not lecture_open:
                    body += "\n\nHeads up: Chabok's lecture (50340) shows full right now."
                notify("PHYS 135A lab open! Register now", body + "\n\nwebreg.usc.edu")
                print(f"[{now}] ALERT:\n{body}")
            else:
                print(f"[{now}] no fitting lab open")
            # forget labs that filled again, so you get re-alerted if they reopen
            alerted = {s["sisSectionId"] for s in labs}
        except Exception as e:
            print(f"[{now}] check failed: {e}")
        time.sleep(CHECK_EVERY_MIN * 60)

if __name__ == "__main__":
    main()
