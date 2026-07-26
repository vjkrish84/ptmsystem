import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pymongo import MongoClient, errors
from datetime import datetime, date, timezone

# ---------------------------------------------------------
# 1. Page Config & Custom Styling (Mobile & Typography)
# ---------------------------------------------------------
st.set_page_config(
    page_title="Enterprise Post-Transplant Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded"
)

def inject_custom_design():
    """Injects responsive CSS for mobile viewports, single-column stacking, and typography."""
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* Responsive adjustment for mobile screens */
    @media (max-width: 768px) {
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 100% !important;
            min-width: 100% !important;
            margin-bottom: 0.5rem;
        }
        [data-testid="stMetric"] {
            padding: 10px !important;
            background-color: #f8f9fa;
            border-radius: 8px;
            border: 1px solid #e9ecef;
        }
    }

    /* Custom Triage Ribbon Styling */
    .ribbon-red {
        background-color: #ffebe9;
        color: #cf222e;
        padding: 10px 16px;
        border-radius: 6px;
        border-left: 6px solid #cf222e;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .ribbon-amber {
        background-color: #fff8c5;
        color: #9a6700;
        padding: 10px 16px;
        border-radius: 6px;
        border-left: 6px solid #d4a72c;
        font-weight: 600;
        margin-bottom: 12px;
    }
    .ribbon-green {
        background-color: #dafbe1;
        color: #1a7f37;
        padding: 10px 16px;
        border-radius: 6px;
        border-left: 6px solid #1a7f37;
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

# Ensure Active Rule Set Document Exists
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

# Ensure Demo Patient Exists
if patients_col.count_documents({"patient_name": "Sarah Connor"}) == 0:
    patients_col.insert_one({
        "patient_name": "Sarah Connor",
        "patient_id": "PT-1001",
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
    st.warning(
        "⚠️ **CLINICAL DECISION-SUPPORT DISCLAIMER:** "
        "This software is an auxiliary clinical decision-support tool. "
        "It does not replace professional clinical evaluation. "
        "All automated triage scoring and interaction warnings must be verified by a licensed clinician.",
        icon="🩺"
    )

def log_audit_event(actor_role: str, actor_id: str, action: str, details: dict):
    audit_col.insert_one({
        "timestamp": datetime.now(timezone.utc),
        "actor_role": actor_role,
        "actor_id": actor_id,
        "action": action,
        "details": details
    })

def evaluate_clinical_triage(latest_doc, prev_doc=None):
    """Evaluates triage status dynamically using the active Mongo rule set."""
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

# ---------------------------------------------------------
# 4. Shared Messaging Component
# ---------------------------------------------------------
def render_communication_hub(patient_name: str, active_role: str):
    st.markdown("#### 💬 Care Team Messages")
    
    messages = list(notifs_col.find({"patient_name": patient_name}).sort("timestamp", -1))
    
    if not messages:
        st.info("No active thread for this profile.")
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
                log_audit_event(active_role, "LOCAL-USER", "SEND_MESSAGE", {"patient": patient_name})
                st.success("Transmitted.")
                st.rerun()

# ---------------------------------------------------------
# 5. Sidebar Navigation
# ---------------------------------------------------------
st.sidebar.title("🩺 Portal Navigation")

active_role = st.sidebar.radio(
    "Select Operating Role:",
    [
        "Patient Portal",
        "Caregiver Proxy View",
        "Doctor (Nephrologist)",
        "Transplant Coordinator",
        "System Administrator"
    ]
)

st.sidebar.divider()
active_rule_doc = rules_col.find_one({"active": True}) or {}
st.sidebar.caption(f"Active Rule Version: **{active_rule_doc.get('ruleset_id', 'N/A')}**")

# =========================================================
# ROLE 1: PATIENT PORTAL
# =========================================================
if active_role == "Patient Portal":
    st.header("📱 Patient Self-Monitoring Portal")

    existing_patients = sorted(vitals_col.distinct("patient_name")) or ["Sarah Connor"]
    selected_patient = st.selectbox("Active Patient Profile:", options=existing_patients)
    p_profile = patients_col.find_one({"patient_name": selected_patient}) or {}

    # Single-Open Accordions for Mobile Usability
    with st.expander("📝 1. Daily Vitals Check-In & Red-Flags", expanded=True):
        with st.form("patient_vitals_submission"):
            c1, c2, c3 = st.columns(3)
            weight = c1.number_input("Weight (kg)", value=68.5, step=0.1)
            temp = c2.number_input("Temp (°F)", value=98.6, step=0.1)
            hr = c3.number_input("Heart Rate (BPM)", value=72)

            c4, c5 = st.columns(2)
            sbp = c4.number_input("Systolic BP", value=120)
            dbp = c5.number_input("Diastolic BP", value=80)

            symptoms = st.multiselect("Report Symptoms:", [
                "Low urine output", "Graft site pain", "Swelling in feet/hands",
                "Shortness of breath", "Incision drainage", "Nausea/Vomiting"
            ])

            if st.form_submit_button("Submit Daily Vitals"):
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
                    "creatinine": 1.2,
                    "tacrolimus": 7.5
                }
                vitals_col.insert_one(log_doc)
                log_audit_event("Patient", selected_patient, "SUBMIT_VITALS", {})
                st.success("Vitals successfully saved to MongoDB!")
                st.rerun()

    with st.expander("📊 2. My Logged Records & Signed Doctor Notes", expanded=False):
        st.markdown("##### Real-Time Dynamic History")
        p_logs = list(vitals_col.find({"patient_name": selected_patient}).sort("timestamp", -1))
        
        if p_logs:
            latest = p_logs[0]
            st.caption(f"Last record updated: {latest['timestamp'].strftime('%Y-%m-%d %H:%M UTC')}")
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Weight", f"{latest.get('weight_kg')} kg")
            m2.metric("BP", f"{latest.get('systolic_bp')}/{latest.get('diastolic_bp')}")
            m3.metric("Temp", f"{latest.get('temperature_f')} °F")
            m4.metric("Heart Rate", f"{latest.get('heart_rate')} BPM")

        st.divider()
        st.markdown("##### Published Clinical Notes from Doctor")
        p_notes = list(notes_col.find({"patient_name": selected_patient}).sort("timestamp", -1))
        if p_notes:
            for note in p_notes:
                st.info(f"🔒 **Signed Consultation Note** ({note['timestamp'].strftime('%Y-%m-%d %H:%M UTC')})\n\n"
                        f"**Attending:** {note.get('doctor_name')}\n\n"
                        f"**Assessment:** {note.get('examination')}\n\n"
                        f"**Plan/Disposition:** {note.get('disposition')}")
        else:
            st.caption("No published clinical notes available.")

    with st.expander("💬 3. Care Team Communication Hub", expanded=False):
        render_communication_hub(selected_patient, "Patient Portal")

    with st.expander("👥 4. Caregiver Proxy Access & Export", expanded=False):
        st.text_input("Delegated Caregiver Email:", value="john.connor@example.com")
        st.checkbox("Allow caregiver to view vital logs", value=True)
        st.button("Save Permissions")
        
        st.divider()
        if p_logs:
            df_export = pd.DataFrame(p_logs)
            st.download_button("📥 Export Health History (CSV)", df_export.to_csv(index=False), file_name=f"{selected_patient}_vitals.csv")

# =========================================================
# ROLE 2: CAREGIVER PROXY VIEW
# =========================================================
elif active_role == "Caregiver Proxy View":
    st.header("👥 Caregiver Proxy View")
    st.info("🔒 Scoped Viewing Mode: Scoped strictly by patient authorization.")

    patient_name = st.selectbox("Select Patient Profile:", ["Sarah Connor"])
    p_logs = list(vitals_col.find({"patient_name": patient_name}).sort("timestamp", -1))

    with st.expander("📊 Patient Vital Trends", expanded=True):
        if p_logs:
            latest = p_logs[0]
            c1, c2, c3 = st.columns(3)
            c1.metric("Weight", f"{latest.get('weight_kg')} kg")
            c2.metric("BP", f"{latest.get('systolic_bp')}/{latest.get('diastolic_bp')}")
            c3.metric("Temp", f"{latest.get('temperature_f')} °F")
        else:
            st.caption("No records available.")

    with st.expander("💬 Care Team Messaging", expanded=False):
        render_communication_hub(patient_name, "Caregiver Proxy View")

# =========================================================
# ROLE 3: DOCTOR (NEPHROLOGIST) WORKSPACE
# =========================================================
elif active_role == "Doctor (Nephrologist)":
    render_clinical_disclaimer()
    st.header("👨‍⚕️ Nephrologist Consultation & Triage Workspace")

    patient_names = sorted(vitals_col.distinct("patient_name")) or ["Sarah Connor"]
    selected_p = st.selectbox("Select Active Patient Workspace:", options=patient_names)
    
    # Query MongoDB for target patient records
    patient_doc = patients_col.find_one({"patient_name": selected_p}) or {}
    logs = list(vitals_col.find({"patient_name": selected_p}).sort("timestamp", -1))
    latest = logs[0] if logs else {}
    prev = logs[1] if len(logs) > 1 else None

    # Evaluate dynamic rules against active MongoDB profile
    status_code, red_flags, amber_flags, explanations = evaluate_clinical_triage(latest, prev)

    # Status Ribbons
    if status_code == "RED":
        st.markdown(f'<div class="ribbon-red">🔴 CRITICAL TRIAGE ALERT: {", ".join(red_flags) or "Immediate Review Required"}</div>', unsafe_allow_html=True)
    elif status_code == "AMBER":
        st.markdown(f'<div class="ribbon-amber">🟡 WARNING: {", ".join(amber_flags) or "Abnormal Parameter Detected"}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="ribbon-green">🟢 STABLE PATIENT STATUS: Vitals within defined thresholds</div>', unsafe_allow_html=True)

    with st.expander("🚨 1. Dynamic Clinical Queue & Deterministic Overrides", expanded=True):
        st.markdown("##### Dynamic Rule Explanations:")
        for exp in explanations:
            st.caption(f"• {exp}")

        st.divider()
        st.markdown("##### Manual Override:")
        ov_col1, ov_col2 = st.columns([2, 1])
        override_val = ov_col1.selectbox("Override Status:", ["GREEN", "AMBER", "RED"])
        override_reason = ov_col2.text_input("Override Reason:")
        
        if st.button("Commit Override to Mongo"):
            if latest:
                vitals_col.update_one({"_id": latest["_id"]}, {"$set": {"override_status": override_val, "override_reason": override_reason}})
                log_audit_event("Doctor", "DOC-NEPH-01", "OVERRIDE_TRIAGE", {"patient": selected_p, "status": override_val})
                st.success("Override written to database.")
                st.rerun()

    with st.expander("💊 2. Patient-Aware Drug Allergy & Interaction Checker", expanded=False):
        p_allergies = patient_doc.get("allergies", ["NSAIDs"])
        st.write(f"**Documented Allergies for {selected_p}:** `{', '.join(p_allergies)}`")

        rx_med = st.selectbox("Test Prescription Clearance:", ["Tacrolimus", "Mycophenolate Mofetil", "Ibuprofen (NSAID)", "Erythromycin"])

        # Dynamic Check against patient profile
        if rx_med == "Ibuprofen (NSAID)" and "NSAIDs" in p_allergies:
            st.error(f"🚨 CONTRAINDICATION: {selected_p} has a documented allergy to NSAIDs! High risk of graft nephrotoxicity.")
        elif rx_med == "Erythromycin":
            st.warning("⚠️ INTERACTION WARNING: Erythromycin inhibits CYP3A4, markedly increasing Tacrolimus troughs.")
        else:
            st.success(f"✅ Prescribing clearance confirmed for {rx_med}.")

    with st.expander("📝 3. Signed Consultation Notes (Auto-Published to Patient)", expanded=False):
        hist = st.text_area("Subjective History:", value="Patient reports feeling well. No fever.")
        exam = st.text_area("Objective Examination:", value="Graft non-tender. BP well-controlled.")
        disp = st.selectbox("Disposition:", ["Maintain Current Protocol", "Adjust Immunosuppression Dose", "Schedule Outpatient Scan"])

        if st.button("✍️ Sign Note & Publish to Patient Profile"):
            note_doc = {
                "patient_name": selected_p,
                "doctor_id": "DOC-NEPH-01",
                "doctor_name": "Dr. Sarah Jenkins",
                "history": hist,
                "examination": exam,
                "disposition": disp,
                "timestamp": datetime.now(timezone.utc)
            }
            notes_col.insert_one(note_doc)
            log_audit_event("Doctor", "DOC-NEPH-01", "SIGN_NOTE", {"patient": selected_p})
            st.success(f"Note signed and auto-published to {selected_p}'s portal!")

# =========================================================
# ROLE 4: TRANSPLANT COORDINATOR WORKFLOW
# =========================================================
elif active_role == "Transplant Coordinator":
    render_clinical_disclaimer()
    st.header("📋 Interactive Coordinator Hub")

    patient_names = sorted(vitals_col.distinct("patient_name")) or ["Sarah Connor"]
    selected_p = st.selectbox("Select Target Patient:", options=patient_names)
    p_profile = patients_col.find_one({"patient_name": selected_p}) or {}

    with st.expander("📥 1. Interactive Intake Queue & Review Actions", expanded=True):
        st.markdown(f"##### Active Intake Status for **{selected_p}**")
        c1, c2 = st.columns(2)
        intake_status = c1.selectbox("Operational Review State:", ["Pending Review", "In Progress", "Review Completed"])
        if c2.button("Update Intake Status"):
            patients_col.update_one({"patient_name": selected_p}, {"$set": {"intake_status": intake_status}}, upsert=True)
            st.success("Status synced to database.")

    with st.expander("💊 2. Interactive Medication Reconciliation Workspace", expanded=False):
        st.markdown("##### Reconcile EHR Orders vs. Patient Self-Reporting")
        meds = p_profile.get("current_medications", [])
        
        if meds:
            for i, m in enumerate(meds):
                col_m1, col_m2 = st.columns([3, 1])
                col_m1.write(f"• **{m.get('drug')}**: EHR Order = `{m.get('dose', 'N/A')}`")
                if col_m2.button("Mark Reconciled", key=f"reconcile_{i}"):
                    patients_col.update_one(
                        {"patient_name": selected_p, "current_medications.drug": m.get('drug')},
                        {"$set": {"current_medications.$.status": "Reconciled"}}
                    )
                    st.success(f"Reconciled {m.get('drug')}")
                    st.rerun()

    with st.expander("📅 3. Appointment Scheduling & Direct Messages", expanded=False):
        app_date = st.date_input("Schedule Surveillance Appointment:")
        app_type = st.selectbox("Type:", ["Graft Ultrasound", "Routine Labs", "Biopsy"])
        
        if st.button("Confirm Appointment"):
            patients_col.update_one(
                {"patient_name": selected_p},
                {"$push": {"appointments": {"date": str(app_date), "type": app_type}}},
                upsert=True
            )
            st.success("Appointment registered in Mongo.")

        st.divider()
        render_communication_hub(selected_p, "Transplant Coordinator")

# =========================================================
# ROLE 5: SYSTEM ADMINISTRATOR
# =========================================================
elif active_role == "System Administrator":
    st.header("⚙️ Dynamic System Governance & Rules Engine")

    with st.expander("📜 1. Live Rules Engine Configuration (RS-DEMO)", expanded=True):
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
                log_audit_event("Admin", "ADMIN-01", "UPDATE_RULES", {"ruleset": active_ruleset.get("ruleset_id")})
                st.success("Rule engine updated! All clinical triage checks now use these new thresholds instantly.")
                st.rerun()

    with st.expander("🛡️ 2. Live System Audit Logs", expanded=False):
        logs = list(audit_col.find().sort("timestamp", -1))
        if logs:
            st.dataframe(pd.DataFrame(logs)[["timestamp", "actor_role", "actor_id", "action", "details"]])
        else:
            st.caption("No audit events logged.")
