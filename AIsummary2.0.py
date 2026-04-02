import re
import requests
import time
from io import BytesIO
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from google import genai
import os
from dotenv import load_dotenv
import urllib3
from requests.exceptions import SSLError, ConnectionError, Timeout

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================
# LOAD ENVIRONMENT VARIABLES
# ==============================
load_dotenv()


def get_next_gemini_key():
    global CURRENT_GEMINI_KEY_INDEX
    key = GEMINI_API_KEYS[CURRENT_GEMINI_KEY_INDEX]
    CURRENT_GEMINI_KEY_INDEX = (CURRENT_GEMINI_KEY_INDEX + 1) % len(GEMINI_API_KEYS)
    return key.strip()


# ==============================
# CONFIGURATION
# ==============================

# Use environment variables for API keys
OCR_API_KEY = os.getenv("OCR_API_KEY")
GEMINI_API_KEYS = os.getenv("GEMINI_API_KEYS", "").split(",")
CURRENT_GEMINI_KEY_INDEX = 0

# Validate API keys are present
if not OCR_API_KEY or not GEMINI_API_KEYS:
    raise ValueError("Missing API keys. Set OCR_API_KEY and GEMINI_API_KEY environment variables.")

INPUT_MD = "Sample.md"
OCR_OUTPUT = "NotiPDF.txt"  # Keeping for backward compatibility but not required

RECORD_FILE = "processed_pdfs.txt"  # Tracks downloaded PDFs
SUMMARY_RECORD_FILE = "processed_summaries.txt"  # Tracks generated summaries
FAILED_PDFS_FILE = "failed_pdfs.txt"  # New file to track failed downloads
OCR_FOLDER = "OCR-PDF-TXT"
SUMMARY_FOLDER = "Summaries"  # New folder for summary files

MODEL = "gemini-2.5-flash"

OCR_ENGINES = [2, 1, 3]
RETRY_LIMIT = 3
REQUEST_DELAY = 3  # Increased from 2
CHUNK_SIZE = 15000
DOWNLOAD_RETRY_LIMIT = 5  # Increased from 3
DOWNLOAD_TIMEOUT = 180  # Increased from 120 (3 minutes)

# ==============================
# GEMINI CLIENT
# ==============================

client = genai.Client(api_key=GEMINI_API_KEYS[0])


# ==============================
# CREATE SESSION FOR BETTER CONNECTION HANDLING
# ==============================

def create_session():
    """Create a requests session with custom settings"""
    session = requests.Session()

    # Configure session with custom adapters
    adapter = requests.adapters.HTTPAdapter(
        max_retries=3,
        pool_connections=10,
        pool_maxsize=10,
        pool_block=False
    )

    session.mount('http://', adapter)
    session.mount('https://', adapter)

    return session


# ==============================
# CREATE FOLDERS IF NOT EXISTS
# ==============================

def ensure_folders():
    """Create required folders if they don't exist"""
    for folder in [OCR_FOLDER, SUMMARY_FOLDER]:
        if not os.path.exists(folder):
            os.makedirs(folder)
            print(f"Created folder: {folder}")


# ==============================
# SANITIZE FILENAME
# ==============================

def sanitize_filename(filename):
    """Remove invalid characters for cross-platform filenames"""
    # Replace invalid characters with underscore
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    # Trim and limit length
    return sanitized[:100].strip()


# ==============================
# LOAD PROCESSED PDF RECORD
# ==============================

def load_processed_pdfs():
    if not os.path.exists(RECORD_FILE):
        return set()
    with open(RECORD_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_processed_pdf(url):
    with open(RECORD_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


# ==============================
# LOAD PROCESSED SUMMARY RECORD
# ==============================

def load_processed_summaries():
    """Track which job serials have been summarized"""
    if not os.path.exists(SUMMARY_RECORD_FILE):
        return set()
    with open(SUMMARY_RECORD_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_processed_summary(serial):
    """Mark a job as summarized"""
    with open(SUMMARY_RECORD_FILE, "a", encoding="utf-8") as f:
        f.write(str(serial) + "\n")


# ==============================
# TRACK FAILED DOWNLOADS
# ==============================

def log_failed_download(serial, title, url, error):
    """Log failed PDF downloads for later retry"""
    with open(FAILED_PDFS_FILE, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"{timestamp}\t{serial}\t{title}\t{url}\t{error}\n")


# ==============================
# VERIFY PROCESSED FILES
# ==============================

def verify_processed_files():
    """Check if all processed PDFs have corresponding OCR files and fix inconsistencies"""
    if not os.path.exists(RECORD_FILE):
        return

    processed_pdfs = load_processed_pdfs()
    fixed_records = []
    corrupted_records = []

    # Create a backup of the original file
    if os.path.exists(RECORD_FILE):
        backup_file = f"{RECORD_FILE}.backup"
        import shutil
        shutil.copy2(RECORD_FILE, backup_file)
        print(f"Created backup of processed PDFs: {backup_file}")

    # Check each URL and find corresponding OCR files
    for url in processed_pdfs:
        found = False
        # Look for any OCR file that might correspond to this URL
        if os.path.exists(OCR_FOLDER):
            for filename in os.listdir(OCR_FOLDER):
                if filename.endswith("-PDF.txt"):
                    filepath = os.path.join(OCR_FOLDER, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read()
                            # Check if URL appears in the file header
                            if url in content:
                                found = True
                                fixed_records.append(url)
                                break
                    except:
                        continue

        if found:
            fixed_records.append(url)
        else:
            corrupted_records.append(url)

    # Rewrite the processed PDFs file with only valid records
    if corrupted_records:
        print(f"Found {len(corrupted_records)} corrupted records. Fixing...")
        with open(RECORD_FILE, "w", encoding="utf-8") as f:
            for url in fixed_records:
                f.write(url + "\n")

        # Log corrupted records
        with open("corrupted_records.txt", "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for url in corrupted_records:
                f.write(f"{timestamp}\t{url}\n")

        print(f"Removed {len(corrupted_records)} corrupted records. Check corrupted_records.txt")


# ==============================
# FIND OCR FILE BY SERIAL
# ==============================

def find_ocr_file_by_serial(serial, title):
    """Find OCR file by serial number, handling filename variations"""
    safe_title = sanitize_filename(f"{serial}_{title}")
    expected_filename = f"{safe_title}-PDF.txt"
    expected_path = os.path.join(OCR_FOLDER, expected_filename)

    if os.path.exists(expected_path):
        return expected_path

    # If expected file doesn't exist, search for any file with this serial
    if os.path.exists(OCR_FOLDER):
        for filename in os.listdir(OCR_FOLDER):
            if filename.startswith(f"{serial}_") and filename.endswith("-PDF.txt"):
                return os.path.join(OCR_FOLDER, filename)

    return None


# ==============================
# EXTRACT JOB + PDF LINKS
# ==============================

def extract_pdf_links():
    with open(INPUT_MD, "r", encoding="utf-8") as f:
        data = f.read()

    job_pattern = r"###\s*(\d+)\.\s*(.*?)\n(.*?)(?=\n###\s*\d+\.|\Z)"
    jobs = re.findall(job_pattern, data, re.S)

    results = []

    for serial, title, content in jobs:
        link = None

        official = re.search(
            r"\|\s*\d+\s*\|\s*Official Notification PDF\s*\|\s*\[.*?\]\((.*?)\)",
            content
        )

        if official:
            link = official.group(1)
        else:
            fallback = re.search(
                r"\|\s*\d+\s*\|\s*Notification PDF\s*\|\s*\[.*?\]\((.*?)\)",
                content
            )
            if fallback:
                link = fallback.group(1)

        if link:
            results.append((serial, title.strip(), link))

    return results


# ==============================
# DOWNLOAD PDF WITH RETRY, USER-AGENT, AND HTTPS FALLBACK
# ==============================

def download_pdf(url):
    """Enhanced download with SSL verification, user-agent, retry logic, and HTTPS fallback"""
    print(f"  Downloading: {url}")

    # List of user-agents to rotate through
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
    ]

    # Try HTTPS version if URL starts with HTTP
    urls_to_try = [url]
    if url.startswith('http://'):
        https_url = url.replace('http://', 'https://', 1)
        urls_to_try.append(https_url)
        print(f"    Will also try HTTPS version: {https_url}")

    # Create session for better connection handling
    session = create_session()

    for target_url in urls_to_try:
        for attempt in range(DOWNLOAD_RETRY_LIMIT):
            try:
                # Rotate user-agent for each attempt
                user_agent = USER_AGENTS[attempt % len(USER_AGENTS)]

                headers = {
                    'User-Agent': user_agent,
                    'Accept': 'application/pdf,text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'Accept-Encoding': 'gzip, deflate',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Cache-Control': 'max-age=0',
                    'Referer': 'https://www.google.com/'
                }

                print(f"    Attempt {attempt + 1}/{DOWNLOAD_RETRY_LIMIT} for {target_url}")
                print(f"    Using User-Agent: {user_agent[:50]}...")

                # First attempt with SSL verification
                try:
                    r = session.get(
                        target_url,
                        timeout=DOWNLOAD_TIMEOUT,
                        headers=headers,
                        allow_redirects=True
                    )
                    r.raise_for_status()

                    # Check if we got HTML instead of PDF (possible error page)
                    content_type = r.headers.get('Content-Type', '').lower()
                    if 'text/html' in content_type and 'pdf' not in target_url.lower():
                        print(f"    Warning: Received HTML instead of PDF. Content-Type: {content_type}")
                        # Check if it's a small HTML error page
                        if len(r.content) < 102400:  # Less than 100KB
                            print(f"    Possible error page or login redirect")
                            # Check for common error messages
                            content_sample = r.content[:500].decode('utf-8', errors='ignore')
                            if '404' in content_sample or 'not found' in content_sample.lower():
                                print(f"    ⚠️ Page may not exist (404)")
                            elif 'access denied' in content_sample.lower() or 'forbidden' in content_sample.lower():
                                print(f"    ⚠️ Access denied - server may be blocking automated requests")
                            continue

                    print(f"    ✓ Download successful! Size: {len(r.content)} bytes")
                    return BytesIO(r.content)

                except SSLError:
                    # If SSL fails, try without verification
                    print(f"    SSL Error, retrying without verification...")
                    r = session.get(
                        target_url,
                        timeout=DOWNLOAD_TIMEOUT,
                        verify=False,
                        headers=headers,
                        allow_redirects=True
                    )
                    r.raise_for_status()
                    print(f"    ✓ Download successful (SSL bypassed)! Size: {len(r.content)} bytes")
                    return BytesIO(r.content)

                except (ConnectionError, Timeout) as e:
                    # Handle connection and timeout errors with exponential backoff
                    if attempt == DOWNLOAD_RETRY_LIMIT - 1:
                        if target_url != urls_to_try[-1]:
                            print(f"    All attempts failed for {target_url}, trying next URL...")
                            break  # Try next URL
                        raise

                    wait_time = (attempt + 1) * 15  # Increased backoff
                    print(f"    Connection/Timeout error: {type(e).__name__}")
                    print(f"    Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                    continue

            except Exception as e:
                if attempt == DOWNLOAD_RETRY_LIMIT - 1:
                    if target_url != urls_to_try[-1]:
                        print(f"    All attempts failed for {target_url}, trying next URL...")
                        break  # Try next URL
                    raise

                wait_time = (attempt + 1) * 10
                print(f"    Error: {type(e).__name__} - {e}")
                print(f"    Retrying in {wait_time} seconds...")
                time.sleep(wait_time)

    raise Exception(f"Failed to download after trying all URLs with {DOWNLOAD_RETRY_LIMIT} attempts each")


# ==============================
# SPLIT PDF INTO PAGES
# ==============================

def split_pdf(pdf_stream):
    reader = PdfReader(pdf_stream)
    total_pages = len(reader.pages)
    chunks = []

    for i in range(total_pages):
        writer = PdfWriter()
        writer.add_page(reader.pages[i])
        buffer = BytesIO()
        writer.write(buffer)
        buffer.seek(0)
        chunks.append((i + 1, buffer))

    return chunks, total_pages


# ==============================
# OCR USING OCR.SPACE
# ==============================

def ocr_chunk(pdf_chunk):
    for engine in OCR_ENGINES:
        for attempt in range(RETRY_LIMIT):
            try:
                response = requests.post(
                    "https://api.ocr.space/parse/image",
                    files={"file": ("chunk.pdf", pdf_chunk.getvalue())},
                    data={
                        "apikey": OCR_API_KEY,
                        "language": "eng",
                        "OCREngine": engine,
                        "scale": True,
                        "isTable": False,
                        "filetype": "PDF",
                        "detectOrientation": True
                    },
                    timeout=120
                )

                result = response.json()

                if result.get("IsErroredOnProcessing"):
                    continue

                parsed = result.get("ParsedResults")

                if parsed:
                    text = parsed[0].get("ParsedText", "")
                    if text.strip():
                        return text

            except Exception as e:
                print(f"    Retrying OCR: {e}")

            time.sleep(REQUEST_DELAY)

    return None


# ==============================
# SAVE INDIVIDUAL JOB OCR TO FILE
# ==============================

def save_job_ocr_to_file(serial, title, url, content, total_pages, successful_pages):
    """Save OCR result for a single job to OCR-PDF-TXT folder"""
    ensure_folders()

    # Create filename from job title
    safe_title = sanitize_filename(f"{serial}_{title}")
    filename = f"{safe_title}-PDF.txt"
    filepath = os.path.join(OCR_FOLDER, filename)

    # Only save if file doesn't exist (avoid overwriting)
    if os.path.exists(filepath):
        print(f"  OCR file already exists: {filename}")
        return filepath

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"Serial: {serial}\n")
        f.write(f"Job Title: {title}\n")
        f.write(f"Source URL: {url}\n")
        f.write(f"Total Pages: {total_pages}\n")
        f.write(f"Successfully OCR'd Pages: {successful_pages}/{total_pages}\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write("=" * 80 + "\n\n")
        f.write(content)

    print(f"  Saved OCR: {filename}")
    return filepath


# ==============================
# FILTER NOISE PAGES
# ==============================

def filter_noise(text):
    """Remove common noise pages like advertisements, disclaimers, etc."""
    noise_keywords = [
        "advertisement",
        "copyright",
        "all rights reserved",
        "disclaimer",
        "index",
        "blank page",
        "this page intentionally left blank",
        "www.",
        ".com",
        "published by"
    ]
    lines = text.splitlines()
    cleaned = []

    for line in lines:
        line_lower = line.lower()
        # Skip if line contains noise keywords AND is short (likely header/footer)
        if any(k in line_lower for k in noise_keywords) and len(line.strip()) < 100:
            continue
        cleaned.append(line)

    return "\n".join(cleaned)


# ==============================
# CLEAN OCR TEXT
# ==============================

def clean_ocr(text):
    """Remove garbage, normalize whitespace, reduce token count"""
    # First filter noise pages
    text = filter_noise(text)

    # Remove excessive newlines
    text = re.sub(r"\n\s*\n", "\n", text)

    # Keep important Unicode characters
    text = re.sub(r"[^\x00-\x7F₹€£¥%/().,:-]+", " ", text)

    # Collapse multiple spaces
    text = re.sub(r"\s{2,}", " ", text)

    # Remove common OCR artifacts but keep important symbols
    text = re.sub(r"[|•·●]", "", text)

    return text.strip()


# ==============================
# GEMINI SUMMARY
# ==============================

def generate_summary(serial, title, file_path):
    """Generate summary from OCR text file"""

    # Check if already summarized
    processed_summaries = load_processed_summaries()
    if str(serial) in processed_summaries:
        print(f"  Summary already exists for Job #{serial}, skipping...")
        return

    print(f"\n  Generating summary for Job #{serial}: {title}")

    with open(file_path, "r", encoding="utf-8") as f:
        # Skip header metadata (first 10 lines)
        lines = f.readlines()
        raw_text = "".join(lines[10:])  # Skip the metadata header

    # Clean OCR text
    text = clean_ocr(raw_text)

    # Log token reduction stats
    original_size = len(raw_text)
    cleaned_size = len(text)
    if original_size > 0:
        reduction = ((original_size - cleaned_size) / original_size) * 100
        print(f"    Text cleaned: {original_size} → {cleaned_size} chars ({reduction:.1f}% reduction)")

    chunks = chunk_text(text, CHUNK_SIZE)
    print(f"    Processing {len(chunks)} chunks...")

    extracted_chunks = []

    for i, chunk in enumerate(chunks):
        print(f"    Gemini chunk {i + 1}/{len(chunks)}")

        prompt = f"""
Extract recruitment details from this notification text.

Ignore OCR noise.

TEXT:
{chunk}
"""

        success = False

        for attempt in range(len(GEMINI_API_KEYS)):

            gemini_key = get_next_gemini_key()
            temp_client = genai.Client(api_key=gemini_key)

            try:
                response = temp_client.models.generate_content(
                    model=MODEL,
                    contents=prompt
                )

                extracted_chunks.append(response.text)
                time.sleep(1)

                success = True
                break

            except Exception as e:
                print(f"    Gemini key failed, switching... ({attempt + 1}/{len(GEMINI_API_KEYS)})")
                print(f"    Error: {e}")

        if not success:
            print("    All Gemini API keys failed, skipping chunk")
            if "503" in str(e) or "unavailable" in str(e).lower():
                print("    Rate limited, waiting 10 seconds...")
                time.sleep(10)
                try:
                    response = client.models.generate_content(
                        model=MODEL,
                        contents=prompt
                    )
                    extracted_chunks.append(response.text)
                except:
                    print("    Retry failed, skipping chunk")

    if not extracted_chunks:
        print("    No chunks successfully processed, skipping summary")
        return

    combined_data = "\n".join(extracted_chunks)

    format_prompt = f"""
You are a STRICT formatting engine with enhanced data verification capabilities.

Your task:
Convert the extracted recruitment data into the EXACT markdown template below.

**CRITICAL RULES FOR DATA ACCURACY:**

1.  **Vacancy Calculation:** If **'For Scheduled Caste (SC)'** is not directly mentioned, you **MUST** attempt to calculate it by summing all zone-wise or category-wise SC vacancies from any vacancy table or regional breakdown provided in the notification.

2.  **IMPORTANT TABLE EXTRACTION RULE (FOR VACANCY DATA):**

    Vacancy information may appear in structured tables, semi-structured text, or OCR-extracted content where columns are not perfectly aligned.

    If category-wise vacancies (UR, SC, ST, OBC, EWS, etc.) appear in any tabular or row-based structure, follow this process:

    **STEP 1 — Identify the Table Structure**
    Locate the header row that contains category names such as:
    UR, SC, ST, OBC, EWS, Total, PwBD, etc.

    Example header:
    Zone | UR | SC | ST | OBC | EWS | Total

    **STEP 2 — Identify Row Entries**
    Each row typically begins with a unit such as:
    Zone / Region / State / Category / Department / Location.

    Example rows:
    Ahmedabad 28 10 7 18 7 70
    Bengaluru 31 10 7 20 7 75

    **STEP 3 — Map Values to Columns**
    Assign numeric values according to the header order.

    Example:
    Ahmedabad 28 10 7 18 7 70

    Mapping:
    UR = 28
    SC = 10
    ST = 7
    OBC = 18
    EWS = 7
    Total = 70

    **STEP 4 — Handle OCR or Broken Formatting**
    If the table formatting is broken due to OCR extraction:
    - Use the repeating numeric pattern across rows.
    - Maintain the same column order as defined in the header.
    - Ignore extra symbols, bullet points, or spacing errors.

    **STEP 5 — Calculate Category Totals When Needed**
    If the notification does not explicitly provide totals for a category (e.g., SC), but zone-wise values exist:

    Calculate the total by summing that category column across all rows.

    Example:
    SC_total = SC_zone1 + SC_zone2 + SC_zone3 + ...

    **STEP 6 — Ignore Non-Vacancy Rows**
    Do NOT include rows such as:
    - Grand Total
    - Gross Total
    - PwBD breakdown
    - Footnotes
    - Empty rows

    **STEP 7 — When Calculation Is Allowed**
    Only calculate totals when:
    - Zone-wise or row-wise category values are present.
    - The column header clearly indicates the category.

    If no category values exist anywhere in the data, then mark it as **"Not Mentioned"**.

    **STEP 8 — Avoid False Failure**
    Do NOT say **"Cannot be calculated"** simply because the table formatting is irregular. If the numeric pattern and column headers allow extraction, perform the calculation.

    Always prioritize numeric patterns and header mapping over visual formatting.

3.  **Computer Proficiency:** Explicitly state **Required, Not Required, or Not Mentioned**. Do not infer this from educational qualifications unless the text explicitly links them.

4.  **Language Proficiency:** Explicitly state **Required, Not Required, or Not Mentioned**. If required and the language is specified (e.g., "proficient in Punjabi"), add a sub-line with the language name.

5.  **Compensation Calculation:** If **'Gross Emoluments'** is Not Mentioned, calculate it using available salary data like CTC range, Pay Level, or Basic Pay + Allowances.

6.  **Exam Pattern Completeness:** Include **all selection stages** and for each stage, provide:
    * **Total Marks**
    * **Total Time**
    * **Negative Marking** (formatted as: **"[Value] marks per wrong answer"** )
    * **Subject-wise breakdown** (Marks, Questions, Time if available)

7.  **Final Re-verification:** After filling the template, **re-verify every field**. Pay special attention to fields you have marked as **"Not Mentioned"** and double-check that the information truly does not exist elsewhere in the provided data before finalizing.

**MANDATORY FORMATTING INSTRUCTIONS:**

*   Under **'💪 Experience Required'**, if no experience requirement is mentioned, write exactly: **'No Experience required'**.
*   Under **'Selection Process'**, present stages sequentially using downward arrows (e.g., Prelims ↓ Mains ↓ Interview) and end with **FINAL MERIT**.

**OUTPUT TEMPLATE (USE EXACTLY):**

### [Job Title]
> _*A brief and compelling overview of the role, its primary purpose, and its value to the organization. Keep this to 1-2 sentences.*_

📅 **Key Dates & Fees**
Application Period: [From Date] – [To Date]
Examination Date(s): [Exam Date(s)]

**Exam Fee:**
* For General: [Fee Amount]
* For SC: [Fee Amount]

📊 **Vacancy Details**
Total Vacancies: [Total Number]
For Scheduled Caste (SC): [Number for SC - CALCULATE FROM ZONE-WISE DATA IF NOT DIRECTLY MENTIONED]

💼 **Compensation & Benefits**
- **Salary Structure:** [e.g., Pay Level, Pay Band, or specific salary range]
- **Gross Emoluments:** Approx. [Amount - CALCULATE IF NOT MENTIONED] per month

✅ **Eligibility Criteria**
**Educational Qualification:**
- [e.g., Bachelor's Degree in any discipline from a recognized university.]
- [e.g., Proficiency in computer applications.]

**Age Limit:**
- **Minimum Age:** [Years]
- **Maximum Age:** [Years]
- *Relaxation in upper age limit for SC/ST/OBC candidates as per government norms.*

**Additional Requirements:**
- **Computer Proficiency:** [Required/Not Required/Not Mentioned]
- **Language Proficiency (Reading, Writing, Understanding):** [Required/Not Required/Not Mentioned]
    <!-- If required, specify language -->
    [Language, e.g., Regional language of applied zone]

💪 **Experience Required**
- [No Experience required / [Number] years of professional experience in [relevant field or industry]]
- [Proven track record of specific achievement or skill - OR omit if not applicable]

> [!question]- Detailed Examination Scheme
>
> **Selection Process:**
>
> [Stage 1 Name]
>           ↓
> [Stage 2 Name]
>           ↓
> [Stage 3 Name]
>           ↓
> [Stage 4 Name - if applicable]
>           ↓
>       FINAL MERIT
>
> **Exam Pattern & Syllabus**
>
> **[Stage 1 Name]**
> * **Total Marks:** [e.g., 200]
> * **Total Time:** [e.g., 2 Hours (120 minutes)]
> * **Negative Marking:** [e.g., 0.25] marks per wrong answer
> * **Subjects:**
>   * [Subject Name]: [Marks] Marks, [Questions] Questions, [Minutes] Min
>   * [Subject Name]: [Marks] Marks, [Questions] Questions, [Minutes] Min
>
> **[Stage 2 Name - if applicable]**
> * **Total Marks:** [e.g., 200]
> * **Total Time:** [e.g., 2 Hours (120 minutes)]
> * **Negative Marking:** [e.g., 0.25] marks per wrong answer
> * **Subjects:**
>   * [Subject Name]: [Marks] Marks, [Questions] Questions, [Minutes] Min
>   * [Subject Name]: [Marks] Marks, [Questions] Questions, [Minutes] Min
>
> **[Stage 3 Name - if applicable, e.g., Personal Interview]**
> * **Total Marks:** [Value]
>
> **Final Merit:**
> Final selection will be based on the candidate's performance in all stages of the selection process. Merit list will be prepared based on the total marks obtained by candidates in the [specify stages, e.g., Written Exam and Interview] after applying applicable reservation norms and cut-offs.

> [!danger]- **Other Important Information:**
> [Include any other crucial details from the notification that candidates must know, such as:
> - Service bond requirements
> - Probation period details
> - Training period duration
> - Posting locations/Zonal preferences
> - Medical standards requirements
> - Physical standards requirements (if applicable)
> - Any other mandatory conditions]

DATA TO FORMAT:
{combined_data}
"""

    try:
        response = None

        for attempt in range(len(GEMINI_API_KEYS)):

            gemini_key = get_next_gemini_key()
            temp_client = genai.Client(api_key=gemini_key)

            try:
                response = temp_client.models.generate_content(
                    model=MODEL,
                    contents=format_prompt
                )
                break

            except Exception as e:
                print(f"    Gemini key failed, switching... ({attempt + 1}/{len(GEMINI_API_KEYS)})")
                print(f"    Error: {e}")

        if response is None:
            print("    All Gemini API keys failed during formatting")
            return

        # Save to Summaries folder with clean name
        safe_title = sanitize_filename(f"{serial}_{title}")
        summary_filename = f"{safe_title}-SUMMARY.md"
        summary_path = os.path.join(SUMMARY_FOLDER, summary_filename)

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(response.text)

        print(f"    Summary saved: {summary_filename}")

        # Mark as processed
        save_processed_summary(serial)

    except Exception as e:
        print(f"    Failed to generate summary: {e}")


# ==============================
# TEXT CHUNKING
# ==============================

def chunk_text(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


# ==============================
# OCR PIPELINE WITH CACHE
# ==============================

def process_all():
    # First, verify and fix any inconsistencies in processed files
    print("\nVerifying processed files...")
    verify_processed_files()

    jobs = extract_pdf_links()
    processed_pdfs = load_processed_pdfs()
    processed_summaries = load_processed_summaries()

    ensure_folders()

    for serial, title, url in jobs:
        print(f"\n{'=' * 60}")
        print(f"Job #{serial}: {title}")
        print(f"{'=' * 60}")

        # Check PDF status
        pdf_already_processed = url in processed_pdfs
        summary_already_exists = str(serial) in processed_summaries

        print(f"  PDF Processed: {'✅' if pdf_already_processed else '❌'}")
        print(f"  Summary Generated: {'✅' if summary_already_exists else '❌'}")

        # Skip only if BOTH exist
        if pdf_already_processed and summary_already_exists:
            print(f"  ✅ Job #{serial} completely processed, skipping...")
            continue

        # Handle case where PDF is marked as processed but file might be missing
        file_path = None
        if pdf_already_processed and not summary_already_exists:
            # Try to find the OCR file
            file_path = find_ocr_file_by_serial(serial, title)

            if file_path:
                print(f"  ✅ Found OCR file: {os.path.basename(file_path)}")
            else:
                print(f"  ⚠️ PDF marked as processed but no OCR file found. Will reprocess...")
                pdf_already_processed = False  # Force reprocess

        # Download and OCR if needed
        if not pdf_already_processed:
            print(f"  Need to download & OCR...")
            try:
                pdf_stream = download_pdf(url)
                chunks, total_pages = split_pdf(pdf_stream)

                successful_pages = 0
                job_ocr_text = ""

                for page_no, chunk in chunks:
                    print(f"    OCR Page {page_no}/{total_pages}")

                    text = ocr_chunk(chunk)

                    if text:
                        successful_pages += 1
                        page_content = f"\n--- Page {page_no} ---\n{text}"
                        job_ocr_text += page_content
                    else:
                        job_ocr_text += f"\n--- Page {page_no} OCR FAILED ---\n"

                # Save OCR file
                file_path = save_job_ocr_to_file(
                    serial=serial,
                    title=title,
                    url=url,
                    content=job_ocr_text,
                    total_pages=total_pages,
                    successful_pages=successful_pages
                )

                # Mark PDF as processed
                save_processed_pdf(url)

            except Exception as e:
                print(f"    ❌ PDF PROCESS FAILED: {e}")

                # Log failed download
                log_failed_download(serial, title, url, str(e))

                # Special handling for EIL (Job #106) and similar problematic sites
                if "eil.co.in" in url or "aai.aero" in url:
                    print(f"\n    💡 TROUBLESHOOTING TIPS:")
                    print(f"      1. Try downloading manually from: {url.replace('http://', 'https://')}")
                    print(f"      2. The server might be blocking automated requests")
                    print(f"      3. You can try using a VPN if the server is geographically restricted")
                    print(f"      4. Check if the file exists by visiting the recruitment portal")
                    print(f"      5. Consider adding the domain to your firewall exceptions")
                    print(f"      6. Try accessing during off-peak hours\n")

                continue
        else:
            # PDF already exists and we found the file
            if not file_path:
                file_path = find_ocr_file_by_serial(serial, title)

            if file_path:
                print(f"  ✅ Using existing OCR file: {os.path.basename(file_path)}")
            else:
                print(f"  ❌ Could not find OCR file for Job #{serial}")
                continue

        # Generate summary if needed
        if not summary_already_exists and file_path and os.path.exists(file_path):
            print(f"  Need to generate summary...")
            generate_summary(serial, title, file_path)
        elif summary_already_exists:
            print(f"  ✅ Summary already exists")
        else:
            print(f"  ❌ OCR file not found or invalid: {file_path}")


# ==============================
# TEXT CHUNKING (duplicate, keeping for compatibility)
# ==============================

def chunk_text(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


# ==============================
# RUN SCRIPT
# ==============================

if __name__ == "__main__":
    print("=" * 60)
    print("JOB NOTIFICATION OCR PIPELINE v3.2")
    print("=" * 60)

    print("\nAPI Key Status:")
    print(f"  OCR API Key: {'✅ Set' if OCR_API_KEY else '❌ Missing'}")
    print(f"  Gemini API Key: {'✅ Set' if GEMINI_API_KEYS else '❌ Missing'}")
    print("-" * 60)

    process_all()

    print("\n" + "=" * 60)
    print("✅ ALL JOBS PROCESSED")
    print("=" * 60)
    print(f"\n📁 OCR files:     '{OCR_FOLDER}/'")
    print(f"📁 Summaries:     '{SUMMARY_FOLDER}/'")
    print(f"📋 PDF tracker:   {RECORD_FILE}")
    print(f"📋 Summary tracker: {SUMMARY_RECORD_FILE}")
    print(f"📋 Failed downloads: {FAILED_PDFS_FILE}")
    print("\n" + "=" * 60)