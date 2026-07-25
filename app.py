import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime, date

# ---------------------------------------------------------
# 1. Page Configuration & Custom CSS
# ---------------------------------------------------------
st.set_page_config(
    page_title="Post-Transplant Clinical & Patient Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    .stButton>button {
        min-height: 2.8rem;
        font-weight: 600;
        border-radius: 8px;
    }
    .red-alert-card {
        background-color: #ffebe9;
        border-left: 5px solid #d9381e;
        padding: 12px;
        border-radius: 6px;
        margin-bottom: 10px;
    }
    .amber-alert-card {
        background-color: #fff8e6;
        border-left: 5px solid #f0b100;
        padding: 12px;
        border-radius: 6px;
        margin-bottom: 10px;
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
# 3. Comprehensive Nephrology Clinical Logic
# ---------------------------------------------------------
def evaluate_clinical_alerts(latest_doc, prev_doc=None):
    """Evaluates vitals, labs, and symptoms against exact Nephrologist threshold notes."""
    red_flags = []
    amber_flags = []

    tx_date = latest_doc.get("transplant_date", datetime.now())
    log_date = latest_doc.get("timestamp", datetime.now())
    if isinstance(tx_date, date) and not isinstance(tx_date, datetime):
        tx_date = datetime.combine(tx_date, datetime.min.time())
    if isinstance(log_date, date) and not isinstance(log_date, datetime):
        log_date = datetime.combine(log_date, datetime.min.time())

    days_post_op = max((log_date - tx_date).days, 0)

    # 1. Weight Spike Trigger (≥ 1.5kg in 24h / 1 log)
    if prev_doc:
        wt_change = latest_doc.get('weight_kg', 0) - prev_doc.get('weight_kg', 0)
        if wt_change >= 1.5:
            red_flags.append(f"Weight Spike (+{wt_change:.1f} kg since last entry)")

    # 2. Temperature Threshold (≥ 100.0°F)
    temp = latest_doc.get("temperature_f", 98.6)
    if temp >= 100.0:
        red_flags.append(f"Fever Alert ({temp:.1f}°F ≥ 100°F)")

    # 3. Blood Pressure Thresholds
    sbp = latest_doc.get("systolic_bp", 120)
    dbp = latest_doc.get("diastolic_bp", 80)
    if sbp > 150 or sbp < 100:
        amber_flags.append(f"Abnormal Systolic BP ({sbp} mmHg | Target: 100–150)")
    if dbp > 100 or dbp < 60:
        amber_flags.append(f"Abnormal Diastolic BP ({dbp} mmHg | Target: 60–100)")

    # 4. Heart Rate Thresholds
    hr = latest_doc.get("heart_rate", 72)
    if hr > 100 or hr < 55:
        amber_flags.append(f"Abnormal Resting Heart Rate ({hr} BPM | Target: 55–100)")

    # 5. Tacrolimus Levels & AM Dose Timing Rules
    tac = latest_doc.get("tacrolimus", 0.0)
    if tac > 0:
        if tac > 12.0:
            red_flags.append(f"Tacrolimus Toxicity High ({tac:.1f} ng/mL > 12.0)")
        elif tac < 4.0:
            red_flags.append(f"Tacrolimus Sub-Therapeutic ({tac:.1f} ng/mL < 4.0 — High Rejection Risk)")
        elif days_post_op <= 90 and not (8.0 <= tac <= 12.0):
            amber_flags.append(f"Tacrolimus Off-Target ({tac:.1f} ng/mL | Months 1–3 Target: 8.0–12.0)")
        elif days_post_op > 90 and not (5.0 <= tac <= 8.0):
            amber_flags.append(f"Tacrolimus Off-Target ({tac:.1f} ng/mL | Maintenance Target: 5.0–8.0)")

    # 6. Labs (Creatinine, BKV PCR, DSA)
    creat = latest_doc.get("creatinine", 1.0)
    if creat >= 1.8:
        red_flags.append(f"Elevated Creatinine ({creat:.2f} mg/dL)")
    elif 1.4 <= creat < 1.8:
        amber_flags.append(f"Borderline Creatinine ({creat:.2f} mg/dL)")

    bkv = latest_doc.get("bkv_load", 0)
    if bkv >= 10000:
        red_flags.append(f"High BKV PCR Load ({bkv:,} copies/mL)")

    dsa = latest_doc.get("dsa_status", "Negative")
    if "High MFI" in dsa:
        red_flags.append(f"DSA Positive Alert ({dsa})")

    # 7. Reported Symptoms
    symptoms = latest_doc.get("symptoms", [])
    if symptoms:
        red_flags.append(f"Reported Symptoms: {', '.join(symptoms)}")

    return red_flags, amber_flags, days_post_op


def calculate_surveillance_milestones(days_post_op):
    """Calculates due/overdue milestones based on post-op days."""
    months_post_op = days_post_op / 30.43
    
    milestones = {
        "lab_monitoring": "Monthly (Months 6–12)" if months_post_op >= 6 else ("Every 2 Weeks (Months 4–6)" if months_post_op >= 3 else "Weekly / Twice Weekly"),
        "bkv_pcr": "Monthly" if months_post_op <= 9 else ("Every 3 Months" if months_post_op <= 24 else "As Clinically Indicated"),
        "dsa_screening": "Due at Month 3, 6, 12, then Annually",
        "ultrasound": "Due at Wk 1, Mo 1, Mo 3, Mo 6, Mo 12, then Annually",
        "dxa_scan": "Due within Year 1 (Baseline), then q2–3 years",
        "skin_exam": "Annual Skin Exam Due (Started at Month 6)" if months_post_op >= 6 else "Pending (Starts at Month 6)"
    }
    return milestones

# ---------------------------------------------------------
# 4. URL Navigation Routing
# ---------------------------------------------------------
query_params = st.query_params
default_role = query_params.get("role", "patient")
if default_role not in ["patient", "doctor"]:
    default_role = "patient"

col_title, col_role = st.columns([3, 1])
with col_title:
    st.title("🩺 Post-Transplant Care & Triage System")

with col_role:
    selected_role = st.selectbox(
        "Navigation Role",
        options=["patient", "doctor"],
        index=0 if default_role == "patient" else 1,
        format_func=lambda x: "📱 Patient Portal" if x == "patient" else "👨‍⚕️ Doctor / Coordinator Dashboard"
    )

st.divider()

# Mandatory Clinical Disclaimer Banner
st.warning("""
**⚠️ CLINICAL DECISION SUPPORT DISCLAIMER & NOTICE FOR PROVIDERS**  
This portal is an automated data aggregation and clinical decision-support demonstration tool. **It does not constitute final medical advice, diagnosis, or automated treatment orders.** Healthcare providers must independently review, verify, and validate all incoming patient parameters, lab values, and uploaded documents prior to making clinical management decisions.
""")

# =========================================================
# VIEW 1: PATIENT PORTAL
# =========================================================
if selected_role == "patient":
    st.subheader("📱 Patient Portal & Daily Check-In")

    # EMERGENCY CALLOUT BANNER
    st.error("""
    **🚨 GO TO THE NEAREST HOSPITAL IMMEDIATELY IF YOU HAVE:**  
    Difficulty breathing, heavy bleeding, chest pain, seizures, one-sided weakness, slurred speech, facial droop, or hit your head after falling.
    """)

    tab_checkin, tab_when_to_call, tab_safety, tab_nutrition = st.tabs([
        "📝 Daily Check-In & Uploads", 
        "📞 When to Call Coordinator", 
        "🛡️ Infection Rules & Vaccines", 
        "🥗 Nutrition & Food Safety"
    ])

    # --- TAB 1: DAILY ENTRY FORM ---
    with tab_checkin:
        existing_patients = vitals_col.distinct("patient_name")
        patient_option = st.radio("Patient Profile:", ["Select Existing Profile", "➕ Create New Profile"], horizontal=True)

        if patient_option == "Select Existing Profile" and existing_patients:
            selected_patient_name = st.selectbox("Select Your Name:", existing_patients)
            match_doc = vitals_col.find_one({"patient_name": selected_patient_name})
            p_id = match_doc.get("patient_id", "PT-1001") if match_doc else "PT-1001"
            default_tx_date = match_doc.get("transplant_date", datetime(2025, 1, 1)) if match_doc else datetime(2025, 1, 1)
        else:
            selected_patient_name = st.text_input("Full Name:", value="Sarah Connor")
            p_id = st.text_input("Medical Record # / Chart ID:", value="PT-9042")
            default_tx_date = datetime(2025, 1, 1)

        with st.form("patient_daily_entry"):
            st.info("💡 **REMINDER:** On lab days, draw your bloodwork FIRST before taking your morning Tacrolimus dose!")
            
            with st.expander("🩸 1. Daily Physical Vitals", expanded=True):
                c1, c2 = st.columns(2)
                weight = c1.number_input("Weight (kg)", min_value=30.0, max_value=200.0, value=73.8, step=0.1)
                temp = c2.number_input("Body Temp (°F) — Report if ≥100°F", min_value=95.0, max_value=106.0, value=98.6, step=0.1)
                
                c3, c4, c5 = st.columns(3)
                sbp = c3.number_input("Systolic BP (Top #)", min_value=70, max_value=220, value=120)
                dbp = c4.number_input("Diastolic BP (Bottom #)", min_value=40, max_value=140, value=80)
                hr = c5.number_input("Resting HR (BPM)", min_value=30, max_value=200, value=72)

                symptoms = st.multiselect("Select Any Symptoms Present Today:", [
                    "Decreased urine output / Dark urine", 
                    "Pain over transplant site",
                    "Swelling of hands or feet", 
                    "Shortness of breath / Trouble breathing", 
                    "Blood in urine or stool",
                    "Shivering, chills, or confusion",
                    "Incision swelling, redness, or green/yellow leakage",
                    "Burning feeling while urinating / Cloudy urine",
                    "Nausea, vomiting, or diarrhea"
                ])

            with st.expander("🧪 2. Blood, Lab Work & Lab Report Upload", expanded=True):
                col_d1, col_d2 = st.columns(2)
                tx_date_input = col_d1.date_input("Transplant Date", value=default_tx_date)
                lab_date_input = col_d2.date_input("Lab Sample Date", value=date.today())
                
                col_l1, col_l2 = st.columns(2)
                creatinine = col_l1.number_input("Serum Creatinine (mg/dL)", min_value=0.2, max_value=15.0, value=1.1, step=0.1)
                tacrolimus = col_l2.number_input("Tacrolimus Trough Level (ng/mL)", min_value=0.0, max_value=30.0, value=8.5, step=0.5)
                
                col_l3, col_l4 = st.columns(2)
                bkv_load = col_l3.number_input("BKV PCR Load (copies/mL)", min_value=0, max_value=1000000, value=0, step=100)
                dsa_status = col_l4.selectbox("Donor Specific Antibodies (DSA):", ["Negative", "Positive (Low MFI)", "Positive (High MFI)", "Pending"])

                uploaded_lab_file = st.file_uploader("📎 Upload Official Lab Report File (PDF / Image):", type=["pdf", "png", "jpg", "jpeg"], key="lab_upload")

            # NEW SECTION: IMAGING, SCANS & DIAGNOSTICS UPLOAD
            with st.expander("🖼️ 3. Imaging Studies & Surveillance Scan Uploads", expanded=True):
                st.caption("Upload Ultrasound reports, DXA scans, or cancer screening documentation.")
                
                col_img1, col_img2 = st.columns(2)
                us_date = col_img1.date_input("Renal Ultrasound Scan Date", value=date.today())
                us_result = col_img2.text_input("Ultrasound Findings / Resistive Index (RI)", value="Normal graft size, RI = 0.64, no hydronephrosis")
                
                col_img3, col_img4 = st.columns(2)
                dxa_score = col_img3.number_input("DXA Scan T-Score", min_value=-5.0, max_value=3.0, value=-0.8, step=0.1)
                colonoscopy_date = col_img4.text_input("Colonoscopy / Endoscopy Status", value="Cleared (Next due in 5 yrs)")
                
                cancer_screening = st.text_area("Other Cancer Screenings", value="Dermatology: Skin exam clear; Mammogram: Normal")
                
                uploaded_scan_file = st.file_uploader("🖼️ Upload Radiology Scan / Ultrasound / DXA Document:", type=["pdf", "png", "jpg", "jpeg"], key="scan_upload")

            submitted = st.form_submit_button("Submit Entry & Run Alert Check", use_container_width=True)
            if submitted:
                # Lab File Processing
                lab_file_data = None
                lab_file_name = None
                if uploaded_lab_file is not None:
                    lab_file_bytes = uploaded_lab_file.read()
                    lab_file_data = base64.b64encode(lab_file_bytes).decode('utf-8')
                    lab_file_name = uploaded_lab_file.name

                # Scan File Processing
                scan_file_data = None
                scan_file_name = None
                if uploaded_scan_file is not None:
                    scan_file_bytes = uploaded_scan_file.read()
                    scan_file_data = base64.b64encode(scan_file_bytes).decode('utf-8')
                    scan_file_name = uploaded_scan_file.name

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
                    "lab_file_base64": lab_file_data,
                    "lab_file_name": lab_file_name,
                    "us_date": datetime.combine(us_date, datetime.min.time()),
                    "us_findings": us_result,
                    "dxa_score": dxa_score,
                    "colonoscopy": colonoscopy_date,
                    "cancer_screening": cancer_screening,
                    "scan_file_base64": scan_file_data,
                    "scan_file_name": scan_file_name
                }
                vitals_col.insert_one(new_log)
                st.success(f"✅ Entry & Imaging files submitted successfully for {selected_patient_name}!")

    # --- TAB 2: WHEN TO CALL COORDINATOR ---
    with tab_when_to_call:
        st.subheader("📞 When to Call Your Transplant Coordinator")
        st.caption("Never think: 'I don't want to bother my Coordinator with this problem.' Always call immediately!")

        c1, c2 = st.columns(2)
        with c1:
            st.error("### 🚨 Symptoms of REJECTION")
            st.markdown("""
            * Less urine output than usual
            * Fatigue
            * Pain over your transplant site
            * Swelling of your hands or feet
            * **Fever (Temp over 100°F)**
            * **Gained 1.5kg or more in 1 day**
            * Trouble breathing
            * Blood in your urine
            """)

            st.warning("### 💊 Medication & Vitals Issues")
            st.markdown("""
            * **Gained >1.5kg in 24 hours**
            * Systolic BP **>150 or <100 mmHg**
            * Diastolic BP **>100 or <60 mmHg**
            * Resting Heart Rate **>100 or <55 BPM**
            * Medication reaction or missed dose
            * Unable to pay for medications
            * Positive pregnancy test or unprotected sex
            * New prescription or dosage change from outside doctor
            """)

        with c2:
            st.error("### 🦠 Symptoms of INFECTION")
            st.markdown("""
            * **Fever (100°F or higher)** or shivering
            * Confusion or fatigue
            * Swelling, redness, or green/yellow leakage from incision site
            * Burning feeling while urinating or bad-smelling urine
            * Cough (dry or wet) or bloody/green mucus
            * Shortness of breath
            * Nausea, vomiting, or diarrhea
            * Loss of appetite or unexpected weight loss
            * Blood in stool
            """)

    # --- TAB 3: INFECTION PREVENTION & VACCINES ---
    with tab_safety:
        st.subheader("🛡️ Infection Prevention Rules & Vaccine Safety")
        
        st.markdown("### 📅 Restriction Timeline Post-Transplant")
        col_t1, col_t2, col_t3 = st.columns(3)
        with col_t1:
            st.info("**First 3 Months**\n\nAvoid indoor public spaces during busy hours (stores, theaters, gyms). Wear a face mask if unavoidable.")
        with col_t2:
            st.info("**First 6 Months**\n\nDo not dig in soil or garden. Do not swim in untreated water (lakes, oceans).")
        with col_t3:
            st.info("**First Year & Beyond**\n\nNo international travel during Year 1. **Avoid cruises for life.**")

        st.divider()

        st.markdown("### 💉 Vaccine Matrix (Safe vs. Dangerous)")
        v1, v2 = st.columns(2)
        with v1:
            st.success("#### ✅ SAFE Vaccines (Inactivated / Killed)")
            st.markdown("""
            * **Flu Shot** (Annual injection every September)
            * **Pneumonia Shot** (Every 5 years)
            * **Tdap** (Tetanus, diphtheria, pertussis)
            * **Hepatitis A & B series**
            * **HPV & Haemophilus influenzae (HiB)**
            * **Polio (Injection only)** & Meningococcal
            * *Note: Wait at least 2 months post-transplant before receiving vaccines.*
            """)
        with v2:
            st.error("#### ❌ FORBIDDEN Vaccines (Live / Attenuated)")
            st.markdown("""
            * **MMR** (Measles, mumps, rubella)
            * **FluMist** (Nasal spray flu vaccine)
            * **Chickenpox** (Varicella)
            * **Shingles** (Zoster)
            * **BCG Vaccine**
            * *Note: Anyone living with you must get an annual flu shot but avoid live vaccines!*
            """)

    # --- TAB 4: NUTRITION & FOOD SAFETY ---
    with tab_nutrition:
        st.subheader("🥗 Nutrition, Oral Health & Daily Habits")
        
        n1, n2 = st.columns(2)
        with n1:
            st.error("#### 🚫 STRICTLY AVOID")
            st.markdown("""
            * **Grapefruit & Grapefruit Juice** (Affects Tacrolimus levels dangerously)
            * **NSAID Painkillers** (Ibuprofen, Naproxen, Advil, Aleve — cause kidney damage)
            * **Herbal Supplements** (Interact unpredictably with anti-rejection meds)
            * **Raw or Undercooked Foods:** Raw eggs, meat, sushi, unpasteurized milk/cheeses, raw sprouts, pâtés.
            * **Self-serve buffets & salad bars**
            * Leftover cooked food stored past **3 days**
            """)

        with n2:
            st.success("#### ✅ DAILY HEALTHY HABITS")
            st.markdown("""
            * **Hydration:** Drink clean, treated or filtered water throughout the day.
            * **Physical Activity:** Move at least every 2 hours. Do not lift >5kg for 8 weeks post-surgery.
            * **Sun Protection:** Wear SPF 30+ sunscreen, wide-brimmed hats, and long sleeves (11 AM – 3 PM sun avoidance).
            * **Dental Care:** Wash teeth/gums daily. Inform dentist of transplant. Wait 6 months for major dental procedures.
            """)

# =========================================================
# VIEW 2: DOCTOR / COORDINATOR DASHBOARD
# =========================================================
elif selected_role == "doctor":
    st.subheader("👨‍⚕️ Nephrologist & Coordinator Triage Dashboard")

    patient_names = vitals_col.distinct("patient_name")

    if not patient_names:
        st.info("No patient logs found in MongoDB. Share the Patient Portal link to collect daily logs.")
    else:
        patient_summaries = []

        for name in patient_names:
            p_docs = list(vitals_col.find({"patient_name": name}).sort("timestamp", 1))
            if not p_docs:
                continue

            latest = p_docs[-1]
            prev = p_docs[-2] if len(p_docs) > 1 else None

            red_flags, amber_flags, days_post_op = evaluate_clinical_alerts(latest, prev)

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
                "days_post_op": days_post_op,
                "latest_data": latest,
                "full_df": pd.DataFrame(p_docs)
            })

        patient_summaries.sort(key=lambda x: x['priority'])

        # Render Touch-Friendly Patient Cards
        for p in patient_summaries:
            name = p['patient_name']
            status = p['status']
            p_id = p['patient_id']
            days = p['days_post_op']

            summary_line = " | Flags: " + ", ".join(p['red_flags'] if p['red_flags'] else p['amber_flags']) if (p['red_flags'] or p['amber_flags']) else " | All Parameters Within Target"
            button_label = f"{status} - {name} (ID: {p_id} | Day {days} Post-Op){summary_line}"

            if st.button(button_label, key=f"btn_{name}", use_container_width=True):
                st.session_state["selected_patient"] = name
                st.session_state["show_detail"] = True

        st.divider()

        # Detailed Inspection View
        if st.session_state.get("show_detail") and st.session_state.get("selected_patient"):
            selected_name = st.session_state["selected_patient"]
            selected_p = next((p for p in patient_summaries if p['patient_name'] == selected_name), None)

            if selected_p:
                l_data = selected_p['latest_data']
                days_post_op = selected_p['days_post_op']

                with st.expander(f"🔍 Clinical Chart: {selected_p['patient_name']} (Day {days_post_op} Post-Op)", expanded=True):
                    
                    # 1. ALERT SUMMARY BOXES
                    if selected_p['red_flags']:
                        st.error("### 🚨 IMMEDIATE CLINICAL ALERTS\n" + "\n".join([f"- {f}" for f in selected_p['red_flags']]))
                    if selected_p['amber_flags']:
                        st.warning("### ⚠️ WATCH PARAMETERS\n" + "\n".join([f"- {f}" for f in selected_p['amber_flags']]))

                    # 2. SURVEILLANCE MILESTONE TRACKER
                    milestones = calculate_surveillance_milestones(days_post_op)
                    st.markdown("### 📅 Surveillance Milestone Status")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("BKV PCR Frequency", milestones["bkv_pcr"])
                    m2.metric("DSA Protocol", "Months 3, 6, 12")
                    m3.metric("Renal Ultrasound", "Wk 1, Mo 1, 3, 6, 12")
                    m4.metric("Skin Exam Status", milestones["skin_exam"])

                    # 3. VITALS & WEIGHT TRENDS
                    st.markdown("### 📊 Vitals & Weight Retention Trend")
                    v1, v2, v3, v4 = st.columns(4)
                    v1.metric("Weight", f"{l_data['weight_kg']} kg")
                    v2.metric("Temp", f"{l_data['temperature_f']} °F")
                    v3.metric("Blood Pressure", f"{l_data['systolic_bp']}/{l_data['diastolic_bp']} mmHg")
                    v4.metric("Heart Rate", f"{l_data['heart_rate']} BPM")

                    fig = px.line(selected_p['full_df'], x="timestamp", y="weight_kg", title="Weight Log (24h Retention Tracking)", markers=True)
                    st.plotly_chart(fig, use_container_width=True)

                    # 4. LAB VERIFICATION & ATTACHED LAB REPORT
                    st.markdown("### 🧪 Lab Values & Report Document Inspector")
                    l1, l2, l3, l4 = st.columns(4)
                    l1.metric("Creatinine", f"{l_data.get('creatinine', 'N/A')} mg/dL")
                    l2.metric("Tacrolimus Trough", f"{l_data.get('tacrolimus', 'N/A')} ng/mL")
                    l3.metric("BKV PCR Load", f"{l_data.get('bkv_load', 0):,} copies/mL")
                    l4.metric("DSA Status", f"{l_data.get('dsa_status', 'N/A')}")

                    lab_b64 = l_data.get("lab_file_base64")
                    lab_name = l_data.get("lab_file_name")
                    if lab_b64 and lab_name:
                        lab_bytes = base64.b64decode(lab_b64)
                        st.download_button(
                            label=f"📥 Download Lab Report ({lab_name})",
                            data=lab_bytes,
                            file_name=lab_name,
                            mime="application/octet-stream",
                            use_container_width=True,
                            key="btn_dl_lab"
                        )
                    else:
                        st.info("ℹ️ No physical lab report document attached to this entry.")

                    # 5. IMAGING & RADIOLOGY SCAN INSPECTOR
                    st.divider()
                    st.markdown("### 🖼️ Diagnostic Imaging & Radiology Inspector")
                    
                    us_date_str = l_data.get('us_date').strftime('%Y-%m-%d') if l_data.get('us_date') else "N/A"
                    st.markdown(f"**Renal Ultrasound Date:** `{us_date_str}`")
                    st.markdown(f"**Ultrasound Findings / RI:** {l_data.get('us_findings', 'N/A')}")
                    st.markdown(f"**DXA Bone Density T-Score:** `{l_data.get('dxa_score', 'N/A')}`")
                    st.markdown(f"**Colonoscopy Status:** {l_data.get('colonoscopy', 'N/A')}")
                    st.markdown(f"**Cancer Screenings:** {l_data.get('cancer_screening', 'N/A')}")

                    scan_b64 = l_data.get("scan_file_base64")
                    scan_name = l_data.get("scan_file_name")
                    if scan_b64 and scan_name:
                        scan_bytes = base64.b64decode(scan_b64)
                        st.download_button(
                            label=f"📥 Download Radiology Image / Scan ({scan_name})",
                            data=scan_bytes,
                            file_name=scan_name,
                            mime="application/octet-stream",
                            use_container_width=True,
                            key="btn_dl_scan"
                        )
                        if scan_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                            st.image(scan_bytes, caption=f"Uploaded Radiology File: {scan_name}", use_column_width=True)
                    else:
                        st.info("ℹ️ No radiology scan document uploaded for this entry.")
