import os
import sys
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
    h = 12 if hour == 0 else (hour if hour <= 12 else hour - 12)
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

def generate_status_image(current_en, current_tc, custom_warn=None):
    warn_count = len(current_en) + (1 if custom_warn else 0)
    width = 800
    height = 120 + (max(1, warn_count) * 90)
    img = Image.new('RGB', (width, height), color=(43, 45, 49))
    draw = ImageDraw.Draw(img)
    
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        font_title = ImageFont.truetype(font_path, 28)
        font_body = ImageFont.truetype(font_path, 24)
        font_detail = ImageFont.truetype(font_path, 18)
    except IOError:
        font_title = font_body = font_detail = ImageFont.load_default()

    draw.rectangle([0, 0, width, 60], fill=(30, 31, 34))
    now_str = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S HKT")
    draw.text((20, 15), f"HKO Warnings Summary / 現正生效警告 ({now_str})", font=font_title, fill=(255, 255, 255))

    y_offset = 80
    if not current_en and not custom_warn:
        draw.text((20, y_offset), "No warnings currently in force / 現時沒有生效警告", font=font_body, fill=(170, 170, 170))
    else:
        # Draw custom/parody warning first if it exists (highlighted in purple)
        if custom_warn:
            draw.text((20, y_offset), f"⚠️ [CUSTOM] {custom_warn['zh']} | {custom_warn['en']}", font=font_body, fill=(200, 100, 255))
            detail_line = f"Issued: {custom_warn['issue']}"
            if custom_warn.get('expire'):
                detail_line += f" | Valid until: {custom_warn['expire']}"
            draw.text((60, y_offset + 35), detail_line, font=font_detail, fill=(180, 180, 180))
            y_offset += 90

        # Draw official active warnings
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

def post_to_discord(messages, image_path):
    discord_payload = {"content": "\n\n".join(messages)}
    with open(image_path, "rb") as f:
        webhook_response = requests.post(
            WEBHOOK_URL,
            data={"payload_json": json.dumps(discord_payload)},
            files={"file": ("current_warnings.png", f, "image/png")}
        )
    return webhook_response.status_code

def handle_custom_warning():
    w_type = os.environ.get('CUSTOM_TYPE', 'None')
    valid_until = os.environ.get('CUSTOM_VALID_UNTIL', '').strip()
    area = os.environ.get('CUSTOM_AREA', 'None')

    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    zh_issue = format_zh_time(now)
    en_issue = format_en_time(now)

    area_map = {
        'Kowloon': '九龍',
        'Outlying Islands': '離島',
        'West NT': '新界西',
        'East NT': '新界東',
        'HK Island': '香港島'
    }

    messages = []
    custom_warn_visual = None

    if w_type in ['White Rainstorm Warning', 'Blue Rainstorm Warning']:
        zh_name = "白色暴雨警告信號" if "White" in w_type else "藍色暴雨警告信號"
        if not valid_until: valid_until = "[Time not specified]"
        messages.append(f"{zh_name} 在 {zh_issue}發出，有效時間至{valid_until}。\n{w_type} has been issued at {en_issue}, and is valid until {valid_until}.")
        custom_warn_visual = {"zh": zh_name, "en": w_type, "issue": en_issue, "expire": valid_until}
        
    elif w_type in ['Red Rainstorm Watch', 'Black Rainstorm Watch']:
        zh_name = "紅色暴雨戒備信號" if "Red" in w_type else "黑色暴雨戒備信號"
        messages.append(f"{zh_name} 在 {zh_issue}發出。\n{w_type} has been issued at {en_issue}.")
        custom_warn_visual = {"zh": zh_name, "en": w_type, "issue": en_issue, "expire": None}
        
    elif w_type == 'Severe Thunderstorm Emergency':
        zh_area = area_map.get(area, area)
        zh_name = f"{zh_area}嚴重雷暴緊急警告"
        en_name = f"Severe Thunderstorm Emergency Warning for {area}"
        messages.append(f"{zh_name} 在 {zh_issue}發出。\n{en_name} has been issued at {en_issue}.")
        custom_warn_visual = {"zh": zh_name, "en": en_name, "issue": en_issue, "expire": None}

    # Fetch live warnings to append to the custom status image
    data_en = requests.get(HKO_EN_URL).json() or {}
    data_tc = requests.get(HKO_TC_URL).json() or {}

    if messages:
        generate_status_image(data_en, data_tc, custom_warn=custom_warn_visual)
        status = post_to_discord(messages, IMAGE_FILE)
        print(f"Custom warning deployed. Status: {status}")

def fetch_and_send_warnings():
    if not WEBHOOK_URL:
        print("Missing DISCORD_WEBHOOK_URL")
        return

    # 1. Check if this is a manual custom warning run
    if os.environ.get('CUSTOM_ISSUE') == 'true':
        handle_custom_warning()
        return

    # 2. Otherwise, proceed with normal automated HKO tracking
    try:
        data_en = requests.get(HKO_EN_URL).json() or {}
        data_tc = requests.get(HKO_TC_URL).json() or {}
        previous_state = load_previous_state()
        
        messages = []
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        zh_cancel_time = format_zh_time(now)
        en_cancel_time = format_en_time(now)
        
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

        state_to_save = {}
        for k, v in data_en.items():
            v_copy = dict(v)
            v_copy['tc_name'] = data_tc.get(k, {}).get('name', v.get('name'))
            state_to_save[k] = v_copy
            
        save_current_state(state_to_save)

        if messages:
            generate_status_image(data_en, data_tc)
            status = post_to_discord(messages, IMAGE_FILE)
            print(f"Automated check deployed. Status: {status}")
        else:
            print("No new updates. Sleeping peacefully.")

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    fetch_and_send_warnings()
