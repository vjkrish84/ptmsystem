import os
import certifi
import smtplib
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pymongo import MongoClient, errors
from datetime import datetime, date, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ---------------------------------------------------------
# 1. Page Config & Custom Styling
# ---------------------------------------------------------
st.set_page_config(
    page_title="Enterprise Post-Transplant Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def inject_clean_design():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    }

    [data-testid="stSidebar"] { display: none !important; }

    /* Card Styling */
    div[data-testid="stVerticalBlockBorderWrapper"] {
        background-color: #ffffff;
        border-radius: 12px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        padding: 1.25rem;
        margin-bottom: 1rem;
    }

    /* Metric Styling */
    [data-testid="stMetric"] {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 10px;
        padding: 12px 16px;
    }

    /* Primary Tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        border-bottom: 2px solid #e2e8f0;
    }

    .stTabs [data-baseweb="tab"] {
        height: 48px;
        padding: 0px 16px;
        border-radius: 8px 8px 0 0;
        font-weight: 500;
    }

    /* Badges */
    .status-badge-red {
        background-color: #fef2f2;
        color: #991b1b;
        border: 1px solid #fecaca;
        padding: 10px 16px;
        border-radius: 8px;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    .status-badge-amber {
        background-color: #fffbeb;
        color: #92400e;
        border: 1px solid #fde68a;
        padding: 10px 16px;
        border-radius: 8px;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    .status-badge-green {
        background-color: #f0fdf4;
        color: #166534;
        border: 1px solid #bbf7d0;
        padding: 10px 16px;
        border-radius: 8px;
        font-weight: 600;
        margin-bottom: 1rem;
    }
    </style>
    """, unsafe_allow_html=True)

inject_clean_design()

# ---------------------------------------------------------
# 2. Database Connections & Seeding
# ---------------------------------------------------------
@st.cache_resource
def init_connection():
    mongo_uri = st.secrets.get("MONGO_URI") or os.getenv("MONGO_URI")
    if not mongo_uri:
        st.error("⚠️ Database connection string missing! Set `MONGO_URI` in secrets or environment.")
        st.stop()
    try:
        client = MongoClient(mongo_uri, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
        return client
    except errors.PyMongoError as e:
        st.error(f"⚠️ Connection Error: {e}")
        st.stop()

client = init_connection()
db = client["transplant_portal_live"]

vitals_col = db["vitals_logs"]
notifs_col = db["patient_notifications"]
notes_col = db["clinical_notes"]
audit_col = db["audit_logs"]
rules_col = db["ruleset_versions"]
patients_col = db["patient_profiles"]
diagnostics_col = db["diagnostic_reports"]
feedback_col = db["user_feedback"]

# Initialize default seed data if database is fresh
if rules_col.count_documents({}) == 0:
    rules_col.insert_one({
        "ruleset_id": "RS-DEMO-v1.0",
        "active": True,
        "created_at": datetime.now(timezone.utc),
        "approved_by": "Dr. Sarah Jenkins",
        "parameters": {
            "weight_spike_kg": 1.5,
            "fever_temp_f": 100.0,
            "tacrolimus_high": 12.0,
            "tacrolimus_low": 4.0,
            "creatinine_high": 1.8
        }
    })

if patients_col.count_documents({"patient_name": "Sarah Connor"}) == 0:
    patients_col.insert_one({
        "patient_name": "Sarah Connor",
        "patient_id": "PT-1001",
        "organ_type": "Kidney",
        "transplant_date": "2026-01-15",
        "allergies": ["NSAIDs", "Penicillin"],
        "current_medications": [
            {"drug": "Tacrolimus", "EHR_dose": "3mg BID", "patient_dose": "3mg BID", "status": "Matched"},
            {"drug": "Prednisone", "EHR_dose": "5mg Daily", "patient_dose": "10mg Daily", "status": "Mismatch"}
        ],
        "appointments": []
    })

# ---------------------------------------------------------
# 3. Helpers & Core Engines
# ---------------------------------------------------------
def log_audit_event(actor_role: str, actor_id: str, action: str, details: dict):
    audit_col.insert_one({
        "timestamp": datetime.now(timezone.utc),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "details": details
    })

def send_feedback_gmail(category, rating, comment, actor_role):
    admin_email = st.secrets.get("ADMIN_EMAIL", "")
    smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = st.secrets.get("SMTP_PORT", 587)
    smtp_user = st.secrets.get("SMTP_USER", "")
    smtp_pass = st.secrets.get("SMTP_PASSWORD", "")

    if not (admin_email and smtp_user and smtp_pass):
        return False, "SMTP configuration incomplete."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🚨 New Portal Feedback: [{category}]"
        msg["From"] = smtp_user
        msg["To"] = admin_email

        html_content = f"""
        <h2>New User Feedback Submitted</h2>
        <p><strong>Role:</strong> {actor_role}</p>
        <p><strong>Category:</strong> {category}</p>
        <p><strong>Rating:</strong> {rating}/5 Stars</p>
        <p><strong>Comment:</strong> {comment}</p>
        """
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, admin_email, msg.as_string())

        return True, "Email sent successfully."
    except Exception as e:
        return False, str(e)

def evaluate_clinical_triage(latest_doc, prev_doc=None):
    if not latest_doc:
        return "GREEN", [], [], ["No vital records available."]

    active_ruleset = rules_col.find_one({"active": True}) or {}
    params = active_ruleset.get("parameters", {
        "weight_spike_kg": 1.5, "fever_temp_f": 100.0,
        "tacrolimus_high": 12.0, "tacrolimus_low": 4.0, "creatinine_high": 1.8
    })

    red_flags, amber_flags, explanations = [], [], []

    if prev_doc and "weight_kg" in latest_doc and "weight_kg" in prev_doc:
        wt_change = latest_doc["weight_kg"] - prev_doc["weight_kg"]
        if wt_change >= params["weight_spike_kg"]:
            red_flags.append(f"Weight Spike (+{wt_change:.1f} kg)")
            explanations.append(f"Weight gain {wt_change:.1f}kg exceeds rule limit {params['weight_spike_kg']}kg")

    temp = latest_doc.get("temperature_f", 98.6)
    if temp >= params["fever_temp_f"]:
        red_flags.append(f"Fever ({temp:.1f}°F)")
        explanations.append(f"Temperature {temp:.1f}°F ≥ rule limit {params['fever_temp_f']}°F")

    tac = latest_doc.get("tacrolimus", 0.0)
    if tac > 0:
        if tac > params["tacrolimus_high"]:
            red_flags.append(f"High Tacrolimus ({tac:.1f} ng/mL)")
            explanations.append(f"Tacrolimus {tac:.1f} > max limit {params['tacrolimus_high']}")
        elif tac < params["tacrolimus_low"]:
            red_flags.append(f"Low Tacrolimus ({tac:.1f} ng/mL)")
            explanations.append(f"Tacrolimus {tac:.1f} < min limit {params['tacrolimus_low']}")

    creat = latest_doc.get("creatinine", 1.0)
    if creat >= params["creatinine_high"]:
        red_flags.append(f"High Creatinine ({creat:.2f} mg/dL)")
        explanations.append(f"Creatinine {creat:.2f} ≥ rule limit {params['creatinine_high']}")

    if red_flags:
        return "RED", red_flags, amber_flags, explanations
    elif amber_flags:
        return "AMBER", red_flags, amber_flags, explanations
    return "GREEN", red_flags, amber_flags, explanations

def create_new_patient_profile(name, p_id, organ, tx_date, allergies_list, initial_meds):
    if patients_col.find_one({"patient_name": name}):
        return False, "Patient profile already exists with this name."
    
    new_doc = {
        "patient_name": name,
        "patient_id": p_id or f"PT-{abs(hash(name)) % 10000}",
        "organ_type": organ,
        "transplant_date": str(tx_date),
        "allergies": [a.strip() for a in allergies_list if a.strip()],
        "current_medications": initial_meds or [],
        "appointments": [],
        "created_at": datetime.now(timezone.utc)
    }
    patients_col.insert_one(new_doc)
    
    vitals_col.insert_one({
        "patient_id": new_doc["patient_id"],
        "patient_name": name,
        "timestamp": datetime.now(timezone.utc),
        "weight_kg": 70.0,
        "temperature_f": 98.6,
        "heart_rate": 72,
        "systolic_bp": 120,
        "diastolic_bp": 80,
        "symptoms": [],
        "creatinine": 1.0,
        "tacrolimus": 6.0
    })
    return True, "Patient profile successfully created!"

# ---------------------------------------------------------
# 4. Custom Marker & Chart Engine
# ---------------------------------------------------------
def render_vitals_trends_with_custom_markers(patient_name: str):
    logs = list(vitals_col.find({"patient_name": patient_name}).sort("timestamp", 1))
    if not logs:
        st.info("No vital records available for this patient.")
        return

    df = pd.DataFrame(logs)
    df["Formatted_Time"] = df["timestamp"].dt.strftime("%b %d, %H:%M")

    # Fetch active thresholds for markers
    active_ruleset = rules_col.find_one({"active": True}) or {}
    params = active_ruleset.get("parameters", {
        "fever_temp_f": 100.0, "tacrolimus_high": 12.0, "tacrolimus_low": 4.0, "creatinine_high": 1.8
    })

    # Generate Dynamic Custom Marker Colors and Symbols
    temp_colors = ['#dc2626' if t >= params["fever_temp_f"] else '#2563eb' for t in df.get("temperature_f", [98.6]*len(df))]
    temp_symbols = ['triangle-up' if t >= params["fever_temp_f"] else 'circle' for t in df.get("temperature_f", [98.6]*len(df))]

    tac_colors = []
    for tac in df.get("tacrolimus", [6.0]*len(df)):
        if tac > params["tacrolimus_high"] or tac < params["tacrolimus_low"]:
            tac_colors.append('#dc2626')
        else:
            tac_colors.append('#16a34a')

    col1, col2 = st.columns(2)
    with col1:
        fig1 = go.Figure()
        # Weight trace
        fig1.add_trace(go.Scatter(
            x=df["Formatted_Time"], y=df.get("weight_kg", []),
            mode="lines+markers", name="Weight (kg)",
            line=dict(color="#2563eb", width=2),
            marker=dict(size=8, symbol='circle')
        ))
        # Temperature trace with dynamic high-fever custom markers
        fig1.add_trace(go.Scatter(
            x=df["Formatted_Time"], y=df.get("temperature_f", []),
            mode="lines+markers", name="Temp (°F)", yaxis="y2",
            line=dict(color="#d97706", width=2, dash="dot"),
            marker=dict(size=10, color=temp_colors, symbol=temp_symbols)
        ))
        # Threshold Reference Line
        fig1.add_hline(y=params["fever_temp_f"], line_dash="dash", line_color="red", yref="y2", annotation_text="Fever Threshold (100°F)")
        fig1.update_layout(title="Weight & Temp (Custom Alarm Markers)", height=300, margin=dict(l=10, r=10, t=35, b=10), yaxis2=dict(overlaying="y", side="right"))
        st.plotly_chart(fig1, use_container_width=True)

    with col2:
        fig2 = go.Figure()
        # Tacrolimus trace with dynamic outlier markers
        fig2.add_trace(go.Scatter(
            x=df["Formatted_Time"], y=df.get("tacrolimus", []),
            mode="lines+markers", name="Tacrolimus (ng/mL)",
            line=dict(color="#16a34a", width=2),
            marker=dict(size=10, color=tac_colors)
        ))
        # Creatinine trace
        fig2.add_trace(go.Scatter(
            x=df["Formatted_Time"], y=df.get("creatinine", []),
            mode="lines+markers", name="Creatinine (mg/dL)", yaxis="y2",
            line=dict(color="#dc2626", width=2)
        ))
        # Upper & Lower Bounds
        fig2.add_hline(y=params["tacrolimus_high"], line_dash="dash", line_color="red", annotation_text="Tac High Limit")
        fig2.add_hline(y=params["tacrolimus_low"], line_dash="dash", line_color="orange", annotation_text="Tac Low Limit")
        fig2.update_layout(title="Tacrolimus & Creatinine Bounds", height=300, margin=dict(l=10, r=10, t=35, b=10), yaxis2=dict(overlaying="y", side="right"))
        st.plotly_chart(fig2, use_container_width=True)

    with st.expander("📄 View Historical Table"):
        target_cols = ["timestamp", "weight_kg", "systolic_bp", "diastolic_bp", "temperature_f", "heart_rate", "tacrolimus", "creatinine", "symptoms"]
        display_df = df.reindex(columns=target_cols).copy()
        display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M")
        display_df.columns = ["Timestamp", "Weight (kg)", "Sys BP", "Dia BP", "Temp (°F)", "Heart Rate", "Tacrolimus", "Creatinine", "Symptoms"]
        st.dataframe(display_df, use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# 5. Shared Reusable Modules
# ---------------------------------------------------------
def render_communication_hub(patient_name: str, active_role: str):
    messages = list(notifs_col.find({"patient_name": patient_name}).sort("timestamp", -1))
    
    col_hist, col_send = st.columns([1.2, 1])
    
    with col_hist:
        st.markdown("##### Transmission History")
        if not messages:
            st.info("No previous care team transmissions.")
        else:
            for msg in messages[:5]:
                urgency = msg.get("urgency", "Routine Message")
                badge = "🔴 URGENT" if "Urgent" in urgency else "🟢 ROUTINE"
                st.caption(f"{badge} | **{msg.get('author', 'User')}** | {msg.get('timestamp').strftime('%b %d, %H:%M UTC')}")
                st.write(msg.get("message"))
                st.divider()

    with col_send:
        st.markdown("##### Transmit Message")
        with st.form(key=f"msg_form_{patient_name}_{active_role}"):
            msg_text = st.text_area("Message Content:", height=90)
            msg_urgency = st.selectbox("Priority Level:", ["Routine Message", "Urgent Clinical Alert"])
            if st.form_submit_button("Send Transmission", use_container_width=True, type="primary"):
                if msg_text.strip():
                    notifs_col.insert_one({
                        "patient_name": patient_name,
                        "sender": active_role.lower().split()[0],
                        "author": active_role,
                        "message": msg_text.strip(),
                        "urgency": msg_urgency,
                        "timestamp": datetime.now(timezone.utc)
                    })
                    log_audit_event(active_role, "LOCAL-USER", "SEND_MESSAGE", {"patient": patient_name, "urgency": msg_urgency})
                    st.success("✅ Transmission sent successfully!")
                    st.rerun()

def render_diagnostics_viewer(patient_name: str, allow_upload: bool = False, actor_role: str = "Patient"):
    if allow_upload:
        with st.container(border=True):
            st.markdown("##### Upload Diagnostic Study or Lab")
            with st.form(key=f"upload_diag_form_{patient_name}_{actor_role}"):
                c1, c2 = st.columns(2)
                d_category = c1.selectbox("Report Category:", ["Comprehensive Lab Panel", "Urinalysis (UA)", "Ultrasound / Imaging Report"])
                d_file = c2.file_uploader("Attach Document:", type=["pdf", "png", "jpg"])
                
                d_notes = st.text_input("Summary Findings:")
                ca, cb = st.columns(2)
                c_val1 = ca.number_input("Serum Creatinine (mg/dL)", value=1.2, step=0.1)
                c_val2 = cb.number_input("Tacrolimus Level (ng/mL)", value=7.5, step=0.1)

                if st.form_submit_button("Upload & Record Diagnostic", type="primary", use_container_width=True):
                    f_name = d_file.name if d_file else "Manual_Entry.pdf"
                    diagnostics_col.insert_one({
                        "patient_name": patient_name,
                        "category": d_category,
                        "uploaded_by": actor_role,
                        "notes": d_notes,
                        "creatinine": c_val1,
                        "tacrolimus": c_val2,
                        "file_name": f_name,
                        "timestamp": datetime.now(timezone.utc)
                    })
                    vitals_col.insert_one({
                        "patient_name": patient_name,
                        "timestamp": datetime.now(timezone.utc),
                        "weight_kg": 70.0, "temperature_f": 98.6, "heart_rate": 72,
                        "systolic_bp": 120, "diastolic_bp": 80, "symptoms": ["Lab Update"],
                        "creatinine": c_val1, "tacrolimus": c_val2
                    })
                    st.success("✅ Diagnostic report uploaded successfully!")
                    st.rerun()

    reports = list(diagnostics_col.find({"patient_name": patient_name}).sort("timestamp", -1))
    if not reports:
        st.info("No diagnostic records available for this patient.")
    else:
        for r in reports:
            with st.container(border=True):
                st.markdown(f"**{r.get('category')}** — `{r.get('timestamp').strftime('%b %d, %Y')}`")
                st.caption(f"Uploaded by: {r.get('uploaded_by')} | File: {r.get('file_name')}")
                st.write(f"Creatinine: **{r.get('creatinine')} mg/dL** | Tacrolimus: **{r.get('tacrolimus')} ng/mL**")
                if r.get("notes"):
                    st.caption(f"Notes: {r.get('notes')}")

def render_feedback_section(actor_role: str):
    with st.container(border=True):
        st.markdown("##### 💬 Submit System Feedback")
        with st.form(key=f"feedback_form_{actor_role}"):
            f_cat = st.selectbox("Feedback Category:", ["Bug Report", "UI Layout Improvement", "Clinical Rule Adjustment", "General Feedback"])
            f_rating = st.slider("Rating (1-5 Stars):", 1, 5, 5)
            f_comment = st.text_area("Your Comments / Suggestions:")
            
            if st.form_submit_button("Submit Feedback", type="primary", use_container_width=True):
                if f_comment.strip():
                    feedback_col.insert_one({
                        "role": actor_role,
                        "category": f_cat,
                        "rating": f_rating,
                        "comment": f_comment.strip(),
                        "timestamp": datetime.now(timezone.utc)
                    })
                    sent, email_msg = send_feedback_gmail(f_cat, f_rating, f_comment, actor_role)
                    if sent:
                        st.success("✅ Feedback saved and email notification sent to admin!")
                    else:
                        st.success("✅ Feedback saved to database!")
                    st.rerun()

# ---------------------------------------------------------
# 6. Header Bar & Navigation
# ---------------------------------------------------------
st.title("🩺 Enterprise Post-Transplant Portal")

active_role = st.radio(
    "Select Operating Role:",
    ["Patient Portal", "Caregiver Proxy", "Doctor Workspace", "Transplant Coordinator", "System Admin"],
    horizontal=True,
    label_visibility="collapsed"
)

st.divider()

all_registered_patients = sorted(patients_col.distinct("patient_name")) or ["Sarah Connor"]

# ---------------------------------------------------------
# ROLE 1: PATIENT PORTAL
# ---------------------------------------------------------
if active_role == "Patient Portal":
    col_sel, col_empty = st.columns([1, 2])
    selected_patient = col_sel.selectbox("Active Patient Account:", options=all_registered_patients)
    p_profile = patients_col.find_one({"patient_name": selected_patient}) or {}

    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Patient Name", selected_patient)
        m2.metric("Organ Type", p_profile.get("organ_type", "Kidney"))
        m3.metric("Transplant Date", p_profile.get("transplant_date", "N/A"))
        m4.metric("Status", "🟢 Active Monitoring")

    tab_vitals, tab_trends, tab_messages, tab_labs, tab_register, tab_fb = st.tabs([
        "📝 Daily Vitals", 
        "📊 Trends & Markers", 
        "💬 Care Team Messages", 
        "🧪 Lab Reports", 
        "👤 Register Account",
        "💬 System Feedback"
    ])

    with tab_vitals:
        with st.container(border=True):
            st.subheader("Log Today's Vital Signs")
            with st.form("patient_vitals_submission"):
                c1, c2, c3 = st.columns(3)
                weight = c1.number_input("Weight (kg)", value=68.5, step=0.1)
                temp = c2.number_input("Body Temp (°F)", value=98.6, step=0.1)
                hr = c3.number_input("Heart Rate (BPM)", value=72)

                c4, c5 = st.columns(2)
                sbp = c4.number_input("Systolic BP", value=120)
                dbp = c5.number_input("Diastolic BP", value=80)

                symptoms = st.multiselect("Report Current Symptoms:", [
                    "Low urine output", "Graft site pain", "Swelling in feet/hands",
                    "Shortness of breath", "Incision drainage", "Nausea/Vomiting"
                ])

                if st.form_submit_button("Submit Vitals Entry", type="primary", use_container_width=True):
                    latest_existing = vitals_col.find_one({"patient_name": selected_patient}, sort=[("timestamp", -1)]) or {}
                    vitals_col.insert_one({
                        "patient_id": p_profile.get("patient_id", "PT-1001"),
                        "patient_name": selected_patient,
                        "timestamp": datetime.now(timezone.utc),
                        "weight_kg": float(weight),
                        "temperature_f": float(temp),
                        "heart_rate": int(hr),
                        "systolic_bp": int(sbp),
                        "diastolic_bp": int(dbp),
                        "symptoms": symptoms,
                        "creatinine": latest_existing.get("creatinine", 1.2),
                        "tacrolimus": latest_existing.get("tacrolimus", 7.5)
                    })
                    log_audit_event("Patient", selected_patient, "SUBMIT_VITALS", {"weight": weight, "temp": temp})
                    st.success("✅ Vitals submitted successfully!")
                    st.rerun()

    with tab_trends:
        render_vitals_trends_with_custom_markers(selected_patient)

    with tab_messages:
        render_communication_hub(selected_patient, "Patient Portal")

    with tab_labs:
        render_diagnostics_viewer(selected_patient, allow_upload=True, actor_role="Patient")

    with tab_register:
        with st.container(border=True):
            st.subheader("Register New Patient Account")
            with st.form("new_patient_self_reg"):
                np_name = st.text_input("Full Name:")
                np_id = st.text_input("Medical Record ID (MRN):")
                np_organ = st.selectbox("Organ Type:", ["Kidney", "Liver", "Heart", "Lung", "Pancreas"])
                np_tx_date = st.date_input("Transplant Date:", value=date.today())
                np_allergies = st.text_input("Known Allergies (comma separated):", value="NSAIDs")
                
                if st.form_submit_button("Create Account Profile", type="primary", use_container_width=True):
                    if np_name.strip():
                        success, msg = create_new_patient_profile(
                            np_name.strip(), np_id.strip(), np_organ, np_tx_date, [a.strip() for a in np_allergies.split(",")],
                            [{"drug": "Tacrolimus", "EHR_dose": "2mg BID", "patient_dose": "2mg BID", "status": "Matched"}]
                        )
                        if success:
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(msg)

    with tab_fb:
        render_feedback_section("Patient")

# ---------------------------------------------------------
# ROLE 2: CAREGIVER PROXY VIEW
# ---------------------------------------------------------
elif active_role == "Caregiver Proxy":
    st.subheader("👥 Caregiver Proxy Management")
    selected_patient = st.selectbox("Select Patient Profile:", options=all_registered_patients)

    tab_trends, tab_messages, tab_labs, tab_fb = st.tabs(["📊 Patient Vitals", "💬 Care Team Messaging", "🧪 Diagnostic Reports", "💬 System Feedback"])

    with tab_trends:
        render_vitals_trends_with_custom_markers(selected_patient)

    with tab_messages:
        render_communication_hub(selected_patient, "Caregiver Proxy View")

    with tab_labs:
        render_diagnostics_viewer(selected_patient, allow_upload=False, actor_role="Caregiver")

    with tab_fb:
        render_feedback_section("Caregiver Proxy")

# ---------------------------------------------------------
# ROLE 3: DOCTOR WORKSPACE
# ---------------------------------------------------------
elif active_role == "Doctor Workspace":
    st.subheader("👨‍⚕️ Nephrologist Triage Workspace")

    selected_p = st.selectbox("Select Active Patient:", options=all_registered_patients)
    patient_doc = patients_col.find_one({"patient_name": selected_p}) or {}
    logs = list(vitals_col.find({"patient_name": selected_p}).sort("timestamp", -1))
    latest = logs[0] if logs else {}
    prev = logs[1] if len(logs) > 1 else None

    status_code, red_flags, amber_flags, explanations = evaluate_clinical_triage(latest, prev)

    if status_code == "RED":
        st.markdown(f'<div class="status-badge-red">🔴 CRITICAL ALERT: {", ".join(red_flags) or "Requires Immediate Clinical Review"}</div>', unsafe_allow_html=True)
    elif status_code == "AMBER":
        st.markdown(f'<div class="status-badge-amber">🟡 WARNING: {", ".join(amber_flags) or "Parameter Deviation Spike Detected"}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="status-badge-green">🟢 STABLE: All clinical parameters within baseline ruleset limits</div>', unsafe_allow_html=True)

    tab_triage, tab_vitals, tab_notes, tab_rx, tab_fb = st.tabs([
        "🚨 Triage & Action", 
        "📊 Vital Trends & Markers", 
        "📝 Consultation Notes", 
        "💊 Drug Clearance",
        "💬 System Feedback"
    ])

    with tab_triage:
        with st.container(border=True):
            st.markdown("##### Clinical Assessment & Status Control")
            for exp in explanations:
                st.write(f"• {exp}")

            st.divider()
            st.markdown("##### Override Triage Category")
            c_ov1, c_ov2 = st.columns([2, 1])
            override_val = c_ov1.selectbox("Override Status Level:", ["GREEN", "AMBER", "RED"])
            override_reason = c_ov2.text_input("Override Justification:")
            if st.button("Apply Manual Status Override", type="primary"):
                if latest:
                    vitals_col.update_one({"_id": latest["_id"]}, {"$set": {"override_status": override_val, "override_reason": override_reason}})
                    log_audit_event("Doctor", "DOC-01", "OVERRIDE_TRIAGE", {"patient": selected_p, "status": override_val})
                    st.success("✅ Triage status override recorded!")
                    st.rerun()

    with tab_vitals:
        render_vitals_trends_with_custom_markers(selected_p)

    with tab_notes:
        with st.container(border=True):
            st.markdown("##### Publish Consultation Note")
            with st.form("doc_notes_form"):
                hist = st.text_area("Subjective History:", value="Patient feels well. No fever reported.")
                exam = st.text_area("Objective Examination:", value="BP well controlled. Graft non-tender.")
                disp = st.selectbox("Disposition Plan:", ["Maintain Current Protocol", "Adjust Immunosuppression Dosage", "Order Outpatient Graft Ultrasound"])
                if st.form_submit_button("Sign & Publish Clinical Note", type="primary", use_container_width=True):
                    notes_col.insert_one({
                        "patient_name": selected_p, "doctor_name": "Dr. Sarah Jenkins",
                        "history": hist, "examination": exam, "disposition": disp,
                        "timestamp": datetime.now(timezone.utc)
                    })
                    log_audit_event("Doctor", "DOC-01", "PUBLISH_NOTE", {"patient": selected_p, "disposition": disp})
                    st.success("✅ Clinical note signed and published!")
                    st.rerun()

    with tab_rx:
        with st.container(border=True):
            st.markdown("##### Drug Interaction & Contraindication Check")
            p_allergies = patient_doc.get("allergies", [])
            st.write(f"Known Patient Allergies: `{', '.join(p_allergies) if p_allergies else 'None Recorded'}`")
            rx_med = st.selectbox("Test Candidate Prescription:", ["Tacrolimus", "Ibuprofen (NSAID)", "Penicillin", "Erythromycin"])
            if rx_med == "Ibuprofen (NSAID)" and "NSAIDs" in p_allergies:
                st.error("🚨 ALLERGY CONTRAINDICATION DETECTED: Patient has recorded NSAID allergy!")
            elif rx_med == "Penicillin" and "Penicillin" in p_allergies:
                st.error("🚨 ALLERGY CONTRAINDICATION DETECTED: Patient has recorded Penicillin allergy!")
            elif rx_med == "Erythromycin":
                st.warning("⚠️ CYP3A4 Interaction Warning: Potential elevation of Tacrolimus blood concentrations.")
            else:
                st.success(f"✅ Prescribing cleared for {rx_med}.")

    with tab_fb:
        render_feedback_section("Doctor Workspace")

# ---------------------------------------------------------
# ROLE 4: TRANSPLANT COORDINATOR WORKFLOW
# ---------------------------------------------------------
elif active_role == "Transplant Coordinator":
    st.subheader("📋 Transplant Coordinator Workstation")
    selected_p = st.selectbox("Select Active Patient Profile:", options=all_registered_patients)
    p_profile = patients_col.find_one({"patient_name": selected_p}) or {}

    tab_meds, tab_appts, tab_onboard, tab_fb = st.tabs([
        "💊 Medication Reconciliation", 
        "📅 Appointments & Messages", 
        "➕ Patient Onboarding",
        "💬 System Feedback"
    ])

    with tab_meds:
        with st.container(border=True):
            st.markdown("##### Medication Reconciliation Suite")
            meds = p_profile.get("current_medications", [])
            if meds:
                updated_meds = []
                for i, m in enumerate(meds):
                    st.markdown(f"**Medication #{i+1}: {m.get('drug')}**")
                    c_m1, c_m2, c_m3 = st.columns([2, 2, 1])
                    ehr_d = c_m1.text_input(f"EHR Dose ({m.get('drug')})", value=m.get('EHR_dose', '3mg BID'), key=f"ehr_{i}")
                    pat_d = c_m2.text_input(f"Patient Reported ({m.get('drug')})", value=m.get('patient_dose', '3mg BID'), key=f"pat_{i}")
                    
                    m_status = "Matched" if ehr_d == pat_d else "Mismatch"
                    c_m3.write(f"Status: **{m_status}**")
                    
                    updated_meds.append({"drug": m.get("drug"), "EHR_dose": ehr_d, "patient_dose": pat_d, "status": m_status})
                    st.divider()

                if st.button("Save Reconciled Medication State", type="primary"):
                    patients_col.update_one({"patient_name": selected_p}, {"$set": {"current_medications": updated_meds}})
                    log_audit_event("Coordinator", "COORD-01", "RECONCILE_MEDS", {"patient": selected_p})
                    st.success("✅ Medication state successfully updated and reconciled!")
                    st.rerun()
            else:
                st.info("No recorded medications for this patient.")

    with tab_appts:
        with st.container(border=True):
            st.markdown("##### Schedule Patient Appointment")
            app_date = st.date_input("Scheduled Date:")
            app_type = st.selectbox("Appointment Type:", ["Graft Ultrasound", "Routine Outpatient Labs", "Renal Biopsy Consult"])
            if st.button("Confirm Appointment Booking", type="primary"):
                patients_col.update_one({"patient_name": selected_p}, {"$push": {"appointments": {"date": str(app_date), "type": app_type}}})
                log_audit_event("Coordinator", "COORD-01", "SCHEDULE_APPOINTMENT", {"patient": selected_p, "type": app_type, "date": str(app_date)})
                st.success("✅ Appointment successfully scheduled!")

        render_communication_hub(selected_p, "Transplant Coordinator")

    with tab_onboard:
        with st.container(border=True):
            st.markdown("##### Register Patient Profile")
            with st.form("coord_reg_form"):
                c_name = st.text_input("Patient Full Name:")
                c_id = st.text_input("MRN / Patient ID:")
                c_organ = st.selectbox("Organ Type:", ["Kidney", "Liver", "Heart", "Lung", "Pancreas"])
                c_tx_date = st.date_input("Transplant Date:", value=date.today())
                c_allergies = st.text_input("Known Allergies (comma separated):", value="NSAIDs")
                
                if st.form_submit_button("Create Profile", type="primary", use_container_width=True):
                    if c_name.strip():
                        success, msg = create_new_patient_profile(
                            c_name.strip(), c_id.strip(), c_organ, c_tx_date, [a.strip() for a in c_allergies.split(",")],
                            [{"drug": "Tacrolimus", "EHR_dose": "3mg BID", "patient_dose": "3mg BID", "status": "Matched"}]
                        )
                        if success:
                            st.success(f"✅ {msg}")
                            st.rerun()
                        else:
                            st.error(msg)

    with tab_fb:
        render_feedback_section("Transplant Coordinator")

# ---------------------------------------------------------
# ROLE 5: SYSTEM ADMINISTRATOR
# ---------------------------------------------------------
elif active_role == "System Admin":
    st.subheader("⚙️ System Governance & Administration")

    tab_rules, tab_audit, tab_feedback = st.tabs([
        "📜 Clinical Rules Engine", 
        "🛡️ Governance Audit Log", 
        "💬 User Feedback Stream"
    ])

    with tab_rules:
        with st.container(border=True):
            st.markdown("##### Live Clinical Threshold Parameters")
            active_ruleset = rules_col.find_one({"active": True}) or {}
            params = active_ruleset.get("parameters", {})
            
            with st.form("update_rules"):
                c1, c2 = st.columns(2)
                new_wt = c1.number_input("Max 24h Weight Gain Threshold (kg)", value=float(params.get("weight_spike_kg", 1.5)), step=0.1)
                new_fever = c2.number_input("Fever Alert Threshold (°F)", value=float(params.get("fever_temp_f", 100.0)), step=0.1)
                
                c3, c4 = st.columns(2)
                new_tac_hi = c3.number_input("Tacrolimus High Threshold (ng/mL)", value=float(params.get("tacrolimus_high", 12.0)), step=0.5)
                new_creat_hi = c4.number_input("Creatinine High Threshold (mg/dL)", value=float(params.get("creatinine_high", 1.8)), step=0.1)

                if st.form_submit_button("Publish Updated Ruleset Version", type="primary", use_container_width=True):
                    rules_col.update_one(
                        {"_id": active_ruleset["_id"]}, 
                        {"$set": {
                            "parameters.weight_spike_kg": new_wt,
                            "parameters.fever_temp_f": new_fever,
                            "parameters.tacrolimus_high": new_tac_hi,
                            "parameters.creatinine_high": new_creat_hi
                        }}
                    )
                    log_audit_event("System Admin", "ADMIN-01", "UPDATE_RULESET", {"weight_threshold": new_wt, "fever_threshold": new_fever})
                    st.success("✅ Ruleset updated and published successfully!")
                    st.rerun()

    with tab_audit:
        with st.container(border=True):
            st.markdown("##### System Action Audit Trail")
            logs = list(audit_col.find().sort("timestamp", -1))
            if logs:
                df_logs = pd.DataFrame(logs)
                df_logs["timestamp"] = df_logs["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                st.dataframe(df_logs.reindex(columns=["timestamp", "actor_role", "actor_id", "action", "details"]), use_container_width=True, hide_index=True)
            else:
                st.info("No recorded audit logs.")

    with tab_feedback:
        with st.container(border=True):
            st.markdown("##### Received User Feedback")
            user_feedbacks = list(feedback_col.find().sort("timestamp", -1))
            if user_feedbacks:
                df_fb = pd.DataFrame(user_feedbacks)
                df_fb["timestamp"] = df_fb["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                st.dataframe(df_fb.reindex(columns=["timestamp", "role", "category", "rating", "comment"]), use_container_width=True, hide_index=True)
            else:
                st.info("No submitted user feedback yet.")
