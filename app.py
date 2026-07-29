import os
import certifi
import base64
import smtplib
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from pymongo import MongoClient, errors
from datetime import datetime, date, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ---------------------------------------------------------
# 1. Page Config & Custom Styling (Dashboard Layout)
# ---------------------------------------------------------
st.set_page_config(
    page_title="Enterprise Post-Transplant Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)

def inject_custom_design():
    """Injects modern, clean CSS for responsive dashboard grids, Apple-style elements, and status ribbons."""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif;
    }

    /* Prevent mobile scroll trapping inside Streamlit expanders */
    .stExpander, [data-testid="stExpander"] {
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }
    
    [data-testid="stExpanderDetails"] {
        max-height: none !important;
        height: auto !important;
        overflow: visible !important;
    }

    /* Position Feedback Floating Icon on Bottom-Left */
    .feedback-floating-container {
        position: fixed;
        bottom: 24px;
        left: 20px;
        z-index: 999998;
    }

    .feedback-floating-container [data-testid="stPopover"] > button {
        background: rgba(255, 255, 255, 0.9) !important;
        backdrop-filter: blur(16px) saturate(180%) !important;
        -webkit-backdrop-filter: blur(16px) saturate(180%) !important;
        border: 1px solid rgba(209, 213, 219, 0.6) !important;
        border-radius: 50% !important;
        width: 50px !important;
        height: 50px !important;
        box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15) !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        font-size: 20px !important;
        transition: transform 0.2s ease !important;
    }

    .feedback-floating-container [data-testid="stPopover"] > button:hover {
        transform: scale(1.08);
    }

    /* Dashboard Metric Styling */
    [data-testid="stMetric"] {
        background-color: #f8f9fa;
        border-radius: 12px;
        border: 1px solid #e9ecef;
        padding: 12px 16px !important;
        box-shadow: 0 2px 4px rgba(0,0,0,0.02);
    }

    /* Apple-style status ribbons */
    .ribbon-red {
        background-color: rgba(255, 59, 48, 0.12);
        color: #d70015;
        padding: 12px 16px;
        border-radius: 12px;
        border-left: 4px solid #ff3b30;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .ribbon-amber {
        background-color: rgba(255, 149, 0, 0.12);
        color: #b25000;
        padding: 12px 16px;
        border-radius: 12px;
        border-left: 4px solid #ff9500;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .ribbon-green {
        background-color: rgba(52, 199, 89, 0.12);
        color: #248a3d;
        padding: 12px 16px;
        border-radius: 12px;
        border-left: 4px solid #34c759;
        font-weight: 600;
        margin-bottom: 12px;
    }
    </style>
    """, unsafe_allow_html=True)

inject_custom_design()

# ---------------------------------------------------------
# 2. Database Initialization & Seeding
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

# Collections
vitals_col = db["vitals_logs"]
notifs_col = db["patient_notifications"]
notes_col = db["clinical_notes"]
audit_col = db["audit_logs"]
rules_col = db["ruleset_versions"]
patients_col = db["patient_profiles"]
diagnostics_col = db["diagnostic_reports"]
feedback_col = db["user_feedback"]

# Seed Active Ruleset Document
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

# Seed Initial Patient Profile
if patients_col.count_documents({"patient_name": "Sarah Connor"}) == 0:
    patients_col.insert_one({
        "patient_name": "Sarah Connor",
        "patient_id": "PT-1001",
        "organ_type": "Kidney",
        "transplant_date": "2026-01-15",
        "allergies": ["NSAIDs", "Penicillin"],
        "current_medications": [
            {"drug": "Tacrolimus", "dose": "3mg BID", "status": "Matched"},
            {"drug": "Prednisone", "EHR_dose": "5mg Daily", "patient_dose": "10mg Daily", "status": "Mismatch"}
        ],
        "appointments": []
    })

# ---------------------------------------------------------
# 3. Helpers & Clinical Engine
# ---------------------------------------------------------
def send_feedback_gmail(category, rating, comment, actor_role):
    """Sends a formatted feedback notification email via Gmail SMTP using Streamlit secrets."""
    admin_email = st.secrets.get("ADMIN_EMAIL", "")
    smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = st.secrets.get("SMTP_PORT", 587)
    smtp_user = st.secrets.get("SMTP_USER", "")
    smtp_pass = st.secrets.get("SMTP_PASSWORD", "")

    if not (admin_email and smtp_user and smtp_pass):
        return False, "Gmail SMTP secrets (`ADMIN_EMAIL`, `SMTP_USER`, `SMTP_PASSWORD`) are not fully configured in `.streamlit/secrets.toml`."

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"🚨 New Portal Feedback: [{category}]"
        msg["From"] = smtp_user
        msg["To"] = admin_email

        html_content = f"""
        <h2>New User Feedback Submitted</h2>
        <hr>
        <p><strong>Role:</strong> {actor_role}</p>
        <p><strong>Category:</strong> {category}</p>
        <p><strong>Rating:</strong> {rating}/5 Stars</p>
        <p><strong>Submitted At:</strong> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
        <br>
        <h3>Feedback Comment:</h3>
        <blockquote style="background: #f4f4f5; padding: 12px; border-left: 4px solid #007aff; border-radius: 4px;">
            {comment}
        </blockquote>
        """
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(smtp_server, int(smtp_port)) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, admin_email, msg.as_string())

        return True, "Email successfully dispatched to Admin."
    except Exception as e:
        return False, str(e)

def render_feedback_floating_widget(active_role):
    """Renders a floating bottom-left popover icon for direct user feedback and Gmail integration."""
    st.markdown('<div class="feedback-floating-container">', unsafe_allow_html=True)
    with st.popover("💬", help="Submit Feedback"):
        st.subheader("💬 Send Platform Feedback")
        st.caption("Found an issue or have a feature request? Let us know!")

        with st.form("gmail_feedback_form", clear_on_submit=True):
            category = st.selectbox("Category:", ["Bug Report", "Feature Request", "UI/UX Suggestion", "General Feedback"])
            stars_idx = st.feedback("stars")
            rating = (stars_idx + 1) if stars_idx is not None else 5
            comment = st.text_area("Your Feedback / Details:", placeholder="Describe what happened or how we can improve...")

            submitted = st.form_submit_button("Submit & Send Email", use_container_width=True, type="primary")

            if submitted:
                if not comment.strip():
                    st.warning("Please provide a brief comment before submitting.")
                else:
                    feedback_col.insert_one({
                        "role": active_role,
                        "category": category,
                        "rating": rating,
                        "comment": comment.strip(),
                        "timestamp": datetime.now(timezone.utc)
                    })

                    log_audit_event(active_role, "LOCAL-USER", "SUBMIT_FEEDBACK", {
                        "category": category,
                        "rating": rating
                    })

                    success, email_msg = send_feedback_gmail(category, rating, comment.strip(), active_role)

                    if success:
                        st.success("✅ Thank you! Your feedback was emailed directly to the team.")
                    else:
                        st.success("✅ Feedback saved to database!")
                        st.info(f"ℹ️ Note on Email Delivery: {email_msg}")

    st.markdown('</div>', unsafe_allow_html=True)

def render_clinical_disclaimer():
    """Renders persistent decision-support disclaimer."""
    st.warning(
        "⚠️ **CLINICAL DECISION-SUPPORT DISCLAIMER:** "
        "This system is an auxiliary clinical decision-support tool. "
        "It does not replace independent clinical evaluation, direct physical examination, or professional medical judgment. "
        "All automated triage scoring, lab/imaging reports, and interaction warnings must be verified by a licensed clinician prior to clinical intervention.",
        icon="🩺"
    )

def log_audit_event(actor_role: str, actor_id: str, action: str, details: dict):
    """Central audit function for recording every system action to MongoDB."""
    audit_col.insert_one({
        "timestamp": datetime.now(timezone.utc),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "details": details
    })

def render_dynamic_patient_fields():
    """Fetches custom field definitions from DB and dynamically renders inputs."""
    custom_inputs = {}
    dynamic_fields = list(db["schema_config"].find({"entity": "patient_input"}))
    
    if dynamic_fields:
        st.markdown("#### ⚙️ Additional Required Parameters")
        grid_cols = st.columns(2)
        
        for idx, field in enumerate(dynamic_fields):
            field_name = field.get("field_name")
            field_type = field.get("field_type", "Text")
            label = f"{field_name} ({field.get('unit', '')})" if field.get('unit') else field_name
            col = grid_cols[idx % 2]
            
            if field_type == "Number":
                custom_inputs[field_name] = col.number_input(label, value=0.0, key=f"dyn_{field_name}")
            elif field_type == "Select":
                options = field.get("options", ["Normal", "Abnormal"])
                custom_inputs[field_name] = col.selectbox(label, options=options, key=f"dyn_{field_name}")
            else:
                custom_inputs[field_name] = col.text_input(label, key=f"dyn_{field_name}")
                
    return custom_inputs

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
            explanations.append(f"Weight change {wt_change:.1f}kg exceeds rule limit {params['weight_spike_kg']}kg")

    temp = latest_doc.get("temperature_f", 98.6)
    if temp >= params["fever_temp_f"]:
        red_flags.append(f"Fever Alert ({temp:.1f}°F)")
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

def render_vitals_trends(patient_name: str):
    """Generates interactive trends and full historical logs safely."""
    logs = list(vitals_col.find({"patient_name": patient_name}).sort("timestamp", 1))
    
    if not logs:
        st.info(f"No historical trends available for {patient_name}.")
        return

    df = pd.DataFrame(logs)
    df["Formatted_Time"] = df["timestamp"].dt.strftime("%b %d, %H:%M")

    col_t1, col_t2 = st.columns(2)

    with col_t1:
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df["Formatted_Time"], y=df.get("weight_kg", []), mode="lines+markers", name="Weight (kg)", line=dict(color="#007aff", width=3)))
        fig1.add_trace(go.Scatter(x=df["Formatted_Time"], y=df.get("temperature_f", []), mode="lines+markers", name="Temp (°F)", yaxis="y2", line=dict(color="#ff9500", width=2, dash="dash")))
        
        fig1.update_layout(
            title=f"📈 Weight & Temp History ({len(df)} Entries)",
            xaxis_title="Time",
            yaxis=dict(title="Weight (kg)"),
            yaxis2=dict(title="Temp (°F)", overlaying="y", side="right"),
            height=300,
            margin=dict(l=20, r=20, t=40, b=20),
            template="plotly_white"
        )
        st.plotly_chart(fig1, use_container_width=True)

    with col_t2:
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df["Formatted_Time"], y=df.get("tacrolimus", []), mode="lines+markers", name="Tacrolimus (ng/mL)", line=dict(color="#34c759", width=3)))
        fig2.add_trace(go.Scatter(x=df["Formatted_Time"], y=df.get("creatinine", []), mode="lines+markers", name="Creatinine (mg/dL)", yaxis="y2", line=dict(color="#ff3b30", width=3)))
        
        fig2.update_layout(
            title="🧪 Tacrolimus & Creatinine Labs",
            xaxis_title="Time",
            yaxis=dict(title="Tacrolimus"),
            yaxis2=dict(title="Creatinine", overlaying="y", side="right"),
            height=300,
            margin=dict(l=20, r=20, t=40, b=20),
            template="plotly_white"
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("##### 📜 Chronological Entry Logs")
    target_cols = ["timestamp", "weight_kg", "systolic_bp", "diastolic_bp", "temperature_f", "heart_rate", "tacrolimus", "creatinine", "symptoms"]
    display_df = df.reindex(columns=target_cols).copy()
    display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M UTC")
    display_df.columns = ["Timestamp", "Weight (kg)", "Sys BP", "Dia BP", "Temp (°F)", "Heart Rate", "Tacrolimus", "Creatinine", "Reported Symptoms"]
    st.dataframe(display_df, use_container_width=True)

def render_custom_markers(patient_name: str, key_prefix: str = "default"):
    """Render custom dynamic parameter historical graphs for a patient profile."""
    patient_logs = list(vitals_col.find({"patient_name": patient_name}).sort("timestamp", 1))
    custom_marker_names = set()
    for log in patient_logs:
        if "custom_fields" in log and isinstance(log["custom_fields"], dict):
            custom_marker_names.update(log["custom_fields"].keys())
            
    if not custom_marker_names:
        st.info("No custom parameters logged for this patient yet.")
        return

    selected_marker = st.selectbox(
        "Select Custom Marker to Inspect:",
        options=sorted(list(custom_marker_names)),
        key=f"{key_prefix}_custom_marker_{patient_name}"
    )
    
    marker_series = []
    for log in patient_logs:
        c_fields = log.get("custom_fields", {})
        if selected_marker in c_fields:
            val = c_fields[selected_marker]
            try:
                num_val = float(val)
            except (ValueError, TypeError):
                num_val = None
                
            marker_series.append({
                "Timestamp": log.get("timestamp"),
                "Value": val,
                "NumericValue": num_val
            })
            
    if marker_series:
        df_marker = pd.DataFrame(marker_series)
        numeric_df = df_marker.dropna(subset=["NumericValue"])
        
        m_col1, m_col2, m_col3 = st.columns(3)
        latest_val = df_marker.iloc[-1]["Value"]
        
        with m_col1:
            st.metric(f"Latest {selected_marker}", str(latest_val))
        if not numeric_df.empty:
            with m_col2:
                st.metric("Historical Min", f"{numeric_df['NumericValue'].min():.2f}")
            with m_col3:
                st.metric("Historical Max", f"{numeric_df['NumericValue'].max():.2f}")
        else:
            with m_col2:
                st.metric("Total Logged Entries", len(df_marker))
            with m_col3:
                st.metric("Data Type", "Text / Categorical")
                
        st.divider()
        if not numeric_df.empty and len(numeric_df) > 1:
            fig = px.line(
                numeric_df, x="Timestamp", y="NumericValue", markers=True,
                title=f"Trend: {selected_marker} over Time",
                labels={"NumericValue": selected_marker, "Timestamp": "Date / Time"}
            )
            fig.update_layout(template="plotly_white", height=300, margin=dict(l=20, r=20, t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        
        st.markdown("##### Detailed Log History")
        st.dataframe(df_marker[["Timestamp", "Value"]].sort_values(by="Timestamp", ascending=False), use_container_width=True, hide_index=True)

# ---------------------------------------------------------
# 4. Shared Components
# ---------------------------------------------------------
def render_communication_hub(patient_name: str, active_role: str):
    st.markdown("#### 💬 Care Team Messages")
    
    messages = list(notifs_col.find({"patient_name": patient_name}).sort("timestamp", -1))
    
    if not messages:
        st.info("No active message history for this profile.")
    else:
        for msg in messages:
            urgency = msg.get("urgency", "Routine")
            badge = "🔴 URGENT" if "Urgent" in urgency else "🟢 ROUTINE"
            sender_role = msg.get("sender", "system")
            avatar = "📱" if sender_role == "patient" else ("👥" if sender_role == "caregiver" else "👨‍⚕️")
            
            with st.chat_message("user" if sender_role in ["patient", "caregiver"] else "assistant", avatar=avatar):
                st.caption(f"{badge} | **{msg.get('author', 'Unknown')}** | {msg.get('timestamp').strftime('%b %d, %H:%M UTC')}")
                st.write(msg.get("message"))

    with st.form(key=f"msg_form_{patient_name}_{active_role}"):
        msg_text = st.text_area("Write message:", height=70)
        msg_urgency = st.selectbox("Priority:", ["Routine Message", "Urgent Clinical Alert"])
        
        if st.form_submit_button("Send Transmission"):
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
                st.success(" ✅ Message transmitted and recorded in message history and audit logs!")
                st.rerun()

def render_diagnostics_viewer(patient_name: str, allow_upload: bool = False, actor_role: str = "Patient"):
    """Renders the diagnostic directory without scrolling locks and with full audit tracking."""
    st.markdown(f"#### 🔬 Diagnostic Reports & Imaging Directory: **{patient_name}**")

    if allow_upload:
        st.subheader("📤 Upload Diagnostic Study / Lab Entry")
        with st.form(key=f"upload_diag_form_{patient_name}_{actor_role}"):
            d_category = st.selectbox("Report Category:", ["Urinalysis (UA)", "Comprehensive Lab Panel", "Ultrasound / Imaging Report"])
            d_file = st.file_uploader("Attach Report File (PDF/PNG/JPG):", type=["pdf", "png", "jpg"])
            d_notes = st.text_area("Clinical Notes / Finding Summary:")
            
            col_a, col_b = st.columns(2)
            c_val1 = col_a.number_input("Serum Creatinine (mg/dL) [Lab]", value=1.2, step=0.1)
            c_val2 = col_b.number_input("Tacrolimus Level (ng/mL) [Lab]", value=7.5, step=0.1)
            
            ua_col1, ua_col2 = st.columns(2)
            ua_protein = ua_col1.selectbox("Protein [Urinalysis]:", ["Negative", "Trace", "+1 (30 mg/dL)", "+2 (100 mg/dL)", "+3 (300 mg/dL)"])
            ua_wbc = ua_col2.selectbox("WBC Esterase [Urinalysis]:", ["Negative", "Trace", "Positive"])
            
            img_impression = st.text_input("Radiology Impression [Imaging]:", value="Normal vascular resistive indices in allografts. No hydronephrosis.")

            if st.form_submit_button("Upload & Parse Diagnostic Report"):
                f_name = d_file.name if d_file else "Manual_Entry.pdf"
                report_doc = {
                    "patient_name": patient_name,
                    "category": d_category,
                    "uploaded_by": actor_role,
                    "notes": d_notes,
                    "creatinine": c_val1,
                    "tacrolimus": c_val2,
                    "urinalysis": {"protein": ua_protein, "wbc_esterase": ua_wbc},
                    "imaging_impression": img_impression,
                    "file_name": f_name,
                    "timestamp": datetime.now(timezone.utc)
                }
                diagnostics_col.insert_one(report_doc)
                
                vitals_col.insert_one({
                    "patient_name": patient_name,
                    "timestamp": datetime.now(timezone.utc),
                    "weight_kg": 70.0,
                    "temperature_f": 98.6,
                    "heart_rate": 72,
                    "systolic_bp": 120,
                    "diastolic_bp": 80,
                    "symptoms": ["Lab Update"],
                    "creatinine": c_val1,
                    "tacrolimus": c_val2
                })
                
                log_audit_event(actor_role, "USER-LOCAL", "UPLOAD_DIAGNOSTIC", {
                    "patient": patient_name,
                    "category": d_category,
                    "file_name": f_name,
                    "creatinine": c_val1,
                    "tacrolimus": c_val2
                })
                st.success(f"✅ {d_category} uploaded and committed to MongoDB & Audit Trail!")
                st.rerun()

    st.divider()
    st.markdown("##### 📁 Historical Diagnostic Reports")
    reports = list(diagnostics_col.find({"patient_name": patient_name}).sort("timestamp", -1))
    
    if not reports:
        st.info("No historical lab, urinalysis, or imaging reports found for this patient.")
    else:
        for r in reports:
            cat_icon = "🧪" if "Lab" in r['category'] else ("🔬" if "Urinalysis" in r['category'] else "📸")
            with st.expander(f"{cat_icon} {r['category']} — {r['timestamp'].strftime('%b %d, %Y %H:%M UTC')}", expanded=False):
                st.caption(f"Uploaded by: **{r.get('uploaded_by', 'System')}** | File: `{r.get('file_name', 'N/A')}`")
                
                if "Urinalysis" in r['category']:
                    u = r.get("urinalysis", {})
                    st.write(f"• **Urinalysis Protein:** `{u.get('protein', 'N/A')}` | **WBC Esterase:** `{u.get('wbc_esterase', 'N/A')}`")
                elif "Imaging" in r['category']:
                    st.write(f"• **Radiology Impression:** `{r.get('imaging_impression', 'N/A')}`")
                else:
                    st.write(f"• **Serum Creatinine:** `{r.get('creatinine')} mg/dL` | **Tacrolimus Level:** `{r.get('tacrolimus')} ng/mL`")
                
                if r.get("notes"):
                    st.write(f"**Notes:** {r.get('notes')}")

def render_clinical_notes_viewer(patient_name: str):
    """Retrieves and displays signed clinical consultation notes for the patient."""
    notes = list(notes_col.find({"patient_name": patient_name}).sort("timestamp", -1))
    
    if not notes:
        st.info("No published clinical notes available at this time.")
        return

    for n in notes:
        ts = n.get("timestamp")
        time_str = ts.strftime("%b %d, %Y at %H:%M UTC") if isinstance(ts, datetime) else "N/A"
        doc_name = n.get("doctor_name", "Attending Physician")
        
        with st.expander(f"📋 Note by {doc_name} — {time_str}", expanded=False):
            st.markdown(f"**Disposition / Plan:** `{n.get('disposition', 'N/A')}`")
            st.divider()
            col_h, col_e = st.columns(2)
            with col_h:
                st.markdown("**Subjective History:**")
                st.write(n.get("history", "N/A"))
            with col_e:
                st.markdown("**Objective Examination:**")
                st.write(n.get("examination", "N/A"))

# ---------------------------------------------------------
# 5. Global Sidebar Navigation & Role Selector Layout
# ---------------------------------------------------------
all_registered_patients = sorted(patients_col.distinct("patient_name")) or ["Sarah Connor"]

role_options = [
    "Patient Portal",
    "Caregiver Proxy View",
    "Doctor (Nephrologist)",
    "Transplant Coordinator",
    "System Administrator"
]

role_icons = {
    "Patient Portal": "📱",
    "Caregiver Proxy View": "👥",
    "Doctor (Nephrologist)": "👨‍⚕️",
    "Transplant Coordinator": "📋",
    "System Administrator": "⚙️"
}

with st.sidebar:
    st.title("🩺 Transplant Portal")
    st.markdown("---")
    
    active_role = st.selectbox(
        "👤 Select Active Role:",
        options=role_options,
        index=0,
        format_func=lambda r: f"{role_icons.get(r, '⚙️')} {r}"
    )
    st.session_state.active_role = active_role
    st.markdown("---")

    # Dynamic Sidebar Sub-Navigation
    if active_role == "Patient Portal":
        patient_nav = st.radio("Navigation", ["Dashboard & Vitals", "Diagnostic Studies", "Care Team Chat", "Clinical Notes", "Onboarding / Profile"])
    elif active_role == "Caregiver Proxy View":
        caregiver_nav = st.radio("Navigation", ["Overview Trends", "Custom Markers", "Diagnostics", "Care Team Chat", "Physician Notes"])
    elif active_role == "Doctor (Nephrologist)":
        doc_nav = st.radio("Navigation", ["Flight Board Queue", "Drug Interactions", "Consultation Entry"])
    elif active_role == "Transplant Coordinator":
        coord_nav = st.radio("Navigation", ["Patient Intake Queue", "Medication Reconciliation", "Schedule & Messages", "Onboard New Patient"])
    elif active_role == "System Administrator":
        admin_nav = st.radio("Navigation", ["Rules Engine", "Dynamic Parameters", "Patient Directory", "User Feedback", "Audit Logs"])

# Render Floating Feedback Widget on Bottom Left
render_feedback_floating_widget(active_role)

# =========================================================
# ROLE 1: PATIENT PORTAL
# =========================================================
if active_role == "Patient Portal":
    st.header("📱 Patient Self-Monitoring Portal")
    
    selected_patient = st.selectbox("Active Patient Profile:", options=all_registered_patients)
    p_profile = patients_col.find_one({"patient_name": selected_patient}) or {}
    latest_vitals = vitals_col.find_one({"patient_name": selected_patient}, sort=[("timestamp", -1)]) or {}

    # Top Overview Metrics Grid
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Weight", f"{latest_vitals.get('weight_kg', 'N/A')} kg")
    m2.metric("Temperature", f"{latest_vitals.get('temperature_f', 'N/A')} °F")
    m3.metric("Blood Pressure", f"{latest_vitals.get('systolic_bp', 'N/A')}/{latest_vitals.get('diastolic_bp', 'N/A')}")
    m4.metric("Tacrolimus", f"{latest_vitals.get('tacrolimus', 'N/A')} ng/mL")
    st.markdown("---")

    if patient_nav == "Dashboard & Vitals":
        st.subheader("📝 Daily Vitals Check-In")
        with st.form("patient_vitals_submission"):
            c1, c2, c3 = st.columns(3)
            weight = c1.number_input("Weight (kg)", value=68.5, step=0.1)
            temp = c2.number_input("Temp (°F)", value=98.6, step=0.1)
            hr = c3.number_input("Heart Rate (BPM)", value=72)

            c4, c5 = st.columns(2)
            sbp = c4.number_input("Systolic BP", value=120)
            dbp = c5.number_input("Diastolic BP", value=80)

            symptoms = st.multiselect("Report Active Symptoms:", [
                "Low urine output", "Graft site pain", "Swelling in feet/hands",
                "Shortness of breath", "Incision drainage", "Nausea/Vomiting"
            ])

            custom_data = render_dynamic_patient_fields()

            if st.form_submit_button("Submit Daily Vitals", type="primary", use_container_width=True):
                latest_existing = vitals_col.find_one({"patient_name": selected_patient}, sort=[("timestamp", -1)]) or {}
                
                log_doc = {
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
                    "tacrolimus": latest_existing.get("tacrolimus", 7.5),
                    "custom_fields": custom_data
                }
                vitals_col.insert_one(log_doc)
                log_audit_event("Patient", selected_patient, "SUBMIT_VITALS", {
                    "weight": weight, "temp": temp, "symptoms": symptoms, "bp": f"{sbp}/{dbp}"
                })
                st.success(f"✅ Vitals logged in MongoDB and Audit Trail for {selected_patient}!")
                st.rerun()

        st.divider()
        st.subheader("📊 Vitals Trends & History")
        render_vitals_trends(selected_patient)

    elif patient_nav == "Diagnostic Studies":
        render_diagnostics_viewer(selected_patient, allow_upload=True, actor_role="Patient")

    elif patient_nav == "Care Team Chat":
        render_communication_hub(selected_patient, "Patient Portal")

    elif patient_nav == "Clinical Notes":
        render_clinical_notes_viewer(selected_patient)

    elif patient_nav == "Onboarding / Profile":
        st.subheader("👤 Register New Patient Profile")
        with st.form("new_patient_self_reg"):
            c_a, c_b = st.columns(2)
            np_name = c_a.text_input("Full Patient Name:")
            np_id = c_b.text_input("Patient Medical Record ID (Optional):")
            
            c_c, c_d = st.columns(2)
            np_organ = c_c.selectbox("Transplant Organ Type:", ["Kidney", "Liver", "Heart", "Lung", "Pancreas"])
            np_tx_date = c_d.date_input("Transplant Date:", value=date.today())
            np_allergies = st.text_input("Known Allergies (comma separated):", value="NSAIDs")
            
            if st.form_submit_button("Register Patient Profile", type="primary"):
                if np_name.strip():
                    allergies_list = [a.strip() for a in np_allergies.split(",")]
                    success, msg = create_new_patient_profile(
                        np_name.strip(), np_id.strip(), np_organ, np_tx_date, allergies_list,
                        [{"drug": "Tacrolimus", "dose": "2mg BID", "status": "Matched"}]
                    )
                    if success:
                        log_audit_event("Patient", np_name, "PATIENT_REGISTERED", {"organ": np_organ, "allergies": allergies_list})
                        st.success(f"✅ {msg}")
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Please enter a valid patient name.")

# =========================================================
# ROLE 2: CAREGIVER PROXY VIEW
# =========================================================
elif active_role == "Caregiver Proxy View":
    st.header("👥 Caregiver Proxy View")
    st.info("🔒 Scoped Viewing Mode: Access restricted to authorized patient profiles.")

    patient_name = st.selectbox("Select Patient Profile:", options=all_registered_patients)

    if caregiver_nav == "Overview Trends":
        render_vitals_trends(patient_name)

    elif caregiver_nav == "Custom Markers":
        st.caption("Real-time telemetry for dynamic, schema-less parameters configured by the System Administrator.")
        render_custom_markers(patient_name, key_prefix="caregiver")

    elif caregiver_nav == "Diagnostics":
        render_diagnostics_viewer(patient_name, allow_upload=False, actor_role="Caregiver")

    elif caregiver_nav == "Care Team Chat":
        render_communication_hub(patient_name, "Caregiver Proxy View")

    elif caregiver_nav == "Physician Notes":
        render_clinical_notes_viewer(patient_name)

# =========================================================
# ROLE 3: DOCTOR (NEPHROLOGIST) WORKSPACE
# =========================================================
elif active_role == "Doctor (Nephrologist)":
    render_clinical_disclaimer()
    st.header("👨‍⚕️ Nephrologist Consultation & Triage Workspace")

    if doc_nav == "Flight Board Queue":
        st.caption("📱 **Mobile-Optimized Patient Flight Board**")
        for p_name in all_registered_patients:
            patient_doc = patients_col.find_one({"patient_name": p_name}) or {}
            logs = list(vitals_col.find({"patient_name": p_name}).sort("timestamp", -1))
            latest = logs[0] if logs else {}
            prev = logs[1] if len(logs) > 1 else None

            status_code, red_flags, amber_flags, explanations = evaluate_clinical_triage(latest, prev)

            if latest.get("override_status"):
                status_code = latest.get("override_status")

            if status_code == "RED":
                status_badge = "🔴 RED ALERT"
                summary_flags = f" — {', '.join(red_flags)}" if red_flags else " — Critical Review Required"
            elif status_code == "AMBER":
                status_badge = "🟡 AMBER WARNING"
                summary_flags = f" — {', '.join(amber_flags)}" if amber_flags else " — Parameter Spike"
            else:
                status_badge = "🟢 GREEN STABLE"
                summary_flags = " — All Vitals Normal"

            accordion_title = f"{status_badge} | {p_name} ({patient_doc.get('organ_type', 'Organ Transplant')}){summary_flags}"

            with st.expander(accordion_title, expanded=False):
                if status_code == "RED":
                    st.markdown(f'<div class="ribbon-red">🔴 CRITICAL TRIAGE ALERT: {", ".join(red_flags) or "Requires Immediate Intervention"}</div>', unsafe_allow_html=True)
                elif status_code == "AMBER":
                    st.markdown(f'<div class="ribbon-amber">🟡 WARNING: {", ".join(amber_flags) or "Abnormal Parameter Detected"}</div>', unsafe_allow_html=True)
                else:
                    st.markdown('<div class="ribbon-green">🟢 STABLE PATIENT STATUS: All vital signs within threshold bounds</div>', unsafe_allow_html=True)

                tab_triage, tab_vitals, tab_custom, tab_diag = st.tabs(["🚨 Triage Logic", "📊 Vitals Trends", "🧪 Custom Markers", "🔬 Diagnostics"])

                with tab_triage:
                    if explanations:
                        for exp in explanations:
                            st.caption(f"• {exp}")
                    else:
                        st.caption("• All logged parameters are currently within baseline thresholds.")

                    ov_col1, ov_col2 = st.columns([2, 1])
                    override_val = ov_col1.selectbox("Manual Override Status:", ["GREEN", "AMBER", "RED"], key=f"ov_val_{p_name}")
                    override_reason = ov_col2.text_input("Override Reason:", key=f"ov_reason_{p_name}")
                    
                    if st.button("Commit Status Override", key=f"btn_ov_{p_name}"):
                        if latest:
                            vitals_col.update_one({"_id": latest["_id"]}, {"$set": {"override_status": override_val, "override_reason": override_reason}})
                            log_audit_event("Doctor", "DOC-NEPH-01", "OVERRIDE_TRIAGE", {
                                "patient": p_name, "status": override_val, "reason": override_reason
                            })
                            st.success(f" ✅ Status overridden to {override_val} for {p_name} and logged in Audit Trail!")
                            st.rerun()

                with tab_vitals:
                    render_vitals_trends(p_name)

                with tab_custom:
                    render_custom_markers(p_name, key_prefix="doc")

                with tab_diag:
                    render_diagnostics_viewer(p_name, allow_upload=True, actor_role="Doctor")

    elif doc_nav == "Drug Interactions":
        p_name = st.selectbox("Select Patient for Interaction Check:", options=all_registered_patients)
        patient_doc = patients_col.find_one({"patient_name": p_name}) or {}
        p_allergies = patient_doc.get("allergies", [])
        
        st.write(f"**Documented Allergies:** `{', '.join(p_allergies) if p_allergies else 'None Recorded'}`")

        rx_med = st.selectbox("Test Prescription Clearance:", ["Tacrolimus", "Mycophenolate Mofetil", "Ibuprofen (NSAID)", "Erythromycin", "Penicillin"], key=f"rx_{p_name}")

        if rx_med == "Ibuprofen (NSAID)" and "NSAIDs" in p_allergies:
            st.error(f"🚨 CONTRAINDICATION: {p_name} has a documented allergy to NSAIDs! High risk of graft nephrotoxicity.")
            log_audit_event("Doctor", "DOC-NEPH-01", "DRUG_CHECK_CONTRAINDICATION", {"patient": p_name, "drug": rx_med, "allergy": "NSAIDs"})
        elif rx_med == "Penicillin" and "Penicillin" in p_allergies:
            st.error(f"🚨 ALLERGY ALERT: {p_name} has a documented allergy to Penicillin!")
            log_audit_event("Doctor", "DOC-NEPH-01", "DRUG_CHECK_ALLERGY", {"patient": p_name, "drug": rx_med, "allergy": "Penicillin"})
        elif rx_med == "Erythromycin":
            st.warning("⚠️ INTERACTION WARNING: Erythromycin inhibits CYP3A4, markedly increasing Tacrolimus troughs.")
            log_audit_event("Doctor", "DOC-NEPH-01", "DRUG_CHECK_INTERACTION", {"patient": p_name, "drug": rx_med, "warning": "CYP3A4 Inhibition"})
        else:
            st.success(f"✅ Prescribing clearance confirmed for {rx_med}.")
            log_audit_event("Doctor", "DOC-NEPH-01", "DRUG_CHECK_CLEARED", {"patient": p_name, "drug": rx_med})

    elif doc_nav == "Consultation Entry":
        p_name = st.selectbox("Select Patient to Sign Note:", options=all_registered_patients)
        with st.form(key=f"note_form_{p_name}"):
            hist = st.text_area("Subjective History:", value="Patient reports feeling well. No fever.")
            exam = st.text_area("Objective Examination:", value="Graft non-tender. BP well-controlled.")
            disp = st.selectbox("Disposition:", ["Maintain Current Protocol", "Adjust Immunosuppression Dose", "Schedule Outpatient Scan"])

            if st.form_submit_button("✍️ Sign Note & Auto-Publish", type="primary"):
                note_doc = {
                    "patient_name": p_name,
                    "doctor_id": "DOC-NEPH-01",
                    "doctor_name": "Dr. Sarah Jenkins",
                    "history": hist,
                    "examination": exam,
                    "disposition": disp,
                    "timestamp": datetime.now(timezone.utc)
                }
                notes_col.insert_one(note_doc)
                log_audit_event("Doctor", "DOC-NEPH-01", "SIGN_CONSULTATION_NOTE", {
                    "patient": p_name, "disposition": disp
                })
                st.success(f" ✅ Consultation note signed, published to {p_name}'s portal, and logged in Audit Trail!")
                st.rerun()

# =========================================================
# ROLE 4: TRANSPLANT COORDINATOR WORKFLOW
# =========================================================
elif active_role == "Transplant Coordinator":
    render_clinical_disclaimer()
    st.header("📋 Coordinator Dashboard")

    selected_p = st.selectbox("Select Target Patient Profile:", options=all_registered_patients)
    p_profile = patients_col.find_one({"patient_name": selected_p}) or {}

    if coord_nav == "Patient Intake Queue":
        st.markdown(f"##### Active Intake Status for **{selected_p}**")
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Organ", p_profile.get('organ_type', 'N/A'))
        c2.metric("Transplant Date", str(p_profile.get('transplant_date', 'N/A')))
        c3.metric("Current Status", p_profile.get('intake_status', 'Pending Review'))

        st.divider()
        col_st, col_btn = st.columns([3, 1])
        intake_status = col_st.selectbox("Operational Review State:", ["Pending Review", "In Progress", "Review Completed"])
        if col_btn.button("Update Intake Status", type="primary"):
            patients_col.update_one({"patient_name": selected_p}, {"$set": {"intake_status": intake_status}}, upsert=True)
            log_audit_event("Coordinator", "COORD-01", "UPDATE_INTAKE_STATUS", {"patient": selected_p, "status": intake_status})
            st.success(f" ✅ Intake status updated to '{intake_status}' for {selected_p}!")

        st.divider()
        st.subheader("📊 Patient Historical Vitals")
        render_vitals_trends(selected_p)

    elif coord_nav == "Medication Reconciliation":
        st.markdown("##### Reconcile EHR Orders vs. Patient Self-Reporting")
        meds = p_profile.get("current_medications", [])
        
        if meds:
            for i, m in enumerate(meds):
                col_m1, col_m2 = st.columns([3, 1])
                col_m1.write(f"• **{m.get('drug')}**: Prescribed Dose = `{m.get('dose', m.get('EHR_dose', 'N/A'))}` | Status = `{m.get('status', 'Pending')}`")
                if col_m2.button("Mark Reconciled", key=f"reconcile_{selected_p}_{i}"):
                    patients_col.update_one(
                        {"patient_name": selected_p, "current_medications.drug": m.get('drug')},
                        {"$set": {"current_medications.$.status": "Reconciled"}}
                    )
                    log_audit_event("Coordinator", "COORD-01", "RECONCILE_MEDICATION", {"patient": selected_p, "drug": m.get('drug')})
                    st.success(f" ✅ {m.get('drug')} successfully reconciled and audited!")
                    st.rerun()
        else:
            st.caption("No medication records present for reconciliation.")

    elif coord_nav == "Schedule & Messages":
        st.subheader("📅 Schedule Surveillance Appointment")
        col_a, col_b = st.columns(2)
        app_date = col_a.date_input("Schedule Date:")
        app_type = col_b.selectbox("Type:", ["Graft Ultrasound", "Routine Labs", "Biopsy"])
        
        if st.button("Confirm Appointment", type="primary"):
            patients_col.update_one(
                {"patient_name": selected_p},
                {"$push": {"appointments": {"date": str(app_date), "type": app_type}}},
                upsert=True
            )
            log_audit_event("Coordinator", "COORD-01", "SCHEDULE_APPOINTMENT", {"patient": selected_p, "type": app_type, "date": str(app_date)})
            st.success(f" ✅ Appointment ({app_type}) scheduled for {app_date} and logged!")

        st.divider()
        render_communication_hub(selected_p, "Transplant Coordinator")

    elif coord_nav == "Onboard New Patient":
        st.subheader("➕ Clinical Intake Onboarding")
        with st.form("coord_new_patient"):
            col1, col2 = st.columns(2)
            c_name = col1.text_input("Patient Full Name:")
            c_id = col2.text_input("MRN / Patient ID:")
            
            col3, col4 = st.columns(2)
            c_organ = col3.selectbox("Organ Type:", ["Kidney", "Liver", "Heart", "Lung", "Pancreas"])
            c_tx_date = col4.date_input("Transplant Date:", value=date.today())
            
            c_allergies = st.text_input("Documented Allergies (comma separated):", value="NSAIDs, Penicillin")
            
            col5, col6 = st.columns(2)
            c_tac = col5.text_input("Tacrolimus Initial Dose:", value="3mg BID")
            c_pred = col6.text_input("Prednisone Initial Dose:", value="5mg Daily")

            if st.form_submit_button("Create Patient Record in Database", type="primary"):
                if c_name.strip():
                    meds_list = [
                        {"drug": "Tacrolimus", "dose": c_tac, "status": "Matched"},
                        {"drug": "Prednisone", "dose": c_pred, "status": "Matched"}
                    ]
                    allergies_list = [a.strip() for a in c_allergies.split(",")]
                    success, msg = create_new_patient_profile(
                        c_name.strip(), c_id.strip(), c_organ, c_tx_date, allergies_list, meds_list
                    )
                    if success:
                        log_audit_event("Coordinator", "COORD-01", "ONBOARD_PATIENT", {"patient": c_name, "organ": c_organ})
                        st.success(f" ✅ {msg}")
                        st.rerun()
                    else:
                        st.error(msg)
                else:
                    st.warning("Please provide a valid patient name.")

# =========================================================
# ROLE 5: SYSTEM ADMINISTRATOR
# =========================================================
elif active_role == "System Administrator":
    st.header("⚙️ Dynamic System Governance & Rules Engine")

    if admin_nav == "Rules Engine":
        st.markdown("##### Update Active Rule Thresholds in MongoDB")
        active_ruleset = rules_col.find_one({"active": True}) or {}
        params = active_ruleset.get("parameters", {})

        with st.form("update_rules_form"):
            c1, c2 = st.columns(2)
            new_wt = c1.number_input("Max 24h Weight Gain (kg):", value=float(params.get("weight_spike_kg", 1.5)))
            new_fever = c2.number_input("Fever Threshold (°F):", value=float(params.get("fever_temp_f", 100.0)))

            c3, c4 = st.columns(2)
            new_tac_high = c3.number_input("Tacrolimus Upper Limit:", value=float(params.get("tacrolimus_high", 12.0)))
            new_creat_high = c4.number_input("Creatinine Upper Limit:", value=float(params.get("creatinine_high", 1.8)))

            if st.form_submit_button("Publish Rule Set Updates", type="primary"):
                try:
                    rules_col.update_one(
                        {"_id": active_ruleset["_id"]},
                        {"$set": {
                            "parameters.weight_spike_kg": new_wt,
                            "parameters.fever_temp_f": new_fever,
                            "parameters.tacrolimus_high": new_tac_high,
                            "parameters.creatinine_high": new_creat_high,
                            "updated_at": datetime.now(timezone.utc)
                        }}
                    )
                    log_audit_event("Admin", "ADMIN-01", "UPDATE_TRIAGE_RULES", {
                        "ruleset_id": active_ruleset.get("ruleset_id"),
                        "new_parameters": {
                            "weight_spike_kg": new_wt,
                            "fever_temp_f": new_fever,
                            "tacrolimus_high": new_tac_high,
                            "creatinine_high": new_creat_high
                        }
                    })
                    st.toast("✅ Rules engine updated & audited!", icon="⚙️")
                    st.success("✅ Rules engine threshold updated in MongoDB and audit log!")
                except Exception as e:
                    st.error(f"❌ Failed to update rules: {e}")

        st.divider()
        st.markdown("##### 🔍 Rules Engine Modification History")
        rule_audits = list(audit_col.find({"action": "UPDATE_TRIAGE_RULES"}).sort("timestamp", -1))
        if rule_audits:
            df_rule_audits = pd.DataFrame(rule_audits)
            if "timestamp" in df_rule_audits.columns:
                df_rule_audits["timestamp"] = pd.to_datetime(df_rule_audits["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            if "details" in df_rule_audits.columns:
                df_rule_audits["details"] = df_rule_audits["details"].apply(lambda x: str(x) if isinstance(x, dict) else x)
            st.dataframe(df_rule_audits[["timestamp", "actor_role", "actor_id", "details"]], use_container_width=True, hide_index=True)
        else:
            st.caption("No prior modification history recorded for rules.")

    elif admin_nav == "Dynamic Parameters":
        st.subheader("🛠️ Custom Parameter Configurator")
        tab_list, tab_edit, tab_add, tab_history = st.tabs(["📋 Existing Parameters", "✏️ Edit Parameter", "➕ Add New Parameter", "📜 Audit History"])
        
        existing_params = list(db["schema_config"].find({"entity": "patient_input"}))
        param_names = [p["field_name"] for p in existing_params]

        with tab_list:
            if not existing_params:
                st.info("No custom dynamic parameters defined yet.")
            else:
                df_params = pd.DataFrame(existing_params)
                target_param_cols = ["field_name", "field_type", "unit"]
                df_params_safe = df_params.reindex(columns=target_param_cols)
                df_params_safe.columns = ["Parameter Name", "Data Type", "Unit"]
                st.dataframe(df_params_safe, use_container_width=True, hide_index=True)
                
                st.divider()
                st.markdown("##### 🗑️ Remove Parameter")
                col_del_select, col_del_btn = st.columns([3, 1])
                to_delete = col_del_select.selectbox("Select Parameter to Remove:", options=param_names, key="del_param_select")
                
                if col_del_btn.button("Delete Parameter", type="secondary"):
                    db["schema_config"].delete_one({"field_name": to_delete, "entity": "patient_input"})
                    log_audit_event("Admin", "ADMIN-01", "DELETE_CUSTOM_MARKER", {"field_name": to_delete})
                    st.toast(f"🗑️ Parameter '{to_delete}' removed!", icon="⚠️")
                    st.success(f"Successfully deleted '{to_delete}' from patient intake forms.")
                    st.rerun()

        with tab_edit:
            if not existing_params:
                st.info("No parameters available to edit.")
            else:
                selected_to_edit = st.selectbox("Select Parameter to Edit:", options=param_names, key="edit_param_select")
                current_p_doc = next((p for p in existing_params if p["field_name"] == selected_to_edit), {})
                
                with st.form("edit_custom_param_form"):
                    edit_name = st.text_input("Parameter Name:", value=current_p_doc.get("field_name", ""))
                    edit_type = st.selectbox("Data Type:", ["Number", "Text", "Select"], index=["Number", "Text", "Select"].index(current_p_doc.get("field_type", "Number")) if current_p_doc.get("field_type") in ["Number", "Text", "Select"] else 0)
                    edit_unit = st.text_input("Unit:", value=current_p_doc.get("unit", ""))
                    
                    if st.form_submit_button("Save Parameter Updates", type="primary"):
                        if edit_name.strip():
                            if selected_to_edit != edit_name.strip():
                                db["schema_config"].delete_one({"field_name": selected_to_edit, "entity": "patient_input"})
                            
                            db["schema_config"].update_one(
                                {"field_name": edit_name.strip(), "entity": "patient_input"},
                                {"$set": {
                                    "field_name": edit_name.strip(),
                                    "field_type": edit_type,
                                    "unit": edit_unit.strip(),
                                    "entity": "patient_input",
                                    "updated_at": datetime.now(timezone.utc)
                                }},
                                upsert=True
                            )
                            log_audit_event("Admin", "ADMIN-01", "UPDATE_CUSTOM_MARKER", {
                                "old_name": selected_to_edit,
                                "new_name": edit_name.strip(),
                                "field_type": edit_type,
                                "unit": edit_unit.strip()
                            })
                            st.toast(f"✅ Parameter '{edit_name}' updated!", icon="🛠️")
                            st.success(f"Successfully updated parameter configuration for '{edit_name}'!")
                            st.rerun()
                        else:
                            st.warning("Parameter name cannot be blank.")

        with tab_add:
            col1, col2, col3 = st.columns([2, 2, 1])
            new_field_name = col1.text_input("Parameter Name", key="add_p_name")
            new_field_type = col2.selectbox("Data Type", ["Number", "Text", "Select"], key="add_p_type")
            new_field_unit = col3.text_input("Unit", key="add_p_unit")

            if st.button("➕ Add Parameter to Patient Form", type="primary", key="add_p_btn"):
                if new_field_name.strip():
                    try:
                        db["schema_config"].update_one(
                            {"field_name": new_field_name.strip(), "entity": "patient_input"},
                            {"$set": {
                                "field_name": new_field_name.strip(),
                                "field_type": new_field_type,
                                "unit": new_field_unit.strip(),
                                "entity": "patient_input"
                            }},
                            upsert=True
                        )
                        log_audit_event("Admin", "ADMIN-01", "CREATE_CUSTOM_MARKER", {
                            "field_name": new_field_name.strip(),
                            "field_type": new_field_type,
                            "unit": new_field_unit.strip()
                        })
                        st.toast(f"✅ Marker '{new_field_name}' added!", icon="🧪")
                        st.success(f"✅ Added parameter '{new_field_name}' dynamically and committed to Audit Trail!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Database write error: {e}")
                else:
                    st.warning("⚠️ Please provide a valid parameter name before saving.")

        with tab_history:
            st.markdown("##### 📜 Custom Marker Audit History")
            marker_audits = list(audit_col.find({"action": {"$in": ["CREATE_CUSTOM_MARKER", "UPDATE_CUSTOM_MARKER", "DELETE_CUSTOM_MARKER"]}}).sort("timestamp", -1))
            if marker_audits:
                df_m_audits = pd.DataFrame(marker_audits)
                if "timestamp" in df_m_audits.columns:
                    df_m_audits["timestamp"] = pd.to_datetime(df_m_audits["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S UTC")
                if "details" in df_m_audits.columns:
                    df_m_audits["details"] = df_m_audits["details"].apply(lambda x: str(x) if isinstance(x, dict) else x)
                st.dataframe(df_m_audits[["timestamp", "actor_role", "action", "details"]], use_container_width=True, hide_index=True)
            else:
                st.caption("No audit logs found for custom parameter modifications.")

    elif admin_nav == "Patient Directory":
        st.subheader("👥 Registered Patient Directory")
        all_patients = list(patients_col.find({}, {"_id": 0}))
        if all_patients:
            df_patients = pd.DataFrame(all_patients)
            target_cols = ["patient_name", "patient_id", "organ_type", "transplant_date", "allergies"]
            df_safe = df_patients.reindex(columns=target_cols)
            st.dataframe(df_safe, use_container_width=True)
        else:
            st.caption("No patient profiles registered.")

    elif admin_nav == "User Feedback":
        st.subheader("💬 Platform User Feedback Logs")
        user_feedbacks = list(feedback_col.find().sort("timestamp", -1))
        if user_feedbacks:
            df_fb = pd.DataFrame(user_feedbacks)
            if "timestamp" in df_fb.columns:
                df_fb["timestamp"] = pd.to_datetime(df_fb["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            
            target_fb_cols = ["timestamp", "role", "category", "rating", "comment"]
            df_fb_safe = df_fb.reindex(columns=target_fb_cols)
            df_fb_safe.columns = ["Timestamp", "Role", "Category", "Rating (Stars)", "User Comment"]
            st.dataframe(df_fb_safe, use_container_width=True, hide_index=True)
        else:
            st.caption("No user feedback recorded yet.")

    elif admin_nav == "Audit Logs":
        st.subheader("🛡️ Global Immutable Audit Trail")
        logs = list(audit_col.find().sort("timestamp", -1))
        if logs:
            df_logs = pd.DataFrame(logs)
            if "timestamp" in df_logs.columns:
                df_logs["timestamp"] = pd.to_datetime(df_logs["timestamp"]).dt.strftime("%Y-%m-%d %H:%M:%S UTC")
            if "details" in df_logs.columns:
                df_logs["details"] = df_logs["details"].apply(lambda x: str(x) if isinstance(x, dict) else x)

            target_audit_cols = ["timestamp", "actor_role", "actor_id", "action", "details"]
            df_audit_safe = df_logs.reindex(columns=target_audit_cols)
            st.dataframe(df_audit_safe, use_container_width=True)
        else:
            st.caption("No audit events logged yet.")
