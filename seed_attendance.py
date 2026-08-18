"""
seed_attendance.py
------------------
One-time script to seed attendance.csv with exact present/absent counts
matching the college portal data. Distributes records across weekdays
Jul 6 – Aug 14, 2026 (6 school weeks).

Run: python3 seed_attendance.py
"""

import csv
import os
from datetime import date, timedelta

# ── Real attendance counts from college portal ───────────────────────────────
# (subject_name, presents, absents)
TARGETS = [
    ("CNM",      9,  4),
    ("CNM-TU",   2,  2),
    ("DS",       7,  8),
    ("DBMS",     12, 4),
    ("OS",       6,  7),
    ("Peace",    8,  0),
    ("DS Lab",   8,  4),
    ("OOP Lab",  7,  3),
    ("DBMS Lab", 10, 6),
    ("OS Lab",   9,  7),
]

# ── Date range: Jul 6 (Mon) → Aug 14 (Fri), 2026 ────────────────────────────
START = date(2026, 7, 6)
END   = date(2026, 8, 14)

def weekdays_in_range(start, end):
    """Return list of all Mon–Fri dates in [start, end]."""
    days = []
    d = start
    while d <= end:
        if d.weekday() < 5:   # 0=Mon … 4=Fri
            days.append(d)
        d += timedelta(days=1)
    return days

WEEKDAYS = weekdays_in_range(START, END)

def generate_rows():
    rows = []
    for subject, presents, absents in TARGETS:
        total = presents + absents
        if total == 0:
            continue

        # Pick `total` weekdays spread across the range for this subject
        # (evenly spaced so calendar looks realistic)
        step = max(1, len(WEEKDAYS) // total)
        chosen = []
        idx = 0
        while len(chosen) < total and idx < len(WEEKDAYS):
            chosen.append(WEEKDAYS[idx])
            idx += step
        # If we still don't have enough (step too large), pad from remaining days
        remaining = [d for d in WEEKDAYS if d not in chosen]
        while len(chosen) < total and remaining:
            chosen.append(remaining.pop(0))
        chosen = sorted(chosen[:total])

        # Assign: first `presents` dates → Present, rest → Absent
        for i, d in enumerate(chosen):
            status = "Present" if i < presents else "Absent"
            rows.append((d.strftime("%d-%m-%y"), subject, status))

    # Sort by date then subject for clean CSV
    rows.sort(key=lambda r: (r[0], r[1]))
    return rows

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(script_dir, "attendance.csv")

    rows = generate_rows()

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Date", "Subject_Name", "Status"])
        writer.writerows(rows)

    print(f"✅ Written {len(rows)} rows to {out_path}")

    # Quick verification printout
    from collections import defaultdict
    stats = defaultdict(lambda: {"P": 0, "A": 0})
    for _, subj, status in rows:
        if status == "Present":
            stats[subj]["P"] += 1
        else:
            stats[subj]["A"] += 1

    print(f"\n{'Subject':<12} {'Present':>8} {'Absent':>8} {'Total':>7} {'%':>8}")
    print("-" * 48)
    for subj, counts in sorted(stats.items()):
        p, a = counts["P"], counts["A"]
        t = p + a
        pct = (p / t * 100) if t > 0 else 0
        print(f"{subj:<12} {p:>8} {a:>8} {t:>7} {pct:>7.2f}%")

if __name__ == "__main__":
    main()
