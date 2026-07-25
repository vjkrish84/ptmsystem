import os
import certifi
import base64
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from pymongo import MongoClient
from datetime import datetime, date

# ---------------------------------------------------------
# 1. Compact, Responsive Page Config & Custom CSS
# ---------------------------------------------------------
st.set_page_config(
    page_title="Post-Transplant Portal",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    /* Compact Main Container */
    .stMainBlockContainer, .block-container {
        padding-top: 2rem !important;
        padding-bottom: 2rem !important;
        max-width: 1000px;
        margin: 0 auto;
    }
    
    /* Reduced Mobile & Web Typography */
    html, body, p, label, .stMarkdown, div {
        font-size: 0.92rem !important;
    }
    h1 { font-size: 1.6rem !important; margin-bottom: 0.5rem !important; }
    h2 { font-size: 1.3rem !important; }
    h3 { font-size: 1.1rem !important; }
    h4, h5 { font-size: 1.0rem !important; font-weight: 600 !important; }

    /* Compact Buttons & Input Heights */
    .stButton>button {
        width: 100%;
        min-height: 2.6rem !important;
        font-size: 0.95rem !important;
        font-weight: 600;
        border-radius: 6px;
    }
    .stNumberInput input, .stTextInput input, .stSelectbox div {
        font-size: 0.9rem !important;
    }

    /* Scaling Down Streamlit Metrics for Small Screens */
    [data-testid="stMetricValue"] {
        font-size: 1.25rem !important;
    }
    [data-testid="stMetricLabel"] {
        font-size: 0.8rem !important;
    }

    /* Chat Styling */
    .chat-doc {
        background-color: #eef6ff;
        border-left: 3px solid #0066cc;
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
        font-size: 0.88rem;
    }
    .chat-patient {
        background-color: #f4f4f4;
        border-left: 3px solid #28a745;
        padding: 8px 12px;
        border-radius: 6px;
        margin-bottom: 6px;
        font-size: 0.88rem;
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
# 4. Navigation & Role Selection
# ---------------------------------------------------------
st.title("🩺 Post-Transplant Portal")

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
    del st.session_state["submission_success"]

# =========================================================
# VIEW 1: PATIENT PORTAL
# =========================================================
if selected_role == "patient":
    
    with st.expander("🚨 EMERGENCY RED FLAGS (Click to Read)", expanded=False):
        st.error("""
        **GO TO THE NEAREST EMERGENCY ROOM IMMEDIATELY IF YOU HAVE:**  
        • Difficulty breathing or severe chest pain  
        • Uncontrollable bleeding or severe abdominal pain  
        • Seizures, sudden weakness, or slurred speech
        """)

    # --- PATIENT PROFILE SELECTOR ---
    existing_patients = vitals_col.distinct("patient_name")
    profile_options = ["➕ Create New Patient Profile"] + existing_patients if existing_patients else ["➕ Create New Patient Profile"]
    
    selected_option = st.selectbox(
        "👤 Select Profile:",
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

    st.markdown("<br/>", unsafe_allow_html=True)

    tab_checkin, tab_care_team = st.tabs([
        "📝 Daily Check-In", 
        "💬 Care Team & Safety Info"
    ])

    # --- TAB 1: DAILY CHECK-IN ---
    with tab_checkin:
        with st.form("patient_checkin_form"):
            st.markdown("#### Primary Daily Vitals")
            st.caption("💡 Tip: Draw blood labs before taking morning Tacrolimus dose.")

            c1, c2 = st.columns(2)
            weight = c1.number_input("Weight (kg)", value=70.0, step=0.1)
            temp = c2.number_input("Temp (°F)", value=98.6, step=0.1)

            c3, c4 = st.columns(2)
            sbp = c3.number_input("Systolic BP", value=120)
            dbp = c4.number_input("Diastolic BP", value=80)

            hr = st.number_input("Heart Rate (BPM)", value=72)

            symptoms = st.multiselect("Active Symptoms Today:", [
                "Low urine output", "Pain over transplant site", "Swelling hands/feet", 
                "Shortness of breath", "Blood in urine/stool", "Incision redness/leakage", 
                "Burning urination", "Nausea/Vomiting/Diarrhea"
            ])

            with st.expander("🧪 Labs & Transplant Details", expanded=is_new_patient):
                tx_date_input = st.date_input("Transplant Date", value=default_tx_date)
                creatinine = st.number_input("Creatinine (mg/dL)", value=1.1, step=0.1)
                tacrolimus = st.number_input("Tacrolimus Level (ng/mL)", value=8.5, step=0.5)
                bkv_load = st.number_input("BKV PCR Load (copies/mL)", value=0, step=100)
                dsa_status = st.selectbox("DSA Antibodies:", ["Negative", "Positive (Low MFI)", "Positive (High MFI)", "Pending"])
                uploaded_lab_file = st.file_uploader("Upload Lab Report:", type=["pdf", "png", "jpg", "jpeg"], key="lab_u")
            
            with st.expander("🖼️ Imaging & Diagnostic Scans (Optional)", expanded=False):
                us_result = st.text_input("Ultrasound Findings", value="Normal graft, RI=0.64")
                dxa_score = st.number_input("DXA T-Score", value=-0.8, step=0.1)
                colonoscopy_date = st.text_input("Colonoscopy Status", value="Cleared")
                cancer_screening = st.text_input("Cancer Screenings", value="Dermatology: Clear")
                uploaded_scan_file = st.file_uploader("Upload Scan Report:", type=["pdf", "png", "jpg", "jpeg"], key="scan_u")

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
                st.session_state["submission_success"] = f"✅ Check-in recorded for **{selected_patient_name.strip()}**!"
                st.rerun()

    # --- TAB 2: UNIFIED CARE TEAM CHAT & SAFETY RULES ---
    with tab_care_team:
        st.markdown("#### Care Team Messages")
        
        if is_new_patient:
            st.info("Select an existing patient profile above to view doctor communications.")
        else:
            patient_notifs = list(notifs_col.find({"patient_name": selected_patient_name}).sort("timestamp", -1))
            
            if not patient_notifs:
                st.write("✨ No active message threads with your care team.")
            else:
                for notif in patient_notifs:
                    severity = notif.get("severity", "Routine Advisory")
                    badge = "🔴" if severity == "Urgent Action Required" else ("🟡" if severity == "Follow-up Recommended" else "🟢")
                    
                    with st.expander(f"{badge} {severity} ({notif.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')})", expanded=True):
                        st.markdown(f"""
                        <div class="chat-doc">
                            <strong>👨‍⚕️ Care Team</strong> <em>({notif.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')})</em><br/>
                            {notif.get('message', '')}
                        </div>
                        """, unsafe_allow_html=True)
                        
                        for reply in notif.get("replies", []):
                            sender_icon = "📱" if reply.get("sender") == "patient" else "👨‍⚕️"
                            css_class = "chat-patient" if reply.get("sender") == "patient" else "chat-doc"
                            sender_title = selected_patient_name if reply.get("sender") == "patient" else "Doctor"
                            
                            st.markdown(f"""
                            <div class="{css_class}">
                                <strong>{sender_icon} {sender_title}</strong> <em>({reply.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')})</em><br/>
                                {reply.get('text', '')}
                            </div>
                            """, unsafe_allow_html=True)
                        
                        col_ack, col_reply = st.columns([1, 1])
                        with col_ack:
                            if notif.get("acknowledged"):
                                st.caption("✅ Acknowledged")
                            else:
                                if st.button("Confirm Read", key=f"ack_{notif['_id']}"):
                                    notifs_col.update_one({"_id": notif["_id"]}, {"$set": {"acknowledged": True, "ack_timestamp": datetime.now()}})
                                    st.rerun()

                        with col_reply:
                            with st.popover("💬 Reply"):
                                reply_text = st.text_area("Response:", key=f"p_reply_txt_{notif['_id']}")
                                if st.button("Send Reply", key=f"p_reply_btn_{notif['_id']}"):
                                    if reply_text.strip():
                                        reply_entry = {
                                            "sender": "patient",
                                            "author": selected_patient_name,
                                            "text": reply_text.strip(),
                                            "timestamp": datetime.now()
                                        }
                                        notifs_col.update_one({"_id": notif["_id"]}, {"$push": {"replies": reply_entry}})
                                        st.rerun()

        st.divider()

        with st.expander("📞 When to Call Coordinator", expanded=False):
            st.markdown("""
            • Noticeable drop in urine output or pain over graft site  
            • Fever ≥ 100.0°F or weight gain ≥ 1.5 kg in 24 hours  
            • Redness, swelling, or drainage at incision site
            """)

        with st.expander("🛡️ Vaccines & Diet Rules", expanded=False):
            st.write("**Safe Vaccines:** Flu Shot (Injected), Pneumonia, Tdap")
            st.write("**FORBIDDEN:** Live vaccines (MMR, Nasal FluMist, Yellow Fever)")
            st.write("**Diet:** Avoid Grapefruit, Pomegranate, NSAIDs (Ibuprofen/Advil), raw foods.")

# =========================================================
# VIEW 2: ACCORDION CLINICAL DASHBOARD (HORIZONTAL/COLLAPSIBLE)
# =========================================================
elif selected_role == "doctor":
    st.caption("⚠️ **Notice:** Decision-support tool only. Verify patient logs prior to taking clinical action.")

    patient_names = vitals_col.distinct("patient_name")

    if not patient_names:
        st.info("No patient records found.")
    else:
        # --- 1. PATIENT SELECTION DROPDOWN ---
        patient_summary_list = []
        patient_map = {}

        for name in patient_names:
            p_docs = list(vitals_col.find({"patient_name": name}).sort("timestamp", 1))
            if p_docs:
                latest = p_docs[-1]
                prev = p_docs[-2] if len(p_docs) > 1 else None
                red_flags, amber_flags, days_post_op = evaluate_clinical_alerts(latest, prev)
                
                status_icon = "🔴" if red_flags else ("🟡" if amber_flags else "🟢")
                label = f"{status_icon} {name} (ID: {latest.get('patient_id', 'N/A')})"
                patient_summary_list.append(label)
                patient_map[label] = {
                    "name": name,
                    "docs": p_docs,
                    "latest": latest,
                    "red_flags": red_flags,
                    "amber_flags": amber_flags,
                    "days_post_op": days_post_op
                }

        selected_label = st.selectbox("📋 Select Patient Record:", options=patient_summary_list)
        active_patient = patient_map[selected_label]
        
        p_name = active_patient["name"]
        p_docs = active_patient["docs"]
        latest = active_patient["latest"]
        red_flags = active_patient["red_flags"]
        amber_flags = active_patient["amber_flags"]
        days_post_op = active_patient["days_post_op"]

        # --- 2. HEADER SUMMARY CARDS ---
        st.divider()
        st.markdown(f"### {p_name} — Day {days_post_op} Post-Op")

        if red_flags:
            st.error("🚨 **CRITICAL:** " + " • ".join(red_flags))
        if amber_flags:
            st.warning("⚠️ **WATCH:** " + " • ".join(amber_flags))

        v1, v2, v3, v4, v5 = st.columns(5)
        v1.metric("Weight", f"{latest.get('weight_kg', 'N/A')} kg")
        v2.metric("BP", f"{latest.get('systolic_bp', 'N/A')}/{latest.get('diastolic_bp', 'N/A')}")
        v3.metric("Temp", f"{latest.get('temperature_f', 'N/A')} °F")
        v4.metric("Creatinine", f"{latest.get('creatinine', 'N/A')} mg/dL")
        v5.metric("Tacrolimus", f"{latest.get('tacrolimus', 'N/A')} ng/mL")

        st.markdown("<br/>", unsafe_allow_html=True)

        # --- 3. ACCORDION (COLLAPSIBLE HORIZONTAL EXPANDERS) ---
        
        # ACCORDION SECTION 1: OVERVIEW & LABS
        with st.expander("🩺 1. Primary Overview & Diagnostic Labs", expanded=True):
            c_left, c_right = st.columns(2)
            with c_left:
                st.markdown("##### 🧪 Lab Values")
                st.write(f"• **Creatinine:** {latest.get('creatinine', 'N/A')} mg/dL")
                st.write(f"• **Tacrolimus:** {latest.get('tacrolimus', 'N/A')} ng/mL")
                st.write(f"• **BKV Load:** {latest.get('bkv_load', '0')} copies/mL")
                st.write(f"• **DSA Antibodies:** {latest.get('dsa_status', 'N/A')}")
            
            with c_right:
                st.markdown("##### 🖼️ Imaging Status")
                st.write(f"• **Ultrasound:** {latest.get('us_findings', 'N/A')}")
                st.write(f"• **DXA T-Score:** {latest.get('dxa_score', 'N/A')}")
                st.write(f"• **Colonoscopy:** {latest.get('colonoscopy', 'N/A')}")

            reported_symptoms = latest.get("symptoms", [])
            if reported_symptoms:
                st.error(f"🚩 **Reported Symptoms:** {', '.join(reported_symptoms)}")

        # ACCORDION SECTION 2: PARAMETER TREND ANALYSIS
        with st.expander("📈 2. Parameter Trend Analysis", expanded=False):
            df_p = pd.DataFrame(p_docs)
            trend_param = st.selectbox(
                "Select Trend Metric:",
                ["creatinine", "tacrolimus", "weight_kg", "temperature_f", "systolic_bp"],
                key=f"trend_select_{p_name}"
            )

            if trend_param in df_p.columns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=df_p["timestamp"],
                    y=df_p[trend_param],
                    mode="lines+markers",
                    name=trend_param.capitalize(),
                    line=dict(color="#0066cc", width=2),
                    marker=dict(size=6)
                ))

                if trend_param == "creatinine":
                    fig.add_hline(y=1.8, line_dash="dash", line_color="red", annotation_text="High Limit (1.8)")
                elif trend_param == "tacrolimus":
                    fig.add_hline(y=12.0, line_dash="dash", line_color="red", annotation_text="High Bound (12.0)")
                    fig.add_hline(y=4.0, line_dash="dash", line_color="orange", annotation_text="Low Bound (4.0)")

                fig.update_layout(
                    height=280,
                    margin=dict(l=10, r=10, t=20, b=20),
                    xaxis_title="Date",
                    yaxis_title=trend_param.capitalize(),
                    template="plotly_white"
                )
                st.plotly_chart(fig, use_container_width=True)

        # ACCORDION SECTION 3: MESSAGES & ORDERS
        with st.expander("💬 3. Care Team Messaging & Orders", expanded=False):
            doc_notifs = list(notifs_col.find({"patient_name": p_name}).sort("timestamp", -1))
            
            with st.form(key=f"send_notif_form_{p_name}"):
                st.markdown("**New Clinical Instruction Thread:**")
                c_sev, c_txt = st.columns([1, 2])
                notif_severity = c_sev.selectbox("Priority:", ["Routine Advisory", "Follow-up Recommended", "Urgent Action Required"])
                notif_msg = c_txt.text_area("Message / Prescription Change:", placeholder="e.g. Please adjust Tacrolimus dose to 3mg daily.", height=70)
                
                if st.form_submit_button("Send Instruction Thread"):
                    if notif_msg.strip():
                        notif_doc = {
                            "patient_name": p_name,
                            "patient_id": latest.get("patient_id", "N/A"),
                            "doctor_name": "Transplant Attending",
                            "severity": notif_severity,
                            "message": notif_msg.strip(),
                            "timestamp": datetime.now(),
                            "acknowledged": False,
                            "replies": []
                        }
                        notifs_col.insert_one(notif_doc)
                        st.success("Instruction sent!")
                        st.rerun()

            st.markdown("##### Past Message Threads")
            if doc_notifs:
                for d_notif in doc_notifs:
                    ack_status = "✅ Read" if d_notif.get("acknowledged") else "⏳ Unread"
                    with st.expander(f"Thread: {d_notif.get('severity', 'Notice')} ({d_notif.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')}) - {ack_status}"):
                        st.markdown(f"""
                        <div class="chat-doc">
                            <strong>👨‍⚕️ You</strong> <em>({d_notif.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')})</em><br/>
                            {d_notif.get('message', '')}
                        </div>
                        """, unsafe_allow_html=True)

                        for r in d_notif.get("replies", []):
                            r_icon = "📱" if r.get("sender") == "patient" else "👨‍⚕️"
                            r_css = "chat-patient" if r.get("sender") == "patient" else "chat-doc"
                            r_author = p_name if r.get("sender") == "patient" else "Doctor"
                            st.markdown(f"""
                            <div class="{r_css}">
                                <strong>{r_icon} {r_author}</strong> <em>({r.get('timestamp', datetime.now()).strftime('%b %d, %H:%M')})</em><br/>
                                {r.get('text', '')}
                            </div>
                            """, unsafe_allow_html=True)
                        
                        with st.popover("💬 Reply"):
                            doc_reply_txt = st.text_area("Reply:", key=f"doc_reply_txt_{d_notif['_id']}")
                            if st.button("Send Reply", key=f"doc_reply_btn_{d_notif['_id']}"):
                                if doc_reply_txt.strip():
                                    r_doc = {
                                        "sender": "doctor",
                                        "author": "Transplant Attending",
                                        "text": doc_reply_txt.strip(),
                                        "timestamp": datetime.now()
                                    }
                                    notifs_col.update_one({"_id": d_notif["_id"]}, {"$push": {"replies": r_doc}})
                                    st.rerun()
            else:
                st.caption("No prior message threads.")

        # ACCORDION SECTION 4: ATTACHED REPORTS & SCANS
        with st.expander("📥 4. Attached Files & Reports", expanded=False):
            st.markdown("##### Downloadable Attachments")
            d1, d2 = st.columns(2)
            if latest.get("lab_file_base64"):
                d1.download_button("📄 Download Lab PDF", base64.b64decode(latest["lab_file_base64"]), file_name=latest.get("lab_file_name", "lab.pdf"), key=f"dl_lab_{p_name}")
            else:
                d1.caption("No lab PDF uploaded.")
                
            if latest.get("scan_file_base64"):
                d2.download_button("🖼️ Download Scan Image/PDF", base64.b64decode(latest["scan_file_base64"]), file_name=latest.get("scan_file_name", "scan.pdf"), key=f"dl_scan_{p_name}")
            else:
                d2.caption("No scan image uploaded.")
