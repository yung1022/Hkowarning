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
HISTORY_FILE = 'history.json'
IMAGE_FILE = 'current_warnings.png'

AREA_MAP = {
    'Kowloon': '九龍', 'Outlying Islands': '離島',
    'West NT': '新界西', 'East NT': '新界東', 'HK Island': '香港島'
}

UNOFFICIAL_ASSETS = {
    'White Rainstorm Watch': 'white_rainstorm',
    'Blue Rainstorm Warning': 'blue_rainstorm',
    'Red Rainstorm Watch': 'red_watch',
    'Black Rainstorm Watch': 'black_watch',
    'Severe Thunderstorm Emergency': 'severe_thunderstorm'
}

def translate_areas(area_str):
    if not area_str or str(area_str).strip().lower() == 'none':
        return 'None', 'None'
    areas = [a.strip() for a in area_str.split(',')]
    zh_areas = [AREA_MAP.get(a, a) for a in areas]
    return "及".join(zh_areas), " and ".join(areas)

def get_template_announcement(w_type, en_area):
    area_text = en_area if en_area != 'None' else "most parts of Hong Kong"
    if w_type == 'White Rainstorm Watch':
        return f"1. Expect heavy rain of about 10mm/h to form over the next 2-3 hours.\n2. About 10mm/h of heavy rain is currently impacting on {area_text}."
    elif w_type == 'Blue Rainstorm Warning':
        return "1. Expect heavy rain of about 30mm/h to form over the next 2-3 hours.\n2. About 20mm/h of heavy rain is currently impacting on most parts of Hong Kong."
    elif w_type == 'Red Rainstorm Watch':
        return "The chance of issuing Red Rainstorm Warning has reached more than 70%, it is very likely that a 50mm/h heavy rain will impact Hong Kong very soon."
    elif w_type == 'Black Rainstorm Watch':
        return "The chance of issuing Black Rainstorm Warning has reached more than 70%, it is very likely that a 70mm/h heavy rain will impact Hong Kong very soon."
    elif w_type == 'Severe Thunderstorm Emergency':
        return f"There's currently a huge thunderstorm on {en_area}."
    return ""

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
    return dt.strftime("%I:%M %p").lstrip('0').lower().replace("am", "a.m.").replace("pm", "p.m.")

def parse_custom_target_time(time_str):
    if not time_str or ":" not in time_str: return None
    try:
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        parts = time_str.strip().split(":")
        return now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
    except Exception: return None

def get_warning_identifiers(w_type, area="None"):
    if w_type == 'White Rainstorm Watch': 
        zh_a, en_a = translate_areas(area)
        if en_a != 'None':
            return f"{zh_a}白色暴雨戒備信號", f"White Rainstorm Watch for {en_a}"
        return "白色暴雨戒備信號", "White Rainstorm Watch"
    if w_type == 'Blue Rainstorm Warning': return "藍色暴雨警告信號", w_type
    if w_type == 'Red Rainstorm Watch': return "紅色暴雨戒備信號", w_type
    if w_type == 'Black Rainstorm Watch': return "黑色暴雨戒備信號", w_type
    if w_type == 'Severe Thunderstorm Emergency':
        zh_a, en_a = translate_areas(area)
        return f"{zh_a}嚴重雷暴緊急警告", f"Severe Thunderstorm Emergency Warning for {en_a}"
    return "未知警告", w_type

def calculate_duration(issue_iso, end_iso):
    try:
        start = parse_time(issue_iso)
        end = parse_time(end_iso)
        diff_seconds = int((end - start).total_seconds())
        if diff_seconds < 0: return "0h 0m"
        hours = diff_seconds // 3600
        minutes = (diff_seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    except Exception:
        return "Unknown"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception: pass
    return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_active_history(history, type_code, is_custom=False):
    for item in history['warnings']:
        if item['status'] == 'active' and item['code'] == type_code and item.get('is_custom', False) == is_custom:
            return item
    return None

def paste_icon(img, folder, filename, x, y):
    path = f"assets/{folder}/{filename}.png"
    if os.path.exists(path):
        icon = Image.open(path).convert("RGBA").resize((32, 32))
        img.paste(icon, (x, int(y)), icon)
        return True
    return False

def generate_status_image(official_en, official_tc, custom_warn, chances):
    rs_level = 0
    if "WRAIN" in official_en:
        code = official_en["WRAIN"].get("code", "")
        if "A" in code: rs_level = 1
        elif "R" in code: rs_level = 2
        elif "B" in code: rs_level = 3

    show_red = (chances.get('red') or rs_level >= 1) and rs_level < 2
    show_blk = (chances.get('black') or rs_level >= 1) and rs_level < 3

    width = 800
    off_count = len(official_en)
    chances_h = 0
    if show_red: chances_h += 30
    if show_blk: chances_h += 30
    if chances_h > 0: chances_h += 20
    
    height = 60 + 50 + (off_count * 90 if off_count else 50) + 50 + (90 if custom_warn else 50) + chances_h + 30
    
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

    draw.rectangle([0, 0, width, 60], fill=(30, 31, 34))
    now_str = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M:%S HKT")
    draw.text((20, 15), f"HKO Weather Monitoring Board ({now_str})", font=font_title, fill=(255, 255, 255))

    y = 80
    draw.text((20, y), "Official Warnings / 官方警告", font=font_sec, fill=(114, 137, 218))
    y += 35
    if not official_en:
        draw.text((40, y), "No official warnings in force / 現時沒有官方生效警告", font=font_body, fill=(150, 150, 150))
        y += 40
    else:
        for key, en_warn in official_en.items():
            zh_name = official_tc.get(key, {}).get('name', en_warn.get('name'))
            warn_code = en_warn.get('code', key)
            
            if paste_icon(img, "official", warn_code, 35, y):
                draw.text((75, y + 2), f"{zh_name} | {en_warn.get('name')}", font=font_body, fill=(255, 100, 100))
            else:
                draw.text((35, y), f"⚠️ {zh_name} | {en_warn.get('name')}", font=font_body, fill=(255, 100, 100))
            
            detail = f"Issued: {format_en_time(parse_time(en_warn.get('issueTime')))}"
            if en_warn.get('expireTime'):
                detail += f" | Valid until: {format_en_time(parse_time(en_warn.get('expireTime')))}"
            draw.text((75, y + 35), detail, font=font_detail, fill=(180, 180, 180))
            y += 85

    y += 15
    draw.text((20, y), "Unofficial Parody Warnings / 非官方警告", font=font_sec, fill=(155, 89, 182))
    y += 35
    if not custom_warn:
        draw.text((40, y), "No custom warnings active / 現時沒有非官方警告", font=font_body, fill=(150, 150, 150))
        y += 40
    else:
        zh_n, en_n = get_warning_identifiers(custom_warn['type'], custom_warn.get('area', 'None'))
        asset_name = UNOFFICIAL_ASSETS.get(custom_warn['type'], 'default')
        
        if paste_icon(img, "unofficial", asset_name, 35, y):
            draw.text((75, y + 2), f"{zh_n} | {en_n}", font=font_body, fill=(200, 120, 255))
        else:
            draw.text((35, y), f"🔮 {zh_n} | {en_n}", font=font_body, fill=(200, 120, 255))
        
        iss_dt = parse_time(custom_warn.get('issueTime'))
        detail = f"Issued: {format_en_time(iss_dt)}"
        if custom_warn.get('expireTime'):
            exp_dt = parse_time(custom_warn.get('expireTime'))
            detail += f" | Valid until: {format_en_time(exp_dt)}"
        draw.text((75, y + 35), detail, font=font_detail, fill=(180, 180, 180))
        y += 85

    if show_red or show_blk:
        y += 10
        if show_red:
            val = chances.get('red', '--')
            draw.text((40, y), f"🔴 Chances for Red Rainstorm Warning: {val}", font=font_body, fill=(255, 100, 100))
            y += 30
        if show_blk:
            val = chances.get('black', '--')
            draw.text((40, y), f"⚫ Chances for Black Rainstorm Warning: {val}", font=font_body, fill=(150, 150, 150))

    img.save(IMAGE_FILE)

def post_to_discord(messages, official_en, official_tc, custom, chances):
    if not messages: return
    generate_status_image(official_en, official_tc, custom, chances)
    payload = {"content": "\n\n".join(messages)}
    
    try:
        with open(IMAGE_FILE, "rb") as f:
            requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": (IMAGE_FILE, f, "image/png")})
    except Exception as e:
        print(f"Error posting to Discord: {e}")

def main():
    if not WEBHOOK_URL: return
    
    action_env = os.environ.get('CUSTOM_ACTION', '').strip()
    action = action_env.split()[0] if action_env else 'NONE'
    
    c_type = os.environ.get('CUSTOM_TYPE', '').strip()
    v_until = os.environ.get('CUSTOM_VALID_UNTIL', '').strip()
    c_area = os.environ.get('CUSTOM_AREA', 'None').strip()
    custom_announcement = os.environ.get('CUSTOM_ANNOUNCEMENT', '').strip()
    in_red_chance = os.environ.get('RED_CHANCE', '').strip()
    in_blk_chance = os.environ.get('BLACK_CHANCE', '').strip()
    
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    official_en = requests.get(HKO_EN_URL).json() or {}
    official_tc = requests.get(HKO_TC_URL).json() or {}
    
    state_data = load_json(STATE_FILE, {"official": {}, "custom": None, "chances": {}})
    prev_official = state_data.get("official", {})
    current_custom = state_data.get("custom", None)
    chances = state_data.get("chances", {})
    
    history = load_json(HISTORY_FILE, {"warnings": [], "announcements": []})
    
    if in_red_chance: chances['red'] = "" if in_red_chance.upper() == 'CLEAR' else in_red_chance
    if in_blk_chance: chances['black'] = "" if in_blk_chance.upper() == 'CLEAR' else in_blk_chance
    
    messages = []
    has_image_update_only = (in_red_chance or in_blk_chance) and action == 'NONE'
    
    # 1. Handle Standalone Announcements
    if action == 'ANNOUNCE':
        _, en_area = translate_areas(c_area)
        final_announcement = custom_announcement if custom_announcement else get_template_announcement(c_type, en_area)
        if final_announcement:
            messages.append(f"📢 **Announcement / 特別報告:**\n{final_announcement}")
            history['announcements'].append({
                "time": now.isoformat(),
                "text": final_announcement
            })

    # 2. Handle Custom Warnings Actions
    elif action in ['ISSUE', 'EXTEND', 'CANCEL']:
        zh_name, en_name = get_warning_identifiers(c_type, c_area)
        target_expire_dt = parse_custom_target_time(v_until)
        
        if action == 'ISSUE':
            if current_custom and "Rainstorm" in current_custom['type'] and "Rainstorm Warning" in c_type:
                old_zh, old_en = get_warning_identifiers(current_custom['type'], current_custom.get('area', 'None'))
                messages.append(f"🔄 {old_zh} 在{format_zh_time(now)}取消並被替代。\n{old_en} has been replaced and cancelled at {format_en_time(now)}.")
                old_hist = get_active_history(history, current_custom['type'], is_custom=True)
                if old_hist:
                    old_hist['status'] = 'cancelled'
                    old_hist['end_time'] = now.isoformat()
                    old_hist['duration'] = calculate_duration(old_hist['issue_time'], now.isoformat())

            new_custom = {
                "type": c_type, "area": c_area,
                "issueTime": now.isoformat(),
                "expireTime": target_expire_dt.isoformat() if target_expire_dt and "Watch" not in c_type and "Emergency" not in c_type else None
            }
            
            if new_custom["expireTime"]:
                issuance_msg = f"{zh_name} 在 {format_zh_time(now)}發出，有效時間至{format_zh_time(target_expire_dt)}。\n{en_name} has been issued at {format_en_time(now)}, and is valid until {format_en_time(target_expire_dt)}."
            else:
                issuance_msg = f"{zh_name} 在 {format_zh_time(now)}發出。\n{en_name} has been issued at {format_en_time(now)}."

            _, en_area = translate_areas(c_area)
            final_announcement = custom_announcement if custom_announcement else get_template_announcement(c_type, en_area)
            if final_announcement:
                issuance_msg += f"\n\n📢 **Announcement / 特別報告:**\n{final_announcement}"
                history['announcements'].append({"time": now.isoformat(), "text": final_announcement})
                
            messages.append(issuance_msg)
            current_custom = new_custom
            
            history['warnings'].append({
                "id": f"CUST-{int(now.timestamp())}",
                "is_custom": True, "code": c_type,
                "zh_name": zh_name, "en_name": en_name,
                "issue_time": now.isoformat(),
                "expire_time": new_custom['expireTime'],
                "status": "active"
            })

        elif action == 'EXTEND' and current_custom and current_custom['type'] == c_type:
            if target_expire_dt:
                current_custom['expireTime'] = target_expire_dt.isoformat()
                messages.append(f"{zh_name} 有效時間延長至{format_zh_time(target_expire_dt)}。\n{en_name} has been extended until {format_en_time(target_expire_dt)}.")
                hist_item = get_active_history(history, c_type, is_custom=True)
                if hist_item: hist_item['expire_time'] = target_expire_dt.isoformat()

        elif action == 'CANCEL' and current_custom and current_custom['type'] == c_type:
            messages.append(f"{zh_name} 在{format_zh_time(now)}取消。\n{en_name} has been cancelled at {format_en_time(now)}.")
            hist_item = get_active_history(history, c_type, is_custom=True)
            if hist_item:
                hist_item['status'] = 'cancelled'
                hist_item['end_time'] = now.isoformat()
                hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())
            current_custom = None

    else:
        # Custom Native Expiry / Auto-Cancel
        if current_custom:
            is_official_upg = False
            zh_c, en_c = get_warning_identifiers(current_custom['type'], current_custom.get('area', 'None'))
            
            if "Watch" in current_custom['type']:
                rcode = official_en.get("WRAIN", {}).get("code", "")
                if (current_custom['type'] == 'White Rainstorm Watch' and rcode in ["A", "R", "B"]) or \
                   (current_custom['type'] == 'Red Rainstorm Watch' and rcode in ["R", "B"]) or \
                   (current_custom['type'] == 'Black Rainstorm Watch' and rcode == "B"):
                    messages.append(f"🛑 {zh_c} 因應天文台正式發出相應暴雨警告，在{format_zh_time(now)}自動取消。\n{en_c} has been automatically cancelled at {format_en_time(now)} due to official HKO upgrade.")
                    is_official_upg = True
                    hist_item = get_active_history(history, current_custom['type'], is_custom=True)
                    if hist_item:
                        hist_item['status'] = 'cancelled'
                        hist_item['end_time'] = now.isoformat()
                        hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())
                    current_custom = None

            if current_custom and current_custom.get('expireTime') and not is_official_upg:
                exp_dt = parse_time(current_custom['expireTime'])
                if now >= exp_dt:
                    messages.append(f"{zh_c} 有效時間在{format_zh_time(exp_dt)}終止。\n{en_c} valid until {format_en_time(exp_dt)} has terminated.")
                    hist_item = get_active_history(history, current_custom['type'], is_custom=True)
                    if hist_item:
                        hist_item['status'] = 'expired'
                        hist_item['end_time'] = exp_dt.isoformat()
                        hist_item['duration'] = calculate_duration(hist_item['issue_time'], exp_dt.isoformat())
                    current_custom = None

        # Official Warnings: Issues and Extends
        for code, en_warn in official_en.items():
            prev_w = prev_official.get(code, {})
            zh_n = official_tc.get(code, {}).get('name', en_warn.get('name'))
            en_n = en_warn.get('name')
            iss_t = parse_time(en_warn.get('issueTime'))
            exp_t = parse_time(en_warn.get('expireTime'))
            
            if not prev_w:
                if exp_t:
                    messages.append(f"{zh_n} 在 {format_zh_time(iss_t)}發出，有效時間至{format_zh_time(exp_t)}。\n{en_n} has been issued at {format_en_time(iss_t)}, and is valid until {format_en_time(exp_t)}.")
                else:
                    messages.append(f"{zh_n} 在 {format_zh_time(iss_t)}發出。\n{en_n} has been issued at {format_en_time(iss_t)}.")
                
                history['warnings'].append({
                    "id": f"OFF-{code}-{int(iss_t.timestamp())}",
                    "is_custom": False, "code": code,
                    "zh_name": zh_n, "en_name": en_n,
                    "issue_time": iss_t.isoformat(),
                    "expire_time": exp_t.isoformat() if exp_t else None,
                    "status": "active"
                })
            
            elif en_warn.get('updateTime') != prev_w.get('updateTime'):
                if code == "WTS" and en_warn.get('actionCode') == "EXTEND":
                    messages.append(f"{zh_n} 有效時間延長至{format_zh_time(exp_t)}。\n{en_n} has been extended until {format_en_time(exp_t)}.")
                    hist_item = get_active_history(history, code, is_custom=False)
                    if hist_item: hist_item['expire_time'] = exp_t.isoformat()

        # Official Warnings: Cancels and Expires
        for code, prev_w in prev_official.items():
            if code not in official_en:
                zh_n = prev_w.get('tc_name', prev_w.get('name'))
                en_n = prev_w.get('name')
                exp_t = parse_time(prev_w.get('expireTime'))
                
                if code == "WTS" and exp_t:
                    messages.append(f"{zh_n} 有效時間在{format_zh_time(exp_t)}終止。\n{en_n} valid until {format_en_time(exp_t)} has terminated.")
                else:
                    messages.append(f"{zh_n} 在{format_zh_time(now)}取消。\n{en_n} has been cancelled at {format_en_time(now)}.")
                
                hist_item = get_active_history(history, code, is_custom=False)
                if hist_item:
                    hist_item['status'] = 'cancelled' if not exp_t else 'expired'
                    hist_item['end_time'] = now.isoformat()
                    hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())

    if has_image_update_only and not messages:
        messages.append("📊 預測機率已手動更新。\nForecast probabilities manually updated.")

    next_official_state = {}
    for k, v in official_en.items():
        v_copy = dict(v)
        v_copy['tc_name'] = official_tc.get(k, {}).get('name', v.get('name'))
        next_official_state[k] = v_copy

    if messages:
        post_to_discord(messages, official_en, official_tc, current_custom, chances)
        
    save_json(STATE_FILE, {"official": next_official_state, "custom": current_custom, "chances": chances})
    save_json(HISTORY_FILE, history)

if __name__ == "__main__":
    main()
