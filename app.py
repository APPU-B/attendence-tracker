import streamlit as st
import subprocess
import json
import os
import pandas as pd
from datetime import datetime, timedelta
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Set page config
st.set_page_config(
    page_title="Automated Attendance Tracker",
    page_icon="📅",
    layout="wide",
    initial_sidebar_state="expanded"
)

# App directory configuration
APP_DIR = os.path.dirname(os.path.abspath(__file__))
ANALYTICS_BIN = os.path.join(APP_DIR, "analytics")

# Resolve dynamic data paths for production deployment
DATA_DIR = os.environ.get("DATA_DIR")
if not DATA_DIR and os.path.isdir("/app/data"):
    DATA_DIR = "/app/data"
    os.environ["DATA_DIR"] = "/app/data"  # Ensure it is inherited by C subprocesses

if DATA_DIR:
    CSV_PATH = os.path.join(DATA_DIR, "attendance.csv")
    TIMETABLE_PATH = os.path.join(DATA_DIR, "timetable.csv")
else:
    CSV_PATH = os.path.join(APP_DIR, "attendance.csv")
    TIMETABLE_PATH = os.path.join(APP_DIR, "timetable.csv")

# Google Sheets API configuration
def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_CREDS_JSON")
    scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    if creds_json:
        # Load credentials from env var holding raw JSON string
        info = json.loads(creds_json)
        creds = ServiceAccountCredentials.from_json_keyfile_dict(info, scopes)
    else:
        # Fall back to local credentials.json
        creds_path = os.path.join(APP_DIR, "credentials.json")
        if os.path.exists(creds_path):
            creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scopes)
        else:
            raise FileNotFoundError("Google credentials not found in environment (GOOGLE_CREDS_JSON) or local credentials.json")
            
    return gspread.authorize(creds)

def get_cloud_sheets():
    client = get_gspread_client()
    try:
        sh = client.open("AttendanceTrackerCloud")
    except gspread.SpreadsheetNotFound:
        # Create sheet if not found
        sh = client.create("AttendanceTrackerCloud")
        
    try:
        wks_attendance = sh.worksheet("Attendance")
    except gspread.WorksheetNotFound:
        wks_attendance = sh.add_worksheet(title="Attendance", rows="100", cols="3")
        wks_attendance.append_row(["Date", "Subject_Name", "Status"])
        
    try:
        wks_timetable = sh.worksheet("Timetable")
    except gspread.WorksheetNotFound:
        wks_timetable = sh.add_worksheet(title="Timetable", rows="100", cols="2")
        wks_timetable.append_row(["Day_of_Week", "Subject_Name"])
        
    return wks_attendance, wks_timetable

def sync_cloud_to_local():
    try:
        wks_att, wks_tt = get_cloud_sheets()
        
        # 1. Fetch Attendance from Cloud
        att_records = wks_att.get_all_records()
        if att_records:
            df_att = pd.DataFrame(att_records)
        else:
            df_att = pd.DataFrame(columns=["Date", "Subject_Name", "Status"])
        
        # Ensure we have the correct columns
        if all(col in df_att.columns for col in ["Date", "Subject_Name", "Status"]):
            df_att.to_csv(CSV_PATH, index=False)
        
        # 2. Fetch Timetable from Cloud
        tt_records = wks_tt.get_all_records()
        if tt_records:
            df_tt = pd.DataFrame(tt_records)
        else:
            df_tt = pd.DataFrame(columns=["Day_of_Week", "Subject_Name"])
            
        # Ensure we have the correct columns
        if all(col in df_tt.columns for col in ["Day_of_Week", "Subject_Name"]):
            df_tt.to_csv(TIMETABLE_PATH, index=False)
            
        print("Google Sheets: Cloud data successfully pulled to local CSV databases.")
    except Exception as e:
        print(f"Warning: Cloud sync to local failed. Operating in Offline Fallback mode. Error: {e}")

def cloud_update_attendance(date, subject, status):
    try:
        wks_att, _ = get_cloud_sheets()
        records = wks_att.get_all_values()
        found_row_idx = -1
        for idx, row in enumerate(records[1:], start=2):
            if len(row) >= 2 and row[0] == date and row[1] == subject:
                found_row_idx = idx
                break
                
        if found_row_idx != -1:
            wks_att.update_cell(found_row_idx, 3, status)
        else:
            wks_att.append_row([date, subject, status])
    except Exception as e:
        print(f"Warning: Cloud update attendance failed (using local fallback). Error: {e}")

def cloud_add_timetable_slot(day, subject):
    try:
        _, wks_tt = get_cloud_sheets()
        records = wks_tt.get_all_values()
        exists = False
        for row in records[1:]:
            if len(row) >= 2 and row[0] == day and row[1] == subject:
                exists = True
                break
        if not exists:
            wks_tt.append_row([day, subject])
    except Exception as e:
        print(f"Warning: Cloud add timetable slot failed (using local fallback). Error: {e}")

def cloud_delete_timetable_slot(day, subject):
    try:
        _, wks_tt = get_cloud_sheets()
        records = wks_tt.get_all_values()
        found_row_idx = -1
        for idx, row in enumerate(records[1:], start=2):
            if len(row) >= 2 and row[0] == day and row[1] == subject:
                found_row_idx = idx
                break
        if found_row_idx != -1:
            wks_tt.delete_rows(found_row_idx)
    except Exception as e:
        print(f"Warning: Cloud delete timetable slot failed (using local fallback). Error: {e}")

def sync_local_to_cloud():
    try:
        wks_att, wks_tt = get_cloud_sheets()
        
        # Sync Timetable
        df_tt = get_timetable_df()
        wks_tt.clear()
        wks_tt.append_row(["Day_of_Week", "Subject_Name"])
        if not df_tt.empty:
            rows = df_tt.values.tolist()
            wks_tt.append_rows(rows)
            
        # Sync Attendance
        df_att = get_attendance_df()
        wks_att.clear()
        wks_att.append_row(["Date", "Subject_Name", "Status"])
        if not df_att.empty:
            rows = df_att.values.tolist()
            wks_att.append_rows(rows)
            
        print("Google Sheets: Local data successfully pushed to cloud.")
    except Exception as e:
        print(f"Warning: Local to cloud sync failed. Error: {e}")

# Set up the weekly timetable to guarantee at least 3 subjects per day (using 6 unique subjects)
def setup_timetable():
    timetable_data = [
        {"Day_of_Week": "Monday", "Subject_Name": "Mathematics"},
        {"Day_of_Week": "Monday", "Subject_Name": "Chemistry"},
        {"Day_of_Week": "Monday", "Subject_Name": "Biology"},
        
        {"Day_of_Week": "Tuesday", "Subject_Name": "Mathematics"},
        {"Day_of_Week": "Tuesday", "Subject_Name": "Physics"},
        {"Day_of_Week": "Tuesday", "Subject_Name": "History"},
        
        {"Day_of_Week": "Wednesday", "Subject_Name": "Physics"},
        {"Day_of_Week": "Wednesday", "Subject_Name": "Chemistry"},
        {"Day_of_Week": "Wednesday", "Subject_Name": "English"},
        
        {"Day_of_Week": "Thursday", "Subject_Name": "Mathematics"},
        {"Day_of_Week": "Thursday", "Subject_Name": "English"},
        {"Day_of_Week": "Thursday", "Subject_Name": "Biology"},
        
        {"Day_of_Week": "Friday", "Subject_Name": "Physics"},
        {"Day_of_Week": "Friday", "Subject_Name": "Chemistry"},
        {"Day_of_Week": "Friday", "Subject_Name": "History"},
        
        {"Day_of_Week": "Saturday", "Subject_Name": "Mathematics"},
        {"Day_of_Week": "Saturday", "Subject_Name": "Physics"},
        {"Day_of_Week": "Saturday", "Subject_Name": "Biology"},
        
        {"Day_of_Week": "Sunday", "Subject_Name": "Chemistry"},
        {"Day_of_Week": "Sunday", "Subject_Name": "History"},
        {"Day_of_Week": "Sunday", "Subject_Name": "English"}
    ]
    df = pd.DataFrame(timetable_data)
    df.to_csv(TIMETABLE_PATH, index=False)

# Setup June 2026 Mock Attendance (June 1 to June 30, 2026) in dd-mm-yy format
def setup_mock_attendance():
    import random
    random.seed(42)
    
    tt_df = pd.read_csv(TIMETABLE_PATH)
    records = []
    start_date = datetime(2026, 6, 1)
    
    for day_offset in range(30):
        curr_date = start_date + timedelta(days=day_offset)
        date_str = curr_date.strftime("%d-%m-%y")
        day_of_week = curr_date.strftime("%A")
        
        # Get subjects scheduled for this day
        scheduled = tt_df[tt_df["Day_of_Week"] == day_of_week]["Subject_Name"].tolist()
        
        for sub in scheduled:
            # Guarantee warning threshold cases (<82%) and success buffer cases (>=82%)
            if sub == "Mathematics" and day_of_week == "Monday":
                status = "Absent" if (day_offset % 3 == 0) else "Present" # ~66%
            elif sub == "Physics" and day_of_week == "Tuesday":
                status = "Absent" if (day_offset % 4 == 0) else "Present" # ~75%
            elif sub == "Chemistry" and day_of_week == "Wednesday":
                status = "Absent" if (day_offset % 10 == 0) else "Present" # ~90%
            else:
                # Realistic randomized mix of Present, Absent, and Holiday
                rand = random.random()
                if rand < 0.80:
                    status = "Present"
                elif rand < 0.92:
                    status = "Absent"
                else:
                    status = "Holiday"
            records.append({"Date": date_str, "Subject_Name": sub, "Status": status})
            
    df_mock = pd.DataFrame(records)
    df_mock.to_csv(CSV_PATH, index=False)

# Ensure databases exist with correct columns and check for correct timetable size
def init_csv_files():
    timetable_exists = os.path.exists(TIMETABLE_PATH)
    attendance_exists = os.path.exists(CSV_PATH)
    
    # Force re-injection if the file is missing
    if not timetable_exists:
        setup_timetable()
        setup_mock_attendance()
    elif not attendance_exists:
        setup_mock_attendance()

init_csv_files()

# Initialize session-level cloud synchronization once per browser load
if "cloud_sync_done" not in st.session_state:
    sync_cloud_to_local()
    st.session_state["cloud_sync_done"] = True

# Interfacing with C backend
def run_analytics(cmd, *args):
    command = [ANALYTICS_BIN, cmd]
    for arg in args:
        command.append(str(arg))
    try:
        res = subprocess.run(command, capture_output=True, text=True, check=True, cwd=APP_DIR)
        stdout = res.stdout.strip()
        if stdout.startswith('[') or stdout.startswith('{'):
            return json.loads(stdout)
        return {"raw_output": stdout}
    except subprocess.CalledProcessError as e:
        st.error(f"C Backend error: {e.stderr}")
        return None
    except Exception as e:
        st.error(f"Unexpected error: {e}")
        return None

# Attendance record wrapper for Google Sheets sync
def record_attendance_update(date, subject, status):
    # Update locally via C binary
    run_analytics("update", date, subject, status)
    # Update in Google Sheets
    cloud_update_attendance(date, subject, status)

# Always initialize today's date on app start
if os.path.exists(ANALYTICS_BIN):
    run_analytics("init")

# Helpers to read dataframes
def get_attendance_df():
    if os.path.exists(CSV_PATH):
        return pd.read_csv(CSV_PATH)
    return pd.DataFrame(columns=["Date", "Subject_Name", "Status"])

def get_timetable_df():
    if os.path.exists(TIMETABLE_PATH):
        return pd.read_csv(TIMETABLE_PATH)
    return pd.DataFrame(columns=["Day_of_Week", "Subject_Name"])

# Timetable write operations
def add_timetable_slot(day, subject):
    df = get_timetable_df()
    if not df[((df["Day_of_Week"] == day) & (df["Subject_Name"] == subject))].empty:
        return False
    new_row = pd.DataFrame([{"Day_of_Week": day, "Subject_Name": subject}])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_csv(TIMETABLE_PATH, index=False)
    # Sync to cloud
    cloud_add_timetable_slot(day, subject)
    return True

def delete_timetable_slot(day, subject):
    df = get_timetable_df()
    df = df[~((df["Day_of_Week"] == day) & (df["Subject_Name"] == subject))]
    df.to_csv(TIMETABLE_PATH, index=False)
    # Sync to cloud
    cloud_delete_timetable_slot(day, subject)

# Inject CSS for Glassmorphic Dark UI
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif;
}

/* Glassmorphism Card style */
.premium-card {
    background: rgba(17, 24, 39, 0.85);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 16px;
    padding: 22px;
    margin-bottom: 20px;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.35);
    transition: all 0.3s ease;
    color: #ffffff;
}

.premium-card:hover {
    border-color: rgba(255, 255, 255, 0.15);
    transform: translateY(-2px);
}

.success-card {
    border-left: 5px solid #10b981 !important;
    background: linear-gradient(135deg, rgba(17, 24, 39, 0.9) 0%, rgba(6, 78, 59, 0.9) 100%) !important;
}

.warning-card {
    border-left: 5px solid #ef4444 !important;
    background: linear-gradient(135deg, rgba(17, 24, 39, 0.9) 0%, rgba(153, 27, 27, 0.9) 100%) !important;
}

.success-badge {
    background-color: rgba(16, 185, 129, 0.15);
    color: #10b981;
    padding: 3px 10px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 0.8rem;
    border: 1px solid rgba(16, 185, 129, 0.3);
}

.warning-badge {
    background-color: rgba(239, 68, 68, 0.15);
    color: #ef4444;
    padding: 3px 10px;
    border-radius: 12px;
    font-weight: 600;
    font-size: 0.8rem;
    border: 1px solid rgba(239, 68, 68, 0.3);
}

.metric-title {
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: rgba(255, 255, 255, 0.55);
    margin-bottom: 6px;
    font-weight: 500;
}

.metric-value {
    font-size: 2.2rem;
    font-weight: 700;
    line-height: 1.1;
}

/* Style for st.container(border=True) to match premium card layout */
div[data-testid="stVerticalBlockBorderWrapper"] {
    background: rgba(17, 24, 39, 0.85) !important;
    backdrop-filter: blur(14px) !important;
    -webkit-backdrop-filter: blur(14px) !important;
    border: 1px solid rgba(255, 255, 255, 0.08) !important;
    border-radius: 16px !important;
    padding: 18px !important;
    box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.35) !important;
    transition: all 0.3s ease !important;
}

div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    border-color: rgba(255, 255, 255, 0.15) !important;
}

div[data-testid="stVerticalBlockBorderWrapper"]:has(.maintained-marker) {
    border: 2px solid #10b981 !important;
    background: linear-gradient(135deg, rgba(17, 24, 39, 0.95) 0%, rgba(16, 185, 129, 0.12) 100%) !important;
}

div[data-testid="stVerticalBlockBorderWrapper"]:has(.below-82-marker) {
    border: 2px solid #ef4444 !important;
    background: linear-gradient(135deg, rgba(17, 24, 39, 0.95) 0%, rgba(239, 68, 68, 0.12) 100%) !important;
}

div[data-testid="stVerticalBlockBorderWrapper"]:has(.maintained-marker):hover {
    border-color: #34d399 !important;
    box-shadow: 0 8px 32px 0 rgba(16, 185, 129, 0.25) !important;
}

div[data-testid="stVerticalBlockBorderWrapper"]:has(.below-82-marker):hover {
    border-color: #f87171 !important;
    box-shadow: 0 8px 32px 0 rgba(239, 68, 68, 0.25) !important;
}
</style>
""", unsafe_allow_html=True)

# Navigation Menu inside Sidebar (ONLY links/menus)
st.sidebar.markdown("# ⚙️ Navigation Menu")
page = st.sidebar.radio("Go to:", ["Dashboard", "Edit History", "Manage Timetable"])

# Fetch current analytics from backend
stats = run_analytics("status")
if not stats:
    stats = []

# View 1: Dashboard
if page == "Dashboard":
    # ------------------
    # A. Top: Combined Overall Attendance Macro Card
    # ------------------
    total_presents = sum(s.get("presents", 0) for s in stats)
    total_active = sum(s.get("total_active", 0) for s in stats)
    
    overall_percentage = 100.0
    if total_active > 0:
        overall_percentage = (total_presents / total_active) * 100.0
        
    overall_color = "#10b981" if overall_percentage >= 82.0 else "#ef4444"
    
    st.markdown(f"""
    <div class="premium-card" style="border: 1px solid {overall_color}50; background: linear-gradient(135deg, rgba(17, 24, 39, 0.95) 0%, {overall_color}20 100%); margin-bottom: 28px;">
        <div class="metric-title" style="text-align: center;">Combined Overall Attendance</div>
        <div class="metric-value" style="text-align: center; color: {overall_color}; font-size: 3rem; text-shadow: 0 0 15px {overall_color}20;">{overall_percentage:.2f}%</div>
        <div style="text-align: center; margin-top: 8px; font-size: 0.95rem; color: rgba(255,255,255,0.85);">
            Combined Presents: <strong>{total_presents}</strong> / Combined Active Classes: <strong>{total_active}</strong>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # ------------------
    # B. Second: Consolidated layout block of ALL individual subjects in the system
    # ------------------
    st.write("#### Total Attendance in Each Subject:")
    if stats:
        block_cols = st.columns(4)
        for idx, s in enumerate(sorted(stats, key=lambda x: x["subject"])):
            sub_key = s["subject"]
            pct = s["percentage"]
            presents = s.get("presents", 0)
            absents = s.get("absents", 0)
            is_below = s.get("below_threshold", False)
            req_classes = s.get("required_classes", 0)
            bunk_classes = s.get("bunkable_classes", 0)
            
            if is_below:
                bunk_block = f"""<div style="background-color: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; color: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; font-size: 0.78rem; text-align: left; margin-top: 10px; line-height: 1.3;">
    🚨 <strong>Required:</strong> Must attend next <strong>{req_classes}</strong> consecutive classes.
</div>"""
            else:
                if bunk_classes > 0:
                    bunk_block = f"""<div style="background-color: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; color: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; font-size: 0.78rem; text-align: left; margin-top: 10px; line-height: 1.3;">
    🎉 <strong>Safe Bunk:</strong> Can safely skip next <strong>{bunk_classes}</strong> classes.
</div>"""
                else:
                    bunk_block = f"""<div style="background-color: rgba(245, 158, 11, 0.08); border-left: 3px solid #f59e0b; color: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; font-size: 0.78rem; text-align: left; margin-top: 10px; line-height: 1.3;">
    🛡️ <strong>Safety Limit:</strong> Cannot bunk any classes.
</div>"""
                
            card_glow_class = "warning-card" if is_below else "success-card"
            badge_class = "warning-badge" if is_below else "success-badge"
            badge_label = "Below 82%" if is_below else "Maintained"
            color = "#ef4444" if is_below else "#10b981"
            
            marker_class = "below-82-marker" if is_below else "maintained-marker"
            with block_cols[idx % 4]:
                with st.container(border=True):
                    st.markdown(f"""
                    <div class="{marker_class}"></div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <h4 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #ffffff;">{sub_key}</h4>
                        <span class="{badge_class}">{badge_label}</span>
                    </div>
                    <div class="metric-value" style="font-size: 1.8rem; margin: 8px 0; color: {color};">{pct:.2f}%</div>
                    <div style="margin-top: 8px; margin-bottom: 2px; text-align: left;">
                        <span style="background-color: rgba(16, 185, 129, 0.12); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.25); padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.78rem; margin-right: 6px; display: inline-block;">Presents: {presents}</span>
                        <span style="background-color: rgba(239, 68, 68, 0.12); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.25); padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.78rem; display: inline-block;">Absents: {absents}</span>
                    </div>
                    {bunk_block}
                    """, unsafe_allow_html=True)
    else:
        st.info("No stats recorded yet.")

    # ------------------
    # C. Third: Header showing today's date/day and listing subjects explicitly scheduled for today
    # ------------------
    today_day = datetime.now().strftime("%A")
    today_str = datetime.now().strftime("%d-%m-%y")
    
    st.write("---")
    st.markdown(f"### Today's Schedule & Calculations &nbsp;&nbsp;&bull;&nbsp;&nbsp; <span style='font-size: 1.2rem; color: rgba(255,255,255,0.6);'>{today_day}, {today_str}</span>", unsafe_allow_html=True)
    
    tt_df = get_timetable_df()
    today_slots = tt_df[tt_df["Day_of_Week"] == today_day]
    
    if not today_slots.empty:
        subjects_today = today_slots["Subject_Name"].tolist()
        st.write(f"**Today's Scheduled Subjects:** {', '.join(subjects_today)}")
        
        # ------------------
        # D. Fourth: Independent glassmorphic cards for today's subjects
        # ------------------
        grid_cols = st.columns(len(subjects_today))
        att_df = get_attendance_df()
        
        for idx, sub in enumerate(subjects_today):
            with grid_cols[idx]:
                # Locate stats for this subject name directly
                sub_stats = next((s for s in stats if s["subject"] == sub), None)
                
                if sub_stats:
                    pct = sub_stats["percentage"]
                    presents = sub_stats["presents"]
                    absents = sub_stats["absents"]
                    holidays = sub_stats["holidays"]
                    is_below = sub_stats["below_threshold"]
                    req_classes = sub_stats["required_classes"]
                    bunk_classes = sub_stats["bunkable_classes"]
                else:
                    pct, presents, absents, holidays = 0.0, 0, 0, 0
                    is_below, req_classes, bunk_classes = True, 1, 0
                
                # Fetch today's current marked status
                today_marked_row = att_df[(att_df["Date"] == today_str) & (att_df["Subject_Name"] == sub)]
                today_marked_status = today_marked_row.iloc[0]["Status"] if not today_marked_row.empty else "Pending"
                
                status_color_map = {"Present": "#10b981", "Absent": "#ef4444", "Holiday": "#f59e0b", "Pending": "#9ca3af"}
                today_status_color = status_color_map.get(today_marked_status, "#ffffff")
                
                card_glow_class = "warning-card" if is_below else "success-card"
                badge_class = "warning-badge" if is_below else "success-badge"
                badge_label = "Below 82%" if is_below else "Maintained"
                color = "#ef4444" if is_below else "#10b981"
                
                if is_below:
                    bunk_block = f"""<div style="background-color: rgba(239, 68, 68, 0.08); border-left: 3px solid #ef4444; color: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; font-size: 0.78rem; text-align: left; margin-top: 10px; margin-bottom: 12px; line-height: 1.3;">
    🚨 <strong>Required:</strong> Must attend next <strong>{req_classes}</strong> consecutive classes.
</div>"""
                else:
                    if bunk_classes > 0:
                        bunk_block = f"""<div style="background-color: rgba(16, 185, 129, 0.08); border-left: 3px solid #10b981; color: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; font-size: 0.78rem; text-align: left; margin-top: 10px; margin-bottom: 12px; line-height: 1.3;">
        🎉 <strong>Safe Bunk:</strong> Can safely skip next <strong>{bunk_classes}</strong> classes.
    </div>"""
                    else:
                        bunk_block = f"""<div style="background-color: rgba(245, 158, 11, 0.08); border-left: 3px solid #f59e0b; color: rgba(255,255,255,0.85); padding: 6px 10px; border-radius: 4px; font-size: 0.78rem; text-align: left; margin-top: 10px; margin-bottom: 12px; line-height: 1.3;">
        🛡️ <strong>Safety Limit:</strong> Cannot bunk any classes.
    </div>"""
                
                marker_class = "below-82-marker" if is_below else "maintained-marker"
                with st.container(border=True):
                    st.markdown(f"""
                    <div class="{marker_class}"></div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                        <h4 style="margin: 0; font-size: 1.15rem; font-weight: 600; color: #ffffff;">{sub}</h4>
                        <span class="{badge_class}">{badge_label}</span>
                    </div>
                    <div class="metric-value" style="font-size: 1.8rem; margin: 8px 0; color: {color};">{pct:.2f}%</div>
                    <div style="margin-top: 4px; margin-bottom: 8px; text-align: left;">
                        <span style="background-color: rgba(16, 185, 129, 0.12); color: #10b981; border: 1px solid rgba(16, 185, 129, 0.25); padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.78rem; margin-right: 6px; display: inline-block;">Presents: {presents}</span>
                        <span style="background-color: rgba(239, 68, 68, 0.12); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.25); padding: 3px 8px; border-radius: 6px; font-weight: 600; font-size: 0.78rem; display: inline-block;">Absents: {absents}</span>
                    </div>
                    <div style="background-color: {today_status_color}12; color: {today_status_color}; border: 1px solid {today_status_color}35; padding: 2px 8px; border-radius: 6px; font-weight: 600; font-size: 0.8rem; display: inline-block; margin-bottom: 12px;">
                        Status: {today_marked_status}
                    </div>
                    {bunk_block}
                    """, unsafe_allow_html=True)
                    
                    # E. Card Bottoms: Override buttons inside the card box container
                    b_cols = st.columns(3)
                    with b_cols[0]:
                        if st.button("Present", key=f"btn_p_{sub}", use_container_width=True):
                            record_attendance_update(today_str, sub, "Present")
                            st.rerun()
                    with b_cols[1]:
                        if st.button("Absent", key=f"btn_a_{sub}", use_container_width=True):
                            record_attendance_update(today_str, sub, "Absent")
                            st.rerun()
                    with b_cols[2]:
                        if st.button("Holiday", key=f"btn_h_{sub}", use_container_width=True):
                            record_attendance_update(today_str, sub, "Holiday")
                            st.rerun()
    else:
        st.info("No classes scheduled for today in the timetable.")
        
    # Diagnostics (Main Window)
    st.write("---")
    with st.expander("🛠️ Diagnostics & Simulation Tools"):
        diag_cols = st.columns(2)
        with diag_cols[0]:
            if st.button("🔄 Re-Inject June 2026 Mock Dataset", use_container_width=True):
                setup_timetable()
                setup_mock_attendance()
                run_analytics("init")
                sync_local_to_cloud()
                st.success("Re-injected June 2026 mock data default schedule!")
                st.rerun()
        with diag_cols[1]:
            if st.button("🧹 Reset Databases & Start Clean", use_container_width=True):
                if os.path.exists(CSV_PATH):
                    os.remove(CSV_PATH)
                setup_timetable() # populated weekly schedule
                # write blank attendance
                df = pd.DataFrame(columns=["Date", "Subject_Name", "Status"])
                df.to_csv(CSV_PATH, index=False)
                run_analytics("init")
                sync_local_to_cloud()
                st.success("Attendance database cleared!")
                st.rerun()

# View 2: Edit History
elif page == "Edit History":
    st.write("### 📜 History Operations")
    
    # Forms and Retroactive editors in the main window
    col1, col2 = st.columns(2)
    with col1:
        hist_date = st.date_input("Select Date for Override:", datetime.now())
        hist_date_str = hist_date.strftime("%d-%m-%y")
        st.caption(f"Formatted Date: **{hist_date_str}**")
        
    with col2:
        df_att = get_attendance_df()
        df_tt = get_timetable_df()
        subjects_list = sorted(list(set(df_att["Subject_Name"].dropna().tolist() + df_tt["Subject_Name"].dropna().tolist())))
        if subjects_list:
            hist_subject = st.selectbox("Select Subject:", subjects_list)
        else:
            hist_subject = None
            st.warning("No subjects scheduled in timetable.")
            
    if hist_subject:
        st.write(f"Override **{hist_subject}** on date **{hist_date_str}**:")
        btn_hist_cols = st.columns(3)
        with btn_hist_cols[0]:
            if st.button("Set Present", key="set_p_hist", use_container_width=True):
                record_attendance_update(hist_date_str, hist_subject, "Present")
                st.success("Marked Present!")
                st.rerun()
        with btn_hist_cols[1]:
            if st.button("Set Absent", key="set_a_hist", use_container_width=True):
                record_attendance_update(hist_date_str, hist_subject, "Absent")
                st.success("Marked Absent!")
                st.rerun()
        with btn_hist_cols[2]:
            if st.button("Set Holiday", key="set_h_hist", use_container_width=True):
                record_attendance_update(hist_date_str, hist_subject, "Holiday")
                st.success("Marked Holiday!")
                st.rerun()

    # ------------------
    # 4. History Page Grid Calendar Overhaul
    # ------------------
    st.write("---")
    st.write("### Complete Attendance Log")
    st.markdown("Monthly visual grids for **June 2026** per scheduled subject-day slot in the weekly timetable.")
    
    # Retrieve all unique timetable slots
    df_timetable = get_timetable_df()
    df_attendance = get_attendance_df()
    
    if not df_timetable.empty:
        # Sort by day order
        days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        
        # Get unique subjects in alphabetical order
        unique_subs = sorted(list(set(df_timetable["Subject_Name"].dropna().tolist())))
        
        # Render in 3 columns
        cal_cols = st.columns(3)
        
        for idx, sub_name in enumerate(unique_subs):
            # Query all weekdays this subject is scheduled
            scheduled_days = set(df_timetable[df_timetable["Subject_Name"] == sub_name]["Day_of_Week"].tolist())
            scheduled_days_sorted = sorted(list(scheduled_days), key=lambda d: days_order.index(d))
            days_str = ", ".join(scheduled_days_sorted)
            
            # Filter attendance logs for this subject
            sub_att = df_attendance[df_attendance["Subject_Name"] == sub_name]
            
            html = f"""<div style="background: rgba(17, 24, 39, 0.85); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 14px; margin-bottom: 16px; box-shadow: 0 4px 20px 0 rgba(0, 0, 0, 0.2); color: #ffffff;">
<h5 style="margin-top: 0; color: #ffffff; font-size: 0.95rem; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 6px; font-weight: 600; text-align: center;">{sub_name}</h5>
<div style="text-align: center; font-size: 0.75rem; color: rgba(255,255,255,0.5); margin-top: -4px; margin-bottom: 8px;">{days_str}</div>
<div style="display: grid; grid-template-columns: repeat(7, 1fr); gap: 4px; max-width: 250px; margin: 8px auto;">
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">M</div>
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">T</div>
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">W</div>
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">T</div>
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">F</div>
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">S</div>
<div style="text-align: center; font-size: 0.7rem; color: rgba(255,255,255,0.65); font-weight: 600;">S</div>"""
            
            start_date = datetime(2026, 6, 1) # Monday
            for day in range(1, 31):
                curr_date = start_date + timedelta(days=day - 1)
                date_str = curr_date.strftime("%d-%m-%y")
                curr_day_name = curr_date.strftime("%A")
                
                # CORE LOGIC RULE: Default to Yellow Holiday if subject is not scheduled on this day of week
                if curr_day_name in scheduled_days:
                    # Match recorded status in attendance database
                    row_att = sub_att[sub_att["Date"] == date_str]
                    if not row_att.empty:
                        status = row_att.iloc[0]["Status"]
                        if status == "Present":
                            cell_bg = "#10b981" # Green
                            cell_border = "#059669"
                            cell_text = "#ffffff"
                        elif status == "Absent":
                            cell_bg = "#ef4444" # Red
                            cell_border = "#dc2626"
                            cell_text = "#ffffff"
                        elif status == "Holiday":
                            cell_bg = "#f59e0b" # Yellow
                            cell_border = "#d97706"
                            cell_text = "#ffffff"
                        else:
                            cell_bg = "#f59e0b"
                            cell_border = "#d97706"
                            cell_text = "#ffffff"
                    else:
                        cell_bg = "#f59e0b"
                        cell_border = "#d97706"
                        cell_text = "#ffffff"
                else:
                    cell_bg = "#f59e0b"
                    cell_border = "#d97706"
                    cell_text = "#ffffff"
                
                html += f'<div style="background-color: {cell_bg}; border: 1px solid {cell_border}; color: {cell_text}; border-radius: 4px; padding: 2px 0; text-align: center; font-size: 0.75rem; font-weight: 600;" title="{date_str} - {curr_day_name}">{day}</div>'
                
            html += "</div></div>"
            
            with cal_cols[idx % 3]:
                st.markdown(html, unsafe_allow_html=True)
    else:
        st.info("The timetable is empty.")

# View 3: Manage Timetable
elif page == "Manage Timetable":
    st.write("### ⚙️ Timetable Configuration Workspace")
    st.write("Edit slots day-by-day. Moving slots is fully integrated.")
    
    df_tt = get_timetable_df()
    days_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    # 7-column visual card-grid layout for weekly schedule
    week_cols = st.columns(7)
    for idx, day in enumerate(days_order):
        with week_cols[idx]:
            subjects_on_day = df_tt[df_tt["Day_of_Week"] == day]["Subject_Name"].tolist() if not df_tt.empty else []
            
            # Styled card for each day constructed without newlines/indentation to prevent markdown code block interpretation
            html_content = f'<div style="background: rgba(17, 24, 39, 0.85); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 12px; padding: 12px; min-height: 180px; display: flex; flex-direction: column;">'
            html_content += f'<h5 style="margin-top: 0; margin-bottom: 8px; color: #ffffff; font-size: 0.95rem; font-weight: 600; text-align: center; border-bottom: 1px solid rgba(255,255,255,0.08); padding-bottom: 4px;">{day[:3]}</h5>'
            html_content += '<div style="flex-grow: 1; display: flex; flex-direction: column; gap: 6px; justify-content: flex-start; align-items: center; margin-top: 4px;">'
            
            if subjects_on_day:
                for sub in subjects_on_day:
                    html_content += f'<span style="background-color: rgba(255, 255, 255, 0.08); color: #ffffff; padding: 4px 6px; border-radius: 6px; font-size: 0.78rem; text-align: center; width: 100%; border: 1px solid rgba(255, 255, 255, 0.12); display: block; word-break: break-all; box-sizing: border-box;">{sub}</span>'
            else:
                html_content += '<span style="color: rgba(255,255,255,0.35); font-size: 0.78rem; font-style: italic; margin-top: 20px;">No classes</span>'
                
            html_content += '</div></div>'
            st.markdown(html_content, unsafe_allow_html=True)
            
    st.write("---")
    
    tab1, tab2, tab3 = st.tabs(["➕ Add Subject Slot", "❌ Delete Subject Slot", "🔄 Move Subject Slot"])
    
    with tab1:
        st.write("#### Add Subject to Schedule")
        add_cols = st.columns(2)
        with add_cols[0]:
            add_day = st.selectbox("Choose Day:", days_order, key="add_day")
        with add_cols[1]:
            add_sub = st.text_input("Enter Subject Name:", key="add_sub_name").strip()
            
        if st.button("Add Subject", key="btn_add_slot", use_container_width=True):
            if add_sub:
                success = add_timetable_slot(add_day, add_sub)
                if success:
                    st.success(f"Added {add_sub} to {add_day}!")
                    run_analytics("init")
                    st.rerun()
                else:
                    st.warning(f"{add_sub} is already scheduled on {add_day}!")
            else:
                st.error("Please enter a subject name.")
                
    with tab2:
        st.write("#### Delete Subject from Schedule")
        if not df_tt.empty:
            delete_options = df_tt.apply(lambda r: f"{r['Day_of_Week']} - {r['Subject_Name']}", axis=1).tolist()
            selected_del_slot = st.selectbox("Choose Slot to Remove:", delete_options, key="del_slot")
            
            if st.button("Remove Subject Slot", key="btn_del_slot", use_container_width=True):
                del_day, del_sub = selected_del_slot.split(" - ", 1)
                delete_timetable_slot(del_day, del_sub)
                st.success(f"Removed {del_sub} from {del_day}!")
                st.rerun()
        else:
            st.info("No slots to delete.")
            
    with tab3:
        st.write("#### Move Subject Slot to Another Day")
        if not df_tt.empty:
            move_options = df_tt.apply(lambda r: f"{r['Day_of_Week']} - {r['Subject_Name']}", axis=1).tolist()
            selected_move_slot = st.selectbox("Choose Slot to Move:", move_options, key="move_slot")
            target_day = st.selectbox("Move to Target Day:", days_order, key="target_move_day")
            
            if st.button("Move Subject Slot", key="btn_move_slot", use_container_width=True):
                from_day, move_sub = selected_move_slot.split(" - ", 1)
                if from_day == target_day:
                    st.warning("Target day is identical to source day!")
                else:
                    delete_timetable_slot(from_day, move_sub)
                    add_timetable_slot(target_day, move_sub)
                    st.success(f"Moved {move_sub} from {from_day} to {target_day}!")
                    run_analytics("init")
                    st.rerun()
        else:
            st.info("No slots to move.")

    st.markdown("---")
    st.write("### Delete a Subject")
    
    df_att = get_attendance_df()
    df_tt = get_timetable_df()
    unique_subjects = sorted(list(set(df_tt["Subject_Name"].dropna().tolist() + df_att["Subject_Name"].dropna().tolist())))
    
    if unique_subjects:
        purge_subject = st.selectbox("Select Subject to Purge:", unique_subjects, key="purge_subject_select")
        
        with st.expander("⚠️ Review Purge Warning & Confirm"):
            st.warning(f"This will permanently delete all records of '{purge_subject}' from the local database and the cloud sheet. This action cannot be undone.")
            confirm = st.checkbox("I understand this action cannot be undone", key="purge_confirm_chk")
            if confirm:
                if st.button("Delete Subject & All History permanently", key="btn_purge_subject", use_container_width=True):
                    try:
                        # a) Timetable Purge: Delete every row in the local timetable data structure where the subject matches the selected dropdown name.
                        df_tt_clean = df_tt[df_tt["Subject_Name"] != purge_subject]
                        df_tt_clean.to_csv(TIMETABLE_PATH, index=False)
                        
                        # b) Attendance History Purge: Delete every row in the local attendance history data structure where the subject matches the selected dropdown name.
                        df_att_clean = df_att[df_att["Subject_Name"] != purge_subject]
                        df_att_clean.to_csv(CSV_PATH, index=False)
                        
                        # c) Cloud Sync Broadcast: Execute a full data rewrite to the 'AttendanceTrackerCloud' Google Sheet workbook, wiping those corresponding rows from both the 'Attendance' and 'Timetable' worksheets instantly.
                        try:
                            wks_att, wks_tt = get_cloud_sheets()
                            
                            # Rewrite Timetable
                            wks_tt.clear()
                            wks_tt.append_row(["Day_of_Week", "Subject_Name"])
                            if not df_tt_clean.empty:
                                wks_tt.append_rows(df_tt_clean.values.tolist())
                                
                            # Rewrite Attendance
                            wks_att.clear()
                            wks_att.append_row(["Date", "Subject_Name", "Status"])
                            if not df_att_clean.empty:
                                wks_att.append_rows(df_att_clean.values.tolist())
                        except Exception as cloud_err:
                            raise RuntimeError(f"Cloud rewrite failed: {cloud_err}")
                        
                        # d) Local Cache Clearing: Force a clear on all active Streamlit data caches and execute 'st.rerun()' to instantly refresh the homepage card renders.
                        st.cache_data.clear()
                        st.cache_resource.clear()
                        
                        st.success(f"Successfully purged subject '{purge_subject}' and all history!")
                        
                        # Re-initialize the C backend just in case
                        if os.environ.get("ANALYTICS_BIN") or os.path.exists(ANALYTICS_BIN):
                            run_analytics("init")
                            
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error during database purge: {e}")
    else:
        st.info("No subjects found in timetable or attendance history.")

