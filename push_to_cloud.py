"""
push_to_cloud.py — one-time script to push local CSV data to Google Sheets.
Run from the project directory: python3 push_to_cloud.py
"""
import os, sys, json
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

APP_DIR = os.path.dirname(os.path.abspath(__file__))

DATA_DIR = os.environ.get("DATA_DIR")
if DATA_DIR:
    CSV_PATH       = os.path.join(DATA_DIR, "attendance.csv")
    TIMETABLE_PATH = os.path.join(DATA_DIR, "timetable.csv")
else:
    CSV_PATH       = os.path.join(APP_DIR, "attendance.csv")
    TIMETABLE_PATH = os.path.join(APP_DIR, "timetable.csv")

def get_client():
    scopes = ["https://spreadsheets.google.com/feeds",
              "https://www.googleapis.com/auth/drive"]
    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    if creds_json:
        info  = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scopes)
    else:
        creds_path = os.path.join(APP_DIR, "credentials.json")
        if not os.path.exists(creds_path):
            sys.exit("❌  credentials.json not found and GOOGLE_CREDS_JSON not set.")
        creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scopes)
    return gspread.authorize(creds)

def get_or_create_worksheet(sh, title, rows, cols, header):
    try:
        ws = sh.worksheet(title)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=title, rows=str(rows), cols=str(cols))
    ws.clear()
    ws.append_row(header)
    return ws

def main():
    print("🔐 Authorising with Google…")
    client = get_client()

    print("📂 Opening / creating spreadsheet 'AttendanceTrackerCloud'…")
    try:
        sh = client.open("AttendanceTrackerCloud")
    except gspread.SpreadsheetNotFound:
        sh = client.create("AttendanceTrackerCloud")
    print(f"   Spreadsheet URL: {sh.url}")

    # ── Timetable ────────────────────────────────────────────────────────────
    print("\n📅 Pushing timetable.csv …")
    df_tt = pd.read_csv(TIMETABLE_PATH)
    ws_tt = get_or_create_worksheet(sh, "Timetable", 200, 2,
                                    ["Day_of_Week", "Subject_Name"])
    if not df_tt.empty:
        ws_tt.append_rows(df_tt.values.tolist(), value_input_option="RAW")
    print(f"   ✅ {len(df_tt)} timetable rows written.")

    # ── Attendance ────────────────────────────────────────────────────────────
    print("\n📋 Pushing attendance.csv …")
    df_att = pd.read_csv(CSV_PATH)
    ws_att = get_or_create_worksheet(sh, "Attendance", 5000, 3,
                                     ["Date", "Subject_Name", "Status"])
    if not df_att.empty:
        ws_att.append_rows(df_att.values.tolist(), value_input_option="RAW")
    print(f"   ✅ {len(df_att)} attendance rows written.")

    print("\n🎉 Cloud sync complete!")
    print(f"   View your sheet: {sh.url}")

if __name__ == "__main__":
    main()
