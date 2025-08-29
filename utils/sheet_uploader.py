import os, csv
import asyncio
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from config import config_input
import logging

# Logger
logger = logging.getLogger("spider")

# === 2. Append new job entries to corresponding CSVs ===
def _append_jobs(easy_applies, cs_applies, c_applies):
    def append_to_csv(file_name, rows):
        if not rows:
            return
        path = os.path.join("output", file_name)
        with open(path, mode="a", newline='', encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)

    append_to_csv("Easy_applies.csv", easy_applies)
    append_to_csv("CS_applies.csv", cs_applies)
    append_to_csv("Confirmation_applies.csv", c_applies)
    logger.info("✔ Saved in CSV files.")

# === 3. Async wrapper ===
async def jobs_append_to_csv(easy_applies, cs_applies, c_applies):
    print(f"\nEasy: {len(easy_applies)}, CS: {len(cs_applies)}, C: {len(c_applies)}")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, lambda: _append_jobs(easy_applies, cs_applies, c_applies))
    except Exception as e:
        logger.error(f"❌ Error saving to CSV: {e}")


# After complete scraping, sort rows descending by Matching % column and append to Google Sheet

def update_google_sheets_from_csv(file=config_input.CSV_FILE):
    # 🔐 Google Sheets credentials
    base_dir = os.path.dirname(__file__)
    creds_path = os.path.join(base_dir, "gs_credentials.json")
    workbook_id = config_input.WORKBOOK_ID
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]

    # ✅ Auth & connect
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    client = gspread.authorize(creds)
    workbook = client.open_by_key(workbook_id)

    encodings_to_try = ['utf-8', 'utf-8-sig', 'latin1', 'cp1252']

    # 📄 file in output/
    file_name = file
    file_path = os.path.join("output", file_name)
    sheet_name = os.path.splitext(file_name)[0]  # "Easy_applies.csv" → "Easy_applies"

    try:
        worksheet = workbook.worksheet(sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        logger.warning(f"⚠️ Sheet '{sheet_name}' not found. Creating a new one...")
        worksheet = workbook.add_worksheet(title=sheet_name, rows="1000", cols="20")


    rows = []
    for encoding in encodings_to_try:
        try:
            with open(file_path, 'r', newline='', encoding=encoding) as f:
                reader = csv.reader(f)
                rows = [row for row in reader if any(row)]
            break
        except Exception as e:
            print(f"Error to reading")


    if not rows:
        print(f"⚠️ Could not read or file is empty: {file_path}. Skipping.")


    # Remove header if already present in sheet
    try:
        header = rows[0]
        data = rows[1:] if len(rows) > 1 else []
    except Exception as e:
        logger.error(f"⚠️ Failed to process rows from {file_path}: {e}")

    try:
        # Step 1: Get next empty row in column A
        next_empty_row = len(worksheet.get_all_values()) + 1
        range_start = f"A{next_empty_row}"

        # Step 2: Prepare pre-header rows
        now = datetime.now()
        today_str = f"{now.month}/{now.day}/{now.year}"  # Always gives e.g., 8/7/2025
        pre_rows = [[""], [""], [today_str, sheet_name]]  # Two blank rows, one metadata row

        # Step 3: Combine all rows
        all_rows = pre_rows + data

        # Step 4: Upload starting from column A
        worksheet.update(range_start, all_rows, value_input_option="RAW")
        print(f"✅ Appended {len(data)} rows to '{sheet_name}' from column A with header")
    except Exception as e:
        logger.error(f"❌ Failed to append to '{sheet_name}': {e}")


