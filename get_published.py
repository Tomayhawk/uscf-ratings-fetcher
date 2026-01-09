import sys
import requests

def fetch_ratings(uscf_id):
    api_url = f"https://ratings-api.uschess.org/api/v1/members/{uscf_id}"
    
    # Headers to mimic a real browser request
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://ratings.uschess.org/",
        "Origin": "https://ratings.uschess.org"
    }

    try:
        # Fetch data
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # Parse player info
        name = f"{data.get('firstName')} {data.get('lastName')}"
        member_id = data.get('id')

        print(f"\nPlayer: {name}")
        print(f"ID:     {member_id}\n")

        # Map API codes to readable labels
        rating_map = {
            'R': 'Regular', 'Q': 'Quick', 'B': 'Blitz',
            'OR': 'Online Regular', 'OQ': 'Online Quick', 'OB': 'Online Blitz'
        }
        
        # Pre-fill all categories as 'Unrated'
        ratings = {label: "Unrated" for label in rating_map.values()}

        # Update with actual values from API
        for entry in data.get('ratings', []):
            code = entry.get('ratingSystem')
            if code in rating_map:
                ratings[rating_map[code]] = entry.get('rating')

        # Specific print order for display
        display_order = [
            'Regular', 'Quick', 'Blitz', 
            'Online Regular', 'Online Quick', 'Online Blitz'
        ]

        # Display results
        print("=" * 30)
        print(f"{'TYPE':<20} {'RATING':<10}")
        print("=" * 30)
        
        for key in display_order:
            print(f"{key:<20} {ratings[key]}")
            
        print("=" * 30)

    except requests.exceptions.RequestException as e:
        print(f"Network Error: {e}")
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    # Default to Hikaru Nakamura if no argument provided
    target_id = sys.argv[1] if len(sys.argv) > 1 else "12641216"
    fetch_ratings(target_id)
