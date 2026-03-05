import os
from datetime import date, datetime
import pandas as pd
import streamlit as st

from supabase import create_client


# =============================
# CONFIG
# =============================
st.set_page_config(page_title="Job Application Tracker", layout="wide")

st.title("Job Application Tracker")


# =============================
# SUPABASE CLIENT
# =============================
def get_supabase():
    # Streamlit Cloud uses st.secrets; local can use env vars
    supabase_url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "")).strip()
    supabase_key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", "")).strip()

    if not supabase_url or not supabase_key:
        st.error(
            "Missing Supabase credentials. Add SUPABASE_URL and SUPABASE_ANON_KEY in Streamlit Secrets."
        )
        st.stop()

    return create_client(supabase_url, supabase_key)


supabase = get_supabase()


# =============================
# OPTIONS (Dropdowns)
# =============================
VISA_OPTIONS = ["Yes", "No"]

STATUS_OPTIONS = [
    "Applied",
    "In Process",
    "No Response",
    "Rejected",
]

LAST_UPDATE_OPTIONS = [
    "Submitted",
    "Assessment Sent",
    "Assessment Passed",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Confirmed",
    "Offer Received",
    "Offer Accepted",
    "No Update Yet",
    "Rejected",
]

GREEN_UPDATES = {
    "Assessment Sent",
    "Assessment Passed",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Confirmed",
    "Offer Received",
    "Offer Accepted",
}


# =============================
# COLOR RULES
# =============================
def safe_date(x):
    # Supabase returns ISO string or date
    if x is None or x == "":
        return None
    if isinstance(x, date):
        return x
    try:
        return datetime.fromisoformat(str(x)).date()
    except Exception:
        return None


def compute_color_group(status: str, last_update: str, date_applied_val) -> str:
    s = (status or "").strip()
    lu = (last_update or "").strip()
    d = safe_date(date_applied_val) or date.today()

    # Red = rejected
    if s == "Rejected" or lu == "Rejected":
        return "Red"

    # Green = active progress
    if s == "In Process" or lu in GREEN_UPDATES:
        return "Green"

    # Orange = no update 21+ days
    if lu == "No Update Yet":
        days = (date.today() - d).days
        if days >= 21:
            return "Orange"

    # Yellow = everything else
    return "Yellow"


def row_style(row: pd.Series):
    group = row.get("_color_group", "Yellow")

    # Background + text color
    # (Fix readability on orange/yellow by using dark text)
    if group == "Green":
        bg = "#26A65B"
        fg = "white"
    elif group == "Yellow":
        bg = "#F4D03F"
        fg = "#111111"
    elif group == "Orange":
        bg = "#F39C12"
        fg = "#111111"
    else:  # Red
        bg = "#E74C3C"
        fg = "white"

    return [f"background-color: {bg}; color: {fg};"] * len(row)


COLOR_ORDER = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}


# =============================
# AUTH UI
# =============================
def auth_ui():
    st.subheader("Login / Sign up")

    tabs = st.tabs(["Login", "Sign up"])

    with tabs[0]:
        with st.form("login_form"):
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pass")
            login_btn = st.form_submit_button("Login")

        if login_btn:
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state["sb_session"] = res.session
                st.session_state["sb_user"] = res.user
                st.success("Logged in ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with tabs[1]:
        with st.form("signup_form"):
            email = st.text_input("Email", key="signup_email")
            password = st.text_input("Password", type="password", key="signup_pass")
            signup_btn = st.form_submit_button("Create account")

        if signup_btn:
            try:
                res = supabase.auth.sign_up({"email": email, "password": password})
                st.success("Account created ✅ Now login from the Login tab.")
            except Exception as e:
                st.error(f"Sign up failed: {e}")


def logout_btn():
    if st.button("Logout", use_container_width=True):
        try:
            supabase.auth.sign_out()
        except Exception:
            pass
        st.session_state.pop("sb_session", None)
        st.session_state.pop("sb_user", None)
        st.rerun()


# =============================
# DATA ACCESS
# =============================
def require_user():
    user = st.session_state.get("sb_user")
    if not user:
        auth_ui()
        st.stop()
    return user


def load_jobs(user_id: str):
    # RLS will already limit, but filtering makes it explicit & safer
    res = (
        supabase.table("jobs")
        .select("id,user_id,date_applied,company,position,visa,status,last_update,created_at")
        .eq("user_id", user_id)
        .execute()
    )
    data = res.data or []
    df = pd.DataFrame(data)

    if df.empty:
        # Provide correct columns so UI still renders
        df = pd.DataFrame(
            columns=["id", "user_id", "date_applied", "company", "position", "visa", "status", "last_update", "created_at"]
        )
    return df


def insert_job(payload: dict):
    return supabase.table("jobs").insert(payload).execute()


def update_job(job_id: int, user_id: str, payload: dict):
    # RLS protects, but we also add user_id filter
    return supabase.table("jobs").update(payload).eq("id", job_id).eq("user_id", user_id).execute()


def delete_job(job_id: int, user_id: str):
    return supabase.table("jobs").delete().eq("id", job_id).eq("user_id", user_id).execute()


# =============================
# MAIN APP
# =============================
user = require_user()
logout_btn()

user_id = user.id

st.divider()

# ---------- Add new ----------
with st.expander("➕ Add New Application", expanded=True):
    with st.form("add_job_form", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 2, 2])

        with c1:
            company = st.text_input("Company Name")
            position = st.text_input("Position")

        with c2:
            date_applied = st.date_input("Date Applied", value=date.today())
            visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=1, key="add_visa")

        with c3:
            status = st.selectbox("Status", STATUS_OPTIONS, index=0, key="add_status")
            last_update = st.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=0, key="add_last_update")

        save_btn = st.form_submit_button("Save Job")

    if save_btn:
        if not company.strip() or not position.strip():
            st.error("Company and Position are required.")
        else:
            payload = {
                "user_id": user_id,  # IMPORTANT for RLS insert policy
                "date_applied": str(date_applied),
                "company": company.strip(),
                "position": position.strip(),
                "visa": visa,
                "status": status,
                "last_update": last_update,
            }

            try:
                insert_job(payload)
                st.success("Saved ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

# ---------- Load jobs ----------
df = load_jobs(user_id)

# Normalize types
df["date_applied"] = df["date_applied"].apply(safe_date)
df["company"] = df["company"].astype(str)
df["position"] = df["position"].astype(str)
df["visa"] = df["visa"].astype(str)
df["status"] = df["status"].astype(str)
df["last_update"] = df["last_update"].astype(str)

# Compute color group (internal only)
# --- SAFETY: remove internal columns if they already exist (or exist multiple times) ---
internal_cols = {"_color_group", "_color_rank", "Job #"}
df = df.loc[:, ~df.columns.isin(list(internal_cols))]

# Also remove duplicated columns (this is the usual cause of your ValueError)
df = df.loc[:, ~df.columns.duplicated()]

# --- Compute color group safely (no .apply expansion issues) ---
if df.empty:
    df["_color_group"] = []
else:
    df["_color_group"] = [
        compute_color_group(r.get("status"), r.get("last_update"), r.get("date_applied"))
        for _, r in df.iterrows()
    ]
# Sort key
df["_color_rank"] = df["_color_group"].map(COLOR_ORDER).fillna(9).astype(int)

# Create Job # numbering AFTER sorting
def apply_auto_sort(dataframe: pd.DataFrame) -> pd.DataFrame:
    # Order: Green -> Yellow -> Orange -> Red (Rejected at bottom),
    # and inside each group sort by Date Applied (newest first).
    return dataframe.sort_values(
        by=["_color_rank", "date_applied", "created_at"],
        ascending=[True, False, False],
        kind="mergesort",  # stable
        na_position="last",
    )


# ---------- Filters + Search ----------
st.subheader("Applications List")

f1, f2, f3, f4, f5 = st.columns([2.5, 1.2, 1.2, 1.2, 1.2])

with f1:
    query = st.text_input("Search (company / position / status / last update)", "")

with f2:
    status_filter = st.selectbox("Status Filter", ["All"] + STATUS_OPTIONS, index=0, key="filter_status")

with f3:
    visa_filter = st.selectbox("Visa Filter", ["All"] + VISA_OPTIONS, index=0, key="filter_visa")

with f4:
    color_filter = st.selectbox("Color Group", ["All", "Green", "Yellow", "Orange", "Red"], index=0, key="filter_color")

with f5:
    sort_choice = st.selectbox(
        "Sort",
        ["Auto (best)", "Date Applied (Newest)", "Date Applied (Oldest)", "Company (A-Z)"],
        index=0,
        key="filter_sort",
    )

filtered = df.copy()

if status_filter != "All":
    filtered = filtered[filtered["status"] == status_filter]

if visa_filter != "All":
    filtered = filtered[filtered["visa"] == visa_filter]

if color_filter != "All":
    filtered = filtered[filtered["_color_group"] == color_filter]

if query.strip():
    q = query.strip().lower()
    mask = (
        filtered["company"].str.lower().str.contains(q, na=False)
        | filtered["position"].str.lower().str.contains(q, na=False)
        | filtered["status"].str.lower().str.contains(q, na=False)
        | filtered["last_update"].str.lower().str.contains(q, na=False)
    )
    filtered = filtered[mask]

# Apply sort
if sort_choice == "Auto (best)":
    filtered = apply_auto_sort(filtered)
elif sort_choice == "Date Applied (Newest)":
    filtered = filtered.sort_values(by=["date_applied"], ascending=[False], na_position="last")
elif sort_choice == "Date Applied (Oldest)":
    filtered = filtered.sort_values(by=["date_applied"], ascending=[True], na_position="last")
else:
    filtered = filtered.sort_values(by=["company"], ascending=[True], na_position="last")

# Job numbering (based on CURRENT view)
filtered = filtered.reset_index(drop=True)
filtered.insert(0, "Job #", filtered.index + 1)

# Build display dataframe (DO NOT show internal columns)
display_cols = ["Job #", "date_applied", "company", "position", "visa", "status", "last_update"]
display_df = filtered[display_cols].rename(
    columns={
        "date_applied": "Date Applied",
        "company": "Company",
        "position": "Position",
        "visa": "Visa Sponsorship",
        "status": "Status",
        "last_update": "Last Update",
    }
)

# Styling based on hidden _color_group, but apply in same row order as display
# Rebuild a styling frame aligned to display_df rows
style_base = filtered.copy()

styled = display_df.style.apply(
    lambda row: row_style(style_base.loc[row.name]),
    axis=1,
)

st.caption(
    "Rules: Red = Rejected | Green = In process / interviews / assessments | "
    "Orange = No update ≥ 21 days | Yellow = Everything else. "
    "Auto Sort: Green → Yellow → Orange → Red, newest Date Applied first inside each group."
)

st.dataframe(styled, use_container_width=True, hide_index=True)

st.divider()

# ---------- Edit / Update / Delete ----------
st.subheader("Edit / Update Existing Entry")

if df.empty:
    st.info("No saved jobs yet.")
else:
    # Use the *real* IDs for editing
    # We show a readable label but store id
    edit_df = apply_auto_sort(df.copy()).reset_index(drop=True)
    edit_df.insert(0, "Job #", edit_df.index + 1)

    options = []
    for _, r in edit_df.iterrows():
        options.append(
            (
                int(r["id"]),
                f'#{int(r["Job #"])} | {safe_date(r["date_applied"])} | {r["company"]} | {r["position"]}',
            )
        )

    selected = st.selectbox(
        "Select a job to edit",
        options=options,
        format_func=lambda x: x[1],
        key="edit_select",
    )

    selected_id = selected[0]
    current = df[df["id"] == selected_id].iloc[0].to_dict()

    with st.form("edit_form"):
        ec1, ec2, ec3 = st.columns([2, 2, 2])

        with ec1:
            new_company = st.text_input("Company Name", value=str(current.get("company", "")), key="edit_company")
            new_position = st.text_input("Position", value=str(current.get("position", "")), key="edit_position")

        with ec2:
            new_date_applied = st.date_input(
                "Date Applied",
                value=safe_date(current.get("date_applied")) or date.today(),
                key="edit_date",
            )
            new_visa = st.selectbox(
                "Visa Sponsorship",
                VISA_OPTIONS,
                index=VISA_OPTIONS.index(str(current.get("visa"))) if str(current.get("visa")) in VISA_OPTIONS else 1,
                key="edit_visa",
            )

        with ec3:
            cur_status = str(current.get("status", "Applied"))
            cur_last = str(current.get("last_update", "Submitted"))

            new_status = st.selectbox(
                "Status",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(cur_status) if cur_status in STATUS_OPTIONS else 0,
                key="edit_status",
            )
            new_last_update = st.selectbox(
                "Last Update",
                LAST_UPDATE_OPTIONS,
                index=LAST_UPDATE_OPTIONS.index(cur_last) if cur_last in LAST_UPDATE_OPTIONS else 0,
                key="edit_last_update",
            )

        b1, b2 = st.columns([1, 1])
        with b1:
            update_btn = st.form_submit_button("Update")
        with b2:
            delete_btn = st.form_submit_button("Delete", type="secondary")

    if update_btn:
        if not new_company.strip() or not new_position.strip():
            st.error("Company and Position are required.")
        else:
            payload = {
                "date_applied": str(new_date_applied),
                "company": new_company.strip(),
                "position": new_position.strip(),
                "visa": new_visa,
                "status": new_status,
                "last_update": new_last_update,
                # IMPORTANT: keep user_id unchanged (RLS depends on it)
            }
            try:
                update_job(selected_id, user_id, payload)
                st.success("Updated ✅")
                st.rerun()
            except Exception as e:
                st.error(f"Update failed: {e}")

    if delete_btn:
        try:
            delete_job(selected_id, user_id)
            st.success("Deleted ✅")
            st.rerun()
        except Exception as e:
            st.error(f"Delete failed: {e}")

