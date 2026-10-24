import streamlit as st
import json
import re
from pdf_parser import extract_text
from prompts import build_prompt
from gemma_agent import analyze_spending

# --- Configuration ---
st.set_page_config(page_title="Spending Analyzer", page_icon="💰", layout="wide")


def clean_json_response(raw_text):
    """Removes markdown formatting if Gemma returns it."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n", "", text)
        text = re.sub(r"\n```$", "", text)
    return json.loads(text)


st.title("💰 Spending Analyzer")
st.write("Upload a bank statement to pinpoint weaknesses and suggest cutbacks.")

uploaded_file = st.file_uploader("Upload your bank statement (PDF)", type=["pdf"])

if uploaded_file is not None:
    if st.button("Analyze my spending", type="primary"):
        with st.status("Analyzing...", expanded=True) as status:
            
            st.write("⏳ Extracting text from PDF...")
            uploaded_file.seek(0) # Reset file pointer before reading
            pdf_text = extract_text(uploaded_file)

            st.write(f"Characters extracted: {len(pdf_text)}")
            
            # Debug expander to verify text extraction
            with st.expander("DEBUG: View Extracted PDF Text"):
                st.write(pdf_text if pdf_text.strip() else "NO TEXT EXTRACTED. The PDF might be a scanned image.")

            if not pdf_text.strip():
                status.update(label="Failed to read PDF.", state="error")
                st.stop()

            st.write("⏳ Building instructions for AI...")
            prompt = build_prompt(pdf_text)
            
            st.write("⏳ Asking Gemma 4 (This may take a moment)...")
            raw_response = analyze_spending(prompt)

            if ("Traceback" in raw_response or "API Error" in raw_response or "INTERNAL" in raw_response or "Error initializing" in raw_response):
                st.error(raw_response)
                st.stop()

            try:
                report_data = clean_json_response(raw_response)
                status.update(label="Analysis complete!", state="complete", expanded=False)
            
            except json.JSONDecodeError:
                status.update(label="AI returned invalid data format.", state="error")
                st.error("Raw Output:")
                st.write(raw_response)
                st.stop()

        # --- Dashboard ---
        st.divider()
        st.header("Your Analysis")
        
        summary = report_data.get("summary", {})
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Spent", f"{summary.get('currency', '£')}{summary.get('total_spent', 0)}")
        col2.metric("Total Income", f"{summary.get('currency', '£')}{summary.get('total_income', 0)}")
        col3.metric("Period", summary.get("period", "Unknown"))

        tab1, tab2, tab3 = st.tabs(["Actionable Tips", "Subscriptions", "Transactions"])
        
        with tab1:
            st.subheader("Category Breakdown & Tips")
            for cat in report_data.get("categories", []):
                # FIXED: Put it all on one line and use a dash instead of a newline
                with st.expander(f"{cat.get('name')} - {summary.get('currency', '£')}{cat.get('total', 0)}"):
                    for tip in cat.get("tips", []):
                        st.markdown(f"- {tip}")

        with tab2:
            st.subheader("Detected Subscriptions")
            subs = report_data.get("subscriptions", [])
            if subs:
                st.dataframe(subs, width="stretch")
            else:
                st.info("No recurring subscriptions detected.")

        with tab3:
            st.subheader("Raw Extracted Transactions")
            txns = report_data.get("transactions", [])
            if txns:
                st.dataframe(txns, width="stretch")
            else:
                st.info("No transactions found.")