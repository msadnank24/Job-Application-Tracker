import os
from datetime import date, datetime

import pandas as pd
import streamlit as st
from supabase import create_client, Client


# ----------------------------
# Page setup
# ----------------------------
st.set_page_config(page_title="Job Application Tracker", layout="wide")
st.title("Job Application Tracker")


# ----------------------------
# Supabase config (Streamlit Cloud Secrets OR env vars)
# ----------------------------
def get_secret(name: str, default: str = "") -> str:
    # Streamlit Cloud secrets: st.secrets["NAME"]
    # Local fallback: env vars
    try:
        return st.secrets[name]
    except Exception:
        return os.getenv(name, default)


SUPABASE_URL = get_secret("SUPABASE_URL")
SUPABASE_ANON_KEY = get_secret("SUPABASE_ANON_KEY")

if not SUPABASE_URL or not SUPABASE_ANON_KEY:
    st.error(
        "Missing SUPABASE_URL / SUPABASE_ANON_KEY.\n\n"
        "Add them in Streamlit Cloud → App settings → Secrets.\n"
        "Format:\n"
        'SUPABASE_URL = "https://xxxx.supabase.co"\n'
        'SUPABASE_ANON_KEY = "your_publishable_key"\n'
    )
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


# ----------------------------
# Helpers: Auth + PostgREST client with token (IMPORTANT for RLS)
# ----------------------------
def is_logged_in() -> bool:
    return bool(st.session_state.get("access_token")) and bool(st.session_state.get("user_id"))


def get_db():
    """
    Returns an authenticated PostgREST client using the user's access token.
    This is REQUIRED so Supabase RLS policies will allow insert/update/delete.
    """
    token = st.session_state.get("access_token")
    if not token:
        return None
    return supabase.postgrest.auth(token)


def logout():
    # client-side cleanup
    st.session_state.pop("access_token", None)
    st.session_state.pop("user_id", None)
    st.session_state.pop("email", None)
    st.rerun()


# ----------------------------
# App dropdown options (you can expand these anytime)
# ----------------------------
STATUS_OPTIONS = [
    "Applied",
    "In Process",
    "Interview Scheduled",
    "Phone Screen Scheduled",
    "Assessment Sent",
    "Offer",
    "Rejected",
    "No Response",
]

LAST_UPDATE_OPTIONS = [
    "Submitted",
    "No Update Yet",
    "Assessment Sent",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "In Process",
    "Offer",
    "Rejected",
]


# ----------------------------
# Color coding rules (readable)
# ----------------------------
def classify_row(status: str, last_update: str, date_applied: date):
    """
    Returns: (group_name, priority_int)
    priority lower = higher in list
    Sorting order needed:
      Green -> Yellow -> Orange -> Red
    """
    s = (status or "").strip().lower()
    lu = (last_update or "").strip().lower()

    # Red: rejected
    if s == "rejected" or lu == "rejected":
        return ("Red", 3)

    # Green: in progress / interview / offer etc
    green_keywords = ["in process", "interview", "phone screen", "assessment", "offer"]
    if any(k in s for k in green_keywords) or any(k in lu for k in green_keywords):
        return ("Green", 0)

    # Orange: no update for >= 21 days
    # (Only apply if not already green/red)
    try:
        days = (date.today() - date_applied).days
    except Exception:
        days = 0

    if "no update" in lu or "no response" in s:
        if days >= 21:
            return ("Orange", 2)

    # Yellow: default (recent/ongoing)
    return ("Yellow", 1)


def row_bg_color(group: str):
    """
    Background colors chosen for readability (no harsh orange).
    """
    if group == "Green":
        return "#1f8f4f"   # readable green
    if group == "Yellow":
        return "#f1d04b"   # readable yellow
    if group == "Orange":
        return "#f0b35a"   # soft orange (readable text)
    if group == "Red":
        return "#c23b31"   # readable red
    return "#2b2b2b"


def row_text_color(group: str):
    # For yellow/orange use dark text, for green/red use white
    if group in ["Yellow", "Orange"]:
        return "#111111"
    return "#ffffff"


def style_table(df: pd.DataFrame):
    if df.empty:
        return df

    def apply_style(row):
        group = row.get("ColorGroup", "Yellow")
        bg = row_bg_color(group)
        fg = row_text_color(group)
        return [f"background-color: {bg}; color: {fg};"] * len(row)

    return df.style.apply(apply_style, axis=1)


# ----------------------------
# AUTH UI (Signup/Login)
# ----------------------------
if not is_logged_in():
    st.subheader("Login / Sign up")
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### Log in")
        login_email = st.text_input("Email", key="login_email")
        login_password = st.text_input("Password", type="password", key="login_password")
        if st.button("Log in", use_container_width=True):
            try:
                res = supabase.auth.sign_in_with_password({"email": login_email, "password": login_password})
                st.session_state["access_token"] = res.session.access_token
                st.session_state["user_id"] = res.user.id
                st.session_state["email"] = login_email
                st.success("Logged in!")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with col2:
        st.markdown("### Sign up")
        signup_email = st.text_input("Email ", key="signup_email")
        signup_password = st.text_input("Password ", type="password", key="signup_password")
        st.caption("If you enabled 'Confirm email' in Supabase, you must confirm first before logging in.")
        if st.button("Create account", use_container_width=True):
            try:
                supabase.auth.sign_up({"email": signup_email, "password": signup_password})
                st.success("Account created! Now log in from the left side.")
            except Exception as e:
                st.error(f"Signup failed: {e}")

    st.stop()


# Logged in UI
topbar = st.columns([1, 1, 6])
with topbar[0]:
    st.caption(f"Signed in as: **{st.session_state.get('email', 'user')}**")
with topbar[1]:
    if st.button("Log out"):
        logout()


# ----------------------------
# Load data from Supabase (authed)
# ----------------------------
db = get_db()
if db is None:
    st.error("Auth token missing. Please log out and log in again.")
    st.stop()

# Fetch jobs (RLS ensures only user's rows return)
try:
    rows = db.from_("jobs").select("*").execute().data
except Exception as e:
    st.error(f"Failed to load jobs: {e}")
    rows = []


def to_date(x):
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        return date.today()


df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
    "id", "user_id", "date_applied", "company", "position", "visa", "status", "last_update", "created_at"
])

if not df.empty:
    df["date_applied"] = df["date_applied"].apply(to_date)

    # classify colors
    groups = df.apply(lambda r: classify_row(r.get("status", ""), r.get("last_update", ""), r.get("date_applied", date.today())), axis=1)
    df["ColorGroup"] = [g[0] for g in groups]
    df["GroupPriority"] = [g[1] for g in groups]

    # Sorting: Green -> Yellow -> Orange -> Red; then newest date_applied first
    df = df.sort_values(by=["GroupPriority", "date_applied"], ascending=[True, False], kind="mergesort").reset_index(drop=True)

    # Job number
    df.insert(0, "Job #", range(1, len(df) + 1))


# ----------------------------
# Add new application
# ----------------------------
st.markdown("---")
with st.expander("➕ Add New Application", expanded=False):
    c1, c2, c3 = st.columns(3)
    company = c1.text_input("Company Name", key="add_company")
    position = c2.text_input("Position", key="add_position")
    date_applied = c3.date_input("Date Applied", value=date.today(), key="add_date")

    c4, c5, c6 = st.columns(3)
    visa = c4.selectbox("Visa Sponsorship", ["Yes", "No"], index=1, key="add_visa")
    status = c5.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index("Applied"), key="add_status")
    last_update = c6.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=LAST_UPDATE_OPTIONS.index("Submitted"), key="add_lastupdate")

    if st.button("Save Job", key="save_job_btn"):
        if not company.strip() or not position.strip():
            st.warning("Company and Position are required.")
        else:
            try:
                db.from_("jobs").insert({
                    "user_id": st.session_state["user_id"],
                    "date_applied": str(date_applied),
                    "company": company.strip(),
                    "position": position.strip(),
                    "visa": visa,
                    "status": status,
                    "last_update": last_update
                }).execute()
                st.success("Saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")


# ----------------------------
# Search + Filters
# ----------------------------
st.markdown("## Applications List")

filter_row = st.columns([2, 1, 1, 1, 1])
search = filter_row[0].text_input("Search (company / position / status / last update)", key="search_box")

status_filter = filter_row[1].selectbox("Status Filter", ["All"] + STATUS_OPTIONS, index=0, key="filter_status")
visa_filter = filter_row[2].selectbox("Visa Filter", ["All", "Yes", "No"], index=0, key="filter_visa")
color_filter = filter_row[3].selectbox("Color Group", ["All", "Green", "Yellow", "Orange", "Red"], index=0, key="filter_color")
sort_choice = filter_row[4].selectbox("Sort", ["Auto (best)", "Date Applied (newest)", "Company (A-Z)"], index=0, key="sort_choice")

view_df = df.copy()

if not view_df.empty:
    # Apply filters
    if status_filter != "All":
        view_df = view_df[view_df["status"].astype(str) == status_filter]

    if visa_filter != "All":
        view_df = view_df[view_df["visa"].astype(str) == visa_filter]

    if color_filter != "All":
        view_df = view_df[view_df["ColorGroup"].astype(str) == color_filter]

    if search.strip():
        q = search.strip().lower()
        mask = (
            view_df["company"].astype(str).str.lower().str.contains(q, na=False)
            | view_df["position"].astype(str).str.lower().str.contains(q, na=False)
            | view_df["status"].astype(str).str.lower().str.contains(q, na=False)
            | view_df["last_update"].astype(str).str.lower().str.contains(q, na=False)
        )
        view_df = view_df[mask]

    # Apply sorting choice
    if sort_choice == "Auto (best)":
        view_df = view_df.sort_values(by=["GroupPriority", "date_applied"], ascending=[True, False], kind="mergesort")
    elif sort_choice == "Date Applied (newest)":
        view_df = view_df.sort_values(by=["date_applied"], ascending=[False], kind="mergesort")
    elif sort_choice == "Company (A-Z)":
        view_df = view_df.sort_values(by=["company"], ascending=[True], kind="mergesort")

    view_df = view_df.reset_index(drop=True)
    view_df["Job #"] = range(1, len(view_df) + 1)


# ----------------------------
# Display table (color coded)
# ----------------------------
table_cols = ["Job #", "date_applied", "company", "position", "visa", "status", "last_update"]
if view_df.empty:
    st.info("No applications found yet (or filters removed everything).")
else:
    show_df = view_df[table_cols].rename(columns={
        "date_applied": "Date Applied",
        "company": "Company",
        "position": "Position",
        "visa": "Visa Sponsorship",
        "status": "Status",
        "last_update": "Last Update",
        "ColorGroup": "Color Group",
    })
    st.dataframe(style_table(show_df), use_container_width=True, height=420)


st.caption(
    "Rules: Red = Rejected (always bottom) | Green = In progress/interview/offer | "
    "Orange = No update ≥ 21 days | Yellow = ongoing/recent. "
    "Auto sorting: Green → Yellow → Orange → Red, then newest Date Applied."
)


# ----------------------------
# Edit / Delete existing jobs
# ----------------------------
st.markdown("---")
st.subheader("Edit / Update an Existing Entry")

if df.empty:
    st.info("Nothing to edit yet.")
else:
    # We use the *real* id from Supabase
    # Make selection label nice
    df_for_picker = df.copy()
    if "date_applied" in df_for_picker.columns:
        df_for_picker["date_applied"] = df_for_picker["date_applied"].apply(lambda x: x if isinstance(x, date) else to_date(x))

    df_for_picker["label"] = df_for_picker.apply(
        lambda r: f'#{int(r["Job #"])} | {r.get("company","")} — {r.get("position","")} ({r.get("date_applied")})',
        axis=1
    )

    selected_label = st.selectbox(
        "Select a job to edit",
        options=df_for_picker["label"].tolist(),
        key="edit_picker"
    )

    selected_row = df_for_picker[df_for_picker["label"] == selected_label].iloc[0]
    job_id = int(selected_row["id"])

    e1, e2, e3 = st.columns(3)
    new_company = e1.text_input("Company", value=str(selected_row.get("company", "")), key=f"edit_company_{job_id}")
    new_position = e2.text_input("Position", value=str(selected_row.get("position", "")), key=f"edit_position_{job_id}")
    new_date = e3.date_input("Date Applied", value=to_date(selected_row.get("date_applied", date.today())), key=f"edit_date_{job_id}")

    e4, e5, e6 = st.columns(3)
    new_visa = e4.selectbox("Visa Sponsorship", ["Yes", "No"], index=(0 if str(selected_row.get("visa", "No")) == "Yes" else 1), key=f"edit_visa_{job_id}")

    current_status = str(selected_row.get("status", "Applied"))
    if current_status not in STATUS_OPTIONS:
        current_status = "Applied"
    new_status = e5.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(current_status), key=f"edit_status_{job_id}")

    current_lu = str(selected_row.get("last_update", "Submitted"))
    if current_lu not in LAST_UPDATE_OPTIONS:
        current_lu = "Submitted"
    new_last_update = e6.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=LAST_UPDATE_OPTIONS.index(current_lu), key=f"edit_lastupdate_{job_id}")

    b1, b2 = st.columns([1, 1])
    if b1.button("✅ Save Changes", key=f"btn_save_{job_id}", use_container_width=True):
        try:
            db.from_("jobs").update({
                "company": new_company.strip(),
                "position": new_position.strip(),
                "date_applied": str(new_date),
                "visa": new_visa,
                "status": new_status,
                "last_update": new_last_update
            }).eq("id", job_id).execute()
            st.success("Updated!")
            st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")

    if b2.button("🗑️ Delete Entry", key=f"btn_delete_{job_id}", use_container_width=True):
        try:
            db.from_("jobs").delete().eq("id", job_id).execute()
            st.success("Deleted!")
            st.rerun()
        except Exception as e:
            st.error(f"Delete failed: {e}")

