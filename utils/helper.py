import urllib.parse
import traceback, os, shutil, csv
from dotenv import load_dotenv
from playwright.async_api import Page
import google.generativeai as genai
import asyncio, random
import platform, subprocess, ctypes
from urllib.parse import urlparse, parse_qs
import smtplib
from email.message import EmailMessage
import mimetypes
from config import config_input
from groq import Groq
import logging

# Logger
logger = logging.getLogger("spider")

# Load environment variables
load_dotenv()

# Create CSV file for simultinouly saveing scraping data
def create_csv_and_failed_load_urls_files(csv_file, failed_load_urls_file):
    """Create empty CSV files inside output/ directory."""
    os.makedirs("output", exist_ok=True)
    path = os.path.join("output", f"{csv_file}")
    with open(path, mode="w", newline='', encoding="utf-8"):
        pass
    with open(failed_load_urls_file, "w") as f:
        pass
    logger.info(f"Created fresh file: {path}")
    logger.info(f"Created fresh file: {failed_load_urls_file}")

# Load jobs id from previews 1,2,3 day ago processed jobs for avoid duplicate
def load_processed_jobs_id(filename=config_input.PROCESSED_JOBS_FILE_PATH):
    """Load job IDs from previously processed jobs file."""
    try:
        jobs_id = set()
        with open(filename, 'r') as f:
            for url in f:
                parsed_url = urlparse(url.strip())
                query_params = parse_qs(parsed_url.query)
                job_id = query_params.get("jk", [None])[0]
                if job_id:
                    jobs_id.add(job_id)
        logger.info(f"Loaded {len(jobs_id)} job IDs from {filename}")
        return jobs_id
    except Exception:
        logger.exception("Error loading job IDs")
        return set()

# Create a logs and debugging_screenshot folder for saveing spider and screenshots
def create_debugging_screenshots_folder(folder_path):
    """Recreate debugging/log folders from scratch."""
    try:
        if os.path.exists(folder_path):
            shutil.rmtree(folder_path)
            os.mkdir(folder_path)
            logger.info(f"Created new folder: {folder_path}")
    except Exception:
        logger.exception(f"Failed to create folder {folder_path}")

async def get_job_id(url: str) -> str | None:
    """Extract job_id from a LinkedIn job URL."""
    try:
        parsed_url = urllib.parse.urlparse(url)
        # path looks like: /jobs/view/4279496727/
        parts = parsed_url.path.strip("/").split("/")
        if "view" in parts:
            idx = parts.index("view")
            if idx + 1 < len(parts):
                return parts[idx + 1]
        return None
    except Exception:
        logger.exception("Error extracting job_id")
        return None
async def update_processed_jobs(links):
    """Append new processed jobs to the file."""
    try:
        with open(config_input.PROCESSED_JOBS_FILE_PATH, "a") as f:
            for link in links:
                f.write(f"{link}\n")
            f.flush()
        logger.info(f"Updated processed jobs with {len(links)} new links")
    except Exception:
        logger.exception("Failed to update processed jobs")

# # AI matching function
# genai.configure(api_key=os.getenv("GEMIMI_API_KEY"))
# async def get_match_percentage_from_gemini(prompt: str):
#     """Get match percentage using Gemini."""
#     try:
#         model = genai.GenerativeModel(config_input.gemini_model_version)
#         response = await asyncio.to_thread(model.generate_content, prompt)
#         return response.text.strip()
#     except Exception:
#         logger.exception("Error in get_match_percentage")
#         return None

# deepseek logicimport asyncio

async def get_match_percentage_from_groq(prompt):
    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    messages = [{"role": "user", "content": prompt}]
    
    try:
        loop = asyncio.get_event_loop()
        completion = await loop.run_in_executor(
            None,
            lambda: client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0,
                max_tokens=1024,
                top_p=1,
                stream=False
            )
        )

        response_text = completion.choices[0].message.content.strip()
        return response_text

    except Exception as e:
        print("\nError:", e)
        print(traceback.format_exc())
        return None



async def simulate_human_behavior(page: Page):
    """Simulate fast human-like behavior on a page."""
    await asyncio.sleep(random.uniform(0.1, 0.3))  # shorter delay
    scroll_amount = random.randint(50, 200)  # smaller scroll
    await page.mouse.wheel(0, scroll_amount)
    await asyncio.sleep(random.uniform(0.05, 0.2))  # minimal pause
    await page.mouse.move(
        random.randint(0, 800),
        random.randint(0, 600),
        steps=random.randint(2, 5)  # fewer steps, faster
    )
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(random.uniform(0.1, 0.5))  # quick final wait

class SleepBlocker:
    """Prevent system from sleeping during scraping."""

    def __init__(self):
        self.platform = platform.system()
        self.proc = None

    def prevent_sleep(self):
        try:
            if self.platform == "Windows":
                ES_CONTINUOUS = 0x80000000
                ES_SYSTEM_REQUIRED = 0x00000001
                ES_DISPLAY_REQUIRED = 0x00000002
                ctypes.windll.kernel32.SetThreadExecutionState(
                    ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
                )
            elif self.platform == "Darwin":
                self.proc = subprocess.Popen(["caffeinate"])
            elif self.platform == "Linux":
                self.proc = subprocess.Popen(["bash", "-c", "while true; do sleep 60; done"])
            else:
                logger.warning("Unsupported OS for sleep prevention")
        except Exception:
            logger.exception("Failed to prevent sleep")

    def allow_sleep(self):
        try:
            if self.platform == "Windows":
                ES_CONTINUOUS = 0x80000000
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
            elif self.platform in ["Darwin", "Linux"]:
                if self.proc:
                    self.proc.terminate()
                    self.proc = None
            else:
                logger.warning("Unsupported OS for allowing sleep")
        except Exception:
            logger.exception("Failed to allow sleep")

def clean_processed_jobs_file():
    """Keep only the last N lines in processed_jobs.txt."""
    try:
        with open(config_input.PROCESSED_JOBS_FILE_PATH, 'r') as f:
            urls = f.readlines()
        last_urls = urls[-8000:]
        with open(config_input.PROCESSED_JOBS_FILE_PATH, 'w') as f:
            f.writelines(last_urls)
        logger.info(f"Trimmed processed jobs file to last {len(last_urls)} entries")
    except Exception:
        logger.exception("Failed to clean processed jobs file")

def sort_csv_files_by_column(filename=config_input.CSV_FILE, sort_column_index=4):
    """Sort CSV files by a column in descending order."""
    encodings_to_try = ['utf-8', 'latin1', 'cp1252', 'utf-8-sig']

    filename = f"output/{filename}"
    rows, chosen_encoding = None, None

    for encoding in encodings_to_try:
        try:
            with open(filename, 'r', newline='', encoding=encoding) as f:
                rows = list(csv.reader(f))
            chosen_encoding = encoding
            logger.info(f"Read {filename} with {encoding} encoding")
            break
        except UnicodeDecodeError:
            continue
        except Exception:
            logger.warning(f"Error reading {filename} with {encoding}", exc_info=True)

    if not rows:
        logger.warning(f"Could not read {filename} or file is empty. Skipping.")

    try:
        int(rows[0][sort_column_index])
        has_header = False
    except (ValueError, IndexError):
        has_header = True

    header = rows[0] if has_header else None
    data = rows[1:] if has_header else rows

    try:
        data.sort(key=lambda row: int(row[sort_column_index]), reverse=True)
    except Exception:
        logger.warning(f"Sorting failed for {filename}, saving unsorted.", exc_info=True)

    try:
        with open(filename, 'w', newline='', encoding=chosen_encoding) as f:
            writer = csv.writer(f)
            if header:
                writer.writerow(header)
            writer.writerows(data)
        logger.info(f"Sorted and saved {filename}")
    except Exception:
        logger.exception(f"Failed to write sorted data for {filename}")

def send_debugging_screenshots_and_spider_log_email(folder_path="debugging_screenshots", log_file="logs/spider.log"):
    """Send debugging screenshots and spider.log via email."""
    sender = os.getenv("EMAIL_SENDER")
    password = os.getenv("EMAIL_PASSWORD")
    recipient = os.getenv("EMAIL_RECIPIENT")
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = int(os.getenv("SMTP_PORT", 587))

    if not all([sender, password, recipient, smtp_server]):
        logger.error("Missing one or more required .env values for email")
        return

    msg = EmailMessage()
    msg["Subject"] = "🪲 Debugging Files"
    msg["From"] = sender
    msg["To"] = recipient
    msg.set_content("Attached are the latest debugging screenshots and logs.")

    attached = 0

    # Attach screenshots
    if os.path.exists(folder_path):
        for filename in os.listdir(folder_path):
            filepath = os.path.join(folder_path, filename)
            if os.path.isfile(filepath) and filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                ctype, encoding = mimetypes.guess_type(filepath)
                if ctype is None or encoding is not None:
                    ctype = 'application/octet-stream'
                maintype, subtype = ctype.split('/', 1)
                with open(filepath, 'rb') as f:
                    msg.add_attachment(f.read(), maintype=maintype, subtype=subtype, filename=filename)
                    attached += 1
    else:
        logger.warning(f"Folder '{folder_path}' not found.")

    # Attach spider.log
    if os.path.exists(log_file):
        with open(log_file, "rb") as f:
            msg.add_attachment(f.read(), maintype="text", subtype="plain", filename=os.path.basename(log_file))
            attached += 1
    else:
        logger.warning(f"Log file '{log_file}' not found.")

    if attached == 0:
        logger.warning("No files found to attach.")
        return

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        logger.info(f"Email sent to {recipient} with {attached} attachments")
    except Exception:
        logger.exception("Failed to send debugging email")


def append_to_csv(file_name, rows):
        if not rows:
            return
        path = os.path.join("output", file_name)
        with open(path, mode="a", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

# === 3. Async wrapper ===
async def update_csv_with_new_jobs(file_name, rows):
    print(f"\nAppend rows: {len(rows)}")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: append_to_csv(file_name, rows))
    except Exception as e:
        logger.error(f"❌ Error saving to CSV: {e}")
    
# Save those urls which are failed to load
async def save_failed_url(url):
    with open(config_input.faild_to_load_urls_file, "a") as f:
        f.write(f"{url} \n")