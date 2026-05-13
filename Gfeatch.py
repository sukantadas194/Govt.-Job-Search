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
def extract_important_links(soup, heading_element, job_url):
    """Extract important links using various patterns with strict section boundaries"""
    
    extracted_data = []
    
    # Get the current job heading
    current_heading = heading_element
    
    print(f"  📍 Heading found: {current_heading.get_text(strip=True)[:100]}")
    
    # ==============================
    # Find the article container that contains this heading
    # ==============================
    article_container = None
    for parent in current_heading.parents:
        if parent.name == 'article':
            article_container = parent
            break
        if parent.name == 'div' and parent.get('class'):
            class_str = ' '.join(parent.get('class')).lower()
            if any(x in class_str for x in ['post', 'article', 'content', 'main', 'entry-content']):
                article_container = parent
                break
    
    if not article_container:
        article_container = current_heading.find_parent('div', class_=lambda x: x and ('post' in x or 'article' in x))
    
    if not article_container:
        article_container = current_heading.parent
    
    print(f"  📦 Article container: {article_container.name if article_container else 'None'}")
    
    # ==============================
    # COMPREHENSIVE FILTER for unwanted links (MANDATORY)
    # ==============================
    def is_unwanted_link_text(description):
        """Check if link description is unwanted - MUST NOT BE ADDED"""
        unwanted_patterns = [
            # Social media & channels
            'sarkari result', 'join telegram', 'join whatsapp', 'download mobile app', 
            'mobile app', 'join arattai', 'arattai channel', 'whatsapp channel',
            'telegram channel', 'telegram group', 'whatsapp group', 'arattai',
            
            # Navigation
            'home', 'latest jobs', 'employment news', 'search jobs', 'sarkari job',
            'sarkari naukri', 'sarkari naukari', 'anganwadi recruitment',
            'forest department jobs', 'education', 'admit card', 'result', 'answer key',
            'syllabus', 'previous papers', 'old papers', 'sample papers',
            
            # Generic/duplicate
            'click here', 'read more', 'learn more', 'view details', 'more info',
            
            # Non-job related
            'free job alert', 'freejobalert', 'notification (employment news)',
            'employment news notification', 'addendum', 'cancellation notice'
        ]
        
        desc_lower = description.lower().strip()
        
        for pattern in unwanted_patterns:
            if pattern in desc_lower:
                return True
        
        if len(desc_lower) < 3:
            return True
        
        return False
    
    def is_valid_job_link(link):
        """Check if link is a valid job-related link"""
        if not link or link.startswith('#'):
            return False
        
        blocked_urls = [
            'freejobalert.com/latest-notifications',
            'freejobalert.com/employment-news',
            'freejobalert.com/search-jobs',
            'freejobalert.com/sarkarijob',
            'freejobalert.com/sarkari-naukri',
            'freejobalert.com/anganwadi-recruitment',
            'freejobalert.com/forest-department-jobs',
            'freejobalert.com/education',
            'rebrand.ly',
            't.me/FreeJobAlertOfficially',
            'play.google.com/store/apps/details?id=com.freejobalert',
            'whatsapp.com/channel/0029VbBXKhkCsU9UG2tVla0X',
            'sarkariresult.freejobalert.com',
            'web.arattai.in/@freejobalertcom',
            'arattai.in'
        ]
        
        for blocked in blocked_urls:
            if blocked in link:
                return False
        
        return True
    
    # ==============================
    # PATTERN 1: Table containing "Important Links" text (SSC, EIL, CNP Nashik style)
    # ==============================
    if article_container:
        all_tables = article_container.find_all('table')
        
        for table in all_tables:
            table_text = table.get_text(strip=True).lower()
            if 'important links' in table_text:
                print(f"  ✅ Found table with 'Important Links' text")
                rows = table.find_all('tr')
                
                for row in rows:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        description = cols[0].get_text(' ', strip=True)
                        row_text = row.get_text(strip=True).lower()
                        
                        if 'important links' in row_text:
                            continue
                        
                        if not description or len(description) < 2:
                            continue
                        
                        if is_unwanted_link_text(description):
                            continue
                        
                        a_tag = cols[1].find('a')
                        if a_tag:
                            link = a_tag.get('href')
                            if is_valid_job_link(link):
                                description = re.sub(r':$', '', description).strip()
                                extracted_data.append((description, link))
                                print(f"    ✓ Extracted: {description}")
                
                if extracted_data:
                    return extracted_data
    
    # ==============================
    # PATTERN 2: div.table-container with preceding Important Links heading
    # ==============================
    if not extracted_data and article_container:
        table_containers = article_container.find_all('div', class_=lambda x: x and 'table-container' in x)
        
        for container in table_containers:
            prev_h2 = container.find_previous(['h2', 'h3'])
            if prev_h2 and 'important links' in prev_h2.get_text(strip=True).lower():
                table = container.find('table')
                if table:
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = row.find_all('td')
                        if len(cols) >= 2:
                            description = cols[0].get_text(' ', strip=True)
                            if not description or description.lower() == 'link description':
                                continue
                            
                            if is_unwanted_link_text(description):
                                continue
                            
                            a_tag = cols[1].find('a')
                            if a_tag:
                                link = a_tag.get('href')
                                if is_valid_job_link(link):
                                    description = re.sub(r':$', '', description).strip()
                                    extracted_data.append((description, link))
                    
                    if extracted_data:
                        return extracted_data
    
    # ==============================
    # PATTERN 3: Table with th headers (AYJNISHD, NCPOR, DRDO, Vikas Souharda style)
    # ==============================
    if not extracted_data and article_container:
        all_tables = article_container.find_all('table')
        
        for table in all_tables:
            rows = table.find_all('tr')
            if not rows:
                continue
            
            first_row = rows[0]
            header_cols = first_row.find_all('th')
            
            if header_cols and len(header_cols) >= 2:
                print(f"  ✅ Found table with th headers")
                for row in rows[1:]:
                    cols = row.find_all('td')
                    if len(cols) >= 2:
                        description = cols[0].get_text(' ', strip=True)
                        if not description or description.lower() == 'link description':
                            continue
                        
                        if is_unwanted_link_text(description):
                            continue
                        
                        a_tag = cols[1].find('a')
                        if a_tag:
                            link = a_tag.get('href')
                            if is_valid_job_link(link):
                                description = re.sub(r':$', '', description).strip()
                                extracted_data.append((description, link))
                
                if extracted_data:
                    return extracted_data
    
    # ==============================
    # PATTERN 4: UL/LI format after Important Links heading
    # ==============================
    if not extracted_data and article_container:
        for heading in article_container.find_all(['h2', 'h3', 'h4']):
            if 'important links' in heading.get_text(strip=True).lower():
                ul_element = heading.find_next('ul')
                if ul_element:
                    items = ul_element.find_all('li')
                    for li in items:
                        a_tag = li.find('a')
                        if a_tag:
                            full_text = li.get_text(' ', strip=True)
                            link_text = a_tag.get_text(strip=True)
                            description = full_text.replace(link_text, '').strip()
                            description = re.sub(r'click\s*here$', '', description, flags=re.IGNORECASE)
                            description = re.sub(r':$', '', description).strip()
                            
                            if description and not is_unwanted_link_text(description):
                                link = a_tag.get('href')
                                if is_valid_job_link(link):
                                    extracted_data.append((description, link))
                    
                    if extracted_data:
                        return extracted_data
    
    # ==============================
    # PATTERN 5: Paragraphs with links after Important Links heading
    # ==============================
    if not extracted_data:
        for heading in current_heading.find_next_siblings():
            if heading.name and heading.name[0] == 'h' and len(heading.name) == 2:
                break
            if heading.name == 'p':
                a_tags = heading.find_all('a')
                for a in a_tags:
                    p_text = heading.get_text(' ', strip=True)
                    a_text = a.get_text(strip=True)
                    description = p_text.split(a_text)[0].strip()
                    description = re.sub(r':$', '', description).strip()
                    description = re.sub(r'click\s*here$', '', description, flags=re.IGNORECASE).strip()
                    
                    if description and not is_unwanted_link_text(description):
                        link = a.get('href')
                        if is_valid_job_link(link):
                            extracted_data.append((description, link))
                
                if extracted_data:
                    return extracted_data
    
    if not extracted_data:
        print(f"  ⚠️ No important links found")
    
    return extracted_data

    # ==============================
    # PATTERN 6: UL/LI after H2 heading (New pattern for examples 1 & 2)
    # ==============================
    if not extracted_data:
        # Look for h2 or h3 headings that contain "Important Links"
        for heading in soup.find_all(['h2', 'h3']):
            heading_text = heading.get_text(strip=True).lower()
            if 'important links' in heading_text:
                
                # Find the next ul after this heading
                # Skip over any intervening divs (like ads) to find the ul
                next_ul = heading.find_next('ul')
                
                if next_ul:
                    print(f"  ✅ Found UL after heading: {heading_text[:50]}")
                    
                    # Process each li item
                    items = next_ul.find_all('li')
                    for li in items:
                        # Find the strong tag for description
                        strong_tag = li.find('strong')
                        
                        if strong_tag:
                            # Extract description from strong tag
                            description = strong_tag.get_text(strip=True)
                            # Remove colon if present
                            description = re.sub(r':$', '', description).strip()
                            
                            # Find the link
                            a_tag = li.find('a')
                            if a_tag:
                                link = a_tag.get('href')
                                
                                # Validate and add if not unwanted
                                if description and not is_unwanted_link_text(description) and is_valid_job_link(link):
                                    extracted_data.append((description, link))
                                    print(f"    ✓ Extracted: {description} -> {link[:50]}...")
                        else:
                            # Fallback: if no strong tag, try to extract from link text
                            a_tag = li.find('a')
                            if a_tag:
                                full_text = li.get_text(' ', strip=True)
                                a_text = a_tag.get_text(strip=True)
                                description = full_text.replace(a_text, '').strip()
                                description = re.sub(r'click\s*here$', '', description, flags=re.IGNORECASE)
                                description = re.sub(r':$', '', description).strip()
                                
                                if description and not is_unwanted_link_text(description):
                                    link = a_tag.get('href')
                                    if is_valid_job_link(link):
                                        extracted_data.append((description, link))
                                        print(f"    ✓ Extracted (fallback): {description}")
                    
                    # If we found data, return it
                    if extracted_data:
                        return extracted_data
    
    if not extracted_data:
        print(f"  ⚠️ No important links found")
    
    return extracted_data

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
            lambda tag: (tag.name in ["h1", "h2", "h3", "h4"] and
                         "important link" in tag.get_text(strip=True).lower()),
            lambda tag: (tag.name == "h2" and
                         "important links" in tag.get_text(strip=True).lower() and
                         "–" in tag.get_text()),
            lambda tag: (tag.name == "td" and tag.has_attr("colspan") and
                         "important link" in tag.get_text(strip=True).lower()),
            lambda tag: (tag.name == "span" and
                         "important link" in tag.get_text(strip=True).lower()),
            lambda tag: (tag.name == "p" and
                         "important link" in tag.get_text(strip=True).lower()),
            lambda tag: (tag.name == "strong" and
                         "important link" in tag.get_text(strip=True).lower()),
            lambda tag: ("important link" in tag.get_text(strip=True).lower() and
                         tag.name in ["h1", "h2", "h3", "h4", "td", "span", "p", "strong", "div"])
        ]

        for pattern in heading_patterns:
            important_heading = soup.find(pattern)
            if important_heading:
                break

        if not important_heading:
            print("❌ Important Links section NOT FOUND")
            # Write empty section? No, just return without writing anything
            return

        print(f"✅ Found Important Links heading: {important_heading.get_text(strip=True)[:50]}...")

        # Extract links using various patterns
        extracted_links = extract_important_links(soup, important_heading, job_url)

        if not extracted_links:
            print("❌ No relevant important links found")
            # Don't write anything if no links found
            return

        # Remove duplicates while preserving order
        unique_links = []
        seen = set()
        for desc, link in extracted_links:
            if (desc, link) not in seen:
                seen.add((desc, link))
                unique_links.append((desc, link))

        # Extract vacancy from exam_name
        vacancy = ""
        exam_name_without_vacancy = exam_name
        vacancy_pattern = r'–\s*(\d+\s*Posts?)'
        vacancy_match = re.search(vacancy_pattern, exam_name, re.IGNORECASE)

        if vacancy_match:
            vacancy = vacancy_match.group(1).strip()
            exam_name_without_vacancy = exam_name.replace(vacancy_match.group(0), '').strip()
            exam_name_without_vacancy = re.sub(r'\s+$', '', exam_name_without_vacancy)
            exam_name_without_vacancy = re.sub(r'\s+', ' ', exam_name_without_vacancy)

        # Write to file IMMEDIATELY
        file_handle.write(f"### {serial_no}. {recruitment_board} - {exam_name_without_vacancy}\n\n")
        file_handle.write(f"`Post Date: {post_date}`  \n\n")
        file_handle.write(f"- **Recruitment Board:** {recruitment_board}  \n\n")
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
        
        # FORCE FLUSH to disk immediately
        file_handle.flush()
        
        print(f"✅ Important Links extracted - {len(unique_links)} links written to file")

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
# MAIN SCRIPT - REAL-TIME WRITING
# -------------------------------

url = "https://www.freejobalert.com/latest-notifications/"
response = requests.get(url)
soup = BeautifulSoup(response.text, "html.parser")

sections = soup.find_all("h4", class_="latsec")
tables = soup.find_all("table", class_="lattbl")

serial_no = 1

# Open output.md for writing (overwrite)
with open("output.md", "w", encoding="utf-8") as out_file:
    # Open op2.md for writing (overwrite)
    with open("op2.md", "w", encoding="utf-8") as op2_file:
        
        for section, table in zip(sections, tables):
            section_title = section.get_text(strip=True)
            
            # Write section header to output.md
            out_file.write(f"## {section_title}\n\n")
            out_file.write(
                "| Post Date | Recruitment Board | Exam / Post Name | Qualification | Last Date | More Information |\n")
            out_file.write(
                "|-----------|-------------------|------------------|--------------|-----------|------------------|\n")
            
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
                            
                            # Write to output.md immediately
                            out_file.write("| " + " | ".join(data) + " |\n")
                            out_file.flush()  # Force write to disk
                            
                            # FETCH IMPORTANT LINKS PAGE WITH ALL DETAILS
                            full_title = f"{recruitment_board} - {exam_name}"
                            
                            print(f"\n{'='*60}")
                            print(f"📝 PROCESSING JOB #{serial_no}: {full_title}")
                            print(f"{'='*60}")
                            
                            # Write to op2.md in real-time
                            fetch_important_links(job_link, serial_no, op2_file, full_title,
                                                  post_date, recruitment_board, exam_name,
                                                  qualification_text, last_date_text, job_link)
                            
                            # Force flush op2_file to disk
                            op2_file.flush()
                            
                            serial_no += 1
                            
                        else:
                            data.append(more_info_col.get_text(strip=True))
                            out_file.write("| " + " | ".join(data) + " |\n")
                            out_file.flush()
                        
                        filtered_data.append(data)
            
            # Add extra newline after section
            if filtered_data:
                out_file.write("\n\n")
                out_file.flush()
        
        print(f"\n{'='*60}")
        print(f"✅ Total jobs processed: {serial_no - 1}")
        print(f"{'='*60}")

# After generating both output files, remove duplicates from op2.md
print("\n🔍 Removing duplicate job postings from op2.md...")
remove_duplicate_jobs_from_op2("op2.md")
print("✅ Duplicate check completed - op2.md now contains only unique job postings with correct serial numbers")