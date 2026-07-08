import os
import json
import requests

WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
HKO_API_URL = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=en'
STATE_FILE = 'warning_state.json'

def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_current_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def fetch_and_send_warnings():
    if not WEBHOOK_URL:
        print("Error: DISCORD_WEBHOOK_URL environment variable is missing.")
        return

    try:
        response = requests.get(HKO_API_URL)
        response.raise_for_status()
        current_data = response.json() or {}
        previous_data = load_previous_state()
        
        current_keys = set(current_data.keys())
        previous_keys = set(previous_data.keys())
        
        embeds = []
        
        # 1. Process New or Updated Warnings
        for key, current_warning in current_data.items():
            prev_warning = previous_data.get(key, {})
            
            # If it's brand new, or the updateTime has changed (upgrade/extension)
            if not prev_warning or current_warning.get('updateTime') != prev_warning.get('updateTime'):
                
                name = current_warning.get('name', 'Unknown Warning')
                w_type = current_warning.get('type', '')
                issue_time = current_warning.get('issueTime', 'Unknown time')
                expire_time = current_warning.get('expireTime', '')
                action = current_warning.get('actionCode', 'ISSUE')
                
                # Format the title with the specific type if it exists
                title = f"🔴 {name}"
                if w_type:
                    title = f"🔴 {name} - {w_type}"
                    
                # Mention if it's an extension or an upgrade
                if action == "EXTEND":
                    title = "🔄 EXTENDED: " + title[2:]
                elif action in ["UPDATE", "REPLACE"]:
                    title = "⚠️ UPDATED: " + title[2:]
                    
                description = f"**Issued:** {issue_time}"
                if expire_time:
                    description += f"\n**Valid until:** {expire_time}"
                    
                embeds.append({
                    "title": title,
                    "color": 16711680, # Red
                    "description": description
                })

        # 2. Process Cancelled Warnings
        cancelled_keys = previous_keys - current_keys
        for key in cancelled_keys:
            name = previous_data[key].get('name', 'Unknown Warning')
            w_type = previous_data[key].get('type', '')
            
            title = f"⚪ CANCELLED: {name}"
            if w_type:
                title += f" - {w_type}"
                
            embeds.append({
                "title": title,
                "color": 3289650, # Grayish
                "description": "This warning is no longer in force."
            })
            
        # 3. Send to Discord if there are changes
        if embeds:
            discord_payload = {
                "content": "🚨 **HKO Weather Warning Update** 🚨",
                "embeds": embeds
            }
            webhook_response = requests.post(WEBHOOK_URL, json=discord_payload)
            if webhook_response.status_code == 204:
                print(f"Successfully sent {len(embeds)} updates to Discord.")
            else:
                print(f"Discord API error: {webhook_response.status_code}")
        else:
            print("No new updates or cancellations. Sleeping peacefully.")
                
        # 4. Save the exact current payload as the new state
        save_current_state(current_data)
            
    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fetch_and_send_warnings()