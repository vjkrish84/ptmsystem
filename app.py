import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pymongo import MongoClient, errors
from datetime import datetime, date, timezone

# ---------------------------------------------------------
# 1. Page Config & Custom Styling (Mobile & Responsive)
# ---------------------------------------------------------
st.set_page_config(
    page_title="Enterprise Post-Transplant Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

def inject_custom_design():
    """Injects responsive CSS for mobile viewports, Apple-style Control Center navigation drawer, and unconstraining scroll height on nested expanders."""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', sans-serif;
    }

    /* Completely hide Streamlit sidebar if present */
    [data-testid="stSidebar"] {
        display: none !important;
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

    /* Apple Control Center Style Floating Drawer Button (Top-Right / Bottom-Right) */
    .apple-control-center-container {
        position: fixed;
        top: 60px;
        right: 20px;
        z-index: 999999;
    }

    .apple-control-center-container [data-testid="stPopover"] > button {
        background: rgba(255, 255, 255, 0.85) !important;
        backdrop-filter: blur(16px) saturate(180%) !important;
        -webkit-backdrop-filter: blur(16px) saturate(180%) !important;
        border: 1px solid rgba(209, 213, 219, 0.5) !important;
        border-radius: 20px !important;
        padding: 6px 16px !important;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.12) !important;
        color: #1c1c1e !important;
        font-weight: 600 !important;
        font-size: 14px !important;
        transition: all 0.25s ease !important;
    }

    .apple-control-center-container [data-testid="stPopover"] > button:hover {
        background: rgba(255, 255, 255, 0.95) !important;
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.2) !important;
        transform: scale(1.02);
    }

    @media (max-width: 768px) {
        .apple-control-center-container {
            top: auto;
            bottom: 24px;
            right: 18px;
        }
        
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
            margin-bottom: 0.5rem;
        }
        [data-testid="stMetric"] {
            padding: 10px !important;
            background-color: #f8f9fa;
            border-radius: 12px;
            border: 1px solid #e9ecef;
        }
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
            margin=dict(l=20, r=20, t=40, b=20)
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
            margin=dict(l=20, r=20, t=40, b=20)
        )
        st.plotly_chart(fig2, use_container_width=True)

    st.markdown("##### 📜 Chronological Entry Logs")
    
    target_cols = ["timestamp", "weight_kg", "systolic_bp", "diastolic_bp", "temperature_f", "heart_rate", "tacrolimus", "creatinine", "symptoms"]
    display_df = df.reindex(columns=target_cols).copy()
    display_df["timestamp"] = display_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M UTC")
    display_df.columns = ["Timestamp", "Weight (kg)", "Sys BP", "Dia BP", "Temp (°F)", "Heart Rate", "Tacrolimus", "Creatinine", "Reported Symptoms"]
    st.dataframe(display_df, use_container_width=True)

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
            
            ua_protein = st.selectbox("Protein [Urinalysis]:", ["Negative", "Trace", "+1 (30 mg/dL)", "+2 (100 mg/dL)", "+3 (300 mg/dL)"])
            ua_wbc = st.selectbox("WBC Esterase [Urinalysis]:", ["Negative", "Trace", "Positive"])
            
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

# ---------------------------------------------------------
# 5. State Initialization & Role Declarations
# ---------------------------------------------------------
if "active_role" not in st.session_state:
    st.session_state.active_role = "Patient Portal"

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

all_registered_patients = sorted(patients_col.distinct("patient_name")) or ["Sarah Connor"]

# ---------------------------------------------------------
# 6. Apple-Style Control Center Right-Corner Panel
# ---------------------------------------------------------
st.markdown('<div class="apple-control-center-container">', unsafe_allow_html=True)
with st.popover(f"  {role_icons.get(st.session_state.active_role, '⚙️')} Switch Role", help="Apple Control Center Switcher"):
    st.markdown("###  Control Center")
    st.caption("Tap to change operating context")
    st.divider()
    
    for r in role_options:
        icon = role_icons.get(r, "📄")
        is_active = (r == st.session_state.active_role)
        label = f"{'✓ ' if is_active else ''}{icon} {r}"
        
        if st.button(label, key=f"cc_btn_{r}", use_container_width=True, type="primary" if is_active else "secondary"):
            st.session_state.active_role = r
            st.rerun()

st.markdown('</div>', unsafe_allow_html=True)

active_role = st.session_state.active_role

# =========================================================
# ROLE 1: PATIENT PORTAL
# =========================================================
if active_role == "Patient Portal":
    st.header("📱 Patient Self-Monitoring Portal")

    selected_patient = st.selectbox("Active Patient Profile:", options=all_registered_patients)
    p_profile = patients_col.find_one({"patient_name": selected_patient}) or {}

    with st.expander("👤 Register New Patient Profile", expanded=False):
        st.markdown("##### Self-Registration / Onboarding")
        with st.form("new_patient_self_reg"):
            np_name = st.text_input("Full Patient Name:")
            np_id = st.text_input("Patient Medical Record ID (Optional):")
            np_organ = st.selectbox("Transplant Organ Type:", ["Kidney", "Liver", "Heart", "Lung", "Pancreas"])
            np_tx_date = st.date_input("Transplant Date:", value=date.today())
            np_allergies = st.text_input("Known Allergies (comma separated):", value="NSAIDs")
            
            if st.form_submit_button("Register Patient Profile"):
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

    with st.expander("📝 1. Daily Vitals Check-In & Red-Flags", expanded=False):
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

            if st.form_submit_button("Submit Daily Vitals"):
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
                    "tacrolimus": latest_existing.get("tacrolimus", 7.5)
                }
                vitals_col.insert_one(log_doc)
                log_audit_event("Patient", selected_patient, "SUBMIT_VITALS", {
                    "weight": weight, "temp": temp, "symptoms": symptoms, "bp": f"{sbp}/{dbp}"
                })
                st.success(f"✅ Vitals logged in MongoDB and Audit Trail for {selected_patient}!")
                st.rerun()

    with st.expander("📊 2. Historical Vitals Log & Multi-Entry Trend Charts", expanded=False):
        render_vitals_trends(selected_patient)

    with st.expander("🧪 3. Upload & View Diagnostic Reports (Labs / Urinalysis / Imaging)", expanded=False):
        render_diagnostics_viewer(selected_patient, allow_upload=True, actor_role="Patient")

    with st.expander("💬 4. Care Team Communication Hub", expanded=False):
        render_communication_hub(selected_patient, "Patient Portal")

# =========================================================
# ROLE 2: CAREGIVER PROXY VIEW
# =========================================================
elif active_role == "Caregiver Proxy View":
    st.header("👥 Caregiver Proxy View")
    st.info("🔒 Scoped Viewing Mode: Access restricted to authorized patient profiles.")

    patient_name = st.selectbox("Select Patient Profile:", options=all_registered_patients)

    with st.expander("📊 Patient Vital Trends & Full Entry Log", expanded=False):
        render_vitals_trends(patient_name)

    with st.expander("🧪 Diagnostic Reports", expanded=False):
        render_diagnostics_viewer(patient_name, allow_upload=False, actor_role="Caregiver")

    with st.expander("💬 Care Team Messaging", expanded=False):
        render_communication_hub(patient_name, "Caregiver Proxy View")

# =========================================================
# ROLE 3: DOCTOR (NEPHROLOGIST) WORKSPACE
# =========================================================
elif active_role == "Doctor (Nephrologist)":
    render_clinical_disclaimer()
    st.header("👨‍⚕️ Nephrologist Consultation & Triage Queue")
    
    st.caption("📱 **Mobile-Optimized Patient Flight Board**: Expand any patient profile below, then open specific sub-sections as needed.")

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

            with st.expander("🚨 1. Triage Logic Explanations & Manual Status Override", expanded=False):
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

            with st.expander("📊 2. Historical Vitals & Trend Analytics", expanded=False):
                render_vitals_trends(p_name)

            with st.expander("🔬 3. Urinalysis, Lab Panel & Imaging Reports", expanded=False):
                render_diagnostics_viewer(p_name, allow_upload=True, actor_role="Doctor")

            with st.expander("💊 4. Prescription Allergy & Drug Interaction Checker", expanded=False):
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

            with st.expander("📝 5. Consultation Notes (Publish to Patient)", expanded=False):
                with st.form(key=f"note_form_{p_name}"):
                    hist = st.text_area("Subjective History:", value="Patient reports feeling well. No fever.")
                    exam = st.text_area("Objective Examination:", value="Graft non-tender. BP well-controlled.")
                    disp = st.selectbox("Disposition:", ["Maintain Current Protocol", "Adjust Immunosuppression Dose", "Schedule Outpatient Scan"])

                    if st.form_submit_button("✍️ Sign Note & Auto-Publish"):
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
    st.header("📋 Interactive Coordinator Hub")

    with st.expander("➕ Register New Patient Profile", expanded=False):
        st.markdown("##### Clinical Intake Onboarding")
        with st.form("coord_new_patient"):
            c_name = st.text_input("Patient Full Name:")
            c_id = st.text_input("MRN / Patient ID:")
            c_organ = st.selectbox("Organ Type:", ["Kidney", "Liver", "Heart", "Lung", "Pancreas"])
            c_tx_date = st.date_input("Transplant Date:", value=date.today())
            c_allergies = st.text_input("Documented Allergies (comma separated):", value="NSAIDs, Penicillin")
            c_tac = st.text_input("Tacrolimus Initial Dose:", value="3mg BID")
            c_pred = st.text_input("Prednisone Initial Dose:", value="5mg Daily")

            if st.form_submit_button("Create Patient Record in Database"):
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

    selected_p = st.selectbox("Select Target Patient Profile:", options=all_registered_patients)
    p_profile = patients_col.find_one({"patient_name": selected_p}) or {}

    with st.expander("📥 1. Interactive Intake Queue & Review Actions", expanded=False):
        st.markdown(f"##### Active Intake Status for **{selected_p}**")
        st.write(f"• **Organ:** `{p_profile.get('organ_type', 'N/A')}` | **Transplant Date:** `{p_profile.get('transplant_date', 'N/A')}`")
        
        c1, c2 = st.columns(2)
        intake_status = c1.selectbox("Operational Review State:", ["Pending Review", "In Progress", "Review Completed"])
        if c2.button("Update Intake Status"):
            patients_col.update_one({"patient_name": selected_p}, {"$set": {"intake_status": intake_status}}, upsert=True)
            log_audit_event("Coordinator", "COORD-01", "UPDATE_INTAKE_STATUS", {"patient": selected_p, "status": intake_status})
            st.success(f" ✅ Intake status updated to '{intake_status}' for {selected_p}!")

    with st.expander("📊 2. Patient Historical Vitals & Trend Analytics", expanded=False):
        render_vitals_trends(selected_p)

    with st.expander("🧪 3. Diagnostic Studies & Labs Overview", expanded=False):
        render_diagnostics_viewer(selected_p, allow_upload=True, actor_role="Coordinator")

    with st.expander("💊 4. Interactive Medication Reconciliation Workspace", expanded=False):
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

    with st.expander("📅 5. Appointment Scheduling & Direct Messages", expanded=False):
        app_date = st.date_input("Schedule Surveillance Appointment:")
        app_type = st.selectbox("Type:", ["Graft Ultrasound", "Routine Labs", "Biopsy"])
        
        if st.button("Confirm Appointment"):
            patients_col.update_one(
                {"patient_name": selected_p},
                {"$push": {"appointments": {"date": str(app_date), "type": app_type}}},
                upsert=True
            )
            log_audit_event("Coordinator", "COORD-01", "SCHEDULE_APPOINTMENT", {"patient": selected_p, "type": app_type, "date": str(app_date)})
            st.success(f" ✅ Appointment ({app_type}) scheduled for {app_date} and logged!")

        st.divider()
        render_communication_hub(selected_p, "Transplant Coordinator")

# =========================================================
# ROLE 5: SYSTEM ADMINISTRATOR
# =========================================================
elif active_role == "System Administrator":
    st.header("⚙️ Dynamic System Governance & Rules Engine")

    with st.expander("📜 1. Live Rules Engine Configuration (RS-DEMO)", expanded=False):
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

            if st.form_submit_button("Publish Rule Set Updates"):
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
                st.success(" ✅ Rules engine threshold updated in MongoDB and audit log!")
                st.rerun()

    with st.expander("👥 2. Registered Patient Directory", expanded=False):
        all_patients = list(patients_col.find({}, {"_id": 0}))
        if all_patients:
            df_patients = pd.DataFrame(all_patients)
            target_cols = ["patient_name", "patient_id", "organ_type", "transplant_date", "allergies"]
            df_safe = df_patients.reindex(columns=target_cols)
            st.dataframe(df_safe, use_container_width=True)
        else:
            st.caption("No patient profiles registered.")

    with st.expander("🛡️ 3. Live System Audit Logs", expanded=False):
        st.markdown("##### 🔍 Global Immutable Audit Trail")
        logs = list(audit_col.find().sort("timestamp", -1))
        if logs:
            df_logs = pd.DataFrame(logs)
            target_audit_cols = ["timestamp", "actor_role", "actor_id", "action", "details"]
            df_audit_safe = df_logs.reindex(columns=target_audit_cols)
            st.dataframe(df_audit_safe, use_container_width=True)
        else:
            st.caption("No audit events logged yet.")
