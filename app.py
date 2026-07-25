import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pymongo import MongoClient
from datetime import datetime, date

# ---------------------------------------------------------
# 1. Responsive Page Config & CSS
# ---------------------------------------------------------
st.set_page_config(
    page_title="Post-Transplant Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Header offset and layout constraints
st.markdown("""
    <style>
    .stMainBlockContainer, .block-container {
        padding-top: 4.5rem !important;
        padding-bottom: 2rem !important;
        max-width: 1100px;
        margin: 0 auto;
    }
    .stButton>button {
        width: 100%;
        min-height: 3.2rem;
        font-size: 1.05rem;
        font-weight: 600;
        border-radius: 8px;
    }
    .notif-card {
        background-color: #ffffff;
        border: 1px solid #e0e0e0;
        border-left: 5px solid #0066cc;
        border-radius: 8px;
        padding: 15px;
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
        st.error("⚠️ MONGO_URI missing in Streamlit Secrets.")
        st.stop()
    return MongoClient(mongo_uri, tlsCAFile=certifi.where())

client = init_connection()
db = client["transplant_portal"]
vitals_col = db["vitals_logs"]
notifs_col = db["patient_notifications"]

# ---------------------------------------------------------
# 3. Core Clinical Alert Evaluation
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
# 4. Top Header & Navigation
# ---------------------------------------------------------
st.title("🩺 Post-Transplant Portal")
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

if "submission_success" in st.session_state:
    st.success(st.session_state["submission_success"])
    del st.session_state["submission_state"] if "submission_state" in st.session_state else None
    del st.session_state["submission_success"]

# =========================================================
# VIEW 1: PATIENT PORTAL
# =========================================================
if selected_role == "patient":
    
    with st.expander("🚨 EMERGENCY RED FLAGS (Click to Expand)", expanded=False):
        st.error("""
        **GO TO THE NEAREST EMERGENCY ROOM IMMEDIATELY IF YOU HAVE:**  
        • Difficulty breathing or severe chest pain  
        • Uncontrollable bleeding or severe abdominal pain  
        • Seizures, sudden weakness, or slurred speech  
        • Sudden loss of consciousness or head injury
        """)

    tab_checkin, tab_notifs, tab_call, tab_rules = st.tabs([
        "📝 Daily Check-In", 
        "🔔 Doctor Messages",
        "📞 Coordinator", 
        "🛡️ Safety Rules"
    ])

    # --- TAB 1: DAILY CHECK-IN ---
    with tab_checkin:
        existing_patients = vitals_col.distinct("patient_name")
        profile_options = ["➕ Create New Patient Profile"] + existing_patients if existing_patients else ["➕ Create New Patient Profile"]
        
        selected_option = st.selectbox(
            "Select Profile or Register New:",
            options=profile_options,
            index=0 if not existing_patients else 1
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
            
            raw_tx_date = match_doc.get("transplant_date") if match_doc else None
            if isinstance(raw_tx_date, datetime):
                default_tx_date = raw_tx_date.date()
            elif isinstance(raw_tx_date, date):
                default_tx_date = raw_tx_date
            else:
                default_tx_date = date(2025, 1, 1)
                
            is_new_patient = False
            st.info(f"Logging check-in for **{selected_patient_name}** ({p_id})")

        with st.form("patient_checkin_form"):
            st.subheader("1. Essential Daily Vitals")
            st.caption("💡 Tip: Draw blood labs FIRST before taking your morning Tacrolimus dose!")

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
            
            with st.expander("🧪 Blood Labs & Transplant Details", expanded=is_new_patient):
                tx_date_input = st.date_input("Transplant Date", value=default_tx_date)
                lab_date_input = st.date_input("Lab Date", value=date.today())
                creatinine = st.number_input("Creatinine (mg/dL)", value=1.1, step=0.1)
                tacrolimus = st.number_input("Tacrolimus Level (ng/mL)", value=8.5, step=0.5)
                bkv_load = st.number_input("BKV PCR Load (copies/mL)", value=0, step=100)
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
                    "colonoscopy": colonoscopy_date,
                    "cancer_screening": cancer_screening,
                    "scan_file_base64": scan_b64,
                    "scan_file_name": scan_fname
                }
                vitals_col.insert_one(new_log)
                st.session_state["submission_success"] = f"✅ Check-in recorded successfully for **{selected_patient_name.strip()}**!"
                st.rerun()

    # --- TAB 2: DOCTOR MESSAGES / NOTIFICATIONS ---
    with tab_notifs:
        st.subheader("📩 Messages from Your Care Team")
        
        if selected_option == "➕ Create New Patient Profile":
            st.info("Select or register a profile above to view doctor notifications.")
        else:
            patient_notifs = list(notifs_col.find({"patient_name": selected_patient_name}).sort("timestamp", -1))
            
            if not patient_notifs:
                st.write("✨ No new messages or instructions from your care team.")
            else:
                for notif in patient_notifs:
                    severity = notif.get("severity", "Routine Advisory")
                    badge = "🔴" if severity == "Urgent Action Required" else ("🟡" if severity == "Follow-up Recommended" else "🟢")
                    
                    with st.expander(f"{badge} {severity} - {notif.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')}", expanded=True):
                        st.write(f"**From:** {notif.get('doctor_name', 'Transplant Team')}")
                        st.markdown(f"> **Instruction:** {notif.get('message', '')}")
                        
                        if notif.get("acknowledged"):
                            st.caption("✅ You acknowledged this message.")
                        else:
                            if st.button("Confirm & Acknowledge", key=f"ack_{notif['_id']}"):
                                notifs_col.update_one({"_id": notif["_id"]}, {"$set": {"acknowledged": True, "ack_timestamp": datetime.now()}})
                                st.success("Acknowledged! Your care team has been notified.")
                                st.rerun()

    # --- TAB 3: CALL COORDINATOR ---
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

    # --- TAB 4: SAFETY RULES ---
    with tab_rules:
        st.subheader("🛡️ Post-Transplant Guidelines")
        col_a, col_b = st.columns(2)
        with col_a:
            st.success("**Safe Vaccines:** Flu Shot (Injected), Pneumonia, Tdap, Hepatitis B")
            st.error("**FORBIDDEN Vaccines:** Live vaccines (MMR, Nasal FluMist, Chickenpox, Yellow Fever)")
        with col_b:
            st.warning("**Dietary Restrictions:** Avoid Grapefruit/Pomegranate, NSAID pain relievers (Ibuprofen/Advil), and raw/undercooked foods.")

# =========================================================
# VIEW 2: FULL CLINICAL TRIAGE BOARD & TREND ANALYSIS
# =========================================================
elif selected_role == "doctor":
    st.subheader("👨‍⚕️ Clinical Triage & Patient Dashboard")

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
            
            with st.expander(f"{status_tag} — {name} | ID: {latest.get('patient_id', 'N/A')} (Day {days_post_op} Post-Op)"):
                
                # Active Flags
                if red_flags:
                    st.error("🚨 **CRITICAL ALERTS:** " + " • ".join(red_flags))
                if amber_flags:
                    st.warning("⚠️ **WATCH ALERTS:** " + " • ".join(amber_flags))

                # --- 1. LATEST SNAPSHOT ---
                st.markdown("##### 🩺 Primary Vitals")
                v1, v2, v3, v4, v5 = st.columns(5)
                v1.metric("Weight", f"{latest.get('weight_kg', 'N/A')} kg")
                v2.metric("BP", f"{latest.get('systolic_bp', 'N/A')}/{latest.get('diastolic_bp', 'N/A')}")
                v3.metric("Heart Rate", f"{latest.get('heart_rate', 'N/A')} BPM")
                v4.metric("Temperature", f"{latest.get('temperature_f', 'N/A')} °F")
                v5.metric("Last Logged", latest.get("timestamp", datetime.now()).strftime("%b %d, %H:%M"))

                reported_symptoms = latest.get("symptoms", [])
                if reported_symptoms:
                    st.error(f"🚩 **Reported Symptoms:** {', '.join(reported_symptoms)}")

                st.divider()

                # --- 2. HISTORICAL PARAMETER TRENDS ---
                st.markdown("##### 📈 Parameter Trend Analysis")
                df_p = pd.DataFrame(p_docs)
                
                trend_param = st.selectbox(
                    "Select Parameter to Trend:",
                    ["creatinine", "tacrolimus", "weight_kg", "temperature_f", "systolic_bp"],
                    key=f"trend_select_{name}"
                )

                if trend_param in df_p.columns:
                    fig = go.Figure()
                    fig.add_trace(go.Scatter(
                        x=df_p["timestamp"],
                        y=df_p[trend_param],
                        mode="lines+markers",
                        name=trend_param.capitalize(),
                        line=dict(color="#0066cc", width=3),
                        marker=dict(size=7)
                    ))

                    # Reference bounds
                    if trend_param == "creatinine":
                        fig.add_hline(y=1.8, line_dash="dash", line_color="red", annotation_text="High Creatinine Threshold (1.8)")
                    elif trend_param == "tacrolimus":
                        fig.add_hline(y=12.0, line_dash="dash", line_color="red", annotation_text="Upper Tacrolimus Bound (12.0)")
                        fig.add_hline(y=4.0, line_dash="dash", line_color="orange", annotation_text="Lower Tacrolimus Bound (4.0)")
                    elif trend_param == "temperature_f":
                        fig.add_hline(y=100.0, line_dash="dash", line_color="red", annotation_text="Fever Threshold (100.0°F)")

                    fig.update_layout(
                        height=300,
                        margin=dict(l=20, r=20, t=30, b=20),
                        xaxis_title="Check-In Date",
                        yaxis_title=trend_param.capitalize(),
                        template="plotly_white"
                    )
                    st.plotly_chart(fig, use_container_width=True)

                st.divider()

                # --- 3. LABS & IMAGING ---
                st.markdown("##### 🧪 Labs & Imaging Details")
                l1, l2, l3, l4 = st.columns(4)
                l1.metric("Creatinine", f"{latest.get('creatinine', 'N/A')} mg/dL")
                l2.metric("Tacrolimus", f"{latest.get('tacrolimus', 'N/A')} ng/mL")
                l3.metric("BKV PCR Load", f"{latest.get('bkv_load', '0')} copies/mL")
                l4.metric("DSA Antibodies", f"{latest.get('dsa_status', 'N/A')}")

                i1, i2 = st.columns(2)
                i1.write(f"**Ultrasound:** {latest.get('us_findings', 'N/A')}")
                i2.write(f"**DXA T-Score:** {latest.get('dxa_score', 'N/A')}")

                # --- 4. SEND NOTIFICATION TO PATIENT ---
                st.divider()
                st.markdown("##### 📤 Send Instructions/Notification to Patient")
                
                with st.form(key=f"send_notif_form_{name}"):
                    notif_severity = st.selectbox("Priority:", ["Routine Advisory", "Follow-up Recommended", "Urgent Action Required"])
                    notif_msg = st.text_area("Doctor Message / Medication Order:", placeholder="e.g. Please increase fluid intake and repeat Creatinine lab in 48 hours.")
                    
                    submit_notif = st.form_submit_button("Send Notification")
                    
                    if submit_notif:
                        if not notif_msg.strip():
                            st.error("Please enter a message before sending.")
                        else:
                            notif_doc = {
                                "patient_name": name,
                                "patient_id": latest.get("patient_id", "N/A"),
                                "doctor_name": "Transplant Attending",
                                "severity": notif_severity,
                                "message": notif_msg.strip(),
                                "timestamp": datetime.now(),
                                "acknowledged": False
                            }
                            notifs_col.insert_one(notif_doc)
                            st.success(f"✅ Message sent successfully to {name}!")

                # --- 5. DOCUMENT DOWNLOADS ---
                st.divider()
                st.markdown("##### 📥 Attached Reports")
                d1, d2 = st.columns(2)
                if latest.get("lab_file_base64"):
                    d1.download_button("📄 Download Lab Report", base64.b64decode(latest["lab_file_base64"]), file_name=latest.get("lab_file_name", "lab.pdf"), key=f"dl_lab_{name}")
                if latest.get("scan_file_base64"):
                    d2.download_button("🖼️ Download Scan File", base64.b64decode(latest["scan_file_base64"]), file_name=latest.get("scan_file_name", "scan.pdf"), key=f"dl_scan_{name}")
