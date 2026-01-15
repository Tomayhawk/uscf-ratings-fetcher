import sys
import glob
import csv
import re
import calendar
import time
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

# --- CONSTANTS & HELPERS ---
RATING_KEYS = ['R', 'Q', 'B', 'OR', 'OQ', 'OB']
DEFAULT_ID = "32073536"

def get_cutoff_date():
    """Returns the Tuesday before the 3rd Wednesday of last month."""
    today = datetime.today()
    first = today.replace(day=1)
    last_month = first - timedelta(days=1)
    c = calendar.monthcalendar(last_month.year, last_month.month)
    wednesdays = [w[2] for w in c if w[2] != 0]
    return datetime(last_month.year, last_month.month, wednesdays[2]) - timedelta(days=2)

def print_bar(iteration, total, prefix='', length=30):
    percent = f"{100 * (iteration / float(total)):.1f}"
    filled = int(length * iteration // total)
    bar = '█' * filled + '-' * (length - filled)
    sys.stdout.write(f'\r{prefix} |{bar}| {percent}% ({iteration}/{total})')
    sys.stdout.flush()
    if iteration == total: print()

# --- MAIN CLASS ---
class USCFScanner:
    def __init__(self):
        self.cutoff = get_cutoff_date()
        opts = Options()
        opts.add_argument("--headless")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--log-level=3") # Suppress logs
        opts.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)

    def get_published(self, uid):
        """Fetches official monthly ratings via API."""
        data = {'name': 'Unknown', 'ratings': {k: "Unrated" for k in RATING_KEYS}}
        try:
            res = requests.get(f"https://ratings-api.uschess.org/api/v1/members/{uid}", 
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            if res.status_code == 200:
                js = res.json()
                data['name'] = f"{js.get('firstName','')} {js.get('lastName','')}".strip()
                for r in js.get('ratings', []):
                    if r['ratingSystem'] in RATING_KEYS and r['rating']:
                        data['ratings'][r['ratingSystem']] = str(r['rating'])
        except: pass
        return data

    def _parse_row(self, row, is_online):
        """Extracts pre/post ratings from a table row."""
        updates = {}
        tokens = row.get_text(separator="|", strip=True).split("|")
        for code in ['R', 'Q', 'B']:
            if code in tokens:
                try:
                    idx = tokens.index(code)
                    # Find next two 3+ digit numbers (Pre, Post)
                    nums = [t for t in tokens[idx+1:idx+6] if t.isdigit() and len(t) >= 3]
                    if len(nums) >= 2:
                        key = {'R':'OR','Q':'OQ','B':'OB'}[code] if is_online else code
                        updates[key] = nums[1]
                except: pass
        return updates

    def get_live(self, uid):
        """Scans recent tournaments for rating changes."""
        updates = {}
        try:
            self.driver.get(f"https://ratings.uschess.org/player/{uid}")
            try:
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.CSS_SELECTOR, "a[href^='/event/']")))
            except: return updates

            # Collect valid recent events
            events = []
            for el in self.driver.find_elements(By.CSS_SELECTOR, "a[href^='/event/']"):
                url = el.get_attribute("href")
                match = re.search(r'/event/(\d{8})', url)
                if match:
                    dt = datetime.strptime(match.group(1), "%Y%m%d")
                    if dt >= self.cutoff: events.append((dt, url))
            
            # Scan newest first; remove duplicates
            for _, url in sorted(list(set(events)), key=lambda x: x[0], reverse=True):
                self.driver.get(url)
                try:
                    title = WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.TAG_NAME, "h1"))).text
                    is_online = "online" in title.lower()
                except: is_online = False

                # Loop sections until player found
                for _ in range(20):
                    if uid in self.driver.page_source:
                        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
                        link = soup.find("a", string=uid)
                        if link and link.find_parent("tr"):
                            new_data = self._parse_row(link.find_parent("tr"), is_online)
                            for k, v in new_data.items():
                                if k not in updates: updates[k] = v
                            break # Found player, move to next event

                    # Next Section
                    try:
                        btn = self.driver.find_element(By.XPATH, "//button[descendant::*[contains(@class, 'lucide-chevron-right')]]")
                        if btn.get_attribute("disabled"): break
                        btn.click()
                        time.sleep(1.0)
                    except: break
        except: pass
        return updates

    def fetch(self, uid):
        p = self.get_published(uid)
        l = self.get_live(uid)
        final = p['ratings'].copy()
        final.update(l)
        return {'id': uid, 'name': p['name'], 'pub': p['ratings'], 'live': final}

    def close(self):
        self.driver.quit()

# --- ENTRY POINT ---
def main():
    args = sys.argv[1:]
    force_csv = "csv" in args
    if force_csv: args.remove("csv")

    # Determine IDs
    ids = []
    if args:
        ids = [x.strip() for x in " ".join(args).replace(',', ' ').split() if x.strip().isdigit()]
    else:
        # Search for .csv input
        for f in glob.glob("*.csv"):
            if "output" in f: continue
            try:
                content = open(f).read().strip()
                if content: 
                    found = [t.strip() for t in content.splitlines()[0].split(',') if t.strip().isdigit()]
                    if found: 
                        ids = found
                        break
            except: continue
        if not ids: ids = [DEFAULT_ID]

    # Mode Selection
    mode = "file" if len(ids) > 5 else "terminal"
    
    scanner = USCFScanner()
    results = []
    
    try:
        if mode == "file" and not force_csv:
            print(f"[*] Processing {len(ids)} IDs...")
            print_bar(0, len(ids), prefix='Progress:')

        for i, uid in enumerate(ids):
            if mode == "terminal" and not force_csv:
                print(f"Fetching {uid}...", end="\r")
            
            results.append(scanner.fetch(uid))
            
            if mode == "file" and not force_csv:
                print_bar(i + 1, len(ids), prefix='Progress:')
                
    finally:
        scanner.close()

    # Output
    if force_csv:
        for r in results:
            print(", ".join([r['live'][k] for k in RATING_KEYS]))
    
    elif mode == "terminal":
        print("\r" + " "*20 + "\r", end="") # Clear line
        print(f"{'ID':<10} {'Name':<25} {'Reg':<8} {'Quick':<8} {'Blitz':<8} {'Onl-Reg':<8} {'Onl-Qck':<8} {'Onl-Blz':<8}")
        print("-" * 95)
        for res in results:
            l = res['live']
            print(f"{res['id']:<10} {res['name']:<25.24} {l['R']:<8} {l['Q']:<8} {l['B']:<8} {l['OR']:<8} {l['OQ']:<8} {l['OB']:<8}")
        print("-" * 95)

    else:
        fname = "uscf_ratings_output.csv"
        try:
            with open(fname, 'w', newline='') as f:
                writer = csv.writer(f)
                header = ["Name", "ID"] + [f"{k}_{t}" for k in RATING_KEYS for t in ['Published', 'Live']]
                writer.writerow(header)
                for res in results:
                    row = [res['name'], res['id']]
                    for k in RATING_KEYS:
                        row.extend([res['pub'][k], res['live'][k]])
                    writer.writerow(row)
            print(f"[+] Saved {len(results)} records to '{fname}'")
        except Exception as e:
            print(f"[-] Error writing file: {e}")

if __name__ == "__main__":
    main()
