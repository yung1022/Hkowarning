import os
import json
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
HKO_EN_URL = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=en'
HKO_TC_URL = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc'
STATE_FILE = 'warning_state.json'
IMAGE_FILE = 'current_warnings.png'

def parse_time(iso_str):
    if not iso_str: return None
    return datetime.fromisoformat(iso_str)

def format_zh_time(dt):
    if not dt: return ""
    hour = dt.hour
    minute = dt.minute
    period = "上午" if hour < 12 else "下午"
    
    if hour == 0: h = 12
    elif hour <= 12: h = hour
    else: h = hour - 12
    
    return f"{period}{h}:{minute:02d}"

def format_en_time(dt):
    if not dt: return ""
    time_str = dt.strftime("%I:%M %p").lstrip('0').lower()
    return time_str.replace("am", "a.m.").replace("pm", "p.m.")

def format_en_full(dt):
    if not dt: return ""
    date_str = dt.strftime("%d %b %Y")
    return f"{date_str} {format_en_time(dt)}"

def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception: pass
    return {}

def save_current_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)

def generate_status_image(current_en, current_tc):
    width = 800
    height = 120 + (max(1, len(current_en)) * 90)
    img = Image.new('RGB', (width, height), color=(43, 45, 49))
    draw = ImageDraw.Draw(img)
    
    # Load fonts (Using Noto CJK installed via GitHub Actions)
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        font_title = ImageFont.truetype(font_path, 28)
        font_body = ImageFont.truetype(font_path, 24)
        font_detail = ImageFont.truetype(font_path, 18)
    except IOError:
        font_title = font_body = font_detail = ImageFont.load_default()

    # Draw Header
    draw.rectangle([0, 0, width, 60], fill=(30, 31, 34))
    now_str = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S HKT")
    draw.text((20, 15), f"HKO Warnings Summary / 現正生效警告 ({now_str})", font=font_title, fill=(255, 255, 255))

    # Draw active warnings
    y_offset = 80
    if not current_en:
        draw.text((20, y_offset), "No warnings currently in force / 現時沒有生效警告", font=font_body, fill=(170, 170, 170))
    else:
        for code, en_warn in current_en.items():
            tc_warn = current_tc.get(code, {})
            zh_name = tc_warn.get('name', en_warn.get('name'))
            en_name = en_warn.get('name')
            
            draw.text((20, y_offset), f"⚠️ {zh_name} | {en_name}", font=font_body, fill=(255, 100, 100))
            
            issue_time = format_en_time(parse_time(en_warn.get('issueTime')))
            detail_line = f"Issued: {issue_time}"
            if en_warn.get('expireTime'):
                exp_time = format_en_time(parse_time(en_warn.get('expireTime')))
                detail_line += f" | Valid until: {exp_time}"
                
            draw.text((60, y_offset + 35), detail_line, font=font_detail, fill=(180, 180, 180))
            y_offset += 90
            
    img.save(IMAGE_FILE)

def fetch_and_send_warnings():
    if not WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL")
        return

    try:
        data_en = requests.get(HKO_EN_URL).json() or {}
        data_tc = requests.get(HKO_TC_URL).json() or {}
        previous_state = load_previous_state()
        
        messages = []
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        zh_cancel_time = format_zh_time(now)
        en_cancel_time = format_en_time(now)
        
        # 1. Check New or Updated Warnings
        for code, en_warn in data_en.items():
            tc_warn = data_tc.get(code, {})
            prev_warn = previous_state.get(code, {})
            
            if not prev_warn or en_warn.get('updateTime') != prev_warn.get('updateTime'):
                zh_name = tc_warn.get('name', en_warn.get('name', 'Unknown'))
                en_name = en_warn.get('name', 'Unknown')
                
                issue_dt = parse_time(en_warn.get('issueTime'))
                expire_dt = parse_time(en_warn.get('expireTime'))
                
                zh_issue = format_zh_time(issue_dt)
                en_issue = format_en_time(issue_dt)
                en_issue_full = format_en_full(issue_dt)
                zh_expire = format_zh_time(expire_dt)
                en_expire = format_en_time(expire_dt)
                
                action = en_warn.get('actionCode', 'ISSUE')

                if code == "WTS":
                    if action == "EXTEND":
                        messages.append(f"{zh_name} 有效時間延長至{zh_expire}。\n{en_name} issued at {en_issue_full} has been extended until {en_expire}.")
                    else:
                        messages.append(f"{zh_name} 在 {zh_issue}發出，有效時間至{zh_expire}。\n{en_name} has been issued at {en_issue}, and is valid until {en_expire}.")
                else:
                    messages.append(f"{zh_name} 在 {zh_issue}發出。\n{en_name} has been issued at {en_issue}.")

        # 2. Check Cancelled Warnings
        for code, prev_warn in previous_state.items():
            if code not in data_en:
                zh_name = prev_warn.get('tc_name', prev_warn.get('name', 'Unknown'))
                en_name = prev_warn.get('name', 'Unknown')
                
                if code == "WTS":
                    expire_dt = parse_time(prev_warn.get('expireTime'))
                    zh_expire_or_cancel = format_zh_time(expire_dt) if expire_dt else zh_cancel_time
                    messages.append(f"雷暴警告有效時間在{zh_expire_or_cancel}終止。\n{en_name} has been cancelled at {en_cancel_time}.")
                else:
                    messages.append(f"{zh_name} 在{zh_cancel_time}取消。\n{en_name} has been cancelled at {en_cancel_time}.")

        # 3. Save State (include tc_name for future cancellation references)
        state_to_save = {}
        for k, v in data_en.items():
            v_copy = dict(v)
            v_copy['tc_name'] = data_tc.get(k, {}).get('name', v.get('name'))
            state_to_save[k] = v_copy
            
        save_current_state(state_to_save)

        # 4. Generate Image and Send if there are updates
        if messages:
            generate_status_image(data_en, data_tc)
            
            discord_payload = {
                "content": "\n\n".join(messages)
            }
            
            with open(IMAGE_FILE, "rb") as f:
                webhook_response = requests.post(
                    WEBHOOK_URL,
                    data={"payload_json": json.dumps(discord_payload)},
                    files={"file": ("current_warnings.png", f, "image/png")}
                )
                
            if webhook_response.status_code in [200, 204]:
                print(f"Successfully sent {len(messages)} updates to Discord.")
            else:
                print(f"Discord API error: {webhook_response.status_code} - {webhook_response.text}")
        else:
            print("No new updates. Sleeping peacefully.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fetch_and_send_warnings()
