import streamlit as st
import pandas as pd
from datetime import date, datetime

from supabase import create_client


# =========================
# CONFIG
# =========================
st.set_page_config(page_title="Job Application Tracker", page_icon="📌", layout="wide")

# Status / last update dropdown options (edit freely)
STATUS_OPTIONS = [
    "Applied",
    "In Process",
    "No Response",
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

VISA_OPTIONS = ["Yes", "No"]

# Color rules:
# - Red: Rejected (status == Rejected OR last_update == Rejected)
# - Green: In progress signals (status == In Process OR last_update indicates active progress)
# - Orange: No update >= 21 days AND last_update is "No Update Yet" or status is "No Response"
# - Yellow: everything else
NO_UPDATE_DAYS_THRESHOLD = 21


# =========================
# SUPABASE HELPERS
# =========================
@st.cache_resource
def get_supabase_public_client():
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        st.error(
            "Missing SUPABASE_URL / SUPABASE_ANON_KEY in Streamlit Secrets.\n\n"
            "Go to Streamlit Cloud → App Settings → Secrets and add them."
        )
        st.stop()
    return create_client(url, key)


def authed_db_client(access_token: str):
    """
    Returns a supabase client that sends the user's JWT to PostgREST,
    so RLS policies (auth.uid()) work for SELECT/INSERT/UPDATE/DELETE.
    """
    client = get_supabase_public_client()
    # critical: attach the JWT to PostgREST
    client.postgrest.auth(access_token)
    return client


def is_logged_in():
    return bool(st.session_state.get("access_token")) and bool(st.session_state.get("user_id"))


def logout():
    for k in ["access_token", "refresh_token", "user_id", "email"]:
        st.session_state.pop(k, None)
    st.success("Logged out.")
    st.rerun()


# =========================
# UI: AUTH
# =========================
def auth_ui():
    st.title("Job Application Tracker")
    st.caption("Login / Sign up to keep your own private job tracking dashboard.")

    tab_login, tab_signup = st.tabs(["Login", "Sign Up"])

    supabase = get_supabase_public_client()

    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")

        if submitted:
            try:
                res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                session = res.session
                user = res.user
                if not session or not user:
                    st.error("Login failed. Check your email/password.")
                    st.stop()

                st.session_state["access_token"] = session.access_token
                st.session_state["refresh_token"] = session.refresh_token
                st.session_state["user_id"] = user.id
                st.session_state["email"] = user.email
                st.success("Logged in!")
                st.rerun()
            except Exception as e:
                st.error(f"Login error: {e}")

    with tab_signup:
        with st.form("signup_form", clear_on_submit=False):
            email = st.text_input("Email (new account)", placeholder="you@example.com")
            password = st.text_input("Password (min 6 chars)", type="password")
            submitted = st.form_submit_button("Create account")

        if submitted:
            try:
                res = supabase.auth.sign_up({"email": email, "password": password})
                # If confirm email is ON, user must confirm first.
                if res.user:
                    st.success("Account created. If email confirmation is enabled, confirm your email then login.")
                else:
                    st.info("Sign up submitted. Please check your email if confirmation is enabled, then login.")
            except Exception as e:
                st.error(f"Sign up error: {e}")


# =========================
# DATA LOGIC
# =========================
def fetch_jobs():
    """
    Reads jobs for the current user (RLS should enforce this).
    """
    client = authed_db_client(st.session_state["access_token"])
    resp = client.table("jobs").select("*").order("date_applied", desc=True).execute()
    data = resp.data or []
    return pd.DataFrame(data)


def insert_job(payload: dict):
    client = authed_db_client(st.session_state["access_token"])
    resp = client.table("jobs").insert(payload).execute()
    return resp


def update_job(job_id: int, updates: dict):
    client = authed_db_client(st.session_state["access_token"])
    resp = client.table("jobs").update(updates).eq("id", job_id).execute()
    return resp


def delete_job(job_id: int):
    client = authed_db_client(st.session_state["access_token"])
    resp = client.table("jobs").delete().eq("id", job_id).execute()
    return resp


def safe_date(val):
    if val is None or val == "":
        return None
    if isinstance(val, date):
        return val
    try:
        return datetime.fromisoformat(str(val)).date()
    except Exception:
        return None


def compute_color_group(row) -> str:
    status = str(row.get("status", "") or "")
    last_update = str(row.get("last_update", "") or "")
    d_applied = safe_date(row.get("date_applied"))

    # Red: rejected overrides everything
    if status == "Rejected" or last_update == "Rejected":
        return "Red"

    # Green: strong in-progress signals
    in_progress_signals = {
        "In Process",
        "Assessment Sent",
        "Phone Screen Scheduled",
        "Interview Scheduled",
        "Interview Completed",
        "Offer Received",
    }
    if status == "In Process" or last_update in in_progress_signals:
        return "Green"

    # Orange: stale/no update >= threshold
    if d_applied:
        days_open = (date.today() - d_applied).days
        if (last_update == "No Update Yet" or status == "No Response") and days_open >= NO_UPDATE_DAYS_THRESHOLD:
            return "Orange"

    # Yellow: default ongoing/recent
    return "Yellow"


def apply_sorting(df: pd.DataFrame, sort_mode: str) -> pd.DataFrame:
    if df.empty:
        return df

    # internal helper for best sorting
    order_map = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
    df = df.copy()

    # ensure date_applied is sortable
    df["__date_applied"] = pd.to_datetime(df["date_applied"], errors="coerce")
    df["__color_rank"] = df["_color_group"].map(order_map).fillna(9).astype(int)

    if sort_mode == "Auto (best)":
        # Green -> Yellow -> Orange -> Red, then newest date first
        df = df.sort_values(by=["__color_rank", "__date_applied"], ascending=[True, False], na_position="last")
    elif sort_mode == "Date applied (newest)":
        df = df.sort_values(by=["__date_applied"], ascending=[False], na_position="last")
    elif sort_mode == "Date applied (oldest)":
        df = df.sort_values(by=["__date_applied"], ascending=[True], na_position="last")
    elif sort_mode == "Company (A-Z)":
        df = df.sort_values(by=["company"], ascending=[True], na_position="last")
    elif sort_mode == "Status (A-Z)":
        df = df.sort_values(by=["status"], ascending=[True], na_position="last")

    df = df.drop(columns=["__date_applied", "__color_rank"], errors="ignore")
    return df


def style_table(df_work: pd.DataFrame) -> "pd.io.formats.style.Styler":
    """
    df_work contains _color_group but we do NOT show that column.
    We style using it internally.
    """
    # hide helper columns from display
    df_display = df_work.drop(columns=["_color_group"], errors="ignore").copy()

    # row-wise style based on df_work (index-aligned)
    COLOR_CSS = {
        "Green": "background-color: #1f8f4e; color: white;",
        "Yellow": "background-color: #f2d35b; color: black;",
        "Orange": "background-color: #f0b45b; color: black;",
        "Red": "background-color: #d9534f; color: white;",
    }

    color_by_index = df_work["_color_group"].copy()
    color_by_index.index = df_work.index

    def style_row(row):
        cg = str(color_by_index.loc[row.name])
        css = COLOR_CSS.get(cg, "")
        return [css] * len(row)

    return df_display.style.apply(style_row, axis=1)


# =========================
# MAIN APP UI
# =========================
def app_ui():
    st.title("Job Application Tracker")

    c1, c2 = st.columns([1, 1])
    with c1:
        st.caption(f"Logged in as: **{st.session_state.get('email','')}**")
    with c2:
        st.button("Logout", on_click=logout, use_container_width=True)

    st.divider()

    # --- Add new application
    with st.expander("➕ Add New Application", expanded=True):
        colA, colB, colC = st.columns([2, 2, 2])

        with colA:
            company = st.text_input("Company Name", value="", key="new_company")
            visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=1, key="new_visa")  # default "No"
        with colB:
            position = st.text_input("Position", value="", key="new_position")
            status = st.selectbox("Status", STATUS_OPTIONS, index=0, key="new_status")
        with colC:
            date_applied = st.date_input("Date Applied", value=date.today(), key="new_date")
            last_update = st.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=0, key="new_last_update")

        if st.button("Save Job", type="primary", use_container_width=False):
            company_clean = company.strip()
            position_clean = position.strip()
            if not company_clean or not position_clean:
                st.error("Company and Position are required.")
            else:
                payload = {
                    "user_id": st.session_state["user_id"],   # IMPORTANT for RLS insert policy
                    "date_applied": str(date_applied),
                    "company": company_clean,
                    "position": position_clean,
                    "visa": visa,
                    "status": status,
                    "last_update": last_update,
                }
                try:
                    resp = insert_job(payload)
                    if resp.data:
                        st.success("Saved!")
                        st.rerun()
                    else:
                        st.error(f"Failed to save: {resp}")
                except Exception as e:
                    st.error(f"Failed to save: {e}")

    st.divider()

    # --- Load data
    try:
        df = fetch_jobs()
    except Exception as e:
        st.error(f"Could not fetch jobs: {e}")
        st.stop()

    if df.empty:
        st.info("No jobs saved yet. Add your first application above.")
        return

    # compute internal color group
    df = df.copy()
    df["_color_group"] = df.apply(compute_color_group, axis=1)

    # --- Filters + Search + Sort
    f1, f2, f3, f4, f5 = st.columns([3, 1.2, 1.2, 1.2, 1.2])

    with f1:
        q = st.text_input("Search (company / position / status / last update)", value="")
    with f2:
        status_filter = st.selectbox("Status Filter", ["All"] + STATUS_OPTIONS, index=0)
    with f3:
        visa_filter = st.selectbox("Visa Filter", ["All"] + VISA_OPTIONS, index=0)
    with f4:
        color_filter = st.selectbox("Color Group", ["All", "Green", "Yellow", "Orange", "Red"], index=0)
    with f5:
        sort_mode = st.selectbox(
            "Sort",
            ["Auto (best)", "Date applied (newest)", "Date applied (oldest)", "Company (A-Z)", "Status (A-Z)"],
            index=0,
        )

    df_view = df.copy()

    if q.strip():
        qq = q.strip().lower()
        mask = (
            df_view["company"].astype(str).str.lower().str.contains(qq, na=False)
            | df_view["position"].astype(str).str.lower().str.contains(qq, na=False)
            | df_view["status"].astype(str).str.lower().str.contains(qq, na=False)
            | df_view["last_update"].astype(str).str.lower().str.contains(qq, na=False)
        )
        df_view = df_view[mask]

    if status_filter != "All":
        df_view = df_view[df_view["status"] == status_filter]

    if visa_filter != "All":
        df_view = df_view[df_view["visa"] == visa_filter]

    if color_filter != "All":
        df_view = df_view[df_view["_color_group"] == color_filter]

    df_view = apply_sorting(df_view, sort_mode)

    # create visible Job # after sorting/filtering
    df_view = df_view.reset_index(drop=True)
    df_view.insert(0, "Job #", df_view.index + 1)

    # --- Edit existing entry
    st.subheader("Edit / Update Existing Application")

    if len(df_view) == 0:
        st.warning("No results match your search/filters.")
    else:
        # map job# -> real id
        job_choices = [
            f'#{int(r["Job #"])} | {r["company"]} — {r["position"]} | {r["status"]} | {r["last_update"]}'
            for _, r in df_view.iterrows()
        ]
        selected_label = st.selectbox("Select a job to edit", job_choices, key="edit_selector")

        selected_idx = job_choices.index(selected_label)
        selected_row = df_view.iloc[selected_idx]
        selected_id = int(selected_row["id"])  # DB id (hidden later)

        e1, e2, e3 = st.columns([2, 2, 2])
        with e1:
            new_company = st.text_input("Company", value=str(selected_row["company"]), key="edit_company")
            new_visa = st.selectbox(
                "Visa Sponsorship",
                VISA_OPTIONS,
                index=VISA_OPTIONS.index(str(selected_row["visa"])) if str(selected_row["visa"]) in VISA_OPTIONS else 1,
                key="edit_visa",
            )
        with e2:
            new_position = st.text_input("Position", value=str(selected_row["position"]), key="edit_position")
            new_status = st.selectbox(
                "Status",
                STATUS_OPTIONS,
                index=STATUS_OPTIONS.index(str(selected_row["status"])) if str(selected_row["status"]) in STATUS_OPTIONS else 0,
                key="edit_status",
            )
        with e3:
            cur_date = safe_date(selected_row["date_applied"]) or date.today()
            new_date_applied = st.date_input("Date Applied", value=cur_date, key="edit_date_applied")
            new_last_update = st.selectbox(
                "Last Update",
                LAST_UPDATE_OPTIONS,
                index=LAST_UPDATE_OPTIONS.index(str(selected_row["last_update"]))
                if str(selected_row["last_update"]) in LAST_UPDATE_OPTIONS
                else 0,
                key="edit_last_update",
            )

        b1, b2 = st.columns([1, 1])
        with b1:
            if st.button("Save Changes", type="primary", use_container_width=True):
                updates = {
                    "company": new_company.strip(),
                    "position": new_position.strip(),
                    "visa": new_visa,
                    "status": new_status,
                    "last_update": new_last_update,
                    "date_applied": str(new_date_applied),
                }
                try:
                    resp = update_job(selected_id, updates)
                    if resp.data:
                        st.success("Updated!")
                        st.rerun()
                    else:
                        st.error(f"Update failed: {resp}")
                except Exception as e:
                    st.error(f"Update failed: {e}")

        with b2:
            if st.button("Delete Job", use_container_width=True):
                try:
                    resp = delete_job(selected_id)
                    st.success("Deleted.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")

    st.divider()

    # --- Final table (colored, without showing helper color column, and without showing id)
    st.subheader("Applications List")

    # keep id internally for edit mapping, but hide from display
    df_table = df_view.copy()

    # Hide internal columns from the visible table
    cols_to_hide = ["id", "user_id", "_color_group", "created_at"]
    df_table_display_work = df_table.drop(columns=[c for c in cols_to_hide if c in df_table.columns], errors="ignore")

    # But styling needs _color_group. So rebuild a work df that includes it (aligned by index).
    df_style_work = df_table_display_work.copy()
    # Reattach _color_group from df_view (same index)
    df_style_work["_color_group"] = df_view["_color_group"].values

    styled = style_table(df_style_work)
    st.dataframe(styled, use_container_width=True, hide_index=True)

    st.caption(
        "Rules: Red=Rejected | Green=In Process / interview / assessment | Orange=No update ≥ 21 days | Yellow=Other ongoing. "
        "Auto sort: Green → Yellow → Orange → Red, then newest date applied."
    )


# =========================
# RUN
# =========================
def main():
    if not is_logged_in():
        auth_ui()
    else:
        app_ui()


if __name__ == "__main__":
    main()
