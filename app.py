import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime, date

# ---------------------------------------------------------
# 1. Mobile-Optimized Page Config & Compact CSS
# ---------------------------------------------------------
st.set_page_config(
    page_title="Post-Transplant Portal",
    page_icon="🩺",
    layout="centered", # Centered layout works drastically better on mobile devices
    initial_sidebar_state="collapsed"
)

# Streamlined mobile CSS overrides
st.markdown("""
    <style>
    /* Touch-friendly, high-contrast buttons */
    .stButton>button {
        width: 100%;
        min-height: 3.2rem;
        font-size: 1.05rem;
        font-weight: 600;
        border-radius: 10px;
        margin-top: 4px;
        margin-bottom: 4px;
    }
    
    /* Reduce excessive vertical whitespace on mobile */
    .block-container {
        padding-top: 1.5rem;
        padding-bottom: 2rem;
        padding-left: 0.8rem;
        padding-right: 0.8rem;
    }

    /* Clean mobile card containers */
    .mobile-card {
        background-color: #f8f9fa;
        border: 1px solid #e9ecef;
        border-radius: 10px;
        padding: 12px;
        margin-bottom: 12px;
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
        st.error("⚠️ MONGO_URI missing in Secrets.")
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
# 4. Mobile Top Bar & Navigation
# ---------------------------------------------------------
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

# Disclaimer inside a clean, closed expander so it doesn't take up full screen height
with st.expander("⚠️ Clinical Notice & Disclaimer", expanded=False):
    st.caption("This portal is an automated clinical decision-support tool. It does not constitute final medical advice or treatment orders. Providers must independently verify all incoming data.")

# =========================================================
# VIEW 1: MOBILE PATIENT PORTAL
# =========================================================
if selected_role == "patient":
    
    # Emergency Callout - Compact Popover or Expander
    with st.expander("🚨 EMERGENCY WARNINGS", expanded=False):
        st.error("""
        **GO TO THE NEAREST HOSPITAL IMMEDIATELY IF YOU HAVE:**  
        Difficulty breathing, heavy bleeding, chest pain, seizures, one-sided weakness, slurred speech, or hit your head.
        """)

    tab_checkin, tab_call, tab_rules = st.tabs([
        "📝 Check-In", 
        "📞 Coordinator", 
        "🛡️ Safety Rules"
    ])

    # --- TAB 1: STREAMLINED CHECK-IN ---
    with tab_checkin:
        existing_patients = vitals_col.distinct("patient_name")
        
        # Profile selector
        if existing_patients:
            selected_patient_name = st.selectbox("Select Patient Profile:", existing_patients)
            match_doc = vitals_col.find_one({"patient_name": selected_patient_name})
            p_id = match_doc.get("patient_id", "PT-1001") if match_doc else "PT-1001"
            default_tx_date = match_doc.get("transplant_date", datetime(2025, 1, 1)) if match_doc else datetime(2025, 1, 1)
        else:
            selected_patient_name = st.text_input("Full Name:", value="Sarah Connor")
            p_id = "PT-9042"
            default_tx_date = datetime(2025, 1, 1)

        with st.form("mobile_patient_checkin"):
            st.markdown("### 1. Daily Vitals")
            st.caption("💡 Draw blood FIRST before taking morning Tacrolimus!")

            # 2x2 grid for mobile
            col1, col2 = st.columns(2)
            weight = col1.number_input("Weight (kg)", value=73.8, step=0.1)
            temp = col2.number_input("Temp (°F)", value=98.6, step=0.1)

            col3, col4 = st.columns(2)
            sbp = col3.number_input("Systolic BP", value=120)
            dbp = col4.number_input("Diastolic BP", value=80)

            hr = st.number_input("Resting HR (BPM)", value=72)

            symptoms = st.multiselect("Symptoms Today:", [
                "Low urine output", "Pain over transplant site", "Swelling hands/feet", 
                "Shortness of breath", "Blood in urine/stool", "Incision redness/leakage", 
                "Burning urination", "Nausea/Vomiting/Diarrhea"
            ])

            st.divider()

            # LABS AND UPLOADS ARE CLOSED BY DEFAULT TO PREVENT CLUTTER
            with st.expander("🧪 Add Blood Labs & Lab Document (Optional)", expanded=False):
                tx_date_input = st.date_input("Transplant Date", value=default_tx_date)
                lab_date_input = st.date_input("Lab Date", value=date.today())
                creatinine = st.number_input("Creatinine (mg/dL)", value=1.1, step=0.1)
                tacrolimus = st.number_input("Tacrolimus Level (ng/mL)", value=8.5, step=0.5)
                bkv_load = st.number_input("BKV PCR Load", value=0, step=100)
                dsa_status = st.selectbox("DSA Antibodies:", ["Negative", "Positive (Low MFI)", "Positive (High MFI)", "Pending"])
                uploaded_lab_file = st.file_uploader("Upload Lab PDF/Photo:", type=["pdf", "png", "jpg", "jpeg"], key="lab_u")
            
            with st.expander("🖼️ Add Imaging, Ultrasound & Scans (Optional)", expanded=False):
                us_date = st.date_input("Ultrasound Date", value=date.today())
                us_result = st.text_input("Ultrasound Findings", value="Normal graft, RI=0.64")
                dxa_score = st.number_input("DXA T-Score", value=-0.8, step=0.1)
                colonoscopy_date = st.text_input("Colonoscopy Status", value="Cleared")
                cancer_screening = st.text_input("Cancer Screenings", value="Dermatology: Clear")
                uploaded_scan_file = st.file_uploader("Upload Scan PDF/Photo:", type=["pdf", "png", "jpg", "jpeg"], key="scan_u")

            submitted = st.form_submit_button("Submit Daily Check-In", use_container_width=True)
            
            if submitted:
                # File Encodings
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
                    "patient_name": selected_patient_name,
                    "transplant_date": datetime.combine(tx_date_input if 'tx_date_input' in locals() else default_tx_date, datetime.min.time()),
                    "timestamp": datetime.now(),
                    "weight_kg": weight,
                    "systolic_bp": sbp,
                    "diastolic_bp": dbp,
                    "heart_rate": hr,
                    "temperature_f": temp,
                    "symptoms": symptoms,
                    "creatinine": creatinine if 'creatinine' in locals() else 1.1,
                    "tacrolimus": tacrolimus if 'tacrolimus' in locals() else 8.5,
                    "bkv_load": bkv_load if 'bkv_load' in locals() else 0,
                    "dsa_status": dsa_status if 'dsa_status' in locals() else "Negative",
                    "lab_file_base64": lab_b64,
                    "lab_file_name": lab_fname,
                    "us_findings": us_result if 'us_result' in locals() else "",
                    "dxa_score": dxa_score if 'dxa_score' in locals() else -0.8,
                    "scan_file_base64": scan_b64,
                    "scan_file_name": scan_fname
                }
                vitals_col.insert_one(new_log)
                st.success("✅ Check-in saved successfully!")

    # --- TAB 2: CALL COORDINATOR ---
    with tab_call:
        st.subheader("📞 When to Call Immediately")
        with st.expander("🚨 Rejection Symptoms", expanded=True):
            st.write("• Less urine output\n• Fatigue or pain over graft\n• Fever ≥100°F\n• Weight gain ≥1.5kg in 1 day\n• Blood in urine")
        with st.expander("🦠 Infection Symptoms", expanded=True):
            st.write("• Fever ≥100°F or chills\n• Incision redness/pus\n• Burning urine\n• Shortness of breath / Cough\n• Vomiting / Diarrhea")

    # --- TAB 3: SAFETY RULES ---
    with tab_rules:
        st.subheader("🛡️ Quick Safety Guide")
        with st.expander("💉 Safe vs Unsafe Vaccines"):
            st.success("**Safe:** Flu Shot (Injection), Pneumonia, Tdap, Hep B")
            st.error("**FORBIDDEN (Live):** MMR, FluMist (Nasal), Chickenpox, Shingles")
        with st.expander("🥗 Nutrition Rules"):
            st.error("**Avoid:** Grapefruit, NSAIDs (Ibuprofen/Advil), Raw eggs/sushi, Buffets")

# =========================================================
# VIEW 2: CLINICAL TRIAGE DASHBOARD
# =========================================================
elif selected_role == "doctor":
    st.subheader("👨‍⚕️ Triage Board")

    patient_names = vitals_col.distinct("patient_name")

    if not patient_names:
        st.info("No patient entries logged yet.")
    else:
        for name in patient_names:
            p_docs = list(vitals_col.find({"patient_name": name}).sort("timestamp", 1))
            if not p_docs:
                continue

            latest = p_docs[-1]
            prev = p_docs[-2] if len(p_docs) > 1 else None
            red_flags, amber_flags, days_post_op = evaluate_clinical_alerts(latest, prev)

            # Mobile compact status card
            status_tag = "🔴 RED ALERT" if red_flags else ("🟡 WATCH" if amber_flags else "🟢 STABLE")
            
            with st.expander(f"{status_tag} — {name} (Day {days_post_op})"):
                if red_flags:
                    st.error("🚨 " + ", ".join(red_flags))
                if amber_flags:
                    st.warning("⚠️ " + ", ".join(amber_flags))

                c1, c2 = st.columns(2)
                c1.metric("Weight", f"{latest['weight_kg']} kg")
                c2.metric("BP", f"{latest['systolic_bp']}/{latest['diastolic_bp']}")

                c3, c4 = st.columns(2)
                c3.metric("Creatinine", f"{latest.get('creatinine', 'N/A')}")
                c4.metric("Tacrolimus", f"{latest.get('tacrolimus', 'N/A')}")

                # Document downloads inside the patient expansion
                if latest.get("lab_file_base64"):
                    st.download_button("📥 Download Lab PDF", base64.b64decode(latest["lab_file_base64"]), file_name=latest.get("lab_file_name", "lab.pdf"))
                if latest.get("scan_file_base64"):
                    st.download_button("🖼️ Download Radiology Scan", base64.b64decode(latest["scan_file_base64"]), file_name=latest.get("scan_file_name", "scan.pdf"))
