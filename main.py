import os
from datetime import date, datetime
import pandas as pd
import streamlit as st
from supabase import create_client


# -----------------------------
# CONFIG
# -----------------------------
st.set_page_config(page_title="Job Application Tracker", layout="wide")

NO_UPDATE_DAYS_THRESHOLD = 21  # >= 21 days -> Orange (only if "No Update Yet")

VISA_OPTIONS = ["Yes", "No"]

STATUS_OPTIONS = [
    "Applied",
    "In Process",
    "Rejected",
]

LAST_UPDATE_OPTIONS = [
    "Submitted",
    "No Update Yet",
    "Assessment Sent",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Received",
    "Rejected",
]

IN_PROGRESS_UPDATES = {
    "Assessment Sent",
    "Phone Screen Scheduled",
    "Interview Scheduled",
    "Interview Completed",
    "Offer Received",
}


# -----------------------------
# SUPABASE CLIENT
# -----------------------------
def get_supabase_client():
    # Prefer Streamlit Cloud secrets, fallback to env vars
    url = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", ""))
    key = st.secrets.get("SUPABASE_ANON_KEY", os.getenv("SUPABASE_ANON_KEY", ""))

    if not url or not key:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY in Streamlit Secrets.")
        st.stop()

    return create_client(url, key)


def apply_auth_token(sb, access_token: str | None):
    # Critical for RLS: PostgREST must receive the JWT
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
    status = (status or "").strip()
    last_update = (last_update or "").strip()

    # 1) Red overrides everything
    if status == "Rejected" or last_update == "Rejected":
        return "Red"

    # 2) Green = active progress
    if status == "In Process" or last_update in IN_PROGRESS_UPDATES:
        return "Green"

    # 3) Orange/Yellow ONLY based on No Update Yet + age
    if last_update == "No Update Yet" and d_applied:
        days_open = (date.today() - d_applied).days
        if days_open >= NO_UPDATE_DAYS_THRESHOLD:
            return "Orange"
        return "Yellow"

    # 4) Default ongoing
    return "Yellow"


def group_rank(group: str) -> int:
    # Auto sort order: Green -> Yellow -> Orange -> Red
    mapping = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
    return mapping.get(group, 9)


def style_rows(df_display: pd.DataFrame, groups: pd.Series):
    # Row coloring (no visible "Color Group" column)
    def row_style(i):
        g = groups.iloc[i]
        if g == "Green":
            return ["background-color: rgba(46, 204, 113, 0.35); color: white;"] * len(df_display.columns)
        if g == "Yellow":
            return ["background-color: rgba(241, 196, 15, 0.35); color: white;"] * len(df_display.columns)
        if g == "Orange":
            # slightly darker so text readable
            return ["background-color: rgba(230, 126, 34, 0.38); color: white;"] * len(df_display.columns)
        if g == "Red":
            return ["background-color: rgba(231, 76, 60, 0.42); color: white;"] * len(df_display.columns)
        return [""] * len(df_display.columns)

    styled = df_display.style.apply(lambda _row: row_style(_row.name), axis=1)
    styled = styled.set_table_styles(
        [
            {"selector": "th", "props": [("background-color", "rgba(255,255,255,0.04)"), ("color", "white")]},
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

    # Normalize types
    df["date_applied"] = df["date_applied"].apply(safe_date)
    df["company"] = df["company"].astype(str)
    df["position"] = df["position"].astype(str)
    df["visa"] = df["visa"].astype(str)
    df["status"] = df["status"].astype(str)
    df["last_update"] = df["last_update"].astype(str)

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
                # If email confirmation is ON, session may be None
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

    authed = auth_panel(sb)
    if not authed:
        st.stop()

    # session/user guaranteed now
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
            last_update = st.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=LAST_UPDATE_OPTIONS.index("Submitted"))

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
    # FETCH + COMPUTE GROUPS
    # -----------------------------
    df = fetch_jobs(sb, access_token, user_id)

    if df.empty:
        st.info("No jobs yet. Add your first one above.")
        st.stop()

    # Compute groups (kept separately — NOT shown as a column)
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

    # Build a working dataframe copy
    work = df.copy()
    work["_group"] = groups.values
    work["_group_rank"] = work["_group"].apply(group_rank)
    work["_date_sort"] = work["date_applied"].apply(lambda d: d if isinstance(d, date) else date.min)

    # Apply search
    if q:
        mask = (
            work["company"].str.lower().str.contains(q, na=False)
            | work["position"].str.lower().str.contains(q, na=False)
            | work["status"].str.lower().str.contains(q, na=False)
            | work["last_update"].str.lower().str.contains(q, na=False)
        )
        work = work[mask]

    # Apply filters
    if status_filter != "All":
        work = work[work["status"] == status_filter]

    if visa_filter != "All":
        work = work[work["visa"] == visa_filter]

    if color_filter != "All":
        work = work[work["_group"] == color_filter]

    # Apply sort
    if sort_mode == "Auto (best)":
        # Green -> Yellow -> Orange -> Red, then newest date_applied first
        work = work.sort_values(by=["_group_rank", "_date_sort"], ascending=[True, False])
    elif sort_mode == "Date Applied (newest first)":
        work = work.sort_values(by=["_date_sort"], ascending=[False])
    elif sort_mode == "Date Applied (oldest first)":
        work = work.sort_values(by=["_date_sort"], ascending=[True])
    elif sort_mode == "Company (A→Z)":
        work = work.sort_values(by=["company", "_date_sort"], ascending=[True, False])
    elif sort_mode == "Company (Z→A)":
        work = work.sort_values(by=["company", "_date_sort"], ascending=[False, False])

    # Rebuild Job # after sorting
    work = work.reset_index(drop=True)
    work["Job #"] = work.index + 1

    # Display dataframe (hide internal cols)
    display_cols = ["Job #", "date_applied", "company", "position", "visa", "status", "last_update"]
    df_display = work[display_cols].copy()

    # Use the sorted group's series for styling
    sorted_groups = work["_group"].reset_index(drop=True)

    st.dataframe(
        style_rows(df_display, sorted_groups),
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        f"Rules: Red=Rejected | Green=In Process/assessment/interviews/offers | "
        f"Orange=No Update Yet ≥ {NO_UPDATE_DAYS_THRESHOLD} days | Yellow=Other ongoing. "
        f"Auto sort: Green → Yellow → Orange → Red, then newest date applied."
    )

    # -----------------------------
    # EDIT / DELETE
    # -----------------------------
    st.markdown("---")
    st.subheader("Edit / Update an Existing Entry")

    # Let user pick by Job # from CURRENT sorted view
    if work.empty:
        st.info("No results match your current filters.")
        st.stop()

    pick_col1, pick_col2 = st.columns([2, 3])
    with pick_col1:
        pick_job_no = st.selectbox("Select Job #", work["Job #"].tolist(), index=0, key="pick_job_no")
    selected_row = work.loc[work["Job #"] == pick_job_no].iloc[0]
    selected_id = int(selected_row["id"])

    with pick_col2:
        st.caption(f"Editing: **{selected_row['company']}** — {selected_row['position']} (DB id: {selected_id})")

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
                "user_id": user_id,  # ensure RLS passes (auth.uid() == user_id)
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
