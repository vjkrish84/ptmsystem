import os
import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime

# ---------------------------------------------------------
# 1. Mobile-Optimized Page Configuration
# ---------------------------------------------------------
st.set_page_config(
    page_title="Transplant Care Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"  # Collapses sidebar for small phone screens
)

# ---------------------------------------------------------
# 2. Database Connection
# ---------------------------------------------------------
@st.cache_resource
def init_connection():
    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        st.error("⚠️ MONGO_URI environment variable is missing. Check Streamlit Cloud Secrets.")
        st.stop()
    return MongoClient(mongo_uri)

client = init_connection()
db = client["transplant_portal"]
vitals_col = db["vitals_logs"]

patient_id = "PT-9042"

# Header
st.title("🩺 Transplant Care Portal")

# Top Navigation Tabs
tab_patient, tab_doctor, tab_protocols = st.tabs([
    "📱 Patient Entry", 
    "👨‍⚕️ Doctor Dashboard", 
    "📚 Clinical Protocols"
])

# =========================================================
# TAB 1: PATIENT DAILY ENTRY
# =========================================================
with tab_patient:
    st.subheader("Record Today's Vitals")
    st.caption("Submit your morning vitals before taking morning immunosuppressive medications.")
    
    with st.form("patient_daily_log"):
        weight = st.number_input("Weight (kg)", min_value=30.0, max_value=200.0, value=73.8, step=0.1)
        temp = st.number_input("Temperature (°F)", min_value=95.0, max_value=106.0, value=100.4, step=0.1)
        
        sbp = st.number_input("Systolic BP (Top Number)", min_value=70, max_value=220, value=155)
        dbp = st.number_input("Diastolic BP (Bottom Number)", min_value=40, max_value=140, value=95)
        hr = st.number_input("Heart Rate (BPM)", min_value=30, max_value=200, value=104)

        symptoms = st.multiselect("Report Any New Symptoms:", [
            "Fever or Chills", 
            "Decreased urine output / Dark urine", 
            "Pain or tenderness over transplant site",
            "Swelling in feet, legs, or hands", 
            "Shortness of breath", 
            "Incision redness, warmth, or drainage",
            "Nausea / Vomiting / Diarrhea"
        ])

        submitted = st.form_submit_button("Submit Daily Log", use_container_width=True)
        if submitted:
            new_log = {
                "patient_id": patient_id,
                "patient_name": "Sarah Connor",
                "discharge_date": "2026-06-01",
                "timestamp": datetime.now(),
                "weight_kg": weight,
                "systolic_bp": sbp,
                "diastolic_bp": dbp,
                "heart_rate": hr,
                "temperature_f": temp,
                "symptoms": symptoms
            }
            vitals_col.insert_one(new_log)
            st.success("✅ Daily log submitted successfully to your Transplant Coordinator!")

# =========================================================
# TAB 2: DOCTOR CLINICAL DASHBOARD
# =========================================================
with tab_doctor:
    st.subheader("👨‍⚕️ Clinical Triage & Monitoring")
    
    # Fetch logs from MongoDB
    docs = list(vitals_col.find({"patient_id": patient_id}).sort("timestamp", 1))
    
    if not docs:
        st.info("No logs recorded yet. Use the 'Patient Entry' tab to submit a record.")
    else:
        df = pd.DataFrame(docs)
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest
        weight_change_24h = latest['weight_kg'] - prev['weight_kg']

        # Clinical Triage & Alert Thresholds
        red_flags = []
        if weight_change_24h >= 1.5:
            red_flags.append(f"⚠️ **Fluid Retention / Rejection Risk**: Gained +{weight_change_24h:.1f} kg in 24h (Threshold: ≥1.5 kg)")
        if latest['temperature_f'] >= 100.0:
            red_flags.append(f"🔥 **Fever / Infection Risk**: {latest['temperature_f']}°F (Threshold: ≥100.0°F)")
        if latest['systolic_bp'] > 150 or latest['systolic_bp'] < 100:
            red_flags.append(f"🫀 **Abnormal BP**: {latest['systolic_bp']}/{latest['diastolic_bp']} mmHg (Normal: 100-150 Systolic)")
        if latest['heart_rate'] > 100 or latest['heart_rate'] < 55:
            red_flags.append(f"💓 **Abnormal HR**: {latest['heart_rate']} BPM (Normal: 55-100 BPM)")
        if latest.get('symptoms'):
            red_flags.append(f"🚨 **Reported Symptoms**: {', '.join(latest['symptoms'])}")

        # Red-Flag Banner Display
        if red_flags:
            st.error("### 🚨 URGENT CLINICAL ALERTS TRIGGERED")
            for flag in red_flags:
                st.markdown(f"- {flag}")
        else:
            st.success("✅ Patient is stable. No active red flags.")

        st.divider()
        st.markdown(f"**Patient:** {latest['patient_name']} | **ID:** `{patient_id}` | **Discharge:** {latest.get('discharge_date', 'N/A')}")

        # Metrics 2x2 Grid (Phone Friendly)
        c1, c2 = st.columns(2)
        c1.metric("Weight", f"{latest['weight_kg']} kg", f"{weight_change_24h:+.1f} kg (24h)")
        c2.metric("Temp", f"{latest['temperature_f']} °F")
        
        c3, c4 = st.columns(2)
        c3.metric("Blood Pressure", f"{latest['systolic_bp']}/{latest['diastolic_bp']}")
        c4.metric("Heart Rate", f"{latest['heart_rate']} BPM")

        st.divider()

        # Weight Trend Graph (Fluid Retention Tracker)
        fig = px.line(
            df, x="timestamp", y="weight_kg", 
            title="Weight Log Trend (Fluid Retention Monitoring)", 
            markers=True
        )
        fig.update_layout(margin=dict(l=10, r=10, t=30, b=10))
        st.plotly_chart(fig, use_container_width=True)

# =========================================================
# TAB 3: CLINICAL PROTOCOLS & REFERENCE
# =========================================================
with tab_protocols:
    st.subheader("📋 Post-Transplant Standard Protocols")
    st.caption("Nephrology protocol reference sheet for clinical guidelines & patient management.")

    with st.expander("🔬 Lab Frequency & Drug Level Schedules", expanded=True):
        st.markdown("""
        * **Months 1–3 Post-Transplant:**
          * **Tacrolimus / Cyclosporine Trough:** 2–3x weekly (Target Tacrolimus Level: 8–12 ng/mL)
          * **CBC & CMP:** 2–3x weekly
          * **BK Virus NAT & CMV PCR:** Monthly
        * **Months 4–6 Post-Transplant:**
          * **Tacrolimus Trough:** Every 2 weeks (Target Tacrolimus Level: 6–8 ng/mL)
          * **BK Virus NAT & CMV PCR:** Every 3 months
        * **Months 6–12 Post-Transplant:**
          * **Labs & Drug Levels:** Monthly
          * **Donor-Specific Antibodies (DSA) & Renal US:** As clinically indicated or at 12-month protocol mark.
        """)

    with st.expander("🛡️ Infection Control & Food Safety Rules"):
        st.markdown("""
        * **Food Safety Guidelines:**
          * **STRICTLY AVOID:** Grapefruit, Seville oranges, and starfruit (P-glycoprotein / CYP3A4 inhibitors that elevate Tacrolimus toxicity).
          * **No raw/undercooked items:** Raw sushi, unpasteurized cheese, deli meats (unless heated), soft-boiled eggs.
          * Tap water must be from a municipal source or boiled during initial 3 months.
        * **Infection Prevention:**
          * Wear N95 mask in enclosed public spaces for the first 3 to 6 months.
          * No live vaccines (e.g., MMR, Varicella, Yellow Fever) for transplant recipient or close household contacts.
        """)

    with st.expander("🎗️ Long-Term Preventive & Cancer Screening Schedule"):
        st.markdown("""
        * **Dermatology:** Annual full-body skin exam starting at Month 6 (elevated risk of Squamous Cell Carcinoma due to immunosuppression).
        * **Routine Cancer Screenings:**
          * **Mammogram:** Annually for female recipients ≥40 years old.
          * **Colonoscopy:** Every 10 years (or per risk history) starting at age 45.
          * **Pap Smear:** Annually for female recipients.
        * **Bone Health:** DEXA scan at baseline and every 1–2 years to monitor post-transplant steroid-induced osteoporosis.
        """)