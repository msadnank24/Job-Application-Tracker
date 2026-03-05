import os
from datetime import date, datetime
import pandas as pd
import streamlit as st
from supabase import create_client

# -----------------------------
# PAGE CONFIG
# -----------------------------
st.set_page_config(page_title="Job Application Tracker", layout="wide")

NO_UPDATE_DAYS_THRESHOLD = 21  # >=21 days (Applied + No Update Yet) -> Orange

VISA_OPTIONS = ["Yes", "No"]

STATUS_OPTIONS = ["Applied", "In Process", "Rejected"]

LAST_UPDATE_OPTIONS = [
    "No Update Yet",
    "Submitted",
    "Assessment Sent",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Received",
    "Rejected",
]

# Anything here = GREEN
PROGRESS_UPDATES = {
    "Assessment Sent",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Received",
}


# -----------------------------
# SUPABASE
# -----------------------------
def get_supabase_client():
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))

    if not url or not key:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY in Streamlit Secrets.")
        st.stop()

    return create_client(url, key)


def apply_auth_token(sb, access_token: str | None):
    # IMPORTANT for RLS
    if access_token:
        sb.postgrest.auth(access_token)
    return sb


# -----------------------------
# HELPERS
# -----------------------------
def safe_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.fromisoformat(str(value)).date()
    except Exception:
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date()
        except Exception:
            return None


def compute_color_group(status: str, last_update: str, d_applied: date | None) -> str:
    """
    EXACT RULES YOU WANTED:
    - Red: rejected (status or last_update)
    - Green: any positive/progress update OR status In Process
    - Yellow: Applied / early stage
    - Orange: Applied + No Update Yet for >= 21 days
    """
    status = (status or "").strip()
    last_update = (last_update or "").strip()

    # RED
    if status == "Rejected" or last_update == "Rejected":
        return "Red"

    # GREEN
    if status == "In Process" or last_update in PROGRESS_UPDATES:
        return "Green"

    # ORANGE / YELLOW (Applied / early stage)
    # Orange ONLY when still no updates (No Update Yet) and old enough
    if last_update == "No Update Yet" and d_applied:
        age_days = (date.today() - d_applied).days
        if age_days >= NO_UPDATE_DAYS_THRESHOLD:
            return "Orange"
        return "Yellow"

    # Submitted is still early stage -> Yellow (even if old)
    return "Yellow"


def group_rank(group: str) -> int:
    # Auto sort: Green -> Yellow -> Orange -> Red
    return {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}.get(group, 9)


def style_rows(df_display: pd.DataFrame, groups: pd.Series):
    """
    Stronger colors (not transparent) so Yellow/Orange don't look brown/dirty.
    Also make text BLACK on Yellow/Orange for readability.
    """
    def row_style(i):
        g = groups.iloc[i]
        if g == "Green":
            return ["background-color:#1f9d55; color:white;"] * len(df_display.columns)
        if g == "Yellow":
            return ["background-color:#f1c40f; color:black;"] * len(df_display.columns)
        if g == "Orange":
            return ["background-color:#e67e22; color:black;"] * len(df_display.columns)
        if g == "Red":
            return ["background-color:#e74c3c; color:white;"] * len(df_display.columns)
        return [""] * len(df_display.columns)

    styled = df_display.style.apply(lambda _row: row_style(_row.name), axis=1)
    styled = styled.set_table_styles(
        [
            {"selector": "th", "props": [("background-color", "rgba(255,255,255,0.06)"), ("color", "white")]},
            {"selector": "td", "props": [("border-color", "rgba(255,255,255,0.08)")]},
        ]
    )
    return styled


def fetch_jobs(sb, access_token: str, user_id: str) -> pd.DataFrame:
    sb = apply_auth_token(sb, access_token)
    resp = sb.table("jobs").select("*").eq("user_id", user_id).execute()
    data = resp.data or []
    df = pd.DataFrame(data)

    if df.empty:
        return df

    df["date_applied"] = df["date_applied"].apply(safe_date)
    for c in ["company", "position", "visa", "status", "last_update"]:
        df[c] = df[c].astype(str)

    return df


def do_insert_job(sb, access_token: str, payload: dict):
    sb = apply_auth_token(sb, access_token)
    return sb.table("jobs").insert(payload).execute()


def do_update_job(sb, access_token: str, job_id: int, payload: dict):
    sb = apply_auth_token(sb, access_token)
    return sb.table("jobs").update(payload).eq("id", job_id).execute()


def do_delete_job(sb, access_token: str, job_id: int):
    sb = apply_auth_token(sb, access_token)
    return sb.table("jobs").delete().eq("id", job_id).execute()


# -----------------------------
# AUTH UI
# -----------------------------
def auth_panel(sb):
    st.title("Job Application Tracker")

    if "session" not in st.session_state:
        st.session_state.session = None
    if "user" not in st.session_state:
        st.session_state.user = None

    if st.session_state.session and st.session_state.user:
        col1, col2 = st.columns([1, 3])
        with col1:
            if st.button("Log out"):
                try:
                    sb.auth.sign_out()
                except Exception:
                    pass
                st.session_state.session = None
                st.session_state.user = None
                st.rerun()
        with col2:
            st.caption(f"Signed in as: **{st.session_state.user.email}**")
        return True

    tab1, tab2 = st.tabs(["Login", "Sign up"])

    with tab1:
        email = st.text_input("Email", key="login_email")
        password = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            try:
                res = sb.auth.sign_in_with_password({"email": email, "password": password})
                st.session_state.session = res.session
                st.session_state.user = res.user
                st.success("Logged in.")
                st.rerun()
            except Exception as e:
                st.error(f"Login failed: {e}")

    with tab2:
        email = st.text_input("Email", key="signup_email")
        password = st.text_input("Password", type="password", key="signup_pass")
        if st.button("Create account"):
            try:
                res = sb.auth.sign_up({"email": email, "password": password})
                if res.session:
                    st.session_state.session = res.session
                    st.session_state.user = res.user
                    st.success("Account created & signed in.")
                    st.rerun()
                else:
                    st.success("Account created. Check your email to confirm, then login.")
            except Exception as e:
                st.error(f"Signup failed: {e}")

    return False


# -----------------------------
# MAIN APP
# -----------------------------
def main():
    sb = get_supabase_client()

    if not auth_panel(sb):
        st.stop()

    session = st.session_state.session
    user = st.session_state.user
    access_token = session.access_token
    user_id = user.id

    st.markdown("---")

    # -----------------------------
    # ADD NEW JOB
    # -----------------------------
    with st.expander("➕ Add New Application", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            company = st.text_input("Company Name", "")
            visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=1 if "No" in VISA_OPTIONS else 0)
        with c2:
            position = st.text_input("Position", "")
            status = st.selectbox("Status", STATUS_OPTIONS, index=0)
        with c3:
            date_applied = st.date_input("Date Applied", value=date.today())
            last_update = st.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=LAST_UPDATE_OPTIONS.index("No Update Yet"))

        if st.button("Save Job"):
            if not company.strip() or not position.strip():
                st.warning("Company and Position are required.")
            else:
                payload = {
                    "user_id": user_id,
                    "date_applied": date_applied.isoformat(),
                    "company": company.strip(),
                    "position": position.strip(),
                    "visa": visa,
                    "status": status,
                    "last_update": last_update,
                }
                try:
                    do_insert_job(sb, access_token, payload)
                    st.success("Saved.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to save: {e}")

    # -----------------------------
    # FETCH + GROUPS
    # -----------------------------
    df = fetch_jobs(sb, access_token, user_id)
    if df.empty:
        st.info("No jobs yet. Add your first one above.")
        st.stop()

    groups = df.apply(
        lambda r: compute_color_group(
            status=str(r.get("status", "")),
            last_update=str(r.get("last_update", "")),
            d_applied=safe_date(r.get("date_applied")),
        ),
        axis=1,
    )

    # -----------------------------
    # FILTERS / SEARCH / SORT
    # -----------------------------
    st.subheader("Applications List")

    f1, f2, f3, f4, f5 = st.columns([2.6, 1.3, 1.3, 1.3, 1.3])

    with f1:
        q = st.text_input("Search (company / position / status / last update)", "").strip().lower()
    with f2:
        status_filter = st.selectbox("Status Filter", ["All"] + STATUS_OPTIONS, index=0)
    with f3:
        visa_filter = st.selectbox("Visa Filter", ["All"] + VISA_OPTIONS, index=0)
    with f4:
        color_filter = st.selectbox("Color Group", ["All", "Green", "Yellow", "Orange", "Red"], index=0)
    with f5:
        sort_mode = st.selectbox(
            "Sort",
            [
                "Auto (best)",
                "Date Applied (newest first)",
                "Date Applied (oldest first)",
                "Company (A→Z)",
                "Company (Z→A)",
            ],
            index=0,
        )

    work = df.copy()
    work["_group"] = groups.values
    work["_group_rank"] = work["_group"].apply(group_rank)
    work["_date_sort"] = work["date_applied"].apply(lambda d: d if isinstance(d, date) else date.min)

    # Search
    if q:
        mask = (
            work["company"].str.lower().str.contains(q, na=False)
            | work["position"].str.lower().str.contains(q, na=False)
            | work["status"].str.lower().str.contains(q, na=False)
            | work["last_update"].str.lower().str.contains(q, na=False)
        )
        work = work[mask]

    # Filters
    if status_filter != "All":
        work = work[work["status"] == status_filter]
    if visa_filter != "All":
        work = work[work["visa"] == visa_filter]
    if color_filter != "All":
        work = work[work["_group"] == color_filter]

    # Sort
    if sort_mode == "Auto (best)":
        work = work.sort_values(by=["_group_rank", "_date_sort"], ascending=[True, False])
    elif sort_mode == "Date Applied (newest first)":
        work = work.sort_values(by=["_date_sort"], ascending=[False])
    elif sort_mode == "Date Applied (oldest first)":
        work = work.sort_values(by=["_date_sort"], ascending=[True])
    elif sort_mode == "Company (A→Z)":
        work = work.sort_values(by=["company", "_date_sort"], ascending=[True, False])
    elif sort_mode == "Company (Z→A)":
        work = work.sort_values(by=["company", "_date_sort"], ascending=[False, False])

    work = work.reset_index(drop=True)
    work["Job #"] = work.index + 1

    # DISPLAY: friendly headers (no underscores)
    df_display = work[["Job #", "date_applied", "company", "position", "visa", "status", "last_update"]].copy()
    df_display = df_display.rename(
        columns={
            "date_applied": "Date Applied",
            "company": "Company",
            "position": "Position",
            "visa": "Visa Sponsorship",
            "status": "Status",
            "last_update": "Last Update",
        }
    )

    sorted_groups = work["_group"].reset_index(drop=True)

    st.dataframe(
        style_rows(df_display, sorted_groups),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        f"Rules: Red=Rejected | Green=Progress (assessment/interviews/offers) | "
        f"Orange=Applied + No Update Yet ≥ {NO_UPDATE_DAYS_THRESHOLD} days | Yellow=Applied/early stage."
    )

    # -----------------------------
    # EDIT / DELETE
    # -----------------------------
    st.markdown("---")
    st.subheader("Edit / Update an Existing Entry")

    if work.empty:
        st.info("No results match your filters.")
        st.stop()

    pick_job_no = st.selectbox("Select Job #", work["Job #"].tolist(), index=0, key="pick_job_no")
    selected_row = work.loc[work["Job #"] == pick_job_no].iloc[0]
    selected_id = int(selected_row["id"])

    ec1, ec2, ec3 = st.columns(3)
    with ec1:
        new_company = st.text_input("Company", value=str(selected_row["company"]), key=f"edit_company_{selected_id}")
        new_visa = st.selectbox(
            "Visa Sponsorship",
            VISA_OPTIONS,
            index=VISA_OPTIONS.index(str(selected_row["visa"])) if str(selected_row["visa"]) in VISA_OPTIONS else 0,
            key=f"edit_visa_{selected_id}",
        )
    with ec2:
        new_position = st.text_input("Position", value=str(selected_row["position"]), key=f"edit_position_{selected_id}")
        new_status = st.selectbox(
            "Status",
            STATUS_OPTIONS,
            index=STATUS_OPTIONS.index(str(selected_row["status"])) if str(selected_row["status"]) in STATUS_OPTIONS else 0,
            key=f"edit_status_{selected_id}",
        )
    with ec3:
        new_date_applied = st.date_input(
            "Date Applied",
            value=safe_date(selected_row["date_applied"]) or date.today(),
            key=f"edit_date_{selected_id}",
        )
        new_last_update = st.selectbox(
            "Last Update",
            LAST_UPDATE_OPTIONS,
            index=LAST_UPDATE_OPTIONS.index(str(selected_row["last_update"]))
            if str(selected_row["last_update"]) in LAST_UPDATE_OPTIONS
            else 0,
            key=f"edit_last_{selected_id}",
        )

    b1, b2, _ = st.columns([1, 1, 6])
    with b1:
        if st.button("Update Job", key=f"btn_update_{selected_id}"):
            payload = {
                "user_id": user_id,  # keep RLS happy
                "date_applied": new_date_applied.isoformat(),
                "company": new_company.strip(),
                "position": new_position.strip(),
                "visa": new_visa,
                "status": new_status,
                "last_update": new_last_update,
            }
            try:
                do_update_job(sb, access_token, selected_id, payload)
                st.success("Updated.")
                st.rerun()
            except Exception as e:
                st.error(f"Update failed: {e}")

    with b2:
        if st.button("Delete Job", key=f"btn_delete_{selected_id}"):
            try:
                do_delete_job(sb, access_token, selected_id)
                st.success("Deleted.")
                st.rerun()
            except Exception as e:
                st.error(f"Delete failed: {e}")


if __name__ == "__main__":
    main()
