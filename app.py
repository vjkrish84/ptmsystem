import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime, date

# ---------------------------------------------------------
# 1. Page Configuration (Auto-collapses sidebar on mobile)
# ---------------------------------------------------------
st.set_page_config(
    page_title="Post-Transplant Care Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize Session State
if "selected_patient" not in st.session_state:
    st.session_state["selected_patient"] = None
if "show_detail" not in st.session_state:
    st.session_state["show_detail"] = False
if "current_nav" not in st.session_state:
    st.session_state["current_nav"] = "📱 Patient Entry"

# Custom CSS for Mobile Touch Targets & Clean Spacing
st.markdown("""
    <style>
    /* Make buttons and select boxes thumb-friendly on mobile */
    .stButton>button {
        min-height: 3rem;
        font-weight: 600;
        border-radius: 8px;
    }
    /* Clean up expander borders on mobile */
    .streamlit-expanderHeader {
        font-size: 1.05rem;
        font-weight: 600;
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
        st.error("⚠️ MONGO_URI environment variable is missing in Streamlit Cloud Secrets.")
        st.stop()
    return MongoClient(mongo_uri, tlsCAFile=certifi.where())

client = init_connection()
db = client["transplant_portal"]
vitals_col = db["vitals_logs"]

# ---------------------------------------------------------
# 3. Clinical Logic Helpers
# ---------------------------------------------------------
def check_tacrolimus_status(tac_level, transplant_date, log_date):
    """Evaluates Tacrolimus trough levels against time-based target windows."""
    if tac_level is None or tac_level == 0:
        return None, None
        
    if isinstance(transplant_date, date) and not isinstance(transplant_date, datetime):
        transplant_date = datetime.combine(transplant_date, datetime.min.time())
    if isinstance(log_date, date) and not isinstance(log_date, datetime):
        log_date = datetime.combine(log_date, datetime.min.time())
        
    days_post_op = (log_date - transplant_date).days
    
    # Critical Absolute Thresholds
    if tac_level > 12.0:
        return "RED", f"Tacrolimus Toxicity High ({tac_level:.1f} ng/mL > 12.0)"
    if tac_level < 4.0:
        return "RED", f"Tacrolimus Sub-Therapeutic ({tac_level:.1f} ng/mL < 4.0 — High Rejection Risk)"

    # Time-based Target Windows
    if days_post_op <= 90:  # Months 1-3
        if not (8.0 <= tac_level <= 12.0):
            return "AMBER", f"Tacrolimus Off-Target ({tac_level:.1f} ng/mL | Early Phase Target: 8.0–12.0)"
    else:  # Maintenance Phase (>3 Months)
        if not (5.0 <= tac_level <= 8.0):
            return "AMBER", f"Tacrolimus Off-Target ({tac_level:.1f} ng/mL | Maint. Target: 5.0–8.0)"

    return "GREEN", "Tacrolimus within target window"

# ---------------------------------------------------------
# 4. Mandatory Clinical Disclaimer Header
# ---------------------------------------------------------
st.warning("""
**⚠️ CLINICAL DECISION SUPPORT DISCLAIMER & NOTICE FOR PROVIDERS**  
This portal is an automated data aggregation and clinical decision-support demonstration tool. **It does not constitute final medical advice, diagnosis, or automated treatment orders.** Healthcare providers must independently review, verify, and validate all incoming patient parameters, lab values, and uploaded documents prior to making clinical management decisions.
""")

st.title("🩺 Post-Transplant Portal")

# ---------------------------------------------------------
# 5. Mobile-Friendly Navigation Control
# ---------------------------------------------------------
# Using a segmented control or drop-down navigation avoids horizontal tab overflow on mobile
nav_options = ["📱 Patient Entry", "👨‍⚕️ Doctor Dashboard", "📚 Clinical Protocols"]

selected_page = st.selectbox(
    "Navigation Menu", 
    options=nav_options, 
    index=nav_options.index(st.session_state["current_nav"]),
    label_visibility="collapsed"
)
st.session_state["current_nav"] = selected_page

st.divider()

# =========================================================
# PAGE 1: PATIENT ENTRY (Mobile Accordion Layout)
# =========================================================
if selected_page == "📱 Patient Entry":
    st.subheader("Record Patient Diagnostics & Vitals")
    
    existing_patients = vitals_col.distinct("patient_name")
    patient_option = st.radio(
        "Patient Profile:", 
        ["Select Existing Profile", "➕ Create New Profile"], 
        horizontal=True
    )
    
    if patient_option == "Select Existing Profile" and existing_patients:
        selected_patient_name = st.selectbox("Select Your Name:", existing_patients)
        match_doc = vitals_col.find_one({"patient_name": selected_patient_name})
        p_id = match_doc.get("patient_id", "PT-1001") if match_doc else "PT-1001"
        default_tx_date = match_doc.get("transplant_date", datetime(2025, 1, 1)) if match_doc else datetime(2025, 1, 1)
    else:
        selected_patient_name = st.text_input("Full Name:", value="Sarah Connor")
        p_id = st.text_input("Patient Medical ID / Chart #:", value="PT-9042")
        default_tx_date = datetime(2025, 1, 1)

    # Use a Form wrapped with Expanders for smooth mobile scrolling
    with st.form("patient_full_entry"):
        
        # Section 1: Physical Vitals
        with st.expander("🩸 1. Daily Physical Vitals", expanded=True):
            c1, c2 = st.columns(2)
            weight = c1.number_input("Weight (kg)", min_value=30.0, max_value=200.0, value=73.8, step=0.1)
            temp = c2.number_input("Temperature (°F)", min_value=95.0, max_value=106.0, value=98.6, step=0.1)
            
            c3, c4, c5 = st.columns(3)
            sbp = c3.number_input("Systolic BP", min_value=70, max_value=220, value=120)
            dbp = c4.number_input("Diastolic BP", min_value=40, max_value=140, value=80)
            hr = c5.number_input("Heart Rate (BPM)", min_value=30, max_value=200, value=72)

            symptoms = st.multiselect("Report New Symptoms:", [
                "Fever or Chills", 
                "Decreased urine output / Dark urine", 
                "Pain or tenderness over transplant site",
                "Swelling in feet, legs, or hands", 
                "Shortness of breath", 
                "Incision redness, warmth, or drainage"
            ])

        # Section 2: Blood & Labs
        with st.expander("🧪 2. Blood, Labs & File Upload", expanded=True):
            col_d1, col_d2 = st.columns(2)
            tx_date_input = col_d1.date_input("Transplant Date", value=default_tx_date)
            lab_date_input = col_d2.date_input("Blood / Lab Sample Date", value=date.today())
            
            col_l1, col_l2 = st.columns(2)
            creatinine = col_l1.number_input("Serum Creatinine (mg/dL)", min_value=0.2, max_value=15.0, value=1.1, step=0.1)
            tacrolimus = col_l2.number_input("Tacrolimus Trough (ng/mL)", min_value=0.0, max_value=30.0, value=8.5, step=0.5)
            
            col_l3, col_l4 = st.columns(2)
            bkv_load = col_l3.number_input("BKV PCR (copies/mL)", min_value=0, max_value=1000000, value=0, step=100)
            dsa_status = col_l4.selectbox("Donor Specific Antibodies (DSA):", ["Negative", "Positive (Low MFI)", "Positive (High MFI)", "Pending"])

            urine_protein = st.selectbox("Urinalysis Protein:", ["Negative", "Trace", "1+", "2+", "3+"])
            
            uploaded_lab_file = st.file_uploader("📎 Upload Official Lab Report (PDF/Image):", type=["pdf", "png", "jpg", "jpeg"])

        # Section 3: Procedures & Screenings
        with st.expander("🏥 3. Diagnostic Procedures & Surveillance", expanded=False):
            col_s1, col_s2 = st.columns(2)
            us_date = col_s1.date_input("Renal Ultrasound Date", value=date.today())
            us_result = col_s2.text_input("Ultrasound Findings / RI", value="Normal graft size, RI = 0.64, no hydronephrosis")
            
            col_s3, col_s4 = st.columns(2)
            dxa_score = col_s3.number_input("DXA Scan T-Score", min_value=-5.0, max_value=3.0, value=-0.8, step=0.1)
            colonoscopy_date = col_s4.text_input("Last Colonoscopy Status", value="Cleared (Next due in 5 yrs)")
            
            cancer_screening = st.text_area("Other Cancer Screenings", value="Dermatology: Clear; Annual Mammogram: Normal")

        submitted = st.form_submit_button("Submit Complete Entry", use_container_width=True)
        if submitted:
            file_data = None
            file_name = None
            if uploaded_lab_file is not None:
                file_bytes = uploaded_lab_file.read()
                file_data = base64.b64encode(file_bytes).decode('utf-8')
                file_name = uploaded_lab_file.name

            new_log = {
                "patient_id": p_id,
                "patient_name": selected_patient_name,
                "transplant_date": datetime.combine(tx_date_input, datetime.min.time()),
                "lab_report_date": datetime.combine(lab_date_input, datetime.min.time()),
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
                "urine_protein": urine_protein,
                "lab_file_base64": file_data,
                "lab_file_name": file_name,
                "us_date": datetime.combine(us_date, datetime.min.time()),
                "us_findings": us_result,
                "dxa_score": dxa_score,
                "colonoscopy": colonoscopy_date,
                "cancer_screening": cancer_screening
            }
            vitals_col.insert_one(new_log)
            st.success(f"✅ Records and lab reports successfully submitted for {selected_patient_name}!")

# =========================================================
# PAGE 2: DOCTOR DASHBOARD (Mobile Triage Cards)
# =========================================================
elif selected_page == "👨‍⚕️ Doctor Dashboard":
    st.subheader("👨‍⚕️ Clinical Triage & Diagnostic Roster")
    st.caption("Tap any patient banner below to review flags, lab reports, and uploaded documents.")

    patient_names = vitals_col.distinct("patient_name")
    
    if not patient_names:
        st.info("No patient logs found in MongoDB. Submit a record under 'Patient Entry'.")
    else:
        patient_summaries = []

        for name in patient_names:
            p_docs = list(vitals_col.find({"patient_name": name}).sort("timestamp", 1))
            if not p_docs:
                continue
            
            p_df = pd.DataFrame(p_docs)
            latest = p_df.iloc[-1]
            prev = p_df.iloc[-2] if len(p_df) > 1 else latest
            weight_change = latest['weight_kg'] - prev['weight_kg']
            
            red_flags = []
            amber_flags = []

            # 1. Tacrolimus Automated Check
            tx_date_val = latest.get("transplant_date", latest['timestamp'])
            lab_date_val = latest.get("lab_report_date", latest['timestamp'])
            tac_val = latest.get("tacrolimus", 0.0)
            
            tac_flag, tac_msg = check_tacrolimus_status(tac_val, tx_date_val, lab_date_val)
            
            if tac_flag == "RED":
                red_flags.append(tac_msg)
            elif tac_flag == "AMBER":
                amber_flags.append(tac_msg)

            # 2. Vitals & Lab Checks
            if weight_change >= 1.5:
                red_flags.append(f"Weight Spike (+{weight_change:.1f}kg/24h)")
            if latest['temperature_f'] >= 100.0:
                red_flags.append(f"Fever ({latest['temperature_f']}°F)")
            if latest.get('creatinine', 1.0) >= 1.8:
                red_flags.append(f"Elevated Creatinine ({latest.get('creatinine')} mg/dL)")
            if latest.get('bkv_load', 0) >= 10000:
                red_flags.append(f"High BKV Load ({latest.get('bkv_load')} copies/mL)")
            if "High MFI" in latest.get('dsa_status', ''):
                red_flags.append(f"DSA Positive ({latest.get('dsa_status')})")
            if latest.get('symptoms'):
                red_flags.append(f"Symptoms ({', '.join(latest['symptoms'])})")

            # 3. Borderline Checks
            if 1.4 <= latest.get('creatinine', 1.0) < 1.8:
                amber_flags.append(f"Borderline Creatinine ({latest.get('creatinine')} mg/dL)")
            if latest['heart_rate'] > 100 or latest['heart_rate'] < 55:
                amber_flags.append(f"Abnormal HR ({latest['heart_rate']} BPM)")

            # Priority Assignment
            if red_flags:
                status_icon = "🔴 RED ALERT"
                priority = 1
            elif amber_flags:
                status_icon = "🟡 AMBER WATCH"
                priority = 2
            else:
                status_icon = "🟢 GREEN STABLE"
                priority = 3

            patient_summaries.append({
                "patient_name": name,
                "patient_id": latest.get('patient_id', 'N/A'),
                "status": status_icon,
                "priority": priority,
                "red_flags": red_flags,
                "amber_flags": amber_flags,
                "latest_data": latest,
                "full_df": p_df,
                "weight_change": weight_change
            })

        patient_summaries.sort(key=lambda x: x['priority'])

        # Render Touch-Friendly Patient Cards
        for p in patient_summaries:
            name = p['patient_name']
            status = p['status']
            p_id = p['patient_id']
            
            summary_line = " | Flags: " + ", ".join(p['red_flags'] if p['red_flags'] else p['amber_flags']) if (p['red_flags'] or p['amber_flags']) else " | Parameters Stable"
            button_label = f"{status}\n{name} (ID: {p_id}){summary_line}"
            
            if st.button(button_label, key=f"btn_{name}", use_container_width=True):
                st.session_state["selected_patient"] = name
                st.session_state["show_detail"] = True

        st.divider()

        # Detailed Patient Inspection
        if st.session_state["show_detail"] and st.session_state["selected_patient"]:
            selected_name = st.session_state["selected_patient"]
            selected_p = next((p for p in patient_summaries if p['patient_name'] == selected_name), None)

            if selected_p:
                l_data = selected_p['latest_data']

                with st.expander(f"🔍 Clinical File: {selected_p['patient_name']}", expanded=True):
                    st.caption(f"Status: **{selected_p['status']}** | Chart ID: `{selected_p['patient_id']}` | Updated: {l_data['timestamp'].strftime('%Y-%m-%d %H:%M')}")

                    if selected_p['red_flags']:
                        st.error("### 🚨 ACTIVE CLINICAL ALERTS\n" + "\n".join([f"- {f}" for f in selected_p['red_flags']]))
                    elif selected_p['amber_flags']:
                        st.warning("### ⚠️ WATCH CONDITIONS\n" + "\n".join([f"- {f}" for f in selected_p['amber_flags']]))
                    else:
                        st.success("✅ All vitals and lab parameters are currently within normal target range.")

                    # Use mobile accordion containers instead of tight horizontal sub-tabs
                    with st.expander("📊 Physical Vitals & Weight Trend", expanded=True):
                        c1, c2 = st.columns(2)
                        c1.metric("Weight", f"{l_data['weight_kg']} kg", f"{selected_p['weight_change']:+.1f} kg")
                        c2.metric("Temp", f"{l_data['temperature_f']} °F")
                        
                        c3, c4 = st.columns(2)
                        c3.metric("BP", f"{l_data['systolic_bp']}/{l_data['diastolic_bp']}")
                        c4.metric("Heart Rate", f"{l_data['heart_rate']} BPM")
                        
                        fig = px.line(selected_p['full_df'], x="timestamp", y="weight_kg", title="Weight Trend (Fluid Retention)", markers=True)
                        st.plotly_chart(fig, use_container_width=True)

                    with st.expander("🧪 Lab Results & Source File", expanded=True):
                        lab_date_str = l_data.get('lab_report_date').strftime('%Y-%m-%d') if l_data.get('lab_report_date') else "N/A"
                        st.info(f"📅 **Blood Sample Date:** {lab_date_str}")
                        
                        l1, l2, l3 = st.columns(3)
                        l1.metric("Creatinine", f"{l_data.get('creatinine', 'N/A')} mg/dL")
                        l2.metric("Tacrolimus", f"{l_data.get('tacrolimus', 'N/A')} ng/mL")
                        l3.metric("Urine Protein", f"{l_data.get('urine_protein', 'N/A')}")

                        l4, l5 = st.columns(2)
                        l4.metric("BKV PCR Load", f"{l_data.get('bkv_load', 0)} copies/mL")
                        l5.metric("DSA Status", f"{l_data.get('dsa_status', 'N/A')}")

                        st.divider()
                        st.markdown("#### 📁 Verification Document Inspector")
                        file_b64 = l_data.get("lab_file_base64")
                        file_name = l_data.get("lab_file_name")

                        if file_b64 and file_name:
                            bytes_decoded = base64.b64decode(file_b64)
                            st.download_button(
                                label=f"📥 Download Uploaded Lab Report ({file_name})",
                                data=bytes_decoded,
                                file_name=file_name,
                                mime="application/octet-stream",
                                use_container_width=True
                            )
                            if file_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                                st.image(bytes_decoded, caption=f"Uploaded Report: {file_name}", use_column_width=True)
                        else:
                            st.warning("⚠️ No physical lab report was uploaded for this record.")

                    with st.expander("🏥 Imaging & Surveillance Screenings", expanded=False):
                        us_date_str = l_data.get('us_date').strftime('%Y-%m-%d') if l_data.get('us_date') else "N/A"
                        st.markdown(f"**Renal Ultrasound Date:** {us_date_str}")
                        st.markdown(f"**Findings:** {l_data.get('us_findings', 'N/A')}")
                        st.markdown(f"**DXA Bone Density T-Score:** `{l_data.get('dxa_score', 'N/A')}`")
                        st.markdown(f"**Colonoscopy History:** {l_data.get('colonoscopy', 'N/A')}")
                        st.markdown(f"**Cancer Screenings:** {l_data.get('cancer_screening', 'N/A')}")

# =========================================================
# PAGE 3: CLINICAL PROTOCOLS
# =========================================================
elif selected_page == "📚 Clinical Protocols":
    st.subheader("📋 Post-Transplant Standard Protocols")
    
    with st.expander("🔬 Lab Frequency & Drug Level Schedules", expanded=True):
        st.markdown("""
        * **Months 1–3:** Tacrolimus Trough 2–3x/wk (Target: 8–12 ng/mL); CBC/CMP 2–3x/wk; BKV/CMV Monthly.
        * **Months 4–6:** Tacrolimus Trough Bi-weekly (Target: 6–8 ng/mL); BKV/CMV Every 3 mos.
        * **Months 6–12:** Monthly labs; Donor-Specific Antibodies (DSA) & Renal US as indicated.
        """)

    with st.expander("🛡️ Infection Control & Food Safety Rules", expanded=True):
        st.markdown("""
        * **Food Safety:** Strictly no grapefruit/starfruit/Seville oranges (interferes with Tacrolimus). No raw meats, unpasteurized dairy, or soft eggs.
        * **Infection Prevention:** Mask in crowded indoor settings for first 3–6 months. No live vaccines.
        """)

    with st.expander("🎗️ Cancer Screening Schedule", expanded=False):
        st.markdown("""
        * **Dermatology:** Annual full-body skin exam (elevated skin cancer risk).
        * **Routine Screenings:** Annual mammogram (women ≥40), Colonoscopy (age ≥45), Annual Pap smear.
        """)
