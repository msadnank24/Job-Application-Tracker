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
    if status == "Rejected" or last_update == "Rejected":
        return "red"

    # GREEN
    if status in GREEN_UPDATES or last_update in GREEN_UPDATES:
        return "green"

    # ORANGE: Applied + (No Update Yet/Submitted) AND >= 21 days since Date Applied
    if status == "Applied" and (last_update in NO_PROGRESS_UPDATES) and days_since >= ORANGE_DAYS:
        return "orange"

    # YELLOW
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


def get_authed_client():
    """
    Build a client with the current user's auth session attached,
    so RLS works properly for select/insert/update/delete.
    """
    client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

    access = st.session_state.get("sb_access_token")
    refresh = st.session_state.get("sb_refresh_token")

    if access and refresh:
        try:
            client.auth.set_session(access, refresh)
        except Exception:
            pass

    if access:
        try:
            client.postgrest.auth(access)
        except Exception:
            pass

    return client


def get_user():
    try:
        client = get_authed_client()
        res = client.auth.get_user()
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
    client = get_authed_client()
    resp = client.table("jobs").select("*").eq("user_id", user_id).execute()
    rows = resp.data or []
    df = pd.DataFrame(rows)

    if df.empty:
        return pd.DataFrame(
            columns=[
                "id", "date_applied", "company", "position", "visa", "status", "last_update",
                "job_link", "salary", "location", "cv_used", "cover_letter_used", "notes"
            ]
        )

    df["date_applied"] = df["date_applied"].apply(_safe_date)

    # ensure optional columns exist
    for col in ["job_link", "salary", "location", "cv_used", "cover_letter_used", "notes"]:
        if col not in df.columns:
            df[col] = ""

    return df


def insert_job(user_id: str, payload: dict):
    client = get_authed_client()
    payload = dict(payload)
    payload["user_id"] = user_id
    return client.table("jobs").insert(payload).execute()


def update_job(user_id: str, job_id: int, payload: dict):
    client = get_authed_client()
    return client.table("jobs").update(payload).eq("id", job_id).eq("user_id", user_id).execute()


def delete_job(user_id: str, job_id: int):
    client = get_authed_client()
    return client.table("jobs").delete().eq("id", job_id).eq("user_id", user_id).execute()


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
    with st.form("add_job_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            company = st.text_input("Company Name")
            visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=1)
        with c2:
            position = st.text_input("Position")
            status = st.selectbox("Status", STATUS_OPTIONS, index=0)
        with c3:
            date_applied = st.date_input("Date Applied", value=date.today())
            last_update = st.selectbox(
                "Last Update",
                LAST_UPDATE_OPTIONS,
                index=LAST_UPDATE_OPTIONS.index("Submitted"),
            )

        with st.expander("More Details"):
            job_link = st.text_input("Job Advert Link")
            salary = st.text_input("Salary")
            location = st.text_input("Job Location")
            cv_used = st.text_area("CV Used")
            cover_letter_used = st.text_area("Cover Letter Used")
            notes = st.text_area("Additional Information / Questions Asked / Notes")

        submitted = st.form_submit_button("Save Job")

        if submitted:
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
                            "job_link": job_link.strip(),
                            "salary": salary.strip(),
                            "location": location.strip(),
                            "cv_used": cv_used.strip(),
                            "cover_letter_used": cover_letter_used.strip(),
                            "notes": notes.strip(),
                        },
                    )
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")

# ---------------------------
# Load data
# ---------------------------
df = fetch_jobs(user.id)
st.subheader("Applications List")

if not df.empty:
    df["_color_group"] = df.apply(color_group, axis=1)
    df["_group_rank"] = df["_color_group"].apply(group_rank)

# ---------------------------
# Filters + Search + Sort
# ---------------------------
f1, f2, f3, f4, f5 = st.columns([3, 2, 2, 2, 2])

with f1:
    q = st.text_input("Search (company / position / status / last update)", value="")
with f2:
    status_filter = st.selectbox("Status Filter", ["All"] + STATUS_OPTIONS)
with f3:
    visa_filter = st.selectbox("Visa Filter", ["All"] + VISA_OPTIONS)
with f4:
    color_filter = st.selectbox("Color Group", ["All", "green", "yellow", "orange", "red"])
with f5:
    sort_mode = st.selectbox(
        "Sort",
        ["Auto (best)", "Date Applied (newest)", "Date Applied (oldest)", "Company (A-Z)", "Company (Z-A)"],
    )

filtered = df.copy()

if not filtered.empty:
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
# Display table with SERIAL Job #
# ---------------------------
if df.empty:
    st.info("No jobs yet. Add one above.")
else:
    filtered = filtered.reset_index(drop=True)
    groups = filtered["_color_group"].copy()

    display_df = pd.DataFrame()
    display_df["Job #"] = range(1, len(filtered) + 1)
    display_df["Date Applied"] = filtered["date_applied"]
    display_df["Company"] = filtered["company"]
    display_df["Position"] = filtered["position"]
    display_df["Visa Sponsorship"] = filtered["visa"]
    display_df["Status"] = filtered["status"]
    display_df["Last Update"] = filtered["last_update"]

    def apply_row_style(row):
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
# View more details
# ---------------------------
st.subheader("View More Details")

if df.empty:
    st.stop()

filtered_for_details = filtered.copy()
if filtered_for_details.empty:
    st.info("No rows match your current filters.")
    st.stop()

pick_job_no = st.selectbox("Select Job # to View More", range(1, len(filtered_for_details) + 1), index=0, key="view_pick")
selected_row = filtered_for_details.iloc[pick_job_no - 1]

with st.expander("More Details", expanded=True):
    st.write(f"**Company:** {selected_row.get('company', '')}")
    st.write(f"**Position:** {selected_row.get('position', '')}")
    st.write(f"**Date Applied:** {selected_row.get('date_applied', '')}")
    st.write(f"**Visa Sponsorship:** {selected_row.get('visa', '')}")
    st.write(f"**Status:** {selected_row.get('status', '')}")
    st.write(f"**Last Update:** {selected_row.get('last_update', '')}")
    st.write(f"**Salary:** {selected_row.get('salary', '')}")
    st.write(f"**Location:** {selected_row.get('location', '')}")

    job_link = str(selected_row.get("job_link", "") or "").strip()
    if job_link:
        st.markdown(f"**Job Advert Link:** [Open Job Advert]({job_link})")

    st.write("**CV Used:**")
    st.text(selected_row.get("cv_used", "") or "")

    st.write("**Cover Letter Used:**")
    st.text(selected_row.get("cover_letter_used", "") or "")

    st.write("**Additional Information / Questions Asked / Notes:**")
    st.text(selected_row.get("notes", "") or "")

# ---------------------------
# Edit / Delete
# ---------------------------
st.subheader("Edit / Update Existing Entry")

df_pick = filtered_for_details.copy()
df_pick["label"] = df_pick.apply(
    lambda r: f'#{r["id"]} — {r.get("company","")} / {r.get("position","")} ({r.get("status","")})',
    axis=1,
)

pick = st.selectbox("Select a job to edit", df_pick["label"].tolist(), key="edit_pick")
current = df_pick[df_pick["label"] == pick].iloc[0].to_dict()
job_id = int(current["id"])

with st.form("edit_job_form"):
    e1, e2, e3 = st.columns(3)
    with e1:
        new_company = st.text_input("Company Name", value=str(current.get("company", "")))
        new_visa = st.selectbox(
            "Visa Sponsorship",
            VISA_OPTIONS,
            index=VISA_OPTIONS.index(str(current.get("visa", "No"))) if str(current.get("visa", "No")) in VISA_OPTIONS else 1,
        )
    with e2:
        new_position = st.text_input("Position", value=str(current.get("position", "")))
        new_status = st.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(str(current.get("status", "Applied"))) if str(current.get("status", "Applied")) in STATUS_OPTIONS else 0,
        )
    with e3:
        cur_date = _safe_date(current.get("date_applied")) or date.today()
        new_date_applied = st.date_input("Date Applied", value=cur_date)
        new_last_update = st.selectbox(
            "Last Update",
            LAST_UPDATE_OPTIONS,
            index=LAST_UPDATE_OPTIONS.index(str(current.get("last_update", "Submitted"))) if str(current.get("last_update", "Submitted")) in LAST_UPDATE_OPTIONS else 0,
        )

    with st.expander("More Details"):
        new_job_link = st.text_input("Job Advert Link", value=str(current.get("job_link", "") or ""))
        new_salary = st.text_input("Salary", value=str(current.get("salary", "") or ""))
        new_location = st.text_input("Job Location", value=str(current.get("location", "") or ""))
        new_cv_used = st.text_area("CV Used", value=str(current.get("cv_used", "") or ""))
        new_cover_letter_used = st.text_area("Cover Letter Used", value=str(current.get("cover_letter_used", "") or ""))
        new_notes = st.text_area("Additional Information / Questions Asked / Notes", value=str(current.get("notes", "") or ""))

    b1, b2 = st.columns([1, 5])
    save_edit = b1.form_submit_button("Save Changes")
    delete_edit = b2.form_submit_button("Delete This Job")

if save_edit:
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
                "job_link": new_job_link.strip(),
                "salary": new_salary.strip(),
                "location": new_location.strip(),
                "cv_used": new_cv_used.strip(),
                "cover_letter_used": new_cover_letter_used.strip(),
                "notes": new_notes.strip(),
            },
        )
        st.success("Updated.")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to update: {e}")

if delete_edit:
    try:
        delete_job(user.id, job_id)
        st.success("Deleted.")
        st.rerun()
    except Exception as e:
        st.error(f"Failed to delete: {e}")
