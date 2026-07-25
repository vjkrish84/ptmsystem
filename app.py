import os
import certifi
import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime

# ---------------------------------------------------------
# 1. Page Configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="Transplant Care Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------------------------------------------------------
# 2. Database Connection (SSL/TLS Fix Included)
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

st.title("🩺 Post-Transplant Care Portal")

tab_patient, tab_doctor, tab_protocols = st.tabs([
    "📱 Patient Entry", 
    "👨‍⚕️ Doctor Dashboard", 
    "📚 Clinical Protocols"
])

# =========================================================
# TAB 1: PATIENT ENTRY (Multi-Patient Selection/Creation)
# =========================================================
with tab_patient:
    st.subheader("Record Daily Vitals")
    
    # Allow existing patient selection or new patient entry
    existing_patients = vitals_col.distinct("patient_name")
    
    patient_option = st.radio(
        "Patient Profile:", 
        ["Select Existing Profile", "➕ Create New Profile"], 
        horizontal=True
    )
    
    if patient_option == "Select Existing Profile" and existing_patients:
        selected_patient_name = st.selectbox("Select Your Name:", existing_patients)
        p_id = vitals_col.find_one({"patient_name": selected_patient_name}).get("patient_id", "PT-1001")
    else:
        selected_patient_name = st.text_input("Full Name:", value="Sarah Connor")
        p_id = st.text_input("Patient Medical ID / Chart #:", value="PT-9042")

    st.caption("Submit your morning vitals before taking morning immunosuppressive medications.")

    with st.form("patient_daily_log"):
        weight = st.number_input("Weight (kg)", min_value=30.0, max_value=200.0, value=73.8, step=0.1)
        temp = st.number_input("Temperature (°F)", min_value=95.0, max_value=106.0, value=98.6, step=0.1)
        
        sbp = st.number_input("Systolic BP (Top #)", min_value=70, max_value=220, value=120)
        dbp = st.number_input("Diastolic BP (Bottom #)", min_value=40, max_value=140, value=80)
        hr = st.number_input("Heart Rate (BPM)", min_value=30, max_value=200, value=72)

        symptoms = st.multiselect("Report New Symptoms:", [
            "Fever or Chills", 
            "Decreased urine output / Dark urine", 
            "Pain or tenderness over transplant site",
            "Swelling in feet, legs, or hands", 
            "Shortness of breath", 
            "Incision redness, warmth, or drainage"
        ])

        submitted = st.form_submit_button("Submit Daily Log", use_container_width=True)
        if submitted:
            new_log = {
                "patient_id": p_id,
                "patient_name": selected_patient_name,
                "timestamp": datetime.now(),
                "weight_kg": weight,
                "systolic_bp": sbp,
                "diastolic_bp": dbp,
                "heart_rate": hr,
                "temperature_f": temp,
                "symptoms": symptoms
            }
            vitals_col.insert_one(new_log)
            st.success(f"✅ Daily log successfully submitted for {selected_patient_name}!")

# =========================================================
# TAB 2: DOCTOR DASHBOARD (Multi-Patient Triage Roster)
# =========================================================
with tab_doctor:
    st.subheader("👨‍⚕️ Clinical Triage Roster")
    
    # Pull all distinct patient names
    patient_names = vitals_col.distinct("patient_name")
    
    if not patient_names:
        st.info("No patient logs found in MongoDB. Submit a record under 'Patient Entry'.")
    else:
        patient_summaries = []

        # Analyze each patient's latest status
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

            # 🔴 RED FLAGS
            if weight_change >= 1.5:
                red_flags.append(f"Weight Spike (+{weight_change:.1f}kg/24h)")
            if latest['temperature_f'] >= 100.0:
                red_flags.append(f"Fever ({latest['temperature_f']}°F)")
            if latest['systolic_bp'] > 150 or latest['systolic_bp'] < 100:
                red_flags.append(f"Abnormal BP ({latest['systolic_bp']}/{latest['diastolic_bp']})")
            if latest.get('symptoms'):
                red_flags.append(f"Symptoms ({', '.join(latest['symptoms'])})")

            # 🟡 AMBER FLAGS
            if latest['heart_rate'] > 100 or latest['heart_rate'] < 55:
                amber_flags.append(f"Abnormal HR ({latest['heart_rate']} BPM)")
            if 140 <= latest['systolic_bp'] <= 150:
                amber_flags.append(f"Borderline BP ({latest['systolic_bp']} Systolic)")

            # Assign Overall Status
            if red_flags:
                status = "🔴 RED ALERT"
                priority = 1
            elif amber_flags:
                status = "🟡 AMBER WATCH"
                priority = 2
            else:
                status = "🟢 GREEN STABLE"
                priority = 3

            patient_summaries.append({
                "patient_name": name,
                "patient_id": latest.get('patient_id', 'N/A'),
                "status": status,
                "priority": priority,
                "latest_time": latest['timestamp'],
                "red_flags": red_flags,
                "amber_flags": amber_flags,
                "latest_data": latest,
                "full_df": p_df,
                "weight_change": weight_change
            })

        # Sort roster by urgency (RED -> AMBER -> GREEN)
        patient_summaries.sort(key=lambda x: x['priority'])

        st.caption("Patients are automatically prioritized by risk level:")

        # Render Overview Banners
        for p in patient_summaries:
            banner_text = f"**{p['status']}** | **{p['patient_name']}** (ID: `{p['patient_id']}`)"
            
            if p['status'] == "🔴 RED ALERT":
                st.error(f"{banner_text}\n\n**Urgent Flags:** " + ", ".join(p['red_flags']))
            elif p['status'] == "🟡 AMBER WATCH":
                st.warning(f"{banner_text}\n\n**Watch Flags:** " + ", ".join(p['amber_flags']))
            else:
                st.success(f"{banner_text} — All vitals within normal range.")

        st.divider()

        # Drill-Down Patient Inspector
        st.subheader("🔍 Detailed Patient Inspector")
        inspect_name = st.selectbox(
            "Select a patient to inspect full vitals and historical charts:",
            options=[p['patient_name'] for p in patient_summaries]
        )

        selected_p = next(p for p in patient_summaries if p['patient_name'] == inspect_name)
        l_data = selected_p['latest_data']

        st.markdown(f"### Selected Profile: {selected_p['patient_name']}")
        st.caption(f"Last Logged: {l_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")

        # Metrics Grid
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Weight", f"{l_data['weight_kg']} kg", f"{selected_p['weight_change']:+.1f} kg")
        c2.metric("Temp", f"{l_data['temperature_f']} °F")
        c3.metric("BP", f"{l_data['systolic_bp']}/{l_data['diastolic_bp']}")
        c4.metric("Heart Rate", f"{l_data['heart_rate']} BPM")

        if l_data.get('symptoms'):
            st.error(f"🚨 **Reported Symptoms:** {', '.join(l_data['symptoms'])}")

        # Historical Trend Chart
        fig = px.line(
            selected_p['full_df'], x="timestamp", y="weight_kg",
            title=f"Fluid Retention Trend for {selected_p['patient_name']}",
            markers=True
        )
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

# =========================================================
# TAB 3: CLINICAL PROTOCOLS
# =========================================================
with tab_protocols:
    st.subheader("📋 Post-Transplant Standard Protocols")
    
    with st.expander("🔬 Lab Frequency & Drug Level Schedules", expanded=True):
        st.markdown("""
        * **Months 1–3:** Tacrolimus Trough 2–3x/wk (Target: 8–12 ng/mL); CBC/CMP 2–3x/wk; BKV/CMV Monthly.
        * **Months 4–6:** Tacrolimus Trough Bi-weekly (Target: 6–8 ng/mL); BKV/CMV Every 3 mos.
        * **Months 6–12:** Monthly labs; Donor-Specific Antibodies (DSA) & Renal US as indicated.
        """)

    with st.expander("🛡️ Infection Control & Food Safety Rules"):
        st.markdown("""
        * **Food Safety:** Strictly no grapefruit/starfruit/Seville oranges (interferes with Tacrolimus). No raw meats, unpasteurized dairy, or soft eggs.
        * **Infection Prevention:** Mask in crowded indoor settings for first 3–6 months. No live vaccines.
        """)

    with st.expander("🎗️ Cancer Screening Schedule"):
        st.markdown("""
        * **Dermatology:** Annual full-body skin exam (elevated skin cancer risk).
        * **Routine Screenings:** Annual mammogram (women ≥40), Colonoscopy (age ≥45), Annual Pap smear.
        """)
