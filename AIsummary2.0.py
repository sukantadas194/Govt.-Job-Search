import re
import requests
import time
import logging
from io import BytesIO
from datetime import datetime
from PyPDF2 import PdfReader, PdfWriter
from google import genai
from collections import defaultdict
import os
from dotenv import load_dotenv
import urllib3
from requests.exceptions import SSLError, ConnectionError, Timeout
from bs4 import BeautifulSoup

# ==============================
# LOGGING SETUP
# ==============================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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

# ✅ FIX 3: ENV VALIDATION IS WRONG - FIXED
if not OCR_API_KEY or not any(k.strip() for k in GEMINI_API_KEYS):
    raise ValueError("Missing API keys. Set OCR_API_KEY and GEMINI_API_KEY environment variables.")

INPUT_MD = "Sample.md"
OCR_OUTPUT = "NotiPDF.txt"

RECORD_FILE = "processed_pdfs.txt"
SUMMARY_RECORD_FILE = "processed_summaries.txt"
FAILED_PDFS_FILE = "failed_pdfs.txt"
OCR_FOLDER = "OCR-PDF-TXT"
SUMMARY_FOLDER = "Summaries"
HTML_FOLDER = "HTML-Content"

MODEL = "gemini-2.5-flash-lite"

OCR_ENGINES = [2, 1, 3]
RETRY_LIMIT = 3
REQUEST_DELAY = 3
# ✅ FIX 8: CHUNK SIZE TOO LARGE - REDUCED
CHUNK_SIZE = 8000
DOWNLOAD_RETRY_LIMIT = 5
DOWNLOAD_TIMEOUT = 180


# ==============================
# GEMINI CLIENT
# ==============================

client = genai.Client(api_key=GEMINI_API_KEYS[0])


# ==============================
# CREATE SESSION FOR BETTER CONNECTION HANDLING
# ==============================

class ManagedSession:
    """Context manager for session handling"""
    def __init__(self):
        self.session = None
    
    def __enter__(self):
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(
            max_retries=3,
            pool_connections=10,
            pool_maxsize=10,
            pool_block=False
        )
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        return self.session
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            self.session.close()


def create_session():
    """Returns a context manager for session handling"""
    return ManagedSession()


# ==============================
# CREATE FOLDERS IF NOT EXISTS
# ==============================

def ensure_folders():
    """Create required folders if they don't exist"""
    for folder in [OCR_FOLDER, SUMMARY_FOLDER, HTML_FOLDER]:
        if not os.path.exists(folder):
            os.makedirs(folder)
            logger.info(f"Created folder: {folder}")


# ==============================
# SANITIZE FILENAME
# ==============================

def sanitize_filename(filename):
    """Remove invalid characters for cross-platform filenames"""
    invalid_chars = r'[<>:"/\\|?*]'
    sanitized = re.sub(invalid_chars, '_', filename)
    # ✅ FIX 10: Added timestamp to avoid collisions
    timestamp = int(time.time())
    return f"{sanitized[:80]}_{timestamp}".strip()


# ==============================
# DETECT FILE TYPE (IMPROVED)
# ==============================

def detect_file_type(response):
    """Smart detection of file type from response"""
    content_type = response.headers.get("Content-Type", "").lower()
    
    # Check by content-type header
    if "pdf" in content_type:
        return "pdf"
    elif "html" in content_type:
        return "html"
    
    # Check by content magic bytes
    if response.content.startswith(b"%PDF"):
        return "pdf"
    
    # ✅ FIX 6: IMPROVED HTML DETECTION
    content_lower = response.content[:500].lower()
    if b"<!DOCTYPE html" in content_lower or b"<html" in content_lower:
        return "html"
    
    return "unknown"


# ==============================
# EXTRACT TEXT FROM HTML (IMPROVED)
# ==============================

def extract_text_from_html(html_stream, url=None):
    """Extract clean text from HTML content with site-specific optimizations"""
    html = html_stream.getvalue().decode("utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    
    # Remove script and style elements
    for tag in soup(["script", "style", "noscript", "meta", "link"]):
        tag.extract()
    
    # Site-specific extraction logic
    if url and "rbi.org.in" in url:
        main_content = soup.find("div", {"id": "content"})
        if not main_content:
            main_content = soup.find("div", {"class": "content"})
        if not main_content:
            main_content = soup.find("div", {"class": "main-content"})
        if main_content:
            soup = main_content
    
    elif url and "aai.aero" in url:
        main_content = soup.find("div", {"class": "entry-content"})
        if main_content:
            soup = main_content
    
    # Get text
    text = soup.get_text(separator="\n")
    
    # Clean up whitespace
    text = re.sub(r"\n\s*\n", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    
    # ✅ FIX 11: RELAXED LINE FILTERING
    lines = text.split('\n')
    cleaned_lines = []
    for line in lines:
        line_stripped = line.strip()
        if len(line_stripped) > 10:  # Reduced from 30 to 10
            cleaned_lines.append(line)
        elif any(keyword in line_stripped.lower() for keyword in ['age', 'salary', 'vacancy', 'total', 'sc', 'st', 'obc', 'ews']):
            cleaned_lines.append(line)
    
    return "\n".join(cleaned_lines).strip()


# ==============================
# SAVE HTML CONTENT TO FILE
# ==============================

def save_html_to_file(serial, title, url, content):
    """Save HTML extracted content for a job"""
    ensure_folders()
    
    safe_title = sanitize_filename(f"{serial}_{title}")
    filename = f"{safe_title}-HTML.txt"
    filepath = os.path.join(HTML_FOLDER, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"Serial: {serial}\n")
        f.write(f"Job Title: {title}\n")
        f.write(f"Source URL: {url}\n")
        f.write(f"Content Type: HTML (extracted)\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write("=" * 80 + "\n\n")
        f.write(content)
    
    logger.info(f"Saved HTML content: {filename}")
    return filepath


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
    if not os.path.exists(SUMMARY_RECORD_FILE):
        return set()
    with open(SUMMARY_RECORD_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())


def save_processed_summary(serial):
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
        logger.info(f"Created backup of processed PDFs: {backup_file}")
    
    # Check each URL and find corresponding OCR files
    for url in processed_pdfs:
        found = False
        if os.path.exists(OCR_FOLDER):
            for filename in os.listdir(OCR_FOLDER):
                if filename.endswith("-PDF.txt"):
                    filepath = os.path.join(OCR_FOLDER, filename)
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            content = f.read()
                            if url in content:
                                found = True
                                break
                    except:
                        continue
        
        # ✅ FIX 2: DOUBLE APPEND BUG - FIXED
        if found:
            fixed_records.append(url)
        else:
            corrupted_records.append(url)
    
    # Rewrite the processed PDFs file with only valid records
    if corrupted_records:
        logger.warning(f"Found {len(corrupted_records)} corrupted records. Fixing...")
        with open(RECORD_FILE, "w", encoding="utf-8") as f:
            for url in fixed_records:
                f.write(url + "\n")
        
        with open("corrupted_records.txt", "a", encoding="utf-8") as f:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            for url in corrupted_records:
                f.write(f"{timestamp}\t{url}\n")
        
        logger.info(f"Removed {len(corrupted_records)} corrupted records")


# ==============================
# FIND OCR FILE BY SERIAL
# ==============================

def find_ocr_file_by_serial(serial, title):
    """Find OCR file by serial number, handling filename variations"""
    # Search without timestamp first
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
    
    job_pattern = r"###\s*(\d+)\.\s*(.+?)\n(.*?)(?=\n###\s*\d+\.\s+|\Z)"
    jobs = re.findall(job_pattern, data, re.S)
    
    results = []
    
    for serial, title, content in jobs:
        link = None
        
        official = re.search(
            r"\|\s*\d+\s*\|.*?(Official|Detailed Advertisement|Notification).*?\|\s*\[.*?\]\((.*?)\)",
            content,
            re.I
        )
        
        if official:
            link = official.group(2)
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
# DOWNLOAD PDF OR HTML WITH ENHANCED HANDLING
# ==============================

def download_pdf(url, serial=None, depth=0):
    """Enhanced download with HTML handling, recursion control, and serial for debugging"""
    # ✅ FIX 5: ADD RECURSION DEPTH CONTROL
    if depth > 3:
        raise Exception("Too many redirects/recursions (possible loop)")
    
    logger.info(f"Downloading: {url} (depth={depth})")
    
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    
    urls_to_try = [url]
    if url.startswith('http://'):
        https_url = url.replace('http://', 'https://', 1)
        urls_to_try.append(https_url)
        logger.info(f"Will also try HTTPS version: {https_url}")
    
    for target_url in urls_to_try:
        for attempt in range(DOWNLOAD_RETRY_LIMIT):
            try:
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
                
                logger.info(f"Attempt {attempt + 1}/{DOWNLOAD_RETRY_LIMIT} for {target_url}")
                
                # ✅ FIX 4: SESSION CONTEXT MANAGER
                with create_session() as session:
                    try:
                        r = session.get(
                            target_url,
                            timeout=DOWNLOAD_TIMEOUT,
                            headers=headers,
                            allow_redirects=True
                        )
                        r.raise_for_status()
                        
                        # ✅ FIX 14: ADD CONTENT SIZE CHECK
                        if len(r.content) < 1000:
                            raise Exception("Downloaded file too small (likely invalid)")
                        
                        file_type = detect_file_type(r)
                        
                        if file_type == "pdf":
                            logger.info(f"✓ Downloaded valid PDF. Size: {len(r.content)} bytes")
                            return BytesIO(r.content), "pdf"
                        
                        elif file_type == "html":
                            logger.warning(f"HTML detected (not PDF). Will parse HTML content.")
                            
                            # Try to find embedded PDF link
                            html_content = r.content.decode("utf-8", errors="ignore")
                            pdf_match = re.search(r'(https?://[^"\']+\.pdf)', html_content, re.I)
                            
                            if pdf_match:
                                real_pdf_url = pdf_match.group(1)
                                logger.info(f"🔁 Found embedded PDF link: {real_pdf_url}")
                                # ✅ FIX 5: PASS DEPTH + 1 FOR RECURSION CONTROL
                                return download_pdf(real_pdf_url, serial, depth + 1)
                            
                            logger.info(f"📄 No PDF link found, returning HTML content")
                            return BytesIO(r.content), "html"
                        
                        else:
                            logger.error(f"Unknown file type: {file_type}")
                            # ✅ FIX 1: serial NOW AVAILABLE
                            debug_filename = f"debug_unknown_{serial or 'unknown'}_{int(time.time())}.html"
                            with open(debug_filename, "wb") as f:
                                f.write(r.content[:10000])
                            raise Exception(f"Unknown file type: {file_type}")
                    
                    except SSLError:
                        logger.warning(f"SSL Error, retrying without verification...")
                        r = session.get(
                            target_url,
                            timeout=DOWNLOAD_TIMEOUT,
                            verify=False,
                            headers=headers,
                            allow_redirects=True
                        )
                        r.raise_for_status()
                        
                        if len(r.content) < 1000:
                            raise Exception("Downloaded file too small (likely invalid)")
                        
                        file_type = detect_file_type(r)
                        if file_type == "pdf":
                            logger.info(f"✓ Downloaded valid PDF (SSL bypassed)! Size: {len(r.content)} bytes")
                            return BytesIO(r.content), "pdf"
                        elif file_type == "html":
                            logger.warning(f"HTML detected (SSL bypassed)")
                            return BytesIO(r.content), "html"
                        else:
                            raise Exception(f"Unknown file type after SSL bypass: {file_type}")
                    
                    except (ConnectionError, Timeout) as e:
                        if attempt == DOWNLOAD_RETRY_LIMIT - 1:
                            if target_url != urls_to_try[-1]:
                                logger.warning(f"All attempts failed for {target_url}, trying next URL...")
                                break
                            raise
                        wait_time = (attempt + 1) * 15
                        logger.warning(f"Connection/Timeout error: {type(e).__name__}")
                        logger.warning(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                        continue
            
            except Exception as e:
                if attempt == DOWNLOAD_RETRY_LIMIT - 1:
                    if target_url != urls_to_try[-1]:
                        logger.warning(f"All attempts failed for {target_url}, trying next URL...")
                        break
                    raise
                wait_time = (attempt + 1) * 10
                logger.warning(f"Error: {type(e).__name__} - {e}")
                logger.warning(f"Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
    
    raise Exception(f"Failed to download after trying all URLs with {DOWNLOAD_RETRY_LIMIT} attempts each")


# ==============================
# SPLIT PDF INTO PAGES
# ==============================

def split_pdf(pdf_stream):
    try:
        reader = PdfReader(pdf_stream)
    except Exception as e:
        raise Exception(f"PDF parsing failed (corrupt or non-PDF content): {e}")
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
    """Sends PDF chunk to OCR.Space and returns reconstructed text."""
    
    for engine in OCR_ENGINES:
        for attempt in range(RETRY_LIMIT):
            try:
                response = requests.post(
                    "https://api.ocr.space/parse/image",
                    files={
                        "file": (
                            "chunk.pdf",
                            pdf_chunk.getvalue(),
                            "application/pdf"
                        )
                    },
                    data={
                        "apikey": OCR_API_KEY,
                        "language": "eng",
                        "OCREngine": engine,
                        "scale": True,
                        "isTable": True,
                        "filetype": "PDF",
                        "detectOrientation": True,
                        "isOverlayRequired": True
                    },
                    timeout=120
                )
                
                response.raise_for_status()
                result = response.json()
                
                # ✅ FIX 7: OCR API HARD FAIL NOT HANDLED - ADDED
                if result.get("OCRExitCode") == 3:
                    logger.error("OCR API quota exhausted")
                    raise Exception("OCR API quota exhausted")
                
                if result.get("IsErroredOnProcessing"):
                    logger.warning(f"OCR Error (Engine {engine}) Attempt {attempt+1}")
                    continue
                
                parsed_results = result.get("ParsedResults", [])
                
                if not parsed_results:
                    continue
                
                all_pages_text = []
                
                for page in parsed_results:
                    overlay = page.get("TextOverlay", {})
                    lines = overlay.get("Lines", [])
                    
                    if lines:
                        page_text = rebuild_layout(lines)
                    else:
                        page_text = page.get("ParsedText", "")
                    
                    if page_text.strip():
                        all_pages_text.append(page_text.strip())
                
                final_text = "\n\n".join(all_pages_text).strip()
                
                if final_text:
                    return final_text
            
            except requests.exceptions.RequestException as e:
                logger.error(f"Network Error: {e}")
            except ValueError as e:
                logger.error(f"JSON Error: {e}")
            except Exception as e:
                logger.error(f"Unexpected Error: {e}")
            
            time.sleep(REQUEST_DELAY)
    
    return None


# ==============================
# LAYOUT RECONSTRUCTION
# ==============================

def rebuild_layout(lines):
    """Converts OCR.Space TextOverlay lines into formatted text"""
    rows = defaultdict(list)
    
    for line in lines:
        y = line.get("MinTop", 0)
        y_key = round(y / 8) * 8
        
        for word in line.get("Words", []):
            x = word.get("Left", 0)
            text = word.get("WordText", "").strip()
            
            if text:
                rows[y_key].append((x, text))
    
    final_lines = []
    
    for y in sorted(rows.keys()):
        words = sorted(rows[y], key=lambda item: item[0])
        
        row_text = ""
        prev_x = 0
        
        for x, word in words:
            gap = x - prev_x
            
            if prev_x == 0:
                row_text += word
            elif gap > 220:
                row_text += "        " + word
            elif gap > 130:
                row_text += "     " + word
            elif gap > 70:
                row_text += "   " + word
            else:
                row_text += " " + word
            
            prev_x = x
        
        final_lines.append(row_text.rstrip())
    
    return "\n".join(final_lines)


# ==============================
# SAVE JOB OCR TO FILE
# ==============================

def save_job_ocr_to_file(serial, title, url, content, total_pages, successful_pages):
    """Save OCR result for a single job to OCR-PDF-TXT folder"""
    ensure_folders()
    
    safe_title = sanitize_filename(f"{serial}_{title}")
    filename = f"{safe_title}-PDF.txt"
    filepath = os.path.join(OCR_FOLDER, filename)
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 80 + "\n")
        f.write(f"Serial: {serial}\n")
        f.write(f"Job Title: {title}\n")
        f.write(f"Source URL: {url}\n")
        f.write(f"Total Pages: {total_pages}\n")
        f.write(f"Successfully Processed Pages: {successful_pages}/{total_pages}\n")
        f.write(f"Timestamp: {datetime.now()}\n")
        f.write("=" * 80 + "\n\n")
        f.write(content)
    
    logger.info(f"Saved OCR: {filename}")
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
        "this page intentionally left blank"
    ]
    lines = text.splitlines()
    cleaned = []
    
    for line in lines:
        line_lower = line.lower()
        if any(k in line_lower for k in noise_keywords) and len(line.strip()) < 100:
            continue
        cleaned.append(line)
    
    return "\n".join(cleaned)


# ==============================
# CLEAN OCR TEXT
# ==============================

def clean_ocr(text):
    """Remove garbage, normalize whitespace, reduce token count"""
    text = filter_noise(text)
    text = re.sub(r"\n\s*\n", "\n", text)
    text = re.sub(r"[^\x00-\x7F₹€£¥%/().,:-]+", " ", text)
    text = re.sub(r"[ \t]{2,}", "  ", text)
    text = re.sub(r"[|•·●]", "", text)
    return text.strip()


# ==============================
# GEMINI SUMMARY
# ==============================

def generate_summary(serial, title, file_path):
    """Generate summary from OCR text file"""
    processed_summaries = load_processed_summaries()
    
    if str(serial) in processed_summaries:
        logger.info(f"Summary already exists for Job #{serial}, skipping...")
        return
    
    logger.info(f"\nGenerating summary for Job #{serial}: {title}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()
        raw_text = "".join(lines[10:])
    
    text = clean_ocr(raw_text)
    
    original_size = len(raw_text)
    cleaned_size = len(text)
    if original_size > 0:
        reduction = ((original_size - cleaned_size) / original_size) * 100
        logger.info(f"Text cleaned: {original_size} → {cleaned_size} chars ({reduction:.1f}% reduction)")
    
    chunks = chunk_text(text, CHUNK_SIZE)
    logger.info(f"Processing {len(chunks)} chunks...")
    
    extracted_chunks = []
    
    for i, chunk in enumerate(chunks):
        logger.info(f"Gemini chunk {i + 1}/{len(chunks)}")
        
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
                # ✅ FIX 9: ADD RATE LIMIT PROTECTION
                time.sleep(2)
                success = True
                break
            except Exception as e:
                logger.warning(f"Gemini key failed, switching... ({attempt + 1}/{len(GEMINI_API_KEYS)})")
                logger.warning(f"Error: {e}")
        
        if not success:
            logger.error("All Gemini API keys failed for this chunk.")
            logger.info("Waiting 10 seconds before next chunk...")
            time.sleep(10)
            continue
    
    if not extracted_chunks:
        logger.error("No chunks successfully processed, skipping summary")
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
                # ✅ FIX 9: ADD RATE LIMIT PROTECTION
                time.sleep(2)
                break
            except Exception as e:
                logger.warning(f"Gemini key failed, switching... ({attempt + 1}/{len(GEMINI_API_KEYS)})")
                if "503" in str(e):
                    time.sleep(5)
        
        if response is None:
            logger.error("All Gemini API keys failed during formatting")
            return
        
        safe_title = sanitize_filename(f"{serial}_{title}")
        summary_filename = f"{safe_title}-SUMMARY.md"
        summary_path = os.path.join(SUMMARY_FOLDER, summary_filename)
        
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(response.text)
        
        logger.info(f"Summary saved: {summary_filename}")
        save_processed_summary(serial)
    
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")


# ==============================
# TEXT CHUNKING
# ==============================

def chunk_text(text, size):
    return [text[i:i + size] for i in range(0, len(text), size)]


# ==============================
# MAIN PROCESSING PIPELINE
# ==============================

def process_all():
    """Main pipeline with HTML handling"""
    logger.info("\nVerifying processed files...")
    verify_processed_files()
    
    jobs = extract_pdf_links()
    logger.info(f"🔍 Total Jobs Found In Sample.md: {len(jobs)}")
    processed_pdfs = load_processed_pdfs()
    processed_summaries = load_processed_summaries()
    
    ensure_folders()
    
    for serial, title, url in jobs:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Job #{serial}: {title}")
        logger.info(f"{'=' * 60}")
        
        pdf_already_processed = url in processed_pdfs
        summary_already_exists = str(serial) in processed_summaries
        
        logger.info(f"PDF Processed: {'✅' if pdf_already_processed else '❌'}")
        logger.info(f"Summary Generated: {'✅' if summary_already_exists else '❌'}")
        
        if pdf_already_processed and summary_already_exists:
            logger.info(f"⚠️ Job #{serial} already fully processed. Skipping.")
            continue
        
        file_path = None
        if pdf_already_processed and not summary_already_exists:
            file_path = find_ocr_file_by_serial(serial, title)
            if file_path:
                logger.info(f"✅ Found OCR file: {os.path.basename(file_path)}")
            else:
                logger.warning(f"⚠️ PDF marked as processed but no OCR file found. Will reprocess...")
                pdf_already_processed = False
        
        if not pdf_already_processed:
            logger.info(f"Need to download & process...")
            try:
                # ✅ FIX 1: PASS serial TO download_pdf
                file_stream, file_type = download_pdf(url, serial=serial)
                
                if file_type == "pdf":
                    logger.info(f"Processing as PDF with OCR...")
                    # ✅ FIX 13: WRAP PDF PARSING IN TRY-CATCH
                    try:
                        chunks, total_pages = split_pdf(file_stream)
                    except Exception as e:
                        logger.error(f"PDF Parse Error: {e}")
                        log_failed_download(serial, title, url, f"PDF Parse Error: {e}")
                        continue
                    
                    successful_pages = 0
                    job_content = ""
                    
                    for page_no, chunk in chunks:
                        logger.info(f"OCR Page {page_no}/{total_pages}")
                        text = ocr_chunk(chunk)
                        
                        if text:
                            successful_pages += 1
                            page_content = f"\n--- Page {page_no} ---\n{text}"
                            job_content += page_content
                        else:
                            job_content += f"\n--- Page {page_no} OCR FAILED ---\n"
                    
                    file_path = save_job_ocr_to_file(
                        serial=serial,
                        title=title,
                        url=url,
                        content=job_content,
                        total_pages=total_pages,
                        successful_pages=successful_pages
                    )
                
                elif file_type == "html":
                    logger.info(f"Processing as HTML (no OCR needed)...")
                    text = extract_text_from_html(file_stream, url)
                    file_path = save_html_to_file(
                        serial=serial,
                        title=title,
                        url=url,
                        content=text
                    )
                    logger.info(f"HTML extracted: {len(text)} characters")
                    
                    # Also save to OCR folder for consistency
                    ocr_file_path = save_job_ocr_to_file(
                        serial=serial,
                        title=title,
                        url=url,
                        content=text,
                        total_pages=1,
                        successful_pages=1
                    )
                    file_path = ocr_file_path
                
                else:
                    logger.error(f"Unsupported file type: {file_type}")
                    continue
                
                save_processed_pdf(url)
            
            except Exception as e:
                logger.error(f"❌ PROCESSING FAILED: {e}")
                log_failed_download(serial, title, url, str(e))
                continue
        else:
            if not file_path:
                file_path = find_ocr_file_by_serial(serial, title)
            
            if file_path:
                logger.info(f"✅ Using existing file: {os.path.basename(file_path)}")
            else:
                logger.error(f"❌ Could not find file for Job #{serial}")
                continue
        
        if not summary_already_exists and file_path and os.path.exists(file_path):
            logger.info(f"Need to generate summary...")
            generate_summary(serial, title, file_path)
        elif summary_already_exists:
            logger.info(f"✅ Summary already exists")
        else:
            logger.error(f"❌ File not found or invalid: {file_path}")


# ==============================
# RUN SCRIPT
# ==============================

if __name__ == "__main__":
    print("=" * 60)
    print("JOB NOTIFICATION PROCESSING PIPELINE v4.1")
    print("ALL CRITICAL FIXES APPLIED")
    print("=" * 60)
    
    print("\nAPI Key Status:")
    print(f"  OCR API Key: {'✅ Set' if OCR_API_KEY else '❌ Missing'}")
    print(f"  Gemini API Keys: {'✅ Set' if any(k.strip() for k in GEMINI_API_KEYS) else '❌ Missing'}")
    print("-" * 60)
    
    try:
        from bs4 import BeautifulSoup
        print("✅ BeautifulSoup installed")
    except ImportError:
        print("❌ BeautifulSoup not installed. Run: pip install beautifulsoup4")
        exit(1)
    
    process_all()
    
    print("\n" + "=" * 60)
    print("✅ ALL JOBS PROCESSED")
    print("=" * 60)
    print(f"\n📁 OCR files:     '{OCR_FOLDER}/'")
    print(f"📁 HTML files:    '{HTML_FOLDER}/'")
    print(f"📁 Summaries:     '{SUMMARY_FOLDER}/'")
    print(f"📋 PDF tracker:   {RECORD_FILE}")
    print(f"📋 Summary tracker: {SUMMARY_RECORD_FILE}")
    print(f"📋 Failed downloads: {FAILED_PDFS_FILE}")
    print(f"📋 Log file:      pipeline.log")
    print("\n" + "=" * 60)