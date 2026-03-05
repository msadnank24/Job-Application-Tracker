# main.py
# Job Application Tracker (Streamlit + Supabase)
# Features:
# - Email/password Signup + Login + Logout
# - Per-user data isolation (works with Supabase RLS policies)
# - Add / Edit / Delete jobs
# - Dropdown for Status + Last Update (same options in add + edit)
# - Color-coded rows (NO "Color Group" column shown)
# - Rules:
#     RED    = Rejected
#     GREEN  = Positive progress (Interview/Assessment/In Process/Offer/etc.)
#     ORANGE = Applied + (Submitted/No Update Yet) AND >= 21 days since Date Applied
#     YELLOW = Other ongoing / applied-recent
# - Auto-sorting: Green -> Yellow -> Orange -> Red, then newest Date Applied first
# - Search + Filters + Sort controls

import os
from datetime import date, datetime
import pandas as pd
import streamlit as st
from supabase import create_client

# ---------------------------
# Page setup
# ---------------------------
st.set_page_config(page_title="Job Application Tracker", page_icon="📌", layout="wide")

# ---------------------------
# Supabase secrets / env
# ---------------------------
SUPABASE_URL = (st.secrets.get("SUPABASE_URL") if hasattr(st, "secrets") else None) or os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = (st.secrets.get("SUPABASE_ANON_KEY") if hasattr(st, "secrets") else None) or os.getenv("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error(
        "Missing Supabase credentials.\n\n"
        "Add these in Streamlit Secrets:\n"
        "SUPABASE_URL = \"https://xxxx.supabase.co\"\n"
        "SUPABASE_ANON_KEY = \"your_publishable_key\"\n"
    )
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# ---------------------------
# Options
# ---------------------------
VISA_OPTIONS = ["Yes", "No"]

STATUS_OPTIONS = [
    "Applied",
    "In Process",
    "Rejected",
]

LAST_UPDATE_OPTIONS = [
    "No Update Yet",
    "Submitted",
    "Assessment Sent",
    "Assessment Completed",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Done",
    "Offer",
    "Hired",
    "Rejected",
]

GREEN_UPDATES = {
    "In Process",
    "Assessment Sent",
    "Assessment Completed",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Done",
    "Offer",
    "Hired",
}

NO_PROGRESS_UPDATES = {
    "No Update Yet",
    "Submitted",
}

ORANGE_DAYS = 21

# ---------------------------
# Helpers
# ---------------------------
def _safe_date(x):
    if x is None or str(x).strip() == "":
        return None
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, str):
        try:
            return date.fromisoformat(x[:10])
        except Exception:
            return None
    return None


def color_group(row) -> str:
    status = str(row.get("status", "")).strip()
    last_update = str(row.get("last_update", "")).strip()

    applied = _safe_date(row.get("date_applied"))
    days_since = (date.today() - applied).days if applied else 0

    # RED
    if status.lower() == "rejected" or last_update.lower() == "rejected":
        return "red"

    # GREEN (any positive progress)
    if status in GREEN_UPDATES or last_update in GREEN_UPDATES:
        return "green"

    # ORANGE (your exact rule)
    if status == "Applied" and (last_update in NO_PROGRESS_UPDATES) and days_since >= ORANGE_DAYS:
        return "orange"

    # YELLOW = everything else ongoing / applied recent
    return "yellow"


def group_rank(g: str) -> int:
    return {"green": 0, "yellow": 1, "orange": 2, "red": 3}.get(g, 9)


def row_bg_css(g: str) -> str:
    if g == "green":
        return "background-color: #23b26b; color: #ffffff;"
    if g == "yellow":
        return "background-color: #f2c94c; color: #111111;"
    if g == "orange":
        return "background-color: #f2994a; color: #111111;"
    if g == "red":
        return "background-color: #eb5757; color: #ffffff;"
    return ""


def get_user():
    try:
        if st.session_state.get("sb_access_token") and st.session_state.get("sb_refresh_token"):
            supabase.auth.set_session(
                st.session_state["sb_access_token"],
                st.session_state["sb_refresh_token"],
            )
        res = supabase.auth.get_user()
        return res.user if res else None
    except Exception:
        return None


def require_login_ui():
    st.title("Job Application Tracker")
    st.caption("Please log in or sign up to access your private dashboard.")

    tab_login, tab_signup = st.tabs(["Login", "Sign up"])

    with tab_login:
        email = st.text_input("Email", key="login_email")
        pw = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login", key="login_btn"):
            try:
                resp = supabase.auth.sign_in_with_password({"email": email, "password": pw})
                st.session_state["sb_access_token"] = resp.session.access_token
                st.session_state["sb_refresh_token"] = resp.session.refresh_token
                st.success("Logged in.")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with tab_signup:
        email2 = st.text_input("Email", key="su_email")
        pw2 = st.text_input("Password", type="password", key="su_pw")
        if st.button("Create account", key="signup_btn"):
            try:
                supabase.auth.sign_up({"email": email2, "password": pw2})
                st.success("Account created. Now go to Login and sign in.")
            except Exception as e:
                st.error(f"Sign up failed: {e}")

    st.stop()


def fetch_jobs(user_id: str) -> pd.DataFrame:
    resp = supabase.table("jobs").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["id", "date_applied", "company", "position", "visa", "status", "last_update"])
    df["date_applied"] = df["date_applied"].apply(_safe_date)
    return df


def insert_job(user_id: str, payload: dict):
    payload = dict(payload)
    payload["user_id"] = user_id  # REQUIRED for RLS WITH CHECK
    return supabase.table("jobs").insert(payload).execute()


def update_job(user_id: str, job_id: int, payload: dict):
    return supabase.table("jobs").update(payload).eq("id", job_id).eq("user_id", user_id).execute()


def delete_job(user_id: str, job_id: int):
    return supabase.table("jobs").delete().eq("id", job_id).eq("user_id", user_id).execute()


# ---------------------------
# Auth gate
# ---------------------------
user = get_user()
if not user:
    require_login_ui()

# Logout
top_cols = st.columns([6, 1])
with top_cols[1]:
    if st.button("Logout", key="logout_btn"):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        st.session_state.pop("sb_access_token", None)
        st.session_state.pop("sb_refresh_token", None)
        st.rerun()

st.title("Job Application Tracker")

# ---------------------------
# Add new application
# ---------------------------
with st.expander("➕ Add New Application", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        company = st.text_input("Company Name", key="add_company")
        visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=1, key="add_visa")
    with c2:
        position = st.text_input("Position", key="add_position")
        status = st.selectbox("Status", STATUS_OPTIONS, index=0, key="add_status")
    with c3:
        date_applied = st.date_input("Date Applied", value=date.today(), key="add_date")
        last_update = st.selectbox(
            "Last Update",
            LAST_UPDATE_OPTIONS,
            index=LAST_UPDATE_OPTIONS.index("Submitted"),
            key="add_last_update",
        )

    if st.button("Save Job", key="save_job_btn"):
        if not company.strip() or not position.strip():
            st.error("Company and Position are required.")
        else:
            try:
                insert_job(
                    user.id,
                    {
                        "date_applied": date_applied.isoformat(),
                        "company": company.strip(),
                        "position": position.strip(),
                        "visa": visa,
                        "status": status,
                        "last_update": last_update,
                    },
                )
                st.success("Saved.")
                st.session_state["add_company"] = ""
                st.session_state["add_position"] = ""
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

# ---------------------------
# Load data
# ---------------------------
df = fetch_jobs(user.id)
st.subheader("Applications List")

# compute groups
if not df.empty:
    df["_color_group"] = df.apply(color_group, axis=1)
    df["_group_rank"] = df["_color_group"].apply(group_rank)
else:
    df["_color_group"] = []
    df["_group_rank"] = []

# ---------------------------
# Filters + Search + Sort
# ---------------------------
f1, f2, f3, f4, f5 = st.columns([3, 2, 2, 2, 2])

with f1:
    q = st.text_input("Search (company / position / status / last update)", value="", key="search_q")
with f2:
    status_filter = st.selectbox("Status Filter", ["All"] + STATUS_OPTIONS, key="status_filter")
with f3:
    visa_filter = st.selectbox("Visa Filter", ["All"] + VISA_OPTIONS, key="visa_filter")
with f4:
    color_filter = st.selectbox("Color Group", ["All", "green", "yellow", "orange", "red"], key="color_filter")
with f5:
    sort_mode = st.selectbox(
        "Sort",
        ["Auto (best)", "Date Applied (newest)", "Date Applied (oldest)", "Company (A-Z)", "Company (Z-A)"],
        key="sort_mode",
    )

filtered = df.copy()

if q.strip():
    qq = q.strip().lower()
    mask = (
        filtered["company"].astype(str).str.lower().str.contains(qq, na=False)
        | filtered["position"].astype(str).str.lower().str.contains(qq, na=False)
        | filtered["status"].astype(str).str.lower().str.contains(qq, na=False)
        | filtered["last_update"].astype(str).str.lower().str.contains(qq, na=False)
    )
    filtered = filtered[mask]

if status_filter != "All":
    filtered = filtered[filtered["status"] == status_filter]

if visa_filter != "All":
    filtered = filtered[filtered["visa"] == visa_filter]

if color_filter != "All":
    filtered = filtered[filtered["_color_group"] == color_filter]

if not filtered.empty:
    if sort_mode == "Auto (best)":
        filtered = filtered.sort_values(by=["_group_rank", "date_applied"], ascending=[True, False], kind="mergesort")
    elif sort_mode == "Date Applied (newest)":
        filtered = filtered.sort_values(by=["date_applied"], ascending=[False], kind="mergesort")
    elif sort_mode == "Date Applied (oldest)":
        filtered = filtered.sort_values(by=["date_applied"], ascending=[True], kind="mergesort")
    elif sort_mode == "Company (A-Z)":
        filtered = filtered.sort_values(by=["company"], ascending=[True], kind="mergesort")
    elif sort_mode == "Company (Z-A)":
        filtered = filtered.sort_values(by=["company"], ascending=[False], kind="mergesort")

# ---------------------------
# Display table (NO Color Group column)
# ---------------------------
display_cols = ["id", "date_applied", "company", "position", "visa", "status", "last_update"]
for c in display_cols:
    if c not in filtered.columns:
        filtered[c] = ""

display_df = filtered[display_cols].copy().reset_index(drop=True)
groups = filtered["_color_group"].copy().reset_index(drop=True) if "_color_group" in filtered.columns else pd.Series([])

display_df = display_df.rename(
    columns={
        "id": "Job #",
        "date_applied": "Date Applied",
        "company": "Company",
        "position": "Position",
        "visa": "Visa Sponsorship",
        "status": "Status",
        "last_update": "Last Update",
    }
)

def apply_row_style(row):
    # row.name is the row index after reset_index(drop=True)
    g = groups.iloc[row.name] if len(groups) > row.name else ""
    return [row_bg_css(g)] * len(row)

styled = display_df.style.apply(apply_row_style, axis=1)

st.dataframe(styled, use_container_width=True, height=360)

st.caption(
    f"Rules: Red=Rejected | Green=In Process / interview / assessment / offer etc. | "
    f"Orange=Applied + (Submitted/No Update Yet) AND ≥ {ORANGE_DAYS} days | Yellow=Other ongoing. "
    "Auto sort: Green → Yellow → Orange → Red, then newest Date Applied."
)

# ---------------------------
# Edit / Delete
# ---------------------------
st.subheader("Edit / Update Existing Entry")

if df.empty:
    st.info("No jobs yet. Add one above.")
else:
    df_pick = df.copy()
    df_pick["label"] = df_pick.apply(
        lambda r: f'#{r["id"]} — {r.get("company","")} / {r.get("position","")} ({r.get("status","")})',
        axis=1,
    )

    pick = st.selectbox("Select a job to edit", df_pick["label"].tolist(), key="edit_pick")
    current = df_pick[df_pick["label"] == pick].iloc[0].to_dict()
    job_id = int(current["id"])

    e1, e2, e3 = st.columns(3)
    with e1:
        new_company = st.text_input("Company Name", value=str(current.get("company", "")), key=f"edit_company_{job_id}")
        new_visa = st.selectbox(
            "Visa Sponsorship",
            VISA_OPTIONS,
            index=VISA_OPTIONS.index(str(current.get("visa", "No"))) if str(current.get("visa", "No")) in VISA_OPTIONS else 1,
            key=f"edit_visa_{job_id}",
        )
    with e2:
        new_position = st.text_input("Position", value=str(current.get("position", "")), key=f"edit_position_{job_id}")
        new_status = st.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(str(current.get("status", "Applied"))) if str(current.get("status", "Applied")) in STATUS_OPTIONS else 0,
            key=f"edit_status_{job_id}",
        )
    with e3:
        cur_date = _safe_date(current.get("date_applied")) or date.today()
        new_date_applied = st.date_input("Date Applied", value=cur_date, key=f"edit_date_{job_id}")
        new_last_update = st.selectbox(
            "Last Update",
            LAST_UPDATE_OPTIONS,
            index=LAST_UPDATE_OPTIONS.index(str(current.get("last_update", "Submitted"))) if str(current.get("last_update", "Submitted")) in LAST_UPDATE_OPTIONS else 0,
            key=f"edit_lastupdate_{job_id}",
        )

    b1, b2 = st.columns([1, 5])

    with b1:
        if st.button("Save Changes", key=f"save_changes_{job_id}"):
            try:
                update_job(
                    user.id,
                    job_id,
                    {
                        "company": new_company.strip(),
                        "position": new_position.strip(),
                        "visa": new_visa,
                        "status": new_status,
                        "last_update": new_last_update,
                        "date_applied": new_date_applied.isoformat(),
                    },
                )
                st.success("Updated.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to update: {e}")

    with b2:
        if st.button("Delete This Job", key=f"delete_{job_id}"):
            try:
                delete_job(user.id, job_id)
                st.success("Deleted.")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to delete: {e}")
