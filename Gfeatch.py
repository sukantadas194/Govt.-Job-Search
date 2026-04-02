import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re


# -------------------------------
# FILTER FUNCTION (QUALIFICATION + DATE)
# -------------------------------
def qualification_and_date_filter(qualification_text, last_date_text):
    keywords = ["Any Graduate", "Any Bachelors Degree", "B.Tech"]

    # Qualification check
    qualification_ok = any(
        keyword.lower() in qualification_text.lower()
        for keyword in keywords
    )

    # Date check
    try:
        last_date = datetime.strptime(last_date_text, "%d-%m-%Y").date()
        today = datetime.today().date()
        date_ok = last_date >= today
    except:
        date_ok = False

    return qualification_ok and date_ok


def qualification_and_date_filter(qualification_text, last_date_text):
    keywords = ["Any Graduate", "Any Bachelors Degree", "B.Tech"]

    # Qualification check
    qualification_ok = any(
        keyword.lower() in qualification_text.lower()
        for keyword in keywords
    )

    print(f"\n--- Processing ---")
    print(f"Qualification text: '{qualification_text}'")
    print(f"Last date text: '{last_date_text}'")
    print(f"Last date raw bytes: {[hex(ord(c)) for c in last_date_text]}")

    # Date check
    try:
        # Try to parse with different formats
        last_date = None

        # Try DD-MM-YYYY format
        try:
            last_date = datetime.strptime(last_date_text.strip(), "%d-%m-%Y").date()
            print(f"Parsed with DD-MM-YYYY: {last_date}")
        except:
            pass

        # Try DD/MM/YYYY format
        if not last_date:
            try:
                last_date = datetime.strptime(last_date_text.strip(), "%d/%m/%Y").date()
                print(f"Parsed with DD/MM/YYYY: {last_date}")
            except:
                pass

        if last_date:
            today = datetime.today().date()
            print(f"Today: {today}")
            date_ok = last_date >= today
            print(f"Date OK: {date_ok}")
        else:
            print(f"Could not parse date: '{last_date_text}'")
            date_ok = False

    except Exception as e:
        print(f"Date parsing error: {e}")
        date_ok = False

    result = qualification_ok and date_ok
    print(f"Final filter result: {result}")
    return result

# -------------------------------
# FILTER UNWANTED LINKS
# -------------------------------
def is_unwanted_link(description):
    """Check if a link should be excluded"""
    unwanted_patterns = [
        "arattai",
        "telegram",
        "whatsapp",
        "sarkari result",
        "download mobile app",
        "mobile app",
        "join arattai",
        "join telegram",
        "join whatsapp"
    ]

    desc_lower = description.lower()
    return any(pattern in desc_lower for pattern in unwanted_patterns)


# -------------------------------
# EXTRACT IMPORTANT LINKS FROM DIFFERENT PATTERNS
# -------------------------------
# -------------------------------
# EXTRACT IMPORTANT LINKS FROM DIFFERENT PATTERNS
# -------------------------------
def extract_important_links(soup, heading_element):
    """Extract important links using various patterns"""

    extracted_data = []  # List of tuples (description, link)

    # Find the div.table-container that follows the heading
    # Look for div with table-container class that's near the heading
    table_container = None

    # Try to find the closest table-container after the heading
    for element in heading_element.find_all_next():
        if element.name == "div" and element.get("class") and "table-container" in element.get("class"):
            table_container = element
            break

    # ==============================
    # PATTERN 1: Table with thead/tbody structure (MP Apex Bank style)
    # ==============================
    if table_container:
        table = table_container.find("table")
        if table:
            # Check if table has thead
            thead = table.find("thead")
            tbody = table.find("tbody")

            if tbody:
                rows = tbody.find_all("tr")

                # Skip header row if it's the first row (for tables without thead)
                start_idx = 0
                if not thead and rows:
                    first_row = rows[0]
                    first_row_text = first_row.get_text(strip=True).lower()
                    if "link type" in first_row_text or "description" in first_row_text or "action" in first_row_text:
                        start_idx = 1

                for row in rows[start_idx:]:
                    cols = row.find_all("td")
                    if len(cols) >= 2:
                        # Get the raw description without modifying it
                        description = cols[0].get_text(" ", strip=True)

                        # Skip unwanted links based on description
                        if is_unwanted_link(description):
                            continue

                        a_tag = cols[1].find("a")
                        if a_tag:
                            link = a_tag.get("href")
                            if link and not link.startswith('#'):
                                extracted_data.append((description, link))

                if extracted_data:
                    return extracted_data

    # ==============================
    # PATTERN 2: Simple UL/LI format
    # ==============================
    # Find the nearest ul after the heading
    ul_element = heading_element.find_next("ul")
    if ul_element:
        items = ul_element.find_all("li")
        for li in items:
            a_tag = li.find("a")
            if not a_tag:
                continue

            # Get the full text first
            full_text = li.get_text(" ", strip=True)

            # Try to extract description by removing the link text
            link_text = a_tag.get_text(strip=True)
            description = full_text

            # Remove the link text if it appears at the end (common pattern)
            if full_text.endswith(link_text):
                description = full_text[:-len(link_text)].strip()
            elif link_text in full_text:
                # If link text is in the middle, split and take the first part
                parts = full_text.split(link_text, 1)
                description = parts[0].strip()

            # Clean up any remaining "click here" but keep the actual description
            description = re.sub(r'click\s*here$', '', description, flags=re.IGNORECASE)
            description = re.sub(r':$', '', description).strip()

            # Skip unwanted links
            if is_unwanted_link(description):
                continue

            link = a_tag.get("href")
            if link and not link.startswith('#'):
                extracted_data.append((description, link))

        if extracted_data:
            return extracted_data

    # ==============================
    # PATTERN 3: Direct table without container
    # ==============================
    # Look for table that might contain important links
    table = heading_element.find_next("table")
    if table:
        rows = table.find_all("tr")

        # Skip header row if it exists
        start_idx = 0
        if rows:
            first_row_text = rows[0].get_text(strip=True).lower()
            if "link type" in first_row_text or "description" in first_row_text or "action" in first_row_text:
                start_idx = 1

        for row in rows[start_idx:]:
            cols = row.find_all("td")
            if len(cols) >= 2:
                # Get the raw description without modifying it
                description = cols[0].get_text(" ", strip=True)

                # Skip unwanted links
                if is_unwanted_link(description):
                    continue

                a_tag = cols[1].find("a")
                if a_tag:
                    link = a_tag.get("href")
                    if link and not link.startswith('#'):
                        extracted_data.append((description, link))

        if extracted_data:
            return extracted_data

    # ==============================
    # PATTERN 4: P with links format
    # ==============================
    # Look for paragraphs containing links near the heading
    for p in heading_element.find_all_next("p", limit=10):
        if "Important Link" in p.get_text() or "Important Links" in p.get_text():
            continue

        a_tags = p.find_all("a")
        for a in a_tags:
            # Get the paragraph text
            p_text = p.get_text(" ", strip=True)
            a_text = a.get_text(strip=True)

            # Try to get description from before the link
            if a_text in p_text:
                parts = p_text.split(a_text, 1)
                description = parts[0].strip()
            else:
                description = a_text

            # Clean up but preserve the main description
            description = re.sub(r':$', '', description).strip()
            description = re.sub(r'click\s*here$', '', description, flags=re.IGNORECASE).strip()

            if description and not is_unwanted_link(description):
                link = a.get("href")
                if link and not link.startswith('#'):
                    # Check if this description+link combo already exists
                    if not any(desc == description and lnk == link for desc, lnk in extracted_data):
                        extracted_data.append((description, link))

        if extracted_data:
            # Don't return immediately, collect all links from paragraphs
            continue

    return extracted_data


# -------------------------------
# FETCH IMPORTANT LINKS FUNCTION - UPDATED FORMAT
# -------------------------------
# -------------------------------
# FETCH IMPORTANT LINKS FUNCTION - UPDATED FORMAT WITH POLISHING
# -------------------------------
def fetch_important_links(job_url, serial_no, file_handle, job_title, post_date="", recruitment_board="", exam_name="",
                          qualification="", last_date="", more_info_link=""):
    print(f"\n🔎 Processing Job #{serial_no}: {job_title}")
    print(f"🌐 Visiting Page: {job_url}")

    try:
        response = requests.get(job_url, timeout=15)

        if response.status_code != 200:
            print(f"❌ Failed to open page — Status Code: {response.status_code}")
            return

        print("✅ Page visited successfully")

        soup = BeautifulSoup(response.text, "html.parser")

        # ==============================
        # FIND IMPORTANT LINKS HEADING
        # ==============================
        important_heading = None

        # Try different heading patterns
        heading_patterns = [
            # h2 with Important Links text
            lambda tag: (tag.name in ["h1", "h2", "h3", "h4"] and
                         "important link" in tag.get_text(strip=True).lower()),
            # h2 with dash format (MP Apex Bank style)
            lambda tag: (tag.name == "h2" and
                         "important links" in tag.get_text(strip=True).lower() and
                         "–" in tag.get_text()),
            # td with colspan (table inside table pattern)
            lambda tag: (tag.name == "td" and tag.has_attr("colspan") and
                         "important link" in tag.get_text(strip=True).lower()),
            # span with Important Links
            lambda tag: (tag.name == "span" and
                         "important link" in tag.get_text(strip=True).lower()),
            # p with Important Links
            lambda tag: (tag.name == "p" and
                         "important link" in tag.get_text(strip=True).lower()),
            # strong with Important Links
            lambda tag: (tag.name == "strong" and
                         "important link" in tag.get_text(strip=True).lower()),
            # Any element with Important Links text
            lambda tag: ("important link" in tag.get_text(strip=True).lower() and
                         tag.name in ["h1", "h2", "h3", "h4", "td", "span", "p", "strong", "div"])
        ]

        for pattern in heading_patterns:
            important_heading = soup.find(pattern)
            if important_heading:
                break

        if not important_heading:
            print("❌ Important Links section NOT FOUND")
            return

        print(f"✅ Found Important Links heading: {important_heading.get_text(strip=True)[:50]}...")

        # Extract links using various patterns
        extracted_links = extract_important_links(soup, important_heading)

        if not extracted_links:
            print("❌ No relevant important links found")
            return

        # Remove duplicates while preserving order
        unique_links = []
        seen = set()
        for desc, link in extracted_links:
            if (desc, link) not in seen:
                seen.add((desc, link))
                unique_links.append((desc, link))

        # Extract vacancy from exam_name if it contains '– Number Posts' pattern
        vacancy = ""
        exam_name_without_vacancy = exam_name

        # Pattern to match "– X Posts" or "– X Post" anywhere in the string
        vacancy_pattern = r'–\s*(\d+\s*Posts?)'
        vacancy_match = re.search(vacancy_pattern, exam_name, re.IGNORECASE)

        if vacancy_match:
            vacancy = vacancy_match.group(1).strip()
            # Remove the vacancy part from exam_name for the Exam / Post Name field
            exam_name_without_vacancy = exam_name.replace(vacancy_match.group(0), '').strip()
            # Clean up any trailing spaces or extra dashes
            exam_name_without_vacancy = re.sub(r'\s+$', '', exam_name_without_vacancy)
            # Ensure no double spaces
            exam_name_without_vacancy = re.sub(r'\s+', ' ', exam_name_without_vacancy)

        # Write to file in the new desired format
        file_handle.write(
            f"### {serial_no}. {recruitment_board} - {exam_name_without_vacancy}\n\n"
        )

        file_handle.write(f"`Post Date: {post_date}`  \n\n")

        file_handle.write(f"- **Recruitment Board:** {recruitment_board}  \n\n")

        # Write Exam / Post Name WITHOUT the vacancy part
        file_handle.write(f"- **Exam / Post Name:** {exam_name_without_vacancy}\n\n")

        if vacancy:
            file_handle.write(f"- **Vacancy:** {vacancy} \n\n")

        file_handle.write(f"- **Qualification:** {qualification}  \n\n")

        file_handle.write(f"`Last Date: {last_date}`  \n\n")

        file_handle.write(f"- [**More Information**]({more_info_link})\n\n")

        file_handle.write(f"### **Important Links —**\n\n")

        file_handle.write("| # | Description | Link |\n")
        file_handle.write("|---|--------------|------|\n")

        for idx, (description, link) in enumerate(unique_links, 1):
            file_handle.write(f"| {idx} | {description} | [Click here]({link}) |\n")
            print(f"✔ Extracted: {description}")

        file_handle.write("\n\n---\n\n")
        print(f"✅ Important Links extracted correctly - {len(unique_links)} links found")

    except requests.exceptions.Timeout:
        print("❌ Timeout while visiting page")
    except requests.exceptions.RequestException as e:
        print(f"❌ Request error: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")


# -------------------------------
# REMOVE DUPLICATE JOB POSTINGS FROM OP2.MD
# -------------------------------
def remove_duplicate_jobs_from_op2(op2_file_path):
    """
    Read op2.md, identify duplicate job postings based on Recruitment Board + Exam/Post Name,
    keep first occurrence, remove duplicates, and renumber serial numbers.
    """
    with open(op2_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # Split content into individual job postings
    # Each job posting starts with "### " and ends with "---"
    job_pattern = r'(### \d+\..*?)(?=\n---\n\n|\Z)'
    job_matches = re.findall(job_pattern, content, re.DOTALL)

    if not job_matches:
        print("No job postings found in op2.md")
        return

    print(f"Found {len(job_matches)} job postings before duplicate removal")

    # Dictionary to track unique jobs (key: Recruitment Board + Exam/Post Name)
    unique_jobs = {}
    unique_jobs_list = []

    for job in job_matches:
        # Extract Recruitment Board and Exam/Post Name
        # Pattern: "### X. Recruitment Board - Exam/Post Name"
        board_exam_match = re.search(r'### \d+\.\s*(.+?)\s*-\s*(.+?)(?=\n)', job)

        if board_exam_match:
            board = board_exam_match.group(1).strip()
            exam = board_exam_match.group(2).strip()
            key = f"{board}|{exam}"  # Unique key

            if key not in unique_jobs:
                unique_jobs[key] = True
                unique_jobs_list.append(job)
                print(f"Keeping: {board} - {exam}")
            else:
                print(f"Removing duplicate: {board} - {exam}")
        else:
            # If pattern doesn't match, keep the job (fallback)
            unique_jobs_list.append(job)

    print(f"Keeping {len(unique_jobs_list)} unique job postings")

    # Renumber serial numbers sequentially
    renumbered_jobs = []
    for idx, job in enumerate(unique_jobs_list, 1):
        # Replace the serial number in "### X." with new number
        renumbered_job = re.sub(r'### \d+\.', f'### {idx}.', job, count=1)
        renumbered_jobs.append(renumbered_job)

    # Rebuild the content with proper separators
    new_content = '\n\n---\n\n'.join(renumbered_jobs)

    # Write back to file
    with open(op2_file_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    print(f"✅ Duplicate removal complete. Final count: {len(renumbered_jobs)} jobs")

# -------------------------------
# MAIN SCRIPT
# -------------------------------

url = "https://www.freejobalert.com/latest-notifications/"
response = requests.get(url)
soup = BeautifulSoup(response.text, "html.parser")

sections = soup.find_all("h4", class_="latsec")
tables = soup.find_all("table", class_="lattbl")

serial_no = 1

with open("output.md", "w", encoding="utf-8") as out_file, \
        open("op2.md", "w", encoding="utf-8") as op2_file:
    for section, table in zip(sections, tables):
        section_title = section.get_text(strip=True)

        rows = table.find_all("tr")
        filtered_data = []

        for row in rows[1:]:
            cols = row.find_all("td")

            if len(cols) >= 7:
                post_date = cols[0].get_text(strip=True)
                recruitment_board = cols[1].get_text(strip=True)
                exam_name = cols[2].get_text(strip=True)
                qualification_text = cols[3].get_text(strip=True)
                last_date_text = cols[5].get_text(strip=True)

                # APPLY NEW FILTER
                if qualification_and_date_filter(qualification_text, last_date_text):

                    data = []

                    # Select columns except Advt No (skip index 4)
                    for i in [0, 1, 2, 3, 5]:
                        data.append(cols[i].get_text(strip=True))

                    # More Info link
                    more_info_col = cols[6]
                    link_tag = more_info_col.find("a")

                    if link_tag and link_tag.has_attr("href"):
                        job_link = link_tag["href"]
                        link_text = link_tag.get_text(strip=True)

                        data.append(f"[{link_text}]({job_link})")

                        # FETCH IMPORTANT LINKS PAGE WITH ALL DETAILS
                        full_title = f"{recruitment_board} - {exam_name}"

                        fetch_important_links(job_link, serial_no, op2_file, full_title,
                                              post_date, recruitment_board, exam_name,
                                              qualification_text, last_date_text, job_link)

                        serial_no += 1

                    else:
                        data.append(more_info_col.get_text(strip=True))

                    filtered_data.append(data)

        if filtered_data:
            out_file.write(f"## {section_title}\n\n")
            out_file.write(
                "| Post Date | Recruitment Board | Exam / Post Name | Qualification | Last Date | More Information |\n")
            out_file.write(
                "|-----------|-------------------|------------------|--------------|-----------|------------------|\n")

            for data in filtered_data:
                out_file.write("| " + " | ".join(data) + " |\n")

            out_file.write("\n\n")

print("✅ output.md and op2.md created successfully")

# After generating both output files, remove duplicates from op2.md
remove_duplicate_jobs_from_op2("op2.md")
print("✅ Duplicate check completed - op2.md now contains only unique job postings with correct serial numbers")