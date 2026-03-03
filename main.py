import sqlite3
import streamlit as st
import pandas as pd
from datetime import date, datetime

# ----------------------------
# DB (persistent storage)
# Existing schema uses: date, company, position, visa, status, last_update
# ----------------------------
conn = sqlite3.connect("jobs.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    company TEXT,
    position TEXT,
    visa TEXT,
    status TEXT,
    last_update TEXT
)
""")
conn.commit()

# ----------------------------
# UI
# ----------------------------
st.set_page_config(page_title="Job Application Tracker", layout="wide")
st.title("Job Application Tracker")

# Your rule: Orange = no update for a long time
NO_UPDATE_DAYS = 21  # change to 30 if you prefer

# Color palette (readable orange + black text)
COLORS = {
    "red":    "#e74c3c",
    "green":  "#27ae60",
    "yellow": "#f7dc6f",
    "orange": "#f8c471",
}

# Sorting priority: Green (top), Yellow, Orange, Red (bottom)
COLOR_PRIORITY = {"green": 1, "yellow": 2, "orange": 3, "red": 4}

STATUS_OPTIONS = ["Applied", "In Process", "Rejected", "No Response"]

LAST_UPDATE_OPTIONS = [
    "Submitted",
    "No Update Yet",
    "Follow-up Sent",
    "Recruiter Replied",
    "Phone Screen Scheduled",
    "Phone Screen Completed",
    "Interview Scheduled",
    "Interview Completed",
    "Assessment Sent",
    "Assessment Submitted",
    "Offer Received",
    "Rejected",
]

# "Green" last updates: recruitment progress signals
GREEN_LAST_UPDATES = {
    "Recruiter Replied",
    "Phone Screen Scheduled",
    "Phone Screen Completed",
    "Interview Scheduled",
    "Interview Completed",
    "Assessment Sent",
    "Assessment Submitted",
    "Offer Received",
}

def parse_iso_date(d) -> date:
    try:
        return datetime.fromisoformat(str(d)).date()
    except Exception:
        return date.today()

def load_jobs_raw() -> pd.DataFrame:
    return pd.read_sql_query("SELECT * FROM jobs", conn)

def classify_row(raw_row) -> tuple[str, str, int]:
    """
    Returns:
      (color_name, bg_hex, priority)

    Your rules:
    - Red: rejected
    - Green: in recruitment process
    - Orange: no update for a long time
    - Yellow: applied recently / ongoing
    """
    status = str(raw_row.get("status", "")).strip()
    last_update = str(raw_row.get("last_update", "")).strip()
    applied_dt = parse_iso_date(raw_row.get("date", ""))

    days_since = (date.today() - applied_dt).days

    # Red if rejected anywhere
    if status.lower() == "rejected" or last_update.lower() == "rejected":
        return "red", COLORS["red"], COLOR_PRIORITY["red"]

    # Green if in process OR last_update indicates progress
    if status == "In Process" or last_update in GREEN_LAST_UPDATES:
        return "green", COLORS["green"], COLOR_PRIORITY["green"]

    # Orange if old/no update for long time
    if days_since >= NO_UPDATE_DAYS:
        return "orange", COLORS["orange"], COLOR_PRIORITY["orange"]

    # Yellow otherwise (recent/ongoing)
    return "yellow", COLORS["yellow"], COLOR_PRIORITY["yellow"]

def text_color_for(color_name: str) -> str:
    # readable text on each bg
    if color_name in {"red", "green"}:
        return "#ffffff"
    return "#000000"

def style_rows(display_df: pd.DataFrame, meta_colors: list[str]):
    """Apply background+text color per row using meta_colors list aligned with display_df rows."""
    def _apply(row, i=[-1]):
        i[0] += 1
        c = meta_colors[i[0]]
        bg = COLORS[c]
        fg = text_color_for(c)
        return [f"background-color: {bg}; color: {fg};" for _ in row]
    return display_df.style.apply(_apply, axis=1)

# ----------------------------
# Add new job
# ----------------------------
with st.expander("➕ Add New Application", expanded=True):
    c1, c2, c3 = st.columns(3)
    with c1:
        company = st.text_input("Company Name", key="add_company")
        position = st.text_input("Position", key="add_position")
    with c2:
        job_date = st.date_input("Date Applied", value=date.today(), key="add_date")
        visa = st.selectbox("Visa Sponsorship", ["Yes", "No"], key="add_visa")
    with c3:
        status = st.selectbox("Status", STATUS_OPTIONS, key="add_status")
        last_update = st.selectbox("Last Update", LAST_UPDATE_OPTIONS, key="add_last_update")

    if st.button("Save Job", key="add_save"):
        if not company.strip() or not position.strip():
            st.error("Company Name and Position are required.")
        else:
            cursor.execute("""
                INSERT INTO jobs (date, company, position, visa, status, last_update)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(job_date), company.strip(), position.strip(), visa, status, last_update))
            conn.commit()
            st.success("Saved ✅")
            st.rerun()

# ----------------------------
# Filters + search
# ----------------------------
st.divider()
st.subheader("Find / Filter")

f1, f2, f3, f4 = st.columns([1, 1, 1, 2])

with f1:
    filter_status = st.selectbox("Filter by Status", ["All"] + STATUS_OPTIONS, key="filter_status")
with f2:
    filter_visa = st.selectbox("Filter by Visa", ["All", "Yes", "No"], key="filter_visa")
with f3:
    filter_color = st.selectbox("Filter by Color Group", ["All", "Green", "Yellow", "Orange", "Red"], key="filter_color")
with f4:
    q = st.text_input("Search (company / position / last update)", key="search_q").strip().lower()

# ----------------------------
# Edit existing entry
# ----------------------------
with st.expander("✏️ Edit Existing Application (updates change colors automatically)", expanded=False):
    raw_for_edit = load_jobs_raw()

    if raw_for_edit.empty:
        st.info("No jobs to edit yet.")
    else:
        # build dropdown list
        labels = []
        label_to_id = {}
        for _, r in raw_for_edit.sort_values("id", ascending=False).iterrows():
            rid = int(r["id"])
            labels.append(f'#{rid} | {r["company"]} — {r["position"]} ({r["date"]})')
            label_to_id[labels[-1]] = rid

        chosen_label = st.selectbox("Select a job", labels, key="edit_pick")
        chosen_id = label_to_id[chosen_label]
        current = raw_for_edit[raw_for_edit["id"] == chosen_id].iloc[0]

        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            new_company = st.text_input("Company", value=str(current["company"]), key=f"edit_company_{chosen_id}")
            new_position = st.text_input("Position", value=str(current["position"]), key=f"edit_position_{chosen_id}")
        with ec2:
            new_date = st.date_input("Date Applied", value=parse_iso_date(current["date"]), key=f"edit_date_{chosen_id}")
            new_visa = st.selectbox(
                "Visa Sponsorship",
                ["Yes", "No"],
                index=0 if str(current["visa"]) == "Yes" else 1,
                key=f"edit_visa_{chosen_id}"
            )
        with ec3:
            cur_status = str(current["status"])
            status_index = STATUS_OPTIONS.index(cur_status) if cur_status in STATUS_OPTIONS else 0
            new_status = st.selectbox(
                "Status",
                STATUS_OPTIONS,
                index=status_index,
                key=f"edit_status_{chosen_id}"
            )

            # EXACT same dropdown options as "Add New"
            lu_val = str(current["last_update"])
            lu_index = LAST_UPDATE_OPTIONS.index(lu_val) if lu_val in LAST_UPDATE_OPTIONS else 0
            new_last_update = st.selectbox(
                "Last Update",
                LAST_UPDATE_OPTIONS,
                index=lu_index,
                key=f"edit_last_update_{chosen_id}"
            )

        s1, s2 = st.columns([1, 1])
        with s1:
            if st.button("Save Changes", key=f"edit_save_{chosen_id}"):
                if not new_company.strip() or not new_position.strip():
                    st.error("Company and Position cannot be empty.")
                else:
                    cursor.execute("""
                        UPDATE jobs
                        SET date=?, company=?, position=?, visa=?, status=?, last_update=?
                        WHERE id=?
                    """, (
                        str(new_date),
                        new_company.strip(),
                        new_position.strip(),
                        new_visa,
                        new_status,
                        new_last_update,
                        chosen_id
                    ))
                    conn.commit()
                    st.success("Updated ✅")
                    st.rerun()

        with s2:
            if st.button("Delete Entry", key=f"edit_delete_{chosen_id}"):
                cursor.execute("DELETE FROM jobs WHERE id=?", (chosen_id,))
                conn.commit()
                st.warning("Deleted.")
                st.rerun()

# ----------------------------
# Build display table with classification + sorting + filtering
# ----------------------------
st.divider()
st.subheader("Applications List")

raw_df = load_jobs_raw()

if raw_df.empty:
    st.info("No saved jobs yet.")
else:
    # Add computed fields: color group, priority, parsed date
    color_names = []
    priorities = []
    parsed_dates = []
    for _, r in raw_df.iterrows():
        cname, _, pr = classify_row(r)
        color_names.append(cname)
        priorities.append(pr)
        parsed_dates.append(parse_iso_date(r["date"]))

    raw_df = raw_df.copy()
    raw_df["__color"] = color_names
    raw_df["__priority"] = priorities
    raw_df["__date_parsed"] = parsed_dates

    # Apply filters
    filtered = raw_df

    if filter_status != "All":
        filtered = filtered[filtered["status"] == filter_status]

    if filter_visa != "All":
        filtered = filtered[filtered["visa"] == filter_visa]

    if filter_color != "All":
        fc = filter_color.lower()
        filtered = filtered[filtered["__color"] == fc]

    if q:
        def row_matches(r):
            hay = f'{r["company"]} {r["position"]} {r["last_update"]}'.lower()
            return q in hay
        filtered = filtered[filtered.apply(row_matches, axis=1)]

    # Sort: Green -> Yellow -> Orange -> Red, then by Date Applied (newest first), then by id desc
    filtered = filtered.sort_values(
        by=["__priority", "__date_parsed", "id"],
        ascending=[True, False, False]
    ).reset_index(drop=True)

    # Build pretty display df
    display_df = filtered.rename(columns={
        "date": "Date Applied",
        "company": "Company",
        "position": "Position",
        "visa": "Visa Sponsorship",
        "status": "Status",
        "last_update": "Last Update",
    })[["Date Applied", "Company", "Position", "Visa Sponsorship", "Status", "Last Update"]]

    # Add Job # based on current sorted+filtered view
    display_df.insert(0, "Job #", range(1, len(display_df) + 1))

    # Color rows based on filtered __color
    meta_colors = filtered["__color"].tolist()

    st.dataframe(
        style_rows(display_df, meta_colors),
        use_container_width=True,
        hide_index=True
    )

st.caption(
    f"Rules: Red=Rejected | Green=In process | Orange=No update ≥ {NO_UPDATE_DAYS} days | Yellow=Recent/Ongoing. "
    "Sorted: Green → Yellow → Orange → Red, then newest Date Applied first."
)