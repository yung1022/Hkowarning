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

AREA_MAP = {
    'Kowloon': '九龍', 'Outlying Islands': '離島',
    'West NT': '新界西', 'East NT': '新界東', 'HK Island': '香港島'
}

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
    return f"{dt.strftime('%d %b %Y')} {format_en_time(dt)}"

def parse_custom_target_time(time_str):
    """Parses standard HH:MM input into a full datetime object for today."""
    if not time_str or ":" not in time_str:
        return None
    try:
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        parts = time_str.strip().split(":")
        return now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
    except Exception:
        return None

def get_warning_identifiers(w_type, area="None"):
    """Returns bilingual names for custom warnings."""
    if w_type == 'White Rainstorm Warning': return "白色暴雨警告信號", w_type
    if w_type == 'Blue Rainstorm Warning': return "藍色暴雨警告信號", w_type
    if w_type == 'Red Rainstorm Watch': return "紅色暴雨戒備信號", w_type
    if w_type == 'Black Rainstorm Watch': return "黑色暴雨戒備信號", w_type
    if w_type == 'Severe Thunderstorm Emergency':
        zh_a = AREA_MAP.get(area, area)
        return f"{zh_a}嚴重雷暴緊急警告", f"Severe Thunderstorm Emergency Warning for {area}"
    return "未知警告", w_type

def load_state():
    """Safely loads state, preserving backward compatibility with older formats."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                if isinstance(data, dict) and ("official" in data or "custom" in data):
                    return data.get("official", {}), data.get("custom", None)
                return data, None
        except Exception: pass
    return {}, None

def save_state(official, custom):
    with open(STATE_FILE, 'w') as f:
        json.dump({"official": official, "custom": custom}, f)

def generate_status_image(official_en, official_tc, custom_warn):
    # Dynamic structural spacing configuration
    width = 800
    off_count = len(official_en)
    height = 60 + 50 + (off_count * 90 if off_count else 50) + 50 + (90 if custom_warn else 50) + 20
    
    img = Image.new('RGB', (width, height), color=(43, 45, 49))
    draw = ImageDraw.Draw(img)
    
    try:
        font_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
        font_title = ImageFont.truetype(font_path, 26)
        font_sec = ImageFont.truetype(font_path, 22)
        font_body = ImageFont.truetype(font_path, 20)
        font_detail = ImageFont.truetype(font_path, 16)
    except IOError:
        font_title = font_sec = font_body = font_detail = ImageFont.load_default()

    # Base Header Banner
    draw.rectangle([0, 0, width, 60], fill=(30, 31, 34))
    now_str = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S HKT")
    draw.text((20, 15), f"HKO Weather Monitoring Board ({now_str})", font=font_title, fill=(255, 255, 255))

    y = 80
    # --- SECTION 1: OFFICIAL WARNINGS ---
    draw.text((20, y), "Official Warnings / 官方警告", font=font_sec, fill=(114, 137, 218))
    y += 35
    if not official_en:
        draw.text((40, y), "No official warnings in force / 現時沒有官方生效警告", font=font_body, fill=(150, 150, 150))
        y += 40
    else:
        for code, en_warn in official_en.items():
            zh_name = official_tc.get(code, {}).get('name', en_warn.get('name'))
            draw.text((40, y), f"⚠️ {zh_name} | {en_warn.get('name')}", font=font_body, fill=(255, 100, 100))
            detail = f"Issued: {format_en_time(parse_time(en_warn.get('issueTime')))}"
            if en_warn.get('expireTime'):
                detail += f" | Valid until: {format_en_time(parse_time(en_warn.get('expireTime')))}"
            draw.text((75, y + 30), detail, font=font_detail, fill=(180, 180, 180))
            y += 85

    # --- SECTION 2: UNOFFICIAL WARNINGS ---
    y += 15
    draw.text((20, y), "Unofficial Parody Warnings / 非官方警告", font=font_sec, fill=(155, 89, 182))
    y += 35
    if not custom_warn:
        draw.text((40, y), "No custom warnings active / 現時沒有非官方警告", font=font_body, fill=(150, 150, 150))
    else:
        zh_n, en_n = get_warning_identifiers(custom_warn['type'], custom_warn.get('area', 'None'))
        draw.text((40, y), f"🔮 {zh_n} | {en_n}", font=font_body, fill=(200, 120, 255))
        
        iss_dt = parse_time(custom_warn.get('issueTime'))
        detail = f"Issued: {format_en_time(iss_dt)}"
        if custom_warn.get('expireTime'):
            exp_dt = parse_time(custom_warn.get('expireTime'))
            detail += f" | Valid until: {format_en_time(exp_dt)}"
        draw.text((75, y + 30), detail, font=font_detail, fill=(180, 180, 180))

    img.save(IMAGE_FILE)

def post_to_discord(messages, official_en, official_tc, custom):
    if not messages: return
    generate_status_image(official_en, official_tc, custom)
    payload = {"content": "\n\n".join(messages)}
    with open(IMAGE_FILE, "rb") as f:
        requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": (IMAGE_FILE, f, "image/png")})

def main():
    if not WEBHOOK_URL: return
    
    action = os.environ.get('CUSTOM_ACTION', 'NONE').split()[0]
    c_type = os.environ.get('CUSTOM_TYPE', '')
    v_until = os.environ.get('CUSTOM_VALID_UNTIL', '')
    c_area = os.environ.get('CUSTOM_AREA', 'None')
    
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    official_en = requests.get(HKO_EN_URL).json() or {}
    official_tc = requests.get(HKO_TC_URL).json() or {}
    prev_official, current_custom = load_state()
    
    messages = []

    # -------------------------------------------------------------
    # PHASE 1: MANUALLY TRIGGERED CUSTOM ACTIONS VIA USER GRAPHICAL TAB
    # -------------------------------------------------------------
    if action in ['ISSUE', 'EXTEND', 'CANCEL']:
        zh_name, en_name = get_warning_identifiers(c_type, c_area)
        target_expire_dt = parse_custom_target_time(v_until)
        
        if action == 'ISSUE':
            # Rule 3.1: Only one active custom rainstorm warning can exist at a time
            if current_custom and "Rainstorm Warning" in current_custom['type'] and "Rainstorm Warning" in c_type:
                old_zh, old_en = get_warning_identifiers(current_custom['type'], current_custom.get('area', 'None'))
                messages.append(f"🔄 {old_zh} 在{format_zh_time(now)}取消並被替代。\n{old_en} has been replaced and cancelled at {format_en_time(now)}.")
            
            # Setup base configurations
            new_custom = {
                "type": c_type, "area": c_area,
                "issueTime": now.isoformat(),
                "expireTime": target_expire_dt.isoformat() if target_expire_dt and "Watch" not in c_type and "Emergency" not in c_type else None
            }
            
            if new_custom["expireTime"]:
                messages.append(f"{zh_name} 在 {format_zh_time(now)}發出，有效時間至{format_zh_time(target_expire_dt)}。\n{en_name} has been issued at {format_en_time(now)}, and is valid until {format_en_time(target_expire_dt)}.")
            else:
                messages.append(f"{zh_name} 在 {format_zh_time(now)}發出。\n{en_name} has been issued at {format_en_time(now)}.")
            current_custom = new_custom

        elif action == 'EXTEND' and current_custom and current_custom['type'] == c_type:
            if target_expire_dt:
                current_custom['expireTime'] = target_expire_dt.isoformat()
                orig_issue_dt = parse_time(current_custom['issueTime'])
                messages.append(f"{zh_name} 有效時間延長至{format_zh_time(target_expire_dt)}。\n{en_name} issued at {format_en_full(orig_issue_dt)} has been extended until {format_en_time(target_expire_dt)}.")

        elif action == 'CANCEL' and current_custom and current_custom['type'] == c_type:
            messages.append(f"{zh_name} 在{format_zh_time(now)}取消。\n{en_name} has been cancelled at {format_en_time(now)}.")
            current_custom = None

    # -------------------------------------------------------------
    # PHASE 2: AUTOMATED RULE TASKS (RUNS EVERY 10 MINS)
    # -------------------------------------------------------------
    else:
        # Check natural safety structural timeout thresholds
        if current_custom and current_custom.get('expireTime'):
            if now >= parse_time(current_custom['expireTime']):
                zh_n, en_n = get_warning_identifiers(current_custom['type'], current_custom.get('area', 'None'))
                messages.append(f"{zh_n} 有效時間在 {format_zh_time(parse_time(current_custom['expireTime']))} 終止。\n{en_n} has expired natively at {format_en_time(parse_time(current_custom['expireTime']))}.")
                current_custom = None

        # Rule 3.2: Automated watch termination rules based on active HKO tracking arrays
        if current_custom and "Watch" in current_custom['type']:
            is_official_red_active = ("WRAIN" in official_en and official_en["WRAIN"].get("type") == "Red")
            is_official_blk_active = ("WRAIN" in official_en and official_en["WRAIN"].get("type") == "Black")
            
            if (current_custom['type'] == 'Red Rainstorm Watch' and is_official_red_active) or \
               (current_custom['type'] == 'Black Rainstorm Watch' and is_official_blk_active):
                zh_n, en_n = get_warning_identifiers(current_custom['type'])
                messages.append(f"🛑 {zh_n} 因應天文台正式發出相應暴雨警告，在{format_zh_time(now)}自動取消。\n{en_n} has been automatically tracking-cancelled at {format_en_time(now)} due to official HKO upgrade release.")
                current_custom = None

        # Process Standard Official HKO Array Structural Diff Loops
        for code, en_warn in official_en.items():
            prev_w = prev_official.get(code, {})
            if not prev_w or en_warn.get('updateTime') != prev_w.get('updateTime'):
                zh_n = official_tc.get(code, {}).get('name', en_warn.get('name'))
                en_n = en_warn.get('name')
                iss_t = parse_time(en_warn.get('issueTime'))
                exp_t = parse_time(en_warn.get('expireTime'))
                
                if code == "WTS":
                    if en_warn.get('actionCode') == "EXTEND":
                        messages.append(f"{zh_n} 有效時間延長至{format_zh_time(exp_t)}。\n{en_n} issued at {format_en_full(iss_t)} has been extended until {format_en_time(exp_t)}.")
                    else:
                        messages.append(f"{zh_n} 在 {format_zh_time(iss_t)}發出，有效時間至{format_zh_time(exp_t)}。\n{en_n} has been issued at {format_en_time(iss_t)}, and is valid until {format_en_time(exp_t)}.")
                else:
                    messages.append(f"{zh_n} 在 {format_zh_time(iss_t)}發出。\n{en_n} has been issued at {format_en_time(iss_t)}.")

        for code, prev_w in prev_official.items():
            if code not in official_en:
                zh_n = prev_w.get('tc_name', prev_w.get('name'))
                en_n = prev_w.get('name')
                if code == "WTS":
                    exp_t = parse_time(prev_w.get('expireTime'))
                    t_str = format_zh_time(exp_t) if exp_t else format_zh_time(now)
                    messages.append(f"雷暴警告有效時間在{t_str}終止。\n{en_n} has been cancelled at {format_en_time(now)}.")
                else:
                    messages.append(f"{zh_n} 在{format_zh_time(now)}取消。\n{en_n} has been cancelled at {format_en_time(now)}.")

    # -------------------------------------------------------------
    # PHASE 3: STATE SYNCHRONIZATION AND DISCORD DELIVERY
    # -------------------------------------------------------------
    next_official_state = {}
    for k, v in official_en.items():
        v_copy = dict(v)
        v_copy['tc_name'] = official_tc.get(k, {}).get('name', v.get('name'))
        next_official_state[k] = v_copy

    if messages:
        post_to_discord(messages, official_en, official_tc, current_custom)
    save_state(next_official_state, current_custom)

if __name__ == "__main__":
    main()
