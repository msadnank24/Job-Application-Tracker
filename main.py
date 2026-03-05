import streamlit as st
import pandas as pd
from datetime import date, datetime, timedelta
from supabase import create_client, Client

# -----------------------------
# Config
# -----------------------------
st.set_page_config(page_title="Job Application Tracker", layout="wide")

STATUS_OPTIONS = ["Applied", "In Process", "Rejected"]
LAST_UPDATE_OPTIONS = [
    "Submitted",
    "Assessment Sent",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Completed",
    "Offer",
    "Rejected",
    "No Update Yet",
]

# Color rules (as you described)
# Red = Rejected
# Green = In recruitment process (Status == In Process)
# Yellow = Applied recently / ongoing
# Orange = No update for long time (>= 21 days since date_applied)
NO_UPDATE_DAYS = 21

# Sort order: Green (top) -> Yellow -> Orange -> Red (bottom)
GROUP_ORDER = {"green": 0, "yellow": 1, "orange": 2, "red": 3}

# -----------------------------
# Supabase client
# -----------------------------
def get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY in Streamlit Secrets.")
        st.stop()
    return create_client(url, key)

sb = get_supabase()

# -----------------------------
# Auth helpers
# -----------------------------
def is_logged_in() -> bool:
    return st.session_state.get("sb_user") is not None

def current_user_id():
    u = st.session_state.get("sb_user")
    return u.get("id") if u else None

def logout():
    try:
        sb.auth.sign_out()
    except Exception:
        pass
    st.session_state["sb_user"] = None
    st.session_state["sb_session"] = None
    st.rerun()

def login_ui():
    st.sidebar.header("Account")

    if is_logged_in():
        u = st.session_state["sb_user"]
        st.sidebar.success(f"Logged in: {u.get('email', '')}")
        if st.sidebar.button("Log out"):
            logout()
        return

    tab1, tab2 = st.sidebar.tabs(["Login", "Sign up"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pw")
        if st.button("Login"):
            try:
                res = sb.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state["sb_session"] = res.session.model_dump() if res.session else None
                st.session_state["sb_user"] = res.user.model_dump() if res.user else None
                st.success("Logged in!")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with tab2:
        email2 = st.text_input("Email", key="signup_email")
        password2 = st.text_input("Password", type="password", key="signup_pw")
        if st.button("Create account"):
            try:
                res = sb.auth.sign_up({"email": email2, "password": password2})
                # If email confirmation is ON in Supabase, user must confirm email.
                st.success("Account created. If confirmation is enabled, check your email.")
            except Exception as e:
                st.error(f"Signup failed: {e}")

# -----------------------------
# DB helpers
# -----------------------------
def fetch_jobs(user_id: str) -> pd.DataFrame:
    resp = sb.table("jobs").select("*").eq("user_id", user_id).execute()
    data = resp.data or []
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame(columns=[
            "id", "user_id", "date_applied", "company", "position", "visa", "status", "last_update", "created_at"
        ])
    # Normalize dates
    if "date_applied" in df.columns:
        df["date_applied"] = pd.to_datetime(df["date_applied"]).dt.date
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    return df

def insert_job(user_id: str, date_applied: date, company: str, position: str, visa: str, status: str, last_update: str):
    sb.table("jobs").insert({
        "user_id": user_id,
        "date_applied": str(date_applied),
        "company": company.strip(),
        "position": position.strip(),
        "visa": visa,
        "status": status,
        "last_update": last_update
    }).execute()

def update_job(job_id: int, updates: dict):
    # dates must be string
    if "date_applied" in updates and isinstance(updates["date_applied"], date):
        updates["date_applied"] = str(updates["date_applied"])
    sb.table("jobs").update(updates).eq("id", job_id).execute()

def delete_job(job_id: int):
    sb.table("jobs").delete().eq("id", job_id).execute()

# -----------------------------
# Coloring + sorting
# -----------------------------
def compute_group(row) -> str:
    status = str(row.get("status", ""))
    last_update = str(row.get("last_update", ""))
    d = row.get("date_applied")

    if status == "Rejected" or last_update == "Rejected":
        return "red"
    if status == "In Process":
        return "green"

    # Applied / other -> decide yellow vs orange based on age if no update
    # "No Update Yet" means we consider the time rule
    if last_update == "No Update Yet":
        if isinstance(d, date):
            if (date.today() - d).days >= NO_UPDATE_DAYS:
                return "orange"
        return "yellow"

    # If they have some activity (assessment/interview/etc) but status still Applied,
    # treat as yellow ongoing
    return "yellow"

def style_rows(df: pd.DataFrame) -> pd.DataFrame:
    # background colors chosen for readability (orange fixed to be readable)
    def row_style(row):
        grp = row["_group"]
        if grp == "green":
            return ["background-color: #1f9d55; color: white;"] * len(row)
        if grp == "yellow":
            return ["background-color: #f2d45c; color: black;"] * len(row)
        if grp == "orange":
            return ["background-color: #f59e0b; color: black;"] * len(row)  # readable orange
        if grp == "red":
            return ["background-color: #dc2626; color: white;"] * len(row)
        return [""] * len(row)

    return df.style.apply(row_style, axis=1)

def sort_jobs(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df["_group"] = df.apply(compute_group, axis=1)
    df["_group_order"] = df["_group"].map(GROUP_ORDER).fillna(99)

    # Sort by group order then by date_applied (newest first) then created_at (newest first)
    # Rejected always bottom due to group order
    df = df.sort_values(
        by=["_group_order", "date_applied", "created_at"],
        ascending=[True, False, False],
        na_position="last"
    ).reset_index(drop=True)

    # Add Job # numbering after sorting
    df.insert(0, "Job #", range(1, len(df) + 1))
    return df

# -----------------------------
# App UI
# -----------------------------
st.title("Job Application Tracker")

# Show login UI in sidebar
login_ui()

if not is_logged_in():
    st.info("Please log in or sign up in the sidebar to use your personal tracker.")
    st.stop()

uid = current_user_id()

# Load jobs
df = fetch_jobs(uid)
df = sort_jobs(df)

# -----------------------------
# Filters / Search
# -----------------------------
with st.expander("🔎 Filter & Search", expanded=False):
    colA, colB, colC, colD = st.columns([2, 2, 2, 2])

    search_text = colA.text_input("Search (company / position)", value="")
    filter_status = colB.multiselect("Filter by Status", STATUS_OPTIONS, default=[])
    filter_visa = colC.multiselect("Filter by Visa Sponsorship", ["Yes", "No"], default=[])
    filter_group = colD.multiselect("Filter by Color Group", ["green", "yellow", "orange", "red"], default=[])

def apply_filters(df_in: pd.DataFrame) -> pd.DataFrame:
    out = df_in.copy()
    if out.empty:
        return out

    if search_text.strip():
        s = search_text.strip().lower()
        out = out[
            out["company"].astype(str).str.lower().str.contains(s, na=False) |
            out["position"].astype(str).str.lower().str.contains(s, na=False)
        ]

    if filter_status:
        out = out[out["status"].isin(filter_status)]

    if filter_visa:
        out = out[out["visa"].isin(filter_visa)]

    if filter_group:
        out = out[out["_group"].isin(filter_group)]

    # re-number after filtering
    out = out.reset_index(drop=True)
    if "Job #" in out.columns:
        out["Job #"] = range(1, len(out) + 1)
    return out

df_view = apply_filters(df)

# -----------------------------
# Add new job
# -----------------------------
with st.expander("➕ Add New Application", expanded=True):
    c1, c2, c3 = st.columns(3)
    company = c1.text_input("Company Name", value="")
    position = c2.text_input("Position", value="")
    date_applied = c3.date_input("Date Applied", value=date.today())

    c4, c5, c6 = st.columns(3)
    visa = c4.selectbox("Visa Sponsorship", ["Yes", "No"], index=1)
    status = c5.selectbox("Status", STATUS_OPTIONS, index=0)
    last_update = c6.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=LAST_UPDATE_OPTIONS.index("Submitted"))

    if st.button("Save Job"):
        if not company.strip() or not position.strip():
            st.warning("Company and Position are required.")
        else:
            try:
                insert_job(uid, date_applied, company, position, visa, status, last_update)
                st.success("Saved!")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

# -----------------------------
# Edit / Delete existing
# -----------------------------
st.subheader("Applications List")

if df_view.empty:
    st.write("No jobs saved yet.")
else:
    # Display styled table (hide internal columns)
    display_cols = ["Job #", "date_applied", "company", "position", "visa", "status", "last_update"]
    pretty = df_view.copy()
    pretty = pretty.rename(columns={
        "date_applied": "Date Applied",
        "company": "Company",
        "position": "Position",
        "visa": "Visa Sponsorship",
        "status": "Status",
        "last_update": "Last Update"
    })

    # Keep group columns for styling, but not shown
    # We'll style on the actual df_view then display renamed columns
    # Easiest: style df_view, but select only display cols after styling
    styled = style_rows(df_view[["Job #","date_applied","company","position","visa","status","last_update","_group"]])
    # Drop _group from visual but keep styling row-wise by using same dataframe width
    # We'll just show it as hidden by renaming to blank and narrow; simpler: show without _group
    # Instead, rebuild style on df_view without _group:
    styled = style_rows(df_view[["Job #","date_applied","company","position","visa","status","last_update","_group"]]).hide(axis="columns", subset=["_group"])
    styled = styled.format({"date_applied": lambda x: x.strftime("%Y-%m-%d") if isinstance(x, date) else str(x)})
    st.dataframe(styled, use_container_width=True, height=340)

    st.caption(
        "Rules: Red=Rejected | Green=In Process | Orange=No update ≥ 21 days (only when Last Update = 'No Update Yet') | Yellow=Recent/Ongoing. "
        "Sorted: Green → Yellow → Orange → Red, then newest Date Applied."
    )

    st.divider()
    st.subheader("✏️ Edit / Delete a Job")

    # Choose by Job # (stable after sorting/filtering)
    job_numbers = df_view["Job #"].tolist()
    selected_job_no = st.selectbox("Select Job # to edit", job_numbers, key="select_job_to_edit")

    # Get row
    row = df_view[df_view["Job #"] == selected_job_no].iloc[0]
    job_id = int(row["id"])

    ec1, ec2, ec3 = st.columns(3)
    new_company = ec1.text_input("Company", value=str(row["company"]), key=f"edit_company_{job_id}")
    new_position = ec2.text_input("Position", value=str(row["position"]), key=f"edit_position_{job_id}")
    new_date = ec3.date_input("Date Applied", value=row["date_applied"] if isinstance(row["date_applied"], date) else date.today(), key=f"edit_date_{job_id}")

    ec4, ec5, ec6 = st.columns(3)
    new_visa = ec4.selectbox("Visa Sponsorship", ["Yes", "No"], index=(0 if str(row["visa"]) == "Yes" else 1), key=f"edit_visa_{job_id}")
    # Unique keys fix the duplicate selectbox error
    new_status = ec5.selectbox(
        "Status",
        STATUS_OPTIONS,
        index=STATUS_OPTIONS.index(str(row["status"])) if str(row["status"]) in STATUS_OPTIONS else 0,
        key=f"edit_status_{job_id}"
    )
    new_last_update = ec6.selectbox(
        "Last Update",
        LAST_UPDATE_OPTIONS,
        index=LAST_UPDATE_OPTIONS.index(str(row["last_update"])) if str(row["last_update"]) in LAST_UPDATE_OPTIONS else 0,
        key=f"edit_lastupdate_{job_id}"
    )

    b1, b2, b3 = st.columns([1,1,6])
    if b1.button("Update Job", key=f"btn_update_{job_id}"):
        try:
            update_job(job_id, {
                "company": new_company.strip(),
                "position": new_position.strip(),
                "date_applied": new_date,
                "visa": new_visa,
                "status": new_status,
                "last_update": new_last_update
            })
            st.success("Updated!")
            st.rerun()
        except Exception as e:
            st.error(f"Update failed: {e}")

    if b2.button("Delete Job", key=f"btn_delete_{job_id}"):
        try:
            delete_job(job_id)
            st.warning("Deleted.")
            st.rerun()
        except Exception as e:
            st.error(f"Delete failed: {e}")
