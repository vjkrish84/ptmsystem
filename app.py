import os
import certifi
import base64
import streamlit as st
import pandas as pd
from pymongo import MongoClient
from datetime import datetime, date

# ---------------------------------------------------------
# 1. Responsive Page Config & CSS Fixes
# ---------------------------------------------------------
st.set_page_config(
    page_title="Post-Transplant Portal",
    page_icon="🩺",
    layout="wide", # Allows broad viewing on desktop, flexes on mobile
    initial_sidebar_state="collapsed"
)

# Fixes header collision and prevents top section cut-offs
st.markdown("""
    <style>
    /* Safely offset page body so top app header doesn't cut off elements */
    .stMainBlockContainer, .block-container {
        padding-top: 4.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 950px; /* Constrains line length on wide screens */
        margin: 0 auto;
    }
    
    /* Touch-friendly full-width action buttons */
    .stButton>button {
        width: 100%;
        min-height: 3.2rem;
        font-size: 1.05rem;
        font-weight: 600;
        border-radius: 8px;
    }

    /* Clean Card Containers */
    .portal-card {
        background-color: #f8f9fa;
        border-left: 4px solid #0066cc;
        padding: 1rem;
        border-radius: 6px;
        margin-bottom: 1rem;
    }
    </style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 2. Database Connection
# ---------------------------------------------------------
@st.cache_resource
def init_connection():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        st.error("⚠️ MONGO_URI missing in Streamlit Secrets.")
        st.stop()
    return MongoClient(mongo_uri, tlsCAFile=certifi.where())

client = init_connection()
db = client["transplant_portal"]
vitals_col = db["vitals_logs"]

# ---------------------------------------------------------
# 3. Core Clinical Logic
# ---------------------------------------------------------
def evaluate_clinical_alerts(latest_doc, prev_doc=None):
    red_flags, amber_flags = [], []

    tx_date = latest_doc.get("transplant_date", datetime.now())
    log_date = latest_doc.get("timestamp", datetime.now())
    if isinstance(tx_date, date) and not isinstance(tx_date, datetime):
        tx_date = datetime.combine(tx_date, datetime.min.time())
    if isinstance(log_date, date) and not isinstance(log_date, datetime):
        log_date = datetime.combine(log_date, datetime.min.time())

    days_post_op = max((log_date - tx_date).days, 0)

    # 1. Weight Spike Trigger (≥ 1.5kg in 24h)
    if prev_doc:
        wt_change = latest_doc.get('weight_kg', 0) - prev_doc.get('weight_kg', 0)
        if wt_change >= 1.5:
            red_flags.append(f"Weight Spike (+{wt_change:.1f} kg)")

    # 2. Temp Alert
    temp = latest_doc.get("temperature_f", 98.6)
    if temp >= 100.0:
        red_flags.append(f"Fever Alert ({temp:.1f}°F)")

    # 3. BP Alert
    sbp, dbp = latest_doc.get("systolic_bp", 120), latest_doc.get("diastolic_bp", 80)
    if sbp > 150 or sbp < 100:
        amber_flags.append(f"Abnormal Systolic BP ({sbp} mmHg)")
    if dbp > 100 or dbp < 60:
        amber_flags.append(f"Abnormal Diastolic BP ({dbp} mmHg)")

    # 4. HR Alert
    hr = latest_doc.get("heart_rate", 72)
    if hr > 100 or hr < 55:
        amber_flags.append(f"Abnormal HR ({hr} BPM)")

    # 5. Tacrolimus Alerts
    tac = latest_doc.get("tacrolimus", 0.0)
    if tac > 0:
        if tac > 12.0:
            red_flags.append(f"High Tacrolimus ({tac:.1f})")
        elif tac < 4.0:
            red_flags.append(f"Low Tacrolimus ({tac:.1f})")

    # 6. Creatinine & Symptoms
    creat = latest_doc.get("creatinine", 1.0)
    if creat >= 1.8:
        red_flags.append(f"High Creatinine ({creat:.2f})")

    symptoms = latest_doc.get("symptoms", [])
    if symptoms:
        red_flags.append(f"Symptoms Reported ({len(symptoms)})")

    return red_flags, amber_flags, days_post_op

# ---------------------------------------------------------
# 4. Top Header & Disclaimer Section
# ---------------------------------------------------------
st.title("🩺 Post-Transplant Portal")

# Prominent, non-truncated clinical warning bar
st.warning("⚠️ **Clinical Notice:** Decision-support tool only. Providers must independently verify incoming patient logs prior to taking clinical action.")

query_params = st.query_params
default_role = query_params.get("role", "patient")
if default_role not in ["patient", "doctor"]:
    default_role = "patient"

selected_role = st.segmented_control(
    "Select Interface",
    options=["patient", "doctor"],
    default=default_role,
    format_func=lambda x: "📱 Patient View" if x == "patient" else "👨‍⚕️ Clinical View",
    label_visibility="collapsed"
)

st.divider()

# =========================================================
# VIEW 1: PATIENT PORTAL
# =========================================================
if selected_role == "patient":
    
    # Emergency Warning Section
    with st.expander("🚨 EMERGENCY RED FLAGS (Click to Expand)", expanded=False):
        st.error("""
        **GO TO THE NEAREST EMERGENCY ROOM IMMEDIATELY IF YOU HAVE:**  
        • Difficulty breathing or severe chest pain  
        • Uncontrollable bleeding or severe abdominal pain  
        • Seizures, sudden weakness, or slurred speech  
        • Sudden loss of consciousness or head injury
        """)

    tab_checkin, tab_call, tab_rules = st.tabs([
        "📝 Daily Check-In", 
        "📞 Coordinator", 
        "🛡️ Safety Rules"
    ])

    # --- TAB 1: DAILY CHECK-IN ---
    # --- TAB 1: DAILY CHECK-IN ---
with tab_checkin:
    existing_patients = vitals_col.distinct("patient_name")
    
    # Allow user to choose between selecting existing profile or creating a new one
    profile_options = ["➕ Create New Patient Profile"] + existing_patients if existing_patients else ["➕ Create New Patient Profile"]
    
    selected_option = st.selectbox(
        "Select Profile or Register New:",
        options=profile_options,
        index=0 if not existing_patients else 1 # Default to existing patient if available
    )

    if selected_option == "➕ Create New Patient Profile":
        c_name, c_id = st.columns(2)
        selected_patient_name = c_name.text_input("Full Name:", value="", placeholder="e.g. Sarah Connor")
        p_id = c_id.text_input("Patient ID (Optional):", value="PT-" + str(hash(datetime.now()) % 10000))
        default_tx_date = date.today()
        is_new_patient = True
    else:
        selected_patient_name = selected_option
        match_doc = vitals_col.find_one({"patient_name": selected_patient_name})
        p_id = match_doc.get("patient_id", "PT-1001") if match_doc else "PT-1001"
        
        # Safely extract existing transplant date
        raw_tx_date = match_doc.get("transplant_date") if match_doc else None
        if isinstance(raw_tx_date, datetime):
            default_tx_date = raw_tx_date.date()
        elif isinstance(raw_tx_date, date):
            default_tx_date = raw_tx_date
        else:
            default_tx_date = date(2025, 1, 1)
            
        is_new_patient = False
        st.success(f"Logging check-in for **{selected_patient_name}** ({p_id})")

    with st.form("patient_checkin_form"):
        st.subheader("1. Essential Daily Vitals")
        st.info("💡 Tip: Draw blood labs FIRST before taking your morning Tacrolimus dose!")

        c1, c2 = st.columns(2)
        weight = c1.number_input("Weight (kg)", value=70.0, step=0.1)
        temp = c2.number_input("Temperature (°F)", value=98.6, step=0.1)

        c3, c4 = st.columns(2)
        sbp = c3.number_input("Systolic BP", value=120)
        dbp = c4.number_input("Diastolic BP", value=80)

        hr = st.number_input("Resting Heart Rate (BPM)", value=72)

        symptoms = st.multiselect("Active Symptoms Today:", [
            "Low urine output", "Pain over transplant site", "Swelling hands/feet", 
            "Shortness of breath", "Blood in urine/stool", "Incision redness/leakage", 
            "Burning urination", "Nausea/Vomiting/Diarrhea"
        ])

        st.divider()
        
        # Collapsible section for labs / dates
        with st.expander("🧪 Blood Labs & Transplant Details", expanded=is_new_patient):
            tx_date_input = st.date_input("Transplant Date", value=default_tx_date)
            lab_date_input = st.date_input("Lab Date", value=date.today())
            creatinine = st.number_input("Creatinine (mg/dL)", value=1.1, step=0.1)
            tacrolimus = st.number_input("Tacrolimus Level (ng/mL)", value=8.5, step=0.5)
            bkv_load = st.number_input("BKV PCR Load", value=0, step=100)
            dsa_status = st.selectbox("DSA Antibodies:", ["Negative", "Positive (Low MFI)", "Positive (High MFI)", "Pending"])
            uploaded_lab_file = st.file_uploader("Upload Lab PDF/Photo:", type=["pdf", "png", "jpg", "jpeg"], key="lab_u")
        
        with st.expander("🖼️ Imaging & Diagnostic Scans (Optional)", expanded=False):
            us_date = st.date_input("Ultrasound Date", value=date.today())
            us_result = st.text_input("Ultrasound Findings", value="Normal graft, RI=0.64")
            dxa_score = st.number_input("DXA T-Score", value=-0.8, step=0.1)
            colonoscopy_date = st.text_input("Colonoscopy Status", value="Cleared")
            cancer_screening = st.text_input("Cancer Screenings", value="Dermatology: Clear")
            uploaded_scan_file = st.file_uploader("Upload Scan PDF/Photo:", type=["pdf", "png", "jpg", "jpeg"], key="scan_u")

        submitted = st.form_submit_button("Submit Check-In", use_container_width=True)
        
        if submitted:
            if is_new_patient and not selected_patient_name.strip():
                st.error("⚠️ Please enter a patient name before submitting!")
                st.stop()

            lab_b64, lab_fname = None, None
            if 'uploaded_lab_file' in locals() and uploaded_lab_file is not None:
                lab_b64 = base64.b64encode(uploaded_lab_file.read()).decode('utf-8')
                lab_fname = uploaded_lab_file.name

            scan_b64, scan_fname = None, None
            if 'uploaded_scan_file' in locals() and uploaded_scan_file is not None:
                scan_b64 = base64.b64encode(uploaded_scan_file.read()).decode('utf-8')
                scan_fname = uploaded_scan_file.name

            new_log = {
                "patient_id": p_id,
                "patient_name": selected_patient_name.strip(),
                "transplant_date": datetime.combine(tx_date_input, datetime.min.time()),
                "timestamp": datetime.now(),
                "weight_kg": weight,
                "systolic_bp": sbp,
                "diastolic_bp": dbp,
                "heart_rate": hr,
                "temperature_f": temp,
                "symptoms": symptoms,
                "creatinine": creatinine,
                "tacrolimus": tacrolimus,
                "bkv_load": bkv_load,
                "dsa_status": dsa_status,
                "lab_file_base64": lab_b64,
                "lab_file_name": lab_fname,
                "us_findings": us_result,
                "dxa_score": dxa_score,
                "scan_file_base64": scan_b64,
                "scan_file_name": scan_fname
            }
            vitals_col.insert_one(new_log)
            st.success(f"✅ Check-in saved for {selected_patient_name}!")
            st.rerun() # Refresh list automatically so the new user appears in dropdown

    # --- TAB 2: CALL COORDINATOR ---
    with tab_call:
        st.subheader("📞 When to Call Your Coordinator")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("""
            **Rejection Indicators:**
            • Noticeable decrease in urine output  
            • Pain or severe tenderness over graft  
            • Fever ≥ 100.0°F  
            • Rapid weight gain (≥ 1.5 kg in 24 hrs)
            """)
        with c2:
            st.markdown("""
            **Infection Indicators:**
            • Chills or temperature spikes  
            • Redness, swelling, or drainage at incision  
            • Persistent cough or shortness of breath  
            • Burning during urination or severe diarrhea
            """)

    # --- TAB 3: SAFETY RULES ---
    with tab_rules:
        st.subheader("🛡️ Post-Transplant Guidelines")
        col_a, col_b = st.columns(2)
        with col_a:
            st.success("**Safe Vaccines:** Flu Shot (Injected), Pneumonia, Tdap, Hepatitis B")
            st.error("**FORBIDDEN Vaccines:** Live vaccines (MMR, Nasal FluMist, Chickenpox, Yellow Fever)")
        with col_b:
            st.warning("**Dietary Restrictions:** Avoid Grapefruit/Pomegranate, NSAID pain relievers (Ibuprofen/Advil), and raw/undercooked foods.")

# =========================================================
# VIEW 2: CLINICAL TRIAGE BOARD
# =========================================================
elif selected_role == "doctor":
    st.subheader("👨‍⚕️ Clinical Triage & Monitoring Board")

    patient_names = vitals_col.distinct("patient_name")

    if not patient_names:
        st.info("No active patient records available.")
    else:
        for name in patient_names:
            p_docs = list(vitals_col.find({"patient_name": name}).sort("timestamp", 1))
            if not p_docs:
                continue

            latest = p_docs[-1]
            prev = p_docs[-2] if len(p_docs) > 1 else None
            red_flags, amber_flags, days_post_op = evaluate_clinical_alerts(latest, prev)

            status_tag = "🔴 RED ALERT" if red_flags else ("🟡 WATCH" if amber_flags else "🟢 STABLE")
            
            with st.expander(f"{status_tag} — {name} (Day {days_post_op} Post-Op)"):
                if red_flags:
                    st.error("🚨 Red Flags: " + ", ".join(red_flags))
                if amber_flags:
                    st.warning("⚠️ Watch Flags: " + ", ".join(amber_flags))

                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Weight", f"{latest['weight_kg']} kg")
                m2.metric("BP", f"{latest['systolic_bp']}/{latest['diastolic_bp']}")
                m3.metric("Creatinine", f"{latest.get('creatinine', 'N/A')}")
                m4.metric("Tacrolimus", f"{latest.get('tacrolimus', 'N/A')}")

                # Download triggers for submitted files
                d1, d2 = st.columns(2)
                if latest.get("lab_file_base64"):
                    d1.download_button("📥 Download Lab Report", base64.b64decode(latest["lab_file_base64"]), file_name=latest.get("lab_file_name", "lab.pdf"))
                if latest.get("scan_file_base64"):
                    d2.download_button("🖼️ Download Diagnostic Scan", base64.b64decode(latest["scan_file_base64"]), file_name=latest.get("scan_file_name", "scan.pdf"))
