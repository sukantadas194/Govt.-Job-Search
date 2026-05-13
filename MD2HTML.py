import re

INPUT_FILE = "op2.md"
OUTPUT_FILE = "jobs.html"


# -------------------------------
# HELPERS
# -------------------------------
def clean_text(text):
    if not text:
        return ""
    # Remove markdown formatting
    text = re.sub(r'\*\*', '', text)
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def is_unwanted(description):
    """STRICT MANDATORY FILTER - Production ready"""
    bad = [
        "sarkari result", "telegram", "whatsapp",
        "mobile app", "channel", "freejobalert",
        "click here", "join our", "result", "answer key",
        "syllabus", "previous paper", "admit card",
        "sarkari", "whatsapp group", "telegram channel"
    ]
    desc = description.lower()
    return any(x in desc for x in bad)


def is_bad_url(url):
    """Block unwanted URLs"""
    bad = [
        "t.me", "whatsapp.com", "play.google.com",
        "freejobalert.com", "rebrand.ly", "bit.ly",
        "tinyurl.com"
    ]
    url_lower = url.lower()
    return any(x in url_lower for x in bad)


def extract_url_from_markdown(text):
    """Extract URL from markdown link format [text](url)"""
    match = re.search(r'\]\(([^)]+)\)', text)
    return match.group(1) if match else ""


def extract_text_from_markdown(text):
    """Extract text from markdown link format [text](url)"""
    match = re.search(r'\[([^\]]+)\]', text)
    return clean_text(match.group(1)) if match else ""


def format_date(date_str):
    """Convert DD/MM/YYYY or DD-MM-YYYY to DD Month YYYY"""
    if not date_str:
        return ""
    # Remove any extra spaces or backticks
    date_str = date_str.strip('`').strip()
    match = re.search(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', date_str)
    if match:
        day, month, year = match.groups()
        months = ["January", "February", "March", "April", "May", "June",
                  "July", "August", "September", "October", "November", "December"]
        month_name = months[int(month) - 1]
        return f"{int(day)} {month_name} {year}"
    return date_str


# -------------------------------
# EXTRACT IMPORTANT LINKS (ROBUST VERSION)
# -------------------------------
def extract_links(section):
    """Robust Important Links extractor (STRICT FILTERING)"""
    links = []

    # Try multiple patterns to find the Important Links table
    patterns = [
        r'### \*\*Important Links\*\* —?\s*\n((?:\|.*\n)+)',
        r'Important Links.*?\n((?:\|.*\n)+)',
        r'\|\s*#\s*\|\s*Description\s*\|\s*Link\s*\|\s*\n((?:\|.*\n)+)'
    ]
    
    table_text = None
    for pattern in patterns:
        table_match = re.search(pattern, section, re.I)
        if table_match:
            table_text = table_match.group(1)
            break
    
    if not table_text:
        return links

    rows = table_text.strip().split('\n')
    
    for row in rows:
        row = row.strip()
        
        # Skip invalid rows
        if not row.startswith('|'):
            continue
        
        # Skip separator row (|---|---|---|)
        if re.match(r'^\|\s*[-:]+\s*\|', row):
            continue
        
        # Parse columns
        cols = [c.strip() for c in row.split('|')]
        # Remove empty first/last elements from split
        cols = [c for c in cols if c]
        
        # Expect at least 2 columns (Description and Link)
        if len(cols) < 2:
            continue
        
        # Handle different column arrangements
        if len(cols) >= 3:
            # Standard format: #, Description, Link
            desc = cols[1] if len(cols) > 1 else cols[0]
            link_part = cols[2] if len(cols) > 2 else cols[-1]
        else:
            # Minimal format: Description, Link
            desc = cols[0]
            link_part = cols[1]
        
        desc = clean_text(desc)
        
        # Extract URL from markdown
        url = extract_url_from_markdown(link_part)
        if not url:
            # Try to extract URL directly if no markdown
            url_match = re.search(r'https?://[^\s\)]+', link_part)
            if url_match:
                url = url_match.group(0)
        
        if not desc or not url:
            continue
        
        # Apply strict filters
        if is_unwanted(desc):
            continue
        
        if is_bad_url(url):
            continue
        
        # Clean up description
        desc = re.sub(r'click here', '', desc, flags=re.I).strip()
        desc = re.sub(r':$', '', desc).strip()
        
        # Skip empty descriptions
        if not desc:
            continue
        
        links.append((desc, url))
    
    return links


# -------------------------------
# EXTRACT FIELD VALUE
# -------------------------------
def extract_field(section, field_names, default=""):
    """Extract field value using multiple possible patterns"""
    if isinstance(field_names, str):
        field_names = [field_names]
    
    for field in field_names:
        # Pattern with bullet and bold
        patterns = [
            rf'[-*]\s*\*\*{re.escape(field)}:\*\*\s*(.*?)(?:\n|$)',
            rf'{re.escape(field)}:\s*\*\*(.*?)\*\*(?:\n|$)',
            rf'{re.escape(field)}:\s*(.*?)(?:\n|$)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, section, re.I)
            if match:
                value = match.group(1).strip()
                # Remove trailing bullet points or dashes
                value = re.sub(r'[-*]$', '', value).strip()
                if value:
                    return clean_text(value)
    
    return default


# -------------------------------
# PARSE JOBS
# -------------------------------
def parse_jobs(content):
    jobs = []
    
    # Split by job sections (### 1., ### 2., etc.)
    sections = re.split(r'\n### \d+\.', content)
    
    for sec in sections[1:]:
        job = {}
        
        # Title - first line after the heading
        title_lines = sec.strip().split('\n')
        job["title"] = clean_text(title_lines[0]) if title_lines else ""
        
        # Post Date - look for backtick enclosed
        post_date_match = re.search(r'`Post Date:\s*(.*?)`', sec, re.I)
        if post_date_match:
            job["post_date_raw"] = post_date_match.group(1).strip()
        else:
            job["post_date_raw"] = ""
        job["post_date"] = format_date(job["post_date_raw"])
        
        # Recruitment Board
        job["board"] = extract_field(sec, [
            "Recruitment Board",
            "Recruitment Board"
        ])
        
        # Post Name - try both formats
        job["post_name"] = extract_field(sec, [
            "Exam / Post Name",
            "Post Name"
        ])
        
        # Qualification
        job["qualification"] = extract_field(sec, ["Qualification"])
        # Vacancy (NEW FIX)
        job["vacancy"] = extract_field(sec, ["Vacancy", "No of Posts", "Number of Posts"], default="Not mentioned")
        
        # Last Date - look for backtick enclosed
        last_date_match = re.search(r'`Last Date:\s*(.*?)`', sec, re.I)
        if last_date_match:
            job["last_date_raw"] = last_date_match.group(1).strip()
        else:
            job["last_date_raw"] = ""
        job["last_date"] = format_date(job["last_date_raw"])
        
        # More Info URL
        more_info_match = re.search(r'\[\*\*More Information\*\*\]\((.*?)\)', sec, re.I)
        if not more_info_match:
            more_info_match = re.search(r'\[More Information.*?\]\((.*?)\)', sec, re.I)
        job["more_info"] = more_info_match.group(1) if more_info_match else "#"
        
        # Extract Important Links
        job["links"] = extract_links(sec)
        
        # Only add job if it has at least one valid link
        # Always include job (even if no links exist)
        jobs.append(job)

        if not job["links"]:
            print(f"⚠️ No links found (included anyway): {job['title'][:50]}...")
            
    return jobs


# -------------------------------
# GENERATE HTML
# -------------------------------
def generate_cards_html(jobs):
    cards_html = ""

    for idx, job in enumerate(jobs, 1):
        links_html = ""

        for i, (desc, link) in enumerate(job["links"], 1):
            btn_text = "Open"
            if "website" in desc.lower():
                btn_text = "Visit"
            elif "notification" in desc.lower() or "pdf" in desc.lower():
                btn_text = "Open"

            links_html += f"""
            <tr>
                <td>{i}</td>
                <td>{desc}</td>
                <td><a href="{link}" class="link-btn" target="_blank">{btn_text}</a></td>
            </tr>"""

        cards_html += f"""
<div class="card" data-id="{idx}">
<div class="serial-badge">{idx}</div>

<div class="bookmark-btn" data-id="{idx}" onclick="toggleBookmark(this)">
    ☆
</div>

    <div class="title">
        {job['title']}
    </div>

    <div class="meta">
        <svg class="icon" viewBox="0 0 24 24"><path d="M7 2v2H5a2 2 0 0 0-2 2v2h18V6a2 2 0 0 0-2-2h-2V2h-2v2H9V2H7zm14 8H3v10a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V10z"/></svg>
        {job['post_date']}
    </div>

    <div class="details">
        <p><strong>Recruitment Board:</strong> {job['board']}</p>
        <p><strong>Post Name:</strong> {job['post_name']}</p>
        <p><strong>Qualification:</strong> {job['qualification']}</p>
        <p><strong>Vacancy:</strong> {job['vacancy']}</p>
    </div>

    <div class="highlight">
        Last Date: {job['last_date']}
    </div>

    <a href="{job['more_info'] if job['more_info'] and job['more_info'] != '#' else 'javascript:void(0)'}" 
   class="btn" 
   target="_blank" 
   rel="noopener noreferrer">
        <svg class="icon" viewBox="0 0 24 24"><path d="M14 3v2h3.59L7 15.59 8.41 17 19 6.41V10h2V3z"/><path d="M5 5h6V3H5a2 2 0 0 0-2 2v6h2z"/></svg>
        View Details
    </a>

    <div class="section-title">Important Links</div>

    <table>
        <thead>
            <tr>
                <th>#</th>
                <th>Description</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody>
{links_html}
        </tbody>
    </table>

    <div class="ai-wrap">
        <button class="ai-btn" onclick="aiProcess(this)">
            ✦ AI Process
        </button>
    </div>

</div>

"""
    return cards_html

# -------------------------------
# FULL HTML
# -------------------------------
def generate_full_html(cards_html, title="Latest Govt Jobs Recruitment 2026"):
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>{title}</title>

<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&family=Poppins:wght@400;500;600&family=Playfair+Display:wght@500;600&display=swap" rel="stylesheet">

<style>
:root {{
    --bg: radial-gradient(circle at 20% 20%, #eef2ff, #f8fbff 60%);
    --glass: rgba(255,255,255,0.55);
    --glass-strong: rgba(255,255,255,0.75);
    --border: rgba(255,255,255,0.4);
    --primary: #3b5cff;
    --text: #111;
    --muted: #6b7280;
}}

* {{
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}}

body {{
    font-family: 'Inter', sans-serif;
    background: var(--bg);
    min-height: 100vh;
    padding: 20px;
}}

/* Background blobs */
body::before, body::after {{
    content: "";
    position: fixed;
    width: 300px;
    height: 300px;
    border-radius: 50%;
    filter: blur(120px);
    z-index: 0;
}}

body::before {{
    background: #6c8cff;
    top: -50px;
    left: -50px;
}}

body::after {{
    background: #a5d8ff;
    bottom: -60px;
    right: -60px;
}}

/* Container */
.container {{
    width: 100%;
    max-width: 880px;
    margin: 0 auto;
    position: relative;
    z-index: 2;
}}

/* Card */
.card {{
    position: relative;
    padding: 20px;
    border-radius: 20px;
    background: var(--glass);
    backdrop-filter: blur(22px);
    border: 1px solid var(--border);

    /* FIXED LEFT BORDER */
    border-left: 3px solid var(--primary);

    box-shadow: 
        0 10px 30px rgba(0,0,0,0.06),
        0 2px 6px rgba(0,0,0,0.04);

    transition: all 0.4s ease;
    margin-bottom: 18px;

    overflow: hidden; /* IMPORTANT FIX */
}}

/* Hover */
.card:hover {{
    transform: translateY(-6px) scale(1.01);
    box-shadow: 
        0 25px 80px rgba(0,0,0,0.12),
        0 10px 30px rgba(0,0,0,0.08);
}}

/* SERIAL NUMBER BADGE */
.serial-badge {{
    position: absolute;
    top: 12px;
    left: 12px;
    width: 26px;
    height: 26px;
    border-radius: 50%;
    background: rgba(59,92,255,0.15);
    border: 1px solid rgba(59,92,255,0.3);
    color: var(--primary);
    font-size: 12px;
    font-weight: 600;

    display: flex;
    align-items: center;
    justify-content: center;

    backdrop-filter: blur(10px);
}}

/* BOOKMARK BUTTON */
.bookmark-btn {{
    position: absolute;
    top: 12px;
    right: 12px;

    width: 34px;
    height: 34px;

    border-radius: 10px;

    background: rgba(255,255,255,0.6);
    border: 1px solid rgba(0,0,0,0.08);

    display: flex;
    align-items: center;
    justify-content: center;

    cursor: pointer;
    font-size: 18px;
    transition: all 0.2s ease;
}}

.bookmark-btn:hover {{
    transform: scale(1.08);
    background: rgba(59,92,255,0.12);
}}

.bookmark-btn.active {{
    background: rgba(59,92,255,0.25);
    border-color: rgba(59,92,255,0.4);
    color: #3b5cff;
}}

/* SERIAL BADGE IMPROVED */
.serial-badge {{
    position: absolute;
    top: 12px;
    left: 12px;

    width: 22px;
    height: 22px;
    border-radius: 50%;

    background: rgba(59,92,255,0.15);
    border: 1px solid rgba(59,92,255,0.3);

    color: var(--primary);
    font-size: 11px;
    font-weight: 600;

    display: flex;
    align-items: center;
    justify-content: center;

    backdrop-filter: blur(10px);
}}

.title {{
    font-family: 'Playfair Display', serif;
    font-size: 22px;
    color: var(--primary);
    margin-bottom: 4px;
    line-height: 1.28;
    margin-top: 16px;   /* pushes title below badge */
}}

.meta {{
    font-size: 12px;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 6px;
    margin-bottom: 10px;
}}

.details {{
    font-family: 'Poppins', sans-serif;
    line-height: 1.5;
    font-size: 14px;
}}

.details p {{
    margin-bottom: 2px;
}}

/* LAST DATE (GLASS BLUE) */
.highlight {{
    margin: 10px 0;
    padding: 9px 12px;
    border-radius: 12px;
    font-size: 14px;
    background: linear-gradient(
        135deg,
        rgba(59, 92, 255, 0.12),
        rgba(165, 216, 255, 0.30)
    );

    border: 1px solid rgba(59, 92, 255, 0.30);

    color: #2c4cff;
    font-weight: 600;

    backdrop-filter: blur(10px);
}}

/* Button */
.btn {{
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin-top: 8px;
    padding: 8px 14px;
    border-radius: 10px;
    font-size: 14px;
    background: linear-gradient(135deg, #3b5cff, #6f8cff);
    color: #fff;
    text-decoration: none;
    transition: all 0.3s ease;
}}

.btn:hover {{
    transform: translateY(-2px);
    box-shadow: 0 10px 25px rgba(59,92,255,0.35);
}}

.section-title {{
    margin-top: 14px;
    font-weight: 600;
    font-size: 15px;
    color: var(--primary);
}}

/* TABLE */
table {{
    width: 100%;
    margin-top: 10px;
    border-collapse: collapse;
    border-radius: 14px;
    overflow: hidden;
    background: rgba(255,255,255,0.65);
    backdrop-filter: blur(14px);
}}

thead {{
    background: rgba(59,92,255,0.08);
}}

th {{
    font-weight: 600;
    font-size: 13px;
    padding: 8px;
    text-align: left;
    color: var(--primary);
}}

td {{
    padding: 8px;
    font-size: 14px;
    border-bottom: 1px solid rgba(0,0,0,0.05);
}}

td:nth-child(2) {{
    font-weight: 500;
}}

/* ZEBRA ROWS */
tbody tr:nth-child(odd) {{
    background: rgba(59, 92, 255, 0.03);
}}

tbody tr:nth-child(even) {{
    background: rgba(165, 216, 255, 0.10);
}}

tbody tr {{
    transition: all 0.25s ease;
}}

tbody tr:hover {{
    background: rgba(59, 92, 255, 0.12);
    transform: scale(1.01);
}}

/* FIX ACTION ALIGNMENT */
th:last-child,
td:last-child {{
    text-align: center;
    vertical-align: middle;
}}

.link-btn {{
    display: inline-block;
    min-width: 70px;
    text-align: center;
    padding: 6px 12px;
    border-radius: 6px;
    background: rgba(59,92,255,0.12);
    color: var(--primary);
    font-size: 13px;
    text-decoration: none;
    transition: all 0.25s ease;
}}

.link-btn:hover {{
    background: var(--primary);
    color: #fff;
    transform: scale(1.05);
}}

.icon {{
    width: 16px;
    height: 16px;
    fill: currentColor;
}}

.top-controls{{
    display:flex;
    gap:12px;
    margin-bottom:22px;
    flex-wrap:wrap;
}}

#searchInput{{
    flex:1;
    min-width:220px;
    padding:12px 14px;
    border:none;
    border-radius:12px;
    background:rgba(255,255,255,0.7);
    font-size:14px;
    outline:none;
}}

#sortSelect{{
    padding: 12px 14px;
    min-width: 180px;

    border: 1px solid rgba(255,255,255,0.55);
    border-radius: 14px;

    background:
        linear-gradient(135deg,
        rgba(255,255,255,0.82),
        rgba(240,245,255,0.72));

    color: var(--primary);
    font-size: 14px;
    font-weight: 600;

    outline: none;
    cursor: pointer;

    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);

    box-shadow:
        0 8px 24px rgba(0,0,0,0.06),
        inset 0 1px 0 rgba(255,255,255,0.55);

    appearance: none;
    -webkit-appearance: none;
    -moz-appearance: none;

    background-image:
        linear-gradient(135deg,
        rgba(255,255,255,0.82),
        rgba(240,245,255,0.72)),
        url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='18' height='18' viewBox='0 0 24 24' fill='%233b5cff'><path d='M7 10l5 5 5-5z'/></svg>");

    background-repeat: no-repeat, no-repeat;
    background-position: left top, right 12px center;
    background-size: auto, 16px;

    padding-right: 40px;
    transition: all 0.25s ease;
}}

#sortSelect:hover{{
    transform: translateY(-1px);
    box-shadow:
        0 12px 28px rgba(59,92,255,0.14);
}}

#sortSelect:focus{{
    border-color: rgba(59,92,255,0.35);
    box-shadow:
        0 0 0 4px rgba(59,92,255,0.10);
}}

#sortSelect option{{
    background: #ffffff;
    color: #111;
    font-weight: 500;
}}

.ai-wrap{{
    margin-top: 16px;
    display: flex;
    justify-content: center;
}}

.ai-btn{{
    border: none;
    outline: none;
    cursor: pointer;

    padding: 10px 18px;
    min-width: 170px;

    border-radius: 999px;

    font-size: 14px;
    font-weight: 600;
    letter-spacing: 0.2px;

    color: #fff;

    background: linear-gradient(
        135deg,
        #6a8cff,
        #3b5cff
    );

    box-shadow:
        0 10px 22px rgba(59,92,255,0.22),
        inset 0 1px 0 rgba(255,255,255,0.28);

    transition: all 0.28s ease;
}}

.ai-btn:hover{{
    transform: translateY(-2px) scale(1.02);
    box-shadow:
        0 16px 28px rgba(59,92,255,0.28);
}}

.ai-btn:active{{
    transform: scale(0.97);
}}

.ai-btn.loading{{
    pointer-events: none;
    opacity: 0.88;
}}

@media (max-width: 600px) {{
    .card {{
        padding: 16px;
    }}

    .title {{
        font-size: 19px;
        margin-top: 16px;
    }}

    td, th {{
        padding: 7px;
        font-size: 13px;
    }}

    .btn {{
        width: 100%;
        justify-content: center;
    }}
}}
</style>
</head>

<body>

<div class="container">

<div class="top-controls">

    <input type="text" id="searchInput" placeholder="Search jobs...">

    <select id="sortSelect" onchange="sortCards()">
        <option value="">Arrange By</option>
        <option value="vac_high">Vacancy High</option>
        <option value="vac_low">Vacancy Low</option>
        <option value="closed">Closed Soon</option>
    </select>

</div>

<div id="cardsWrap">
{cards_html}
</div>

</div>

<script>

function toggleBookmark(el){{
    const id = el.getAttribute("data-id");
    let bookmarks = JSON.parse(localStorage.getItem("bookmarks") || "[]");

    if(bookmarks.includes(id)){{
        bookmarks = bookmarks.filter(x => x !== id);
        el.classList.remove("active");
        el.innerHTML = "☆";
    }} else {{
        bookmarks.push(id);
        el.classList.add("active");
        el.innerHTML = "★";
    }}

    localStorage.setItem("bookmarks", JSON.stringify(bookmarks));
}}

window.addEventListener("DOMContentLoaded", () => {{

    let bookmarks = JSON.parse(localStorage.getItem("bookmarks") || "[]");

    document.querySelectorAll(".bookmark-btn").forEach(btn => {{
        const id = btn.getAttribute("data-id");

        if(bookmarks.includes(id)){{
            btn.classList.add("active");
            btn.innerHTML = "★";
        }}
    }});

    document.getElementById("searchInput").addEventListener("keyup", searchCards);

}});

function searchCards(){{
    let val = document.getElementById("searchInput").value.toLowerCase();

    document.querySelectorAll(".card").forEach(card => {{
        let txt = card.innerText.toLowerCase();
        card.style.display = txt.includes(val) ? "block" : "none";
    }});
}}

function getVacancy(card){{
    let txt = card.innerText.match(/Vacancy:\s*(\d+)/i);
    return txt ? parseInt(txt[1]) : 0;
}}

function getLastDate(card){{
    let txt = card.innerText.match(/Last Date:\s*(.*)/i);
    return txt ? new Date(txt[1]) : new Date("2100-01-01");
}}

function sortCards(){{
    let type = document.getElementById("sortSelect").value;
    let wrap = document.getElementById("cardsWrap");
    let cards = Array.from(document.querySelectorAll(".card"));

    if(type === "vac_high"){{
        cards.sort((a, b) => getVacancy(b) - getVacancy(a));
    }}

    if(type === "vac_low"){{
        cards.sort((a, b) => getVacancy(a) - getVacancy(b));
    }}

    if(type === "closed"){{
        cards.sort((a, b) => getLastDate(a) - getLastDate(b));
    }}

    cards.forEach(card => {{
        wrap.appendChild(card);
    }});
}}

function aiProcess(btn){{
    const oldText = btn.innerHTML;

    btn.classList.add("loading");

    btn.innerHTML = `
        <svg class="icon spin ai-icon" viewBox="0 0 24 24">
            <path d="M12 2a10 10 0 1 0 10 10h-2a8 8 0 1 1-8-8V2z"/>
        </svg>
        <span>Processing...</span>
    `;

    setTimeout(() => {{

        btn.innerHTML = `
            <svg class="icon ai-icon" viewBox="0 0 24 24">
                <path d="M9 16.2l-3.5-3.5L4 14.2l5 5L20 8.2l-1.5-1.4z"/>
            </svg>
            <span>Done</span>
        `;

        setTimeout(() => {{
            btn.classList.remove("loading");
            btn.innerHTML = oldText;
        }}, 1400);

    }}, 1800);
}}

</script>

</body>
</html>"""

# -------------------------------
# MAIN
# -------------------------------
def main():
    try:
        with open(INPUT_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"❌ ERROR: {INPUT_FILE} not found!")
        return
    
    print("🔍 Parsing jobs from markdown...")
    jobs = parse_jobs(content)
    print(f"📊 Successfully parsed {len(jobs)} jobs with valid links")
    
    if not jobs:
        print("❌ No valid jobs found!")
        return
    
    # Generate HTML
    cards_html = generate_cards_html(jobs)
    full_html = generate_full_html(cards_html, f"Latest Govt Jobs - {len(jobs)} Opportunities")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(full_html)
    
    print(f"✅ DONE: {len(jobs)} jobs → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()