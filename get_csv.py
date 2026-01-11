import sys
import time
import re
import calendar
import requests
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

# --- PART 1: FETCH PUBLISHED RATINGS (API) ---
def get_published_ratings(uscf_id):
    url = f"https://ratings-api.uschess.org/api/v1/members/{uscf_id}"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://ratings.uschess.org/",
        "Origin": "https://ratings.uschess.org"
    }
    
    # Initialize with default
    ratings = {k: "Unrated" for k in ['R', 'Q', 'B', 'OR', 'OQ', 'OB']}
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            for entry in data.get('ratings', []):
                code = entry.get('ratingSystem')
                if code in ratings:
                    val = entry.get('rating')
                    # API can return None for rating
                    if val:
                        ratings[code] = str(val)
    except:
        pass # Silently fail back to defaults if API breaks
        
    return ratings

# --- PART 2: FETCH LIVE UPDATES (SELENIUM) ---

def get_cutoff_date():
    today = datetime.today()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    year, month = last_month.year, last_month.month
    c = calendar.monthcalendar(year, month)
    wednesdays = [week[2] for week in c if week[2] != 0]
    # 3rd Wednesday minus buffer
    return datetime(year, month, wednesdays[2]) - timedelta(days=2)

def extract_date(url):
    match = re.search(r'/event/(\d{8})', url)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d")
        except: pass
    return None

def parse_event_sections(driver, uscf_id, event_url):
    driver.get(event_url)
    # Fast wait for title to determine if online
    try:
        title = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        ).text
        is_online = "online" in title.lower()
    except:
        is_online = False

    found_updates = {}
    current_section = 1
    
    # Loop through sections (up to 20 to be safe)
    while current_section <= 20:
        # Check source for ID before parsing HTML
        if uscf_id in driver.page_source:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            link = soup.find("a", string=uscf_id)
            if link:
                row = link.find_parent("tr")
                if row:
                    text = row.get_text(separator="|", strip=True)
                    tokens = text.split("|")
                    
                    # Look for R, Q, B
                    for code in ['R', 'Q', 'B']:
                        if code in tokens:
                            try:
                                idx = tokens.index(code)
                                # Look ahead for numbers
                                nums = [t for t in tokens[idx+1:idx+6] if t.isdigit() and len(t) >= 3]
                                if len(nums) >= 2:
                                    post = nums[1] # [Pre, Post]
                                    
                                    # Map to correct key
                                    key = code
                                    if is_online:
                                        mapping = {'R': 'OR', 'Q': 'OQ', 'B': 'OB'}
                                        key = mapping.get(code, code)
                                    
                                    if key not in found_updates:
                                        found_updates[key] = post
                            except: pass
                
                # If we found the player, we assume they only played one section in this event
                return found_updates

        # Click Next Section
        try:
            btn = driver.find_element(By.XPATH, "//button[descendant::*[contains(@class, 'lucide-chevron-right')]]")
            if btn.get_attribute("disabled"):
                break # End of sections
            btn.click()
            time.sleep(1.0) # Wait for table refresh
            current_section += 1
        except:
            break
            
    return found_updates

def update_with_live_history(uscf_id, current_ratings):
    cutoff = get_cutoff_date()
    
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    # Suppress selenium logs
    options.add_experimental_option('excludeSwitches', ['enable-logging'])
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    try:
        # Get list of events
        driver.get(f"https://ratings.uschess.org/player/{uscf_id}")
        
        # Wait slightly for JS
        WebDriverWait(driver, 10).until(
             EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/event/']"))
        )
        
        elements = driver.find_elements(By.CSS_SELECTOR, "a[href^='/event/']")
        valid_events = []
        seen = set()
        
        for el in elements:
            url = el.get_attribute("href")
            if url in seen: continue
            seen.add(url)
            
            date = extract_date(url)
            if date and date >= cutoff:
                valid_events.append((date, url))
        
        # Sort Newest -> Oldest
        valid_events.sort(key=lambda x: x[0], reverse=True)
        
        # Track which ratings we have updated from live history
        updated_keys = set()
        
        for date, url in valid_events:
            # If we updated everything likely to change, we could stop, 
            # but usually we just scan all recent events to be safe.
            updates = parse_event_sections(driver, uscf_id, url)
            
            for key, val in updates.items():
                if key not in updated_keys:
                    current_ratings[key] = val
                    updated_keys.add(key)
                    
    except Exception:
        pass # If selenium fails, we just return the published ratings
    finally:
        driver.quit()
        
    return current_ratings

# --- MAIN ---
if __name__ == "__main__":
    target_id = sys.argv[1] if len(sys.argv) > 1 else "32073536"
    
    # 1. Get Base
    final_ratings = get_published_ratings(target_id)
    
    # 2. Update with Live
    final_ratings = update_with_live_history(target_id, final_ratings)
    
    # 3. Output CSV
    # Order: R, Q, B, OR, OQ, OB
    order = ['R', 'Q', 'B', 'OR', 'OQ', 'OB']
    output = ", ".join([str(final_ratings[k]) for k in order])
    
    print(output)
