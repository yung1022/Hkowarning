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
    time_str = dt.strftime("%I:%M %p").lstrip('0').lower()
    return time_str.replace("am", "a.m.").replace("pm", "p.m.")

def parse_custom_target_time(time_str):
    if not time_str or ":" not in time_str:
        return None
    try:
        now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        parts = time_str.strip().split(":")
        return now.replace(hour=int(parts[0]), minute=int(parts[1]), second=0, microsecond=0)
    except Exception:
        return None

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

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                data = json.load(f)
                return data.get("official", {}), data.get("custom", None), data.get("chances", {})
        except Exception: pass
    return {}, None, {}

def save_state(official, custom, chances):
    with open(STATE_FILE, 'w') as f:
        json.dump({"official": official, "custom": custom, "chances": chances}, f, indent=2)

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
    with open(IMAGE_FILE, "rb") as f:
        requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": (IMAGE_FILE, f, "image/png")})

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
    prev_official, current_custom, chances = load_state()
    
    if in_red_chance: chances['red'] = "" if in_red_chance.upper() == 'CLEAR' else in_red_chance
    if in_blk_chance: chances['black'] = "" if in_blk_chance.upper() == 'CLEAR' else in_blk_chance
    
    messages = []
    has_image_update_only = (in_red_chance or in_blk_chance) and action == 'NONE'

    if action == 'ANNOUNCE':
        _, en_area = translate_areas(c_area)
        final_announcement = custom_announcement if custom_announcement else get_template_announcement(c_type, en_area)
        if final_announcement:
            messages.append(f"📢 **Announcement / 特別報告:**\n{final_announcement}")

    elif action in ['ISSUE', 'EXTEND', 'CANCEL']:
        zh_name, en_name = get_warning_identifiers(c_type, c_area)
        target_expire_dt = parse_custom_target_time(v_until)
        
        if action == 'ISSUE':
            if current_custom and "Rainstorm" in current_custom['type'] and "Rainstorm Warning" in c_type:
                old_zh, old_en = get_warning_identifiers(current_custom['type'], current_custom.get('area', 'None'))
                messages.append(f"🔄 {old_zh} 在{format_zh_time(now)}取消並被替代。\n{old_en} has been replaced and cancelled at {format_en_time(now)}.")
            
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
                
            messages.append(issuance_msg)
            current_custom = new_custom

        elif action == 'EXTEND' and current_custom and current_custom['type'] == c_type:
            if target_expire_dt:
                current_custom['expireTime'] = target_expire_dt.isoformat()
                messages.append(f"{zh_name} 有效時間延長至{format_zh_time(target_expire_dt)}。\n{en_name} has been extended until {format_en_time(target_expire_dt)}.")

        elif action == 'CANCEL' and current_custom and current_custom['type'] == c_type:
            messages.append(f"{zh_name} 在{format_zh_time(now)}取消。\n{en_name} has been cancelled at {format_en_time(now)}.")
            current_custom = None

    else:
        if current_custom and current_custom.get('expireTime'):
            if now >= parse_time(current_custom['expireTime']):
                zh_n, en_n = get_warning_identifiers(current_custom['type'], current_custom.get('area', 'None'))
                messages.append(f"{zh_n} 有效時間在 {format_zh_time(parse_time(current_custom['expireTime']))} 終止。\n{en_n} has expired natively at {format_en_time(parse_time(current_custom['expireTime']))}.")
                current_custom = None

        if current_custom and "Watch" in current_custom['type']:
            is_official_amber = ("WRAIN" in official_en and "A" in official_en["WRAIN"].get("code", ""))
            is_official_red = ("WRAIN" in official_en and "R" in official_en["WRAIN"].get("code", ""))
            is_official_blk = ("WRAIN" in official_en and "B" in official_en["WRAIN"].get("code", ""))
            
            if (current_custom['type'] == 'White Rainstorm Watch' and (is_official_amber or is_official_red or is_official_blk)) or \
               (current_custom['type'] == 'Red Rainstorm Watch' and is_official_red) or \
               (current_custom['type'] == 'Black Rainstorm Watch' and is_official_blk):
                zh_n, en_n = get_warning_identifiers(current_custom['type'])
                messages.append(f"🛑 {zh_n} 因應天文台正式發出相應暴雨警告，在{format_zh_time(now)}自動取消。\n{en_n} has been automatically cancelled at {format_en_time(now)} due to official HKO upgrade.")
                current_custom = None

        for code, en_warn in official_en.items():
            prev_w = prev_official.get(code, {})
            if not prev_w or en_warn.get('updateTime') != prev_w.get('updateTime'):
                zh_n = official_tc.get(code, {}).get('name', en_warn.get('name'))
                iss_t = parse_time(en_warn.get('issueTime'))
                exp_t = parse_time(en_warn.get('expireTime'))
                
                # Thunderstorm Extend Fix
                if code == "WTS" and en_warn.get('actionCode') == "EXTEND":
                    messages.append(f"{zh_n} 有效時間延長至{format_zh_time(exp_t)}。\n{en_warn.get('name')} extended until {format_en_time(exp_t)}.")
                else:
                    messages.append(f"{zh_n} 在 {format_zh_time(iss_t)}發出。\n{en_warn.get('name')} issued at {format_en_time(iss_t)}.")

        for code, prev_w in prev_official.items():
            if code not in official_en:
                zh_n = prev_w.get('tc_name', prev_w.get('name'))
                
                # Thunderstorm Cancel Fix
                if code == "WTS":
                    exp_t = parse_time(prev_w.get('expireTime'))
                    t_str_zh = format_zh_time(exp_t) if exp_t else format_zh_time(now)
                    t_str_en = format_en_time(exp_t) if exp_t else format_en_time(now)
                    messages.append(f"雷暴警告有效時間在{t_str_zh}終止。\n{prev_w.get('name')} valid until {t_str_en} has terminated.")
                else:
                    messages.append(f"{zh_n} 在{format_zh_time(now)}取消。\n{prev_w.get('name')} cancelled at {format_en_time(now)}.")

    if has_image_update_only and not messages:
        messages.append("📊 預測機率已手動更新。\nForecast probabilities manually updated.")

    next_official_state = {}
    for k, v in official_en.items():
        v_copy = dict(v)
        v_copy['tc_name'] = official_tc.get(k, {}).get('name', v.get('name'))
        next_official_state[k] = v_copy

    if messages:
        post_to_discord(messages, official_en, official_tc, current_custom, chances)
    save_state(next_official_state, current_custom, chances)

if __name__ == "__main__":
    main()
