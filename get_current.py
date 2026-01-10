import sys
import time
import re
import calendar
from datetime import datetime, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup

def get_cutoff_date():
    today = datetime.today()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    year, month = last_month.year, last_month.month
    c = calendar.monthcalendar(year, month)
    wednesdays = [week[2] for week in c if week[2] != 0]
    return datetime(year, month, wednesdays[2]) - timedelta(days=2)

def extract_date(url):
    match = re.search(r'/event/(\d{8})', url)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d")
        except ValueError:
            pass
    return None

def parse_event(driver, uscf_id, event_url):
    driver.get(event_url)
    time.sleep(2)
    
    try:
        title_elem = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.TAG_NAME, "h1"))
        )
        title = title_elem.text
        is_online = "online" in title.lower()
    except:
        title = "Unknown Event"
        is_online = False

    found_data = {}
    current_section = 1
    
    while True:
        if uscf_id in driver.page_source:
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            link = soup.find("a", string=uscf_id)
            if link:
                row = link.find_parent("tr")
                if row:
                    text = row.get_text(separator="|", strip=True)
                    tokens = text.split("|")
                    
                    for code in ['R', 'Q', 'B']:
                        if code in tokens:
                            try:
                                idx = tokens.index(code)
                                nums = [t for t in tokens[idx+1:idx+6] if t.isdigit() and len(t) >= 3]
                                if len(nums) >= 2:
                                    post_rating = nums[1]
                                    key = code
                                    if is_online:
                                        mapping = {'R': 'OR', 'Q': 'OQ', 'B': 'OB'}
                                        key = mapping.get(code, code)
                                    
                                    if key not in found_data:
                                        found_data[key] = post_rating
                            except (ValueError, IndexError):
                                pass

                if found_data:
                    return found_data, title

        try:
            btn = driver.find_element(By.XPATH, "//button[descendant::*[contains(@class, 'lucide-chevron-right')]]")
            if btn.get_attribute("disabled"):
                break
            btn.click()
            time.sleep(1.5)
            current_section += 1
            if current_section > 20: 
                break
        except:
            break
            
    return found_data, title

def main(uscf_id):
    cutoff = get_cutoff_date()
    print(f"--- FETCHING HISTORY FOR {uscf_id} ---")
    print(f"Scanning back to: {cutoff.strftime('%Y-%m-%d')}\n")

    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    
    live_ratings = {k: None for k in ['R', 'Q', 'B', 'OR', 'OQ', 'OB']}
    
    try:
        driver.get(f"https://ratings.uschess.org/player/{uscf_id}")
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
            
            date_obj = extract_date(url)
            if date_obj and date_obj >= cutoff:
                valid_events.append((date_obj, url))
        
        valid_events.sort(key=lambda x: x[0], reverse=True)
        print(f"Found {len(valid_events)} valid tournaments.")
        
        for date_obj, url in valid_events:
            if all(v is not None for v in live_ratings.values()):
                break
                
            display_date = date_obj.strftime('%m-%d')
            event_id = url.split('/')[-1]
            print(f"Scanning: {event_id} ({display_date}) ... ", end="", flush=True)
            
            results, event_name = parse_event(driver, uscf_id, url)
            
            if results:
                print("Found data!")
                for r_type, value in results.items():
                    if live_ratings.get(r_type) is None:
                        live_ratings[r_type] = value
                        print(f"   -> Updated {r_type}: {value} ({event_name[:30]}...)")
            else:
                print("No rating data found.")

        print("\n" + "="*40)
        print("   LIVE RATINGS (Including Online)")
        print("="*40)
        
        labels = {
            'R': 'OTB Regular', 'Q': 'OTB Quick', 'B': 'OTB Blitz',
            'OR': 'Online Reg', 'OQ': 'Online Qck', 'OB': 'Online Blz'
        }
        
        for code, label in labels.items():
            val = live_ratings.get(code)
            display = val if val else "No recent play"
            print(f"{label:<12}: {display}")
            
        print("="*40)

    except Exception as e:
        print(f"\n[-] Error: {e}")
    finally:
        if 'driver' in locals():
            driver.quit()

if __name__ == "__main__":
    tid = sys.argv[1] if len(sys.argv) > 1 else "12641216"
    main(tid)
