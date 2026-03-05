import streamlit as st
import pandas as pd
from datetime import date, datetime

from supabase import create_client, Client

# ----------------------------
# CONFIG
# ----------------------------
st.set_page_config(page_title="Job Application Tracker", layout="wide")

# Dropdown options (edit these anytime)
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

VISA_OPTIONS = ["Yes", "No"]

# Color rules (you asked: red rejected; green best; yellow ongoing; orange stale)
GREEN_STATUSES = {"In Process", "Interview Scheduled", "Phone Screen Scheduled", "Offer"}
RED_STATUSES = {"Rejected"}

# "Orange" = no update >= 21 days OR explicitly "No Response" / "No Update Yet"
ORANGE_LAST_UPDATES = {"No Update Yet"}
ORANGE_STATUSES = {"No Response"}

STALE_DAYS = 21


# ----------------------------
# SUPABASE HELPERS
# ----------------------------
def get_supabase() -> Client:
    url = st.secrets.get("SUPABASE_URL", "")
    key = st.secrets.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        st.error("Missing SUPABASE_URL / SUPABASE_ANON_KEY in Streamlit Secrets.")
        st.stop()

    sb: Client = create_client(url, key)

    # Restore session if saved
    sess = st.session_state.get("sb_session")
    if sess and "access_token" in sess and "refresh_token" in sess:
        try:
            sb.auth.set_session(sess["access_token"], sess["refresh_token"])
        except Exception:
            # session might be expired
            st.session_state.pop("sb_session", None)
    return sb


def get_logged_in_user(sb: Client):
    try:
        u = sb.auth.get_user()
        return u.user if u and u.user else None
    except Exception:
        return None


def save_session_from_auth_response(resp):
    # supabase-py v2 returns resp.session
    if resp and getattr(resp, "session", None):
        st.session_state["sb_session"] = {
            "access_token": resp.session.access_token,
            "refresh_token": resp.session.refresh_token,
        }


# ----------------------------
# COLOR GROUP + SORTING
# ----------------------------
def color_group_for_row(row) -> str:
    """
    Returns: 'Green' 'Yellow' 'Orange' 'Red'
    """
    status = str(row.get("status", "")).strip()
    last_update = str(row.get("last_update", "")).strip()

    # Red always wins
    if status in RED_STATUSES or last_update == "Rejected":
        return "Red"

    # Green = strong progress signals
    if status in GREEN_STATUSES or last_update in {"Interview Scheduled", "Phone Screen Scheduled", "Offer"}:
        return "Green"

    # Orange = stale / no response
    try:
        d = row.get("date_applied")
        if isinstance(d, str):
            d = datetime.fromisoformat(d).date()
        if isinstance(d, date):
            days = (date.today() - d).days
        else:
            days = 0
    except Exception:
        days = 0

    if last_update in ORANGE_LAST_UPDATES or status in ORANGE_STATUSES or days >= STALE_DAYS:
        return "Orange"

    # Otherwise ongoing = Yellow
    return "Yellow"


def group_rank(group_name: str) -> int:
    # You asked: Green on top, then Yellow, then Orange, then Red bottom
    order = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
    return order.get(group_name, 99)


def style_rows(df: pd.DataFrame):
    def row_style(row):
        g = row.get("_color_group", "Yellow")
        # background + text contrast
        if g == "Green":
            return ["background-color: #1f9d55; color: white;"] * len(row)
        if g == "Yellow":
            return ["background-color: #f5d547; color: black;"] * len(row)
        if g == "Orange":
            return ["background-color: #f2a03d; color: black;"] * len(row)
        if g == "Red":
            return ["background-color: #e74c3c; color: white;"] * len(row)
        return [""] * len(row)

    return df.style.apply(row_style, axis=1)


# ----------------------------
# DATA LAYER
# ----------------------------
def fetch_jobs(sb: Client, user_id: str) -> pd.DataFrame:
    # RLS should already restrict, but we also filter explicitly
    res = sb.table("jobs").select("*").eq("user_id", user_id).execute()
    data = res.data if hasattr(res, "data") else []
    df = pd.DataFrame(data)

    if df.empty:
        return df

    # Parse date
    if "date_applied" in df.columns:
        df["date_applied"] = pd.to_datetime(df["date_applied"], errors="coerce").dt.date

    # compute job #
    df = df.sort_values(["date_applied", "id"], ascending=[False, False]).reset_index(drop=True)
    df["job_no"] = df.index + 1

    return df


def insert_job(sb: Client, user_id: str, payload: dict):
    payload = dict(payload)
    payload["user_id"] = user_id  # ✅ critical for RLS
    res = sb.table("jobs").insert(payload).execute()
    return res


def update_job(sb: Client, user_id: str, job_id: int, payload: dict):
    payload = dict(payload)
    # Only update rows owned by the user
    res = sb.table("jobs").update(payload).eq("id", job_id).eq("user_id", user_id).execute()
    return res


def delete_job(sb: Client, user_id: str, job_id: int):
    res = sb.table("jobs").delete().eq("id", job_id).eq("user_id", user_id).execute()
    return res


# ----------------------------
# UI
# ----------------------------
sb = get_supabase()
user = get_logged_in_user(sb)

st.title("Job Application Tracker")

# ----------------------------
# AUTH UI
# ----------------------------
with st.sidebar:
    st.header("Account")

    if not user:
        tab1, tab2 = st.tabs(["Login", "Sign up"])

        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pw")
            if st.button("Login", use_container_width=True, key="btn_login"):
                try:
                    resp = sb.auth.sign_in_with_password({"email": email, "password": password})
                    save_session_from_auth_response(resp)
                    st.success("Logged in ✅")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

        with tab2:
            email2 = st.text_input("Email", key="signup_email")
            pw2 = st.text_input("Password", type="password", key="signup_pw")
            if st.button("Create account", use_container_width=True, key="btn_signup"):
                try:
                    resp = sb.auth.sign_up({"email": email2, "password": pw2})
                    save_session_from_auth_response(resp)
                    st.success("Account created ✅ Now login (or you may already be logged in).")
                    st.rerun()
                except Exception as e:
                    st.error(f"Sign up failed: {e}")

        st.info("You must be logged in to save jobs (RLS).")

    else:
        st.success(f"Logged in as: {user.email}")
        if st.button("Logout", use_container_width=True, key="btn_logout"):
            try:
                sb.auth.sign_out()
            except Exception:
                pass
            st.session_state.pop("sb_session", None)
            st.rerun()


# Stop here if not logged in (prevents RLS insert errors)
if not user:
    st.stop()

USER_ID = user.id

# ----------------------------
# ADD NEW APPLICATION
# ----------------------------
with st.expander("➕ Add New Application", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        company = st.text_input("Company Name", key="new_company")
        visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=1, key="new_visa")
    with c2:
        position = st.text_input("Position", key="new_position")
        status = st.selectbox("Status", STATUS_OPTIONS, index=0, key="new_status")
    with c3:
        date_applied = st.date_input("Date Applied", value=date.today(), key="new_date")
        last_update = st.selectbox("Last Update", LAST_UPDATE_OPTIONS, index=0, key="new_last_update")

    if st.button("Save Job", key="btn_save", use_container_width=False):
        if not company.strip() or not position.strip():
            st.error("Company and Position are required.")
        else:
            payload = {
                "date_applied": str(date_applied),
                "company": company.strip(),
                "position": position.strip(),
                "visa": visa,
                "status": status,
                "last_update": last_update,
            }
            try:
                res = insert_job(sb, USER_ID, payload)
                if getattr(res, "error", None):
                    st.error(f"Failed to save: {res.error}")
                else:
                    st.success("Saved ✅")
                    st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")


# ----------------------------
# LOAD DATA
# ----------------------------
df = fetch_jobs(sb, USER_ID)

st.subheader("Applications List")

if df.empty:
    st.info("No jobs saved yet. Add your first one above.")
    st.stop()

# compute color group (hidden)
df["_color_group"] = df.apply(color_group_for_row, axis=1)
df["_group_rank"] = df["_color_group"].map(group_rank)

# ----------------------------
# FILTERS + SEARCH + SORT
# ----------------------------
f1, f2, f3, f4, f5 = st.columns([2.5, 1.2, 1.2, 1.2, 1.2])

with f1:
    q = st.text_input("Search (company / position / status / last update)", key="search_q").strip().lower()

with f2:
    status_filter = st.selectbox("Status Filter", ["All"] + STATUS_OPTIONS, key="flt_status")

with f3:
    visa_filter = st.selectbox("Visa Filter", ["All"] + VISA_OPTIONS, key="flt_visa")

with f4:
    color_filter = st.selectbox("Color Group", ["All", "Green", "Yellow", "Orange", "Red"], key="flt_color")

with f5:
    sort_mode = st.selectbox(
        "Sort",
        ["Auto (best)", "Date Applied (newest)", "Company (A-Z)", "Status (A-Z)"],
        key="sort_mode",
    )

filtered = df.copy()

if q:
    mask = (
        filtered["company"].astype(str).str.lower().str.contains(q, na=False)
        | filtered["position"].astype(str).str.lower().str.contains(q, na=False)
        | filtered["status"].astype(str).str.lower().str.contains(q, na=False)
        | filtered["last_update"].astype(str).str.lower().str.contains(q, na=False)
    )
    filtered = filtered[mask]

if status_filter != "All":
    filtered = filtered[filtered["status"] == status_filter]

if visa_filter != "All":
    filtered = filtered[filtered["visa"] == visa_filter]

if color_filter != "All":
    filtered = filtered[filtered["_color_group"] == color_filter]

# Sorting rules
if sort_mode == "Auto (best)":
    # Your requested priority: Green -> Yellow -> Orange -> Red (bottom), then newest date applied
    filtered = filtered.sort_values(
        by=["_group_rank", "date_applied", "id"],
        ascending=[True, False, False],
    )
elif sort_mode == "Date Applied (newest)":
    filtered = filtered.sort_values(by=["date_applied", "id"], ascending=[False, False])
elif sort_mode == "Company (A-Z)":
    filtered = filtered.sort_values(by=["company", "date_applied"], ascending=[True, False])
elif sort_mode == "Status (A-Z)":
    filtered = filtered.sort_values(by=["status", "date_applied"], ascending=[True, False])

filtered = filtered.reset_index(drop=True)
filtered["job_no"] = filtered.index + 1

# Display columns (NO color column shown)
show_cols = ["job_no", "date_applied", "company", "position", "visa", "status", "last_update"]
display_df = filtered[show_cols].rename(
    columns={
        "job_no": "Job #",
        "date_applied": "Date Applied",
        "company": "Company",
        "position": "Position",
        "visa": "Visa Sponsorship",
        "status": "Status",
        "last_update": "Last Update",
    }
)

# Apply row colors using hidden group info (align indices)
tmp_for_style = filtered[show_cols + ["_color_group"]].copy()
tmp_for_style.columns = list(display_df.columns) + ["_color_group"]
styled = style_rows(tmp_for_style.drop(columns=["_color_group"]).assign(_color_group=filtered["_color_group"]).rename(columns={"_color_group": "_color_group"}))
# Because styler needs the same columns, we style display_df by rebuilding a style df with same cols:
style_base = display_df.copy()
style_base["_color_group"] = filtered["_color_group"].values
styled = style_rows(style_base).hide(axis="columns", subset=["_color_group"])

st.dataframe(styled, use_container_width=True, height=420)

st.caption(
    f"Rules: Red=Rejected | Green=Interview/Offer/In Process | Orange=No Update ≥ {STALE_DAYS} days or 'No Update Yet/No Response' | Yellow=Everything else. "
    "Auto sort: Green → Yellow → Orange → Red, then newest Date Applied."
)

# ----------------------------
# EDIT / DELETE
# ----------------------------
with st.expander("✏️ Edit / Update Existing Application", expanded=False):
    # pick by Job # from filtered view
    if filtered.empty:
        st.info("No rows in the current filtered view.")
    else:
        pick = st.selectbox(
            "Choose Job # to edit",
            options=filtered["job_no"].tolist(),
            key="edit_pick",
        )
        row = filtered[filtered["job_no"] == pick].iloc[0]
        job_id = int(row["id"])

        e1, e2, e3 = st.columns(3)
        with e1:
            new_company = st.text_input("Company", value=str(row["company"]), key=f"edit_company_{job_id}")
            new_visa = st.selectbox("Visa Sponsorship", VISA_OPTIONS, index=VISA_OPTIONS.index(str(row["visa"])) if str(row["visa"]) in VISA_OPTIONS else 1, key=f"edit_visa_{job_id}")
        with e2:
            new_position = st.text_input("Position", value=str(row["position"]), key=f"edit_position_{job_id}")
            new_status = st.selectbox("Status", STATUS_OPTIONS, index=STATUS_OPTIONS.index(str(row["status"])) if str(row["status"]) in STATUS_OPTIONS else 0, key=f"edit_status_{job_id}")
        with e3:
            new_date = st.date_input("Date Applied", value=row["date_applied"] if isinstance(row["date_applied"], date) else date.today(), key=f"edit_date_{job_id}")
            new_last_update = st.selectbox(
                "Last Update",
                LAST_UPDATE_OPTIONS,
                index=LAST_UPDATE_OPTIONS.index(str(row["last_update"])) if str(row["last_update"]) in LAST_UPDATE_OPTIONS else 0,
                key=f"edit_last_{job_id}",
            )

        cA, cB, cC = st.columns([1.2, 1.2, 2.6])

        with cA:
            if st.button("Update", key=f"btn_update_{job_id}", use_container_width=True):
                payload = {
                    "company": new_company.strip(),
                    "position": new_position.strip(),
                    "visa": new_visa,
                    "status": new_status,
                    "last_update": new_last_update,
                    "date_applied": str(new_date),
                }
                try:
                    res = update_job(sb, USER_ID, job_id, payload)
                    if getattr(res, "error", None):
                        st.error(f"Update failed: {res.error}")
                    else:
                        st.success("Updated ✅")
                        st.rerun()
                except Exception as e:
                    st.error(f"Update failed: {e}")

        with cB:
            if st.button("Delete", key=f"btn_delete_{job_id}", use_container_width=True):
                try:
                    res = delete_job(sb, USER_ID, job_id)
                    if getattr(res, "error", None):
                        st.error(f"Delete failed: {res.error}")
                    else:
                        st.success("Deleted ✅")
                        st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")

        with cC:
            st.info(
                "Tip: If you get an interview call or rejection, just edit Status / Last Update here. "
                "Colors + sorting update automatically."
            )
