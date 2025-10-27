# ========================================
# Gmail Mail Merge Tool - Modern UI Edition (Encoding Fix)
# ========================================
import streamlit as st
import pandas as pd
import base64
import time
import re
import json
import random
import os
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ========================================
# Streamlit Page Setup
# ========================================
st.set_page_config(page_title="Gmail Mail Merge", layout="wide")

# Sidebar
with st.sidebar:
    st.image("logo.png", width=180)
    st.markdown("---")
    st.markdown("### 📧 Gmail Mail Merge Tool")
    st.markdown("A powerful Gmail-based mail merge app with batch send, resume, and follow-up support.")
    st.markdown("---")
    st.markdown("**Quick Links:**")
    st.markdown("- 🏠 Home")
    st.markdown("- 🔁 New Run / Reset")
    st.markdown("- 🗂️ Merge History")
    st.markdown("---")
    st.caption("Developed with ❤️ by Ranjith")

# Main Header
st.markdown("<h1 style='text-align:center;'>📧 Gmail Mail Merge Tool</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align:center;color:gray;'>with Follow-up Replies, Draft Save & Resume Support</p>", unsafe_allow_html=True)
st.markdown("---")

# ========================================
# Gmail API Setup
# ========================================
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.compose",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["gmail"]["client_id"],
        "client_secret": st.secrets["gmail"]["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [st.secrets["gmail"]["redirect_uri"]],
    }
}

# ========================================
# Constants
# ========================================
DONE_FILE = "/tmp/mailmerge_done.json"
BATCH_SIZE_DEFAULT = 50

# ========================================
# Recovery Logic
# ========================================
if os.path.exists(DONE_FILE) and not st.session_state.get("done", False):
    try:
        with open(DONE_FILE, "r") as f:
            done_info = json.load(f)
        file_path = done_info.get("file")
        if file_path and os.path.exists(file_path):
            st.success("✅ Previous mail merge completed successfully.")
            st.download_button(
                "⬇️ Download Updated CSV",
                data=open(file_path, "rb"),
                file_name=os.path.basename(file_path),
                mime="text/csv",
            )
            if st.button("🔁 Reset for New Run"):
                os.remove(DONE_FILE)
                st.session_state.clear()
                st.experimental_rerun()
            st.stop()
    except Exception:
        pass

# ========================================
# Helpers
# ========================================
EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")

def extract_email(value: str):
    if not value:
        return None
    match = EMAIL_REGEX.search(str(value))
    return match.group(0) if match else None

def convert_bold(text):
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(
        r"\[(.*?)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" style="color:#1a73e8; text-decoration:underline;" target="_blank">\1</a>',
        text,
    )
    text = text.replace("\n", "<br>").replace("  ", "&nbsp;&nbsp;")
    return f"""
    <html><body style="font-family: 'Google Sans', Arial, sans-serif; font-size: 14px; line-height: 1.6;">
        {text}
    </body></html>
    """

def get_or_create_label(service, label_name="Mail Merge Sent"):
    try:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label["name"].lower() == label_name.lower():
                return label["id"]
        created_label = service.users().labels().create(
            userId="me",
            body={"name": label_name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
        ).execute()
        return created_label["id"]
    except Exception:
        return None

def send_email_backup(service, csv_path):
    try:
        user_email = service.users().getProfile(userId="me").execute()["emailAddress"]
        msg = MIMEMultipart()
        msg["To"] = user_email
        msg["From"] = user_email
        msg["Subject"] = f"📁 Mail Merge Backup CSV - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        msg.attach(MIMEText("Attached is the backup CSV for your mail merge run.", "plain"))
        with open(csv_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(csv_path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(csv_path)}"'
        msg.attach(part)
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        st.info(f"📧 Backup CSV emailed to {user_email}")
    except Exception as e:
        st.warning(f"⚠️ Could not send backup email: {e}")

def fetch_message_id_header(service, message_id):
    for _ in range(6):
        try:
            msg_detail = service.users().messages().get(
                userId="me", id=message_id, format="metadata", metadataHeaders=["Message-ID"]
            ).execute()
            headers = msg_detail.get("payload", {}).get("headers", [])
            for h in headers:
                if h.get("name", "").lower() == "message-id":
                    return h.get("value")
        except Exception:
            pass
        time.sleep(random.uniform(1, 2))
    return ""

# ========================================
# OAuth Flow
# ========================================
if "creds" not in st.session_state:
    st.session_state["creds"] = None

if st.session_state["creds"]:
    creds = Credentials.from_authorized_user_info(json.loads(st.session_state["creds"]), SCOPES)
else:
    code = st.experimental_get_query_params().get("code", None)
    if code:
        flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
        flow.redirect_uri = st.secrets["gmail"]["redirect_uri"]
        flow.fetch_token(code=code[0])
        creds = flow.credentials
        st.session_state["creds"] = creds.to_json()
        st.rerun()
    else:
        flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
        flow.redirect_uri = st.secrets["gmail"]["redirect_uri"]
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline", include_granted_scopes="true")
        st.markdown(f"### 🔑 Please [authorize the app]({auth_url}) to send emails using your Gmail account.")
        st.stop()

creds = Credentials.from_authorized_user_info(json.loads(st.session_state["creds"]), SCOPES)
service = build("gmail", "v1", credentials=creds)

# ========================================
# Session Setup
# ========================================
if "sending" not in st.session_state:
    st.session_state["sending"] = False
if "done" not in st.session_state:
    st.session_state["done"] = False

# ========================================
# MAIN UI
# ========================================
if not st.session_state["sending"]:
    st.subheader("📤 Step 1: Upload Recipient List")
    st.info("Upload up to **70–80 contacts** for smooth performance.")
    uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

    if uploaded_file:
        # --- FIX: Safe CSV reading with encoding fallback ---
        if uploaded_file.name.lower().endswith("csv"):
            try:
                df = pd.read_csv(uploaded_file, encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    uploaded_file.seek(0)
                    df = pd.read_csv(uploaded_file, encoding="latin1")
                except Exception:
                    st.error("⚠️ Unable to read the uploaded CSV. Please check that it's a valid CSV file.")
                    st.stop()
        else:
            df = pd.read_excel(uploaded_file)
        # -----------------------------------------------------

        for col in ["ThreadId", "RfcMessageId", "Status"]:
            if col not in df.columns:
                df[col] = ""

        st.info("📌 Tip: Include 'ThreadId' and 'RfcMessageId' for follow-ups if available.")
        st.markdown("### ✏️ Edit Your Contact List")
        df = st.data_editor(df, num_rows="dynamic", use_container_width=True)

        st.markdown("---")
        st.subheader("🧩 Step 2: Email Template")

        subject_template = st.text_input("✉️ Subject", "Hello {Name}")
        body_template = st.text_area(
            "📝 Body (Markdown + Variables like {Name})",
            """Dear {Name},

Welcome to **Mail Merge App** demo.

Thanks,  
**Your Company**""",
            height=250,
        )

        label_name = st.text_input("🏷️ Gmail label", "Mail Merge Sent")
        delay = st.slider("⏱️ Delay between emails (seconds)", 20, 75, 20)
        send_mode = st.radio("📬 Choose send mode", ["🆕 New Email", "↩️ Follow-up (Reply)", "💾 Save as Draft"])

        if not df.empty:
            preview_row = df.iloc[0]
            try:
                preview_subject = subject_template.format(**preview_row)
                preview_body = convert_bold(body_template.format(**preview_row))
            except Exception as e:
                preview_subject = subject_template
                preview_body = body_template
                st.warning(f"⚠️ Could not render preview: {e}")

            st.markdown("---")
            st.subheader("👀 Step 3: Preview (First Row)")
            st.markdown(f"**Subject:** {preview_subject}")
            st.markdown(preview_body, unsafe_allow_html=True)

        if st.button("🚀 Start Mail Merge"):
            df = df.reset_index(drop=True)
            df = df.fillna("")
            pending_indices = df.index[df["Status"] != "Sent"].tolist()

            st.session_state.update({
                "sending": True,
                "df": df,
                "pending_indices": pending_indices,
                "subject_template": subject_template,
                "body_template": body_template,
                "label_name": label_name,
                "delay": delay,
                "send_mode": send_mode
            })
            st.rerun()

# ========================================
# Sending Mode with Progress
# ========================================
if st.session_state["sending"]:
    df = st.session_state["df"]
    pending_indices = st.session_state["pending_indices"]
    subject_template = st.session_state["subject_template"]
    body_template = st.session_state["body_template"]
    label_name = st.session_state["label_name"]
    delay = st.session_state["delay"]
    send_mode = st.session_state["send_mode"]

    st.subheader("📨 Sending Emails...")
    progress = st.progress(0)
    status_box = st.empty()

    label_id = None
    if send_mode == "🆕 New Email":
        label_id = get_or_create_label(service, label_name)

    total = len(pending_indices)
    sent_count, skipped, errors = 0, [], []
    batch_count = 0
    sent_message_ids = []

    for i, idx in enumerate(pending_indices):
        if send_mode != "💾 Save as Draft" and batch_count >= BATCH_SIZE_DEFAULT:
            break
        row = df.loc[idx]

        pct = int(((i + 1) / total) * 100)
        progress.progress(min(max(pct, 0), 100))
        status_box.info(f"📩 Processing {i + 1}/{total}")

        to_addr = extract_email(str(row.get("Email", "")).strip())
        if not to_addr:
            skipped.append(row.get("Email"))
            df.loc[idx, "Status"] = "Skipped"
            continue

        try:
            subject = subject_template.format(**row)
            body_html = convert_bold(body_template.format(**row))
            message = MIMEText(body_html, "html")
            message["To"] = to_addr
            message["Subject"] = subject

            msg_body = {}
            if send_mode == "↩️ Follow-up (Reply)":
                thread_id = str(row.get("ThreadId", "")).strip()
                rfc_id = str(row.get("RfcMessageId", "")).strip()
                if thread_id and rfc_id:
                    message["In-Reply-To"] = rfc_id
                    message["References"] = rfc_id
                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    msg_body = {"raw": raw, "threadId": thread_id}
                else:
                    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                    msg_body = {"raw": raw}
            else:
                raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
                msg_body = {"raw": raw}

            if send_mode == "💾 Save as Draft":
                service.users().drafts().create(userId="me", body={"message": msg_body}).execute()
                df.loc[idx, "Status"] = "Draft"
            else:
                sent_msg = service.users().messages().send(userId="me", body=msg_body).execute()
                msg_id = sent_msg.get("id", "")
                df.loc[idx, "ThreadId"] = sent_msg.get("threadId", "")
                df.loc[idx, "RfcMessageId"] = fetch_message_id_header(service, msg_id) or msg_id
                df.loc[idx, "Status"] = "Sent"
                if send_mode == "🆕 New Email" and label_id:
                    sent_message_ids.append(msg_id)

            time.sleep(random.uniform(delay * 0.9, delay * 1.1))
            sent_count += 1
            batch_count += 1
        except Exception as e:
            df.loc[idx, "Status"] = "Error"
            errors.append((to_addr, str(e)))
            st.error(f"❌ Error for {to_addr}: {e}")

    # Label + Backup
    if send_mode != "💾 Save as Draft":
        if sent_message_ids and label_id:
            try:
                service.users().messages().batchModify(
                    userId="me",
                    body={"ids": sent_message_ids, "addLabelIds": [label_id]}
                ).execute()
            except Exception as e:
                st.warning(f"⚠️ Labeling failed: {e}")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_label = re.sub(r'[^A-Za-z0-9_-]', '_', label_name)
        file_name = f"Updated_{safe_label}_{timestamp}.csv"
        file_path = os.path.join("/tmp", file_name)
        df.to_csv(file_path, index=False)
        try:
            send_email_backup(service, file_path)
        except Exception as e:
            st.warning(f"⚠️ Backup email failed: {e}")

        with open(DONE_FILE, "w") as f:
            json.dump({"done_time": str(datetime.now()), "file": file_path}, f)

    st.session_state["sending"] = False
    st.session_state["done"] = True
    st.session_state["summary"] = {"sent": sent_count, "errors": errors, "skipped": skipped}
    st.rerun()

# ========================================
# Completion Summary
# ========================================
if st.session_state["done"]:
    summary = st.session_state.get("summary", {})
    st.subheader("✅ Mail Merge Completed")
    st.success(f"Sent: {summary.get('sent', 0)}")
    if summary.get("errors"):
        st.error(f"❌ {len(summary['errors'])} errors occurred.")
    if summary.get("skipped"):
        st.warning(f"⚠️ Skipped: {summary['skipped']}")
    if st.button("🔁 New Run / Reset"):
        if os.path.exists(DONE_FILE):
            os.remove(DONE_FILE)
        st.session_state.clear()
        st.experimental_rerun()
import streamlit as st
import pandas as pd
import base64
import time
import re
import json
import random
from datetime import datetime, timedelta
import pytz
from email.mime.text import MIMEText
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# ========================================
# Streamlit Page Setup
# ========================================
st.set_page_config(page_title="Gmail Mail Merge", layout="wide")
st.title("📧 Gmail Mail Merge Tool (with Follow-up Replies + Draft Save)")

# ========================================
# Gmail API Setup
# ========================================
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.compose",
]

CLIENT_CONFIG = {
    "web": {
        "client_id": st.secrets["gmail"]["client_id"],
        "client_secret": st.secrets["gmail"]["client_secret"],
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [st.secrets["gmail"]["redirect_uri"]],
    }
}

# ========================================
# Smart Email Extractor
# ========================================
EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")

def extract_email(value: str):
    if not value:
        return None
    match = EMAIL_REGEX.search(str(value))
    return match.group(0) if match else None

# ========================================
# Gmail Label Helper
# ========================================
def get_or_create_label(service, label_name="Mail Merge Sent"):
    try:
        labels = service.users().labels().list(userId="me").execute().get("labels", [])
        for label in labels:
            if label["name"].lower() == label_name.lower():
                return label["id"]

        label_obj = {
            "name": label_name,
            "labelListVisibility": "labelShow",
            "messageListVisibility": "show",
        }
        created_label = service.users().labels().create(userId="me", body=label_obj).execute()
        return created_label["id"]

    except Exception as e:
        st.warning(f"Could not get/create label: {e}")
        return None

# ========================================
# Bold + Link Converter (Verdana)
# ========================================
def convert_bold(text):
    if not text:
        return ""
    text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
    text = re.sub(
        r"\[(.*?)\]\((https?://[^\s)]+)\)",
        r'<a href="\2" style="color:#1a73e8; text-decoration:underline;" target="_blank">\1</a>',
        text,
    )
    text = text.replace("\n", "<br>").replace("  ", "&nbsp;&nbsp;")
    return f"""
    <html>
        <body style="font-family: Verdana, sans-serif; font-size: 14px; line-height: 1.6;">
            {text}
        </body>
    </html>
    """

# ========================================
# OAuth Flow
# ========================================
if "creds" not in st.session_state:
    st.session_state["creds"] = None

if st.session_state["creds"]:
    creds = Credentials.from_authorized_user_info(
        json.loads(st.session_state["creds"]), SCOPES
    )
else:
    code = st.experimental_get_query_params().get("code", None)
    if code:
        flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
        flow.redirect_uri = st.secrets["gmail"]["redirect_uri"]
        flow.fetch_token(code=code[0])
        creds = flow.credentials
        st.session_state["creds"] = creds.to_json()
        st.rerun()
    else:
        flow = Flow.from_client_config(CLIENT_CONFIG, scopes=SCOPES)
        flow.redirect_uri = st.secrets["gmail"]["redirect_uri"]
        auth_url, _ = flow.authorization_url(
            prompt="consent", access_type="offline", include_granted_scopes="true"
        )
        st.markdown(
            f"### 🔑 Please [authorize the app]({auth_url}) to send emails using your Gmail account."
        )
        st.stop()

# Build Gmail API client
creds = Credentials.from_authorized_user_info(json.loads(st.session_state["creds"]), SCOPES)
service = build("gmail", "v1", credentials=creds)

# ========================================
# Upload Recipients
# ========================================
st.header("📤 Upload Recipient List")
st.info("⚠️ Upload maximum of **70–80 contacts** for smooth operation and to protect your Gmail account.")

uploaded_file = st.file_uploader("Upload CSV or Excel file", type=["csv", "xlsx"])

if uploaded_file:
    if uploaded_file.name.endswith("csv"):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.write("✅ Preview of uploaded data:")
    st.dataframe(df.head())
    st.info("📌 Include 'ThreadId' and 'RfcMessageId' columns for follow-ups if needed.")

    # ========================================
    # Email Template
    # ========================================
    st.header("✍️ Compose Your Email")
    subject_template = st.text_input("Subject", "Hello {Name}")
    body_template = st.text_area(
        "Body (supports **bold**, [link](https://example.com), and line breaks)",
        """Dear {Name},

Welcome to our **Mail Merge App** demo.

You can add links like [Visit Google](https://google.com)
and preserve formatting exactly.

Thanks,  
**Your Company**""",
        height=250,
    )

    # ========================================
    # Preview Section
    # ========================================
    st.subheader("👁️ Preview Email")
    if not df.empty:
        recipient_options = df["Email"].astype(str).tolist()
        selected_email = st.selectbox("Select recipient to preview", recipient_options)
        try:
            preview_row = df[df["Email"] == selected_email].iloc[0]
            preview_subject = subject_template.format(**preview_row)
            preview_body = body_template.format(**preview_row)
            preview_html = convert_bold(preview_body)

            # Subject line preview in Verdana
            st.markdown(
                f'<span style="font-family: Verdana, sans-serif; font-size:16px;"><b>Subject:</b> {preview_subject}</span>',
                unsafe_allow_html=True
            )
            st.markdown("---")
            st.markdown(preview_html, unsafe_allow_html=True)
        except KeyError as e:
            st.error(f"⚠️ Missing column in data: {e}")

    # ========================================
    # Label & Timing Options
    # ========================================
    st.header("🏷️ Label & Timing Options")
    label_name = st.text_input("Gmail label to apply (new emails only)", value="Mail Merge Sent")

    delay = st.slider(
        "Delay between emails (seconds)",
        min_value=20,
        max_value=75,
        value=20,
        step=1,
        help="Minimum 20 seconds delay required for safe Gmail sending. Applies to New, Follow-up, and Draft modes."
    )

    # ========================================
    # ✅ "Ready to Send" Button + ETA (All Modes)
    # ========================================
    eta_ready = st.button("🕒 Ready to Send / Calculate ETA")

    if eta_ready:
        try:
            total_contacts = len(df)
            avg_delay = delay
            total_seconds = total_contacts * avg_delay
            total_minutes = total_seconds / 60

            # Local timezone
            local_tz = pytz.timezone("Asia/Kolkata")  # change if needed
            now_local = datetime.now(local_tz)
            eta_start = now_local
            eta_end = now_local + timedelta(seconds=total_seconds)

            eta_start_str = eta_start.strftime("%I:%M %p")
            eta_end_str = eta_end.strftime("%I:%M %p")

            st.success(
                f"📋 Total Recipients: {total_contacts}\n\n"
                f"⏳ Estimated Duration: {total_minutes:.1f} min (±10%)\n\n"
                f"🕒 ETA Window: **{eta_start_str} – {eta_end_str}** (Local Time)\n\n"
                f"✅ Applies to all send modes: New, Follow-up, Draft"
            )
        except Exception as e:
            st.warning(f"ETA calculation failed: {e}")

    # ========================================
    # Send Mode (with Save Draft)
    # ========================================
    send_mode = st.radio(
        "Choose sending mode",
        ["🆕 New Email", "↩️ Follow-up (Reply)", "💾 Save as Draft"]
    )

    # ========================================
    # Main Send/Draft Button
    # ========================================
    if st.button("🚀 Send Emails / Save Drafts"):
        label_id = get_or_create_label(service, label_name)
        sent_count = 0
        skipped, errors = [], []

        with st.spinner("📨 Processing emails... please wait."):
            if "ThreadId" not in df.columns:
                df["ThreadId"] = None
            if "RfcMessageId" not in df.columns:
                df["RfcMessageId"] = None

            for idx, row in df.iterrows():
                to_addr = extract_email(str(row.get("Email", "")).strip())
                if not to_addr:
                    skipped.append(row.get("Email"))
                    continue

                try:
                    subject = subject_template.format(**row)
                    body_html = convert_bold(body_template.format(**row))
                    message = MIMEText(body_html, "html")
                    message["To"] = to_addr
                    message["Subject"] = subject

                    msg_body = {}

                    # ===== Follow-up (Reply) mode =====
                    if send_mode == "↩️ Follow-up (Reply)" and "ThreadId" in row and "RfcMessageId" in row:
                        thread_id = str(row["ThreadId"]).strip()
                        rfc_id = str(row["RfcMessageId"]).strip()

                        if thread_id and thread_id.lower() != "nan" and rfc_id:
                            message["In-Reply-To"] = rfc_id
                            message["References"] = rfc_id
                            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
                            msg_body = {"raw": raw, "threadId": thread_id}
                        else:
                            raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
                            msg_body = {"raw": raw}
                    else:
                        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
                        msg_body = {"raw": raw}

                    # ===============================
                    # ✉️ Send or Save as Draft
                    # ===============================
                    if send_mode == "💾 Save as Draft":
                        draft = service.users().drafts().create(userId="me", body={"message": msg_body}).execute()
                        sent_msg = draft.get("message", {})
                        st.info(f"📝 Draft saved for {to_addr}")
                    else:
                        sent_msg = service.users().messages().send(userId="me", body=msg_body).execute()

                    # 🕒 Delay between operations
                    if delay > 0:
                        time.sleep(random.uniform(delay * 0.9, delay * 1.1))

                    # ✅ RFC Message-ID Fetch
                    message_id_header = None
                    for attempt in range(5):
                        time.sleep(random.uniform(2, 4))
                        try:
                            msg_detail = service.users().messages().get(
                                userId="me",
                                id=sent_msg.get("id", ""),
                                format="metadata",
                                metadataHeaders=["Message-ID"],
                            ).execute()

                            headers = msg_detail.get("payload", {}).get("headers", [])
                            for h in headers:
                                if h.get("name", "").lower() == "message-id":
                                    message_id_header = h.get("value")
                                    break
                            if message_id_header:
                                break
                        except Exception:
                            continue

                    # 🏷️ Apply label to new emails
                    if send_mode == "🆕 New Email" and label_id and sent_msg.get("id"):
                        success = False
                        for attempt in range(3):
                            try:
                                service.users().messages().modify(
                                    userId="me",
                                    id=sent_msg["id"],
                                    body={"addLabelIds": [label_id]},
                                ).execute()
                                success = True
                                break
                            except Exception:
                                time.sleep(1)
                        if not success:
                            st.warning(f"⚠️ Could not apply label to {to_addr}")

                    df.loc[idx, "ThreadId"] = sent_msg.get("threadId", "")
                    df.loc[idx, "RfcMessageId"] = message_id_header or ""

                    sent_count += 1

                except Exception as e:
                    errors.append((to_addr, str(e)))

        # ========================================
        # Summary
        # ========================================
        if send_mode == "💾 Save as Draft":
            st.success(f"📝 Saved {sent_count} draft(s) to your Gmail Drafts folder.")
        else:
            st.success(f"✅ Successfully processed {sent_count} emails.")

        if skipped:
            st.warning(f"⚠️ Skipped {len(skipped)} invalid emails: {skipped}")
        if errors:
            st.error(f"❌ Failed to process {len(errors)}: {errors}")

        # ========================================
        # CSV Download only for New Email mode
        # ========================================
        if send_mode == "🆕 New Email":
            csv = df.to_csv(index=False).encode("utf-8")
            safe_label = re.sub(r'[^A-Za-z0-9_-]', '_', label_name)
            file_name = f"{safe_label}.csv"

            # Visible download button
            st.download_button(
                "⬇️ Download Updated CSV (Click if not auto-downloaded)",
                csv,
                file_name,
                "text/csv",
                key="manual_download"
            )

            # Auto-download via hidden link
            b64 = base64.b64encode(csv).decode()
            st.markdown(
                f'''
                <a id="auto-download-link" href="data:file/csv;base64,{b64}" download="{file_name}"></a>
                <script>
                    document.getElementById("auto-download-link").click();
                </script>
                ''',
                unsafe_allow_html=True
            )
