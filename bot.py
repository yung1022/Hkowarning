import os
import json
import requests
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw, ImageFont

WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL')
HKO_WARNSUM_EN = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=en'
HKO_WARNSUM_TC = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warnsum&lang=tc'
HKO_WARNINFO_EN = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warningInfo&lang=en'
HKO_WARNINFO_TC = 'https://data.weather.gov.hk/weatherAPI/opendata/weather.php?dataType=warningInfo&lang=tc'

STATE_FILE = 'warning_state.json'
HISTORY_FILE = 'history.json'
IMAGE_FILE = 'current_warnings.png'

# --- SEVERITY ENGINE (S1 - S5) ---
def calculate_severity(size_str, intensity_str):
    try:
        size_matches = re.findall(r'\d+', str(size_str))
        size_val = float(size_matches[-1]) if size_matches else 0
        
        int_matches = re.findall(r'\d+', str(intensity_str))
        int_val = float(int_matches[-1]) if int_matches else 0
        
        s_score = 1
        if int_val >= 100 or (int_val >= 70 and size_val >= 50): s_score = 5
        elif int_val >= 70 or (int_val >= 50 and size_val >= 30): s_score = 4
        elif int_val >= 50 or (int_val >= 30 and size_val >= 20): s_score = 3
        elif int_val >= 30 or (int_val >= 10 and size_val >= 10): s_score = 2
        
        return f"S{s_score}"
    except Exception:
        return "S1"

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
    if w_type == 'White Rainstorm Watch': return f"1. Expect heavy rain of about 10mm/h to form over the next 2-3 hours.\n2. About 10mm/h of heavy rain is currently impacting on {area_text}."
    elif w_type == 'Blue Rainstorm Warning': return "1. Expect heavy rain of about 30mm/h to form over the next 2-3 hours.\n2. About 20mm/h of heavy rain is currently impacting on most parts of Hong Kong."
    elif w_type == 'Red Rainstorm Watch': return "The chance of issuing Red Rainstorm Warning has reached more than 70%, it is very likely that a 50mm/h heavy rain will impact Hong Kong very soon."
    elif w_type == 'Black Rainstorm Watch': return "The chance of issuing Black Rainstorm Warning has reached more than 70%, it is very likely that a 70mm/h heavy rain will impact Hong Kong very soon."
    elif w_type == 'Severe Thunderstorm Emergency': return f"There's currently a huge thunderstorm on {en_area}."
    return ""

def parse_time(iso_str):
    if not iso_str: return None
    try:
        return datetime.fromisoformat(iso_str)
    except Exception:
        return None

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
    except Exception: 
        return None

def get_warning_identifiers(w_type, area="None"):
    if w_type == 'White Rainstorm Watch': 
        zh_a, en_a = translate_areas(area)
        if en_a != 'None': return f"{zh_a}白色暴雨戒備信號", f"White Rainstorm Watch for {en_a}"
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
            with open(filepath, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception: pass
    return default

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_active_history(history_list, type_code, key_name='code'):
    for item in history_list:
        if item.get('status') == 'active' and item.get(key_name) == type_code:
            return item
    return None

def fetch_warning_info_text(code, lang='en'):
    url = HKO_WARNINFO_EN if lang == 'en' else HKO_WARNINFO_TC
    try:
        data = requests.get(url, timeout=10).json()
        if "details" in data:
            for item in data["details"]:
                if item.get("warningStatementCode") == code or item.get("subtype") == code:
                    return "\n".join(item.get("contents", []))
    except Exception:
        pass
    return ""

def paste_icon(img, folder, filename, x, y):
    path = f"assets/{folder}/{filename}.png"
    if os.path.exists(path):
        try:
            icon = Image.open(path).convert("RGBA").resize((32, 32))
            img.paste(icon, (x, int(y)), icon)
            return True
        except Exception:
            pass
    return False

def generate_status_image(official_en, official_tc, custom_warns, chances, current_mesos):
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
    cust_count = len(custom_warns)
    meso_count = len(current_mesos)
    
    chances_h = 0
    if show_red: chances_h += 30
    if show_blk: chances_h += 30
    if chances_h > 0: chances_h += 20
    
    height = 60 + 50 + (off_count * 90 if off_count else 50) + 50 + (cust_count * 90 if cust_count else 50) + 50 + (meso_count * 110 if meso_count else 50) + chances_h + 30
    
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

    # Official Warnings
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

    # Custom Warnings
    y += 15
    draw.text((20, y), "Unofficial Parody Warnings / 非官方警告", font=font_sec, fill=(155, 89, 182))
    y += 35
    if not custom_warns:
        draw.text((40, y), "No custom warnings active / 現時沒有非官方警告", font=font_body, fill=(150, 150, 150))
        y += 40
    else:
        for c_key, c_warn in custom_warns.items():
            zh_n, en_n = get_warning_identifiers(c_warn['type'], c_warn.get('area', 'None'))
            asset_name = UNOFFICIAL_ASSETS.get(c_warn['type'], 'default')
            
            if paste_icon(img, "unofficial", asset_name, 35, y):
                draw.text((75, y + 2), f"{zh_n} | {en_n}", font=font_body, fill=(200, 120, 255))
            else:
                draw.text((35, y), f"🔮 {zh_n} | {en_n}", font=font_body, fill=(200, 120, 255))
            
            iss_dt = parse_time(c_warn.get('issueTime'))
            detail = f"Issued: {format_en_time(iss_dt)}"
            if c_warn.get('expireTime'):
                exp_dt = parse_time(c_warn.get('expireTime'))
                detail += f" | Valid until: {format_en_time(exp_dt)}"
            draw.text((75, y + 35), detail, font=font_detail, fill=(180, 180, 180))
            y += 85

    # Mesoscale Discussions
    y += 15
    draw.text((20, y), "Mesoscale Discussions / 中尺度天氣討論", font=font_sec, fill=(243, 156, 18))
    y += 35
    if not current_mesos:
        draw.text((40, y), "No active discussions / 現時沒有生效討論", font=font_body, fill=(150, 150, 150))
        y += 40
    else:
        for m_id, m_data in current_mesos.items():
            sev_str = f" [{m_data.get('severity', 'S1')}]" if m_data.get('severity') else ""
            draw.text((35, y), f"🌪️ Mesoscale Discussion: {m_id}{sev_str}", font=font_body, fill=(243, 156, 18))
            
            kinematics = []
            if m_data.get('center'): kinematics.append(f"Loc: {m_data['center']}")
            if m_data.get('movement'): kinematics.append(f"Dir: {m_data['movement']}")
            if m_data.get('size'): kinematics.append(f"Size: {m_data['size']}")
            if m_data.get('intensity'): kinematics.append(f"Rain: {m_data['intensity']}")
            
            k_str = " | ".join(kinematics)
            if k_str: draw.text((75, y + 35), k_str, font=font_detail, fill=(255, 200, 100))
                
            iss_dt = parse_time(m_data.get('issueTime'))
            detail = f"Issued: {format_en_time(iss_dt)} | See dashboard map for area."
            draw.text((75, y + 55), detail, font=font_detail, fill=(180, 180, 180))
            y += 105

    # Chances
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

def post_to_discord(messages, official_en, official_tc, custom_warns, chances, current_mesos):
    if not messages: return
    generate_status_image(official_en, official_tc, custom_warns, chances, current_mesos)
    
    full_text = "\n\n".join(messages)
    chunks = [full_text[i:i+1900] for i in range(0, len(full_text), 1900)]
    
    try:
        for i, chunk in enumerate(chunks):
            payload = {"content": chunk}
            if i == len(chunks) - 1:
                with open(IMAGE_FILE, "rb") as f:
                    requests.post(WEBHOOK_URL, data={"payload_json": json.dumps(payload)}, files={"file": (IMAGE_FILE, f, "image/png")})
            else:
                requests.post(WEBHOOK_URL, json=payload)
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

    meso_action = os.environ.get('MESO_ACTION', '').strip()
    meso_id = os.environ.get('MESO_ID', '').strip()
    meso_text = os.environ.get('MESO_TEXT', '').strip()
    
    # --- Unpack the embedded payload (now 6 parts) ---
    meso_payload = os.environ.get('MESO_PAYLOAD', '').strip()
    meso_coords, meso_center, meso_size, meso_movement, meso_intensity, meso_severity = "", "", "", "", "", ""
    if meso_payload:
        parts = meso_payload.split('|')
        meso_coords = parts[0] if len(parts) > 0 else ""
        meso_center = parts[1] if len(parts) > 1 else ""
        meso_size = parts[2] if len(parts) > 2 else ""
        meso_movement = parts[3] if len(parts) > 3 else ""
        meso_intensity = parts[4] if len(parts) > 4 else ""
        meso_severity = parts[5] if len(parts) > 5 else calculate_severity(meso_size, meso_intensity)
    
    now = datetime.now(ZoneInfo("Asia/Hong_Kong"))
    
    # Fetch Official Data safely
    try:
        official_en = requests.get(HKO_WARNSUM_EN, timeout=10).json() or {}
    except Exception:
        official_en = {}
        
    try:
        official_tc = requests.get(HKO_WARNSUM_TC, timeout=10).json() or {}
    except Exception:
        official_tc = {}
    
    state_data = load_json(STATE_FILE, {"official": {}, "custom": {}, "chances": {}, "mesoscale": {}})
    prev_official = state_data.get("official", {})
    chances = state_data.get("chances", {})
    current_customs = state_data.get("custom", {})
    current_mesos = state_data.get("mesoscale", {})
        
    history = load_json(HISTORY_FILE, {})
    for k in ["official_warnings", "custom_warnings", "mesoscale_discussions", "announcements"]:
        history.setdefault(k, [])
    
    if in_red_chance: chances['red'] = "" if in_red_chance.upper() == 'CLEAR' else in_red_chance
    if in_blk_chance: chances['black'] = "" if in_blk_chance.upper() == 'CLEAR' else in_blk_chance
    
    messages = []
    
    # 1. Mesoscale Discussion Logic (With Timeline Updates)
    if meso_action == 'ISSUE' and meso_id:
        coords_list = []
        if meso_coords:
            for pair in meso_coords.split(';'):
                if ',' in pair:
                    try:
                        lat, lng = pair.split(',')
                        coords_list.append([float(lat), float(lng)])
                    except ValueError:
                        continue
        
        current_mesos[meso_id] = {
            "id": meso_id, "issueTime": now.isoformat(),
            "coords": coords_list, "text": meso_text, "center": meso_center,
            "movement": meso_movement, "size": meso_size, "intensity": meso_intensity, "severity": meso_severity
        }
        
        # Save track node for Zoom Earth style timeline
        history['mesoscale_discussions'].append({
            "id": meso_id, "issue_time": now.isoformat(), "status": "active",
            "updates": [{
                "time": now.isoformat(), "coords": coords_list, "text": meso_text,
                "center": meso_center, "movement": meso_movement, "size": meso_size, 
                "intensity": meso_intensity, "severity": meso_severity
            }]
        })
        
        msg = f"🌪️ **Mesoscale Discussion Issued: {meso_id}**\n"
        if meso_severity: msg += f"🚨 **Severity Category:** {meso_severity}\n"
        if meso_center: msg += f"📍 **Center:** {meso_center}\n"
        if meso_movement: msg += f"💨 **Movement:** {meso_movement}\n"
        if meso_size: msg += f"📏 **Size:** {meso_size}\n"
        if meso_intensity: msg += f"🌧️ **Intensity:** {meso_intensity}\n"
        if meso_text: msg += f"\n{meso_text}\n"
        msg += f"\n*(Area displayed on dashboard map)*"
        messages.append(msg)

    elif meso_action == 'UPDATE' and meso_id:
        if meso_id in current_mesos:
            m_data = current_mesos[meso_id]
            hist_item = get_active_history(history['mesoscale_discussions'], meso_id, key_name='id')
            
            if meso_coords:
                coords_list = []
                for pair in meso_coords.split(';'):
                    if ',' in pair:
                        try:
                            lat, lng = pair.split(',')
                            coords_list.append([float(lat), float(lng)])
                        except ValueError:
                            continue
                if coords_list: m_data['coords'] = coords_list
            else:
                coords_list = m_data.get('coords', [])
            
            # Update kinematics if payload provided them
            if meso_center: m_data['center'] = meso_center
            if meso_movement: m_data['movement'] = meso_movement
            if meso_size: m_data['size'] = meso_size
            if meso_intensity: m_data['intensity'] = meso_intensity
            if meso_severity: m_data['severity'] = meso_severity
            if meso_text: m_data['text'] = meso_text
            
            if hist_item:
                if 'updates' not in hist_item:
                    hist_item['updates'] = []
                hist_item['updates'].append({
                    "time": now.isoformat(), "coords": coords_list,
                    "center": m_data.get('center'), "movement": m_data.get('movement'),
                    "size": m_data.get('size'), "intensity": m_data.get('intensity'),
                    "severity": m_data.get('severity'), "text": m_data.get('text')
                })
                
            msg = f"🔄 **Mesoscale Discussion Updated: {meso_id}**\n"
            if m_data.get('severity'): msg += f"🚨 **Severity Category:** {m_data['severity']}\n"
            if m_data.get('center'): msg += f"📍 **Center:** {m_data['center']}\n"
            if m_data.get('movement'): msg += f"💨 **Movement:** {m_data['movement']}\n"
            if m_data.get('size'): msg += f"📏 **Size:** {m_data['size']}\n"
            if m_data.get('intensity'): msg += f"🌧️ **Intensity:** {m_data['intensity']}\n"
            if m_data.get('text'): msg += f"\n{m_data['text']}\n"
            msg += f"\n*(Area and forecast line updated on dashboard map)*"
            messages.append(msg)

    elif meso_action == 'CANCEL' and meso_id:
        if meso_id in current_mesos:
            del current_mesos[meso_id]
            messages.append(f"🛑 **Mesoscale Discussion Cancelled: {meso_id}**")
        hist_item = get_active_history(history['mesoscale_discussions'], meso_id, key_name='id')
        if hist_item:
            hist_item['status'] = 'cancelled'
            hist_item['end_time'] = now.isoformat()
            hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())

    # 2. Custom Announcements & Parody Warnings
    if action == 'ANNOUNCE':
        _, en_area = translate_areas(c_area)
        final_announcement = custom_announcement if custom_announcement else get_template_announcement(c_type, en_area)
        if final_announcement:
            messages.append(f"📢 **Announcement / 特別報告:**\n{final_announcement}")
            history['announcements'].append({"time": now.isoformat(), "text": final_announcement})

    elif action in ['ISSUE', 'EXTEND', 'CANCEL'] and c_type:
        zh_name, en_name = get_warning_identifiers(c_type, c_area)
        target_expire_dt = parse_custom_target_time(v_until)
        target_custom = current_customs.get(c_type)
        
        if action == 'ISSUE':
            if target_custom:
                old_zh, old_en = get_warning_identifiers(target_custom['type'], target_custom.get('area', 'None'))
                messages.append(f"🔄 {old_zh} 在{format_zh_time(now)}取消並被替代。\n{old_en} has been replaced and cancelled at {format_en_time(now)}.")
                old_hist = get_active_history(history['custom_warnings'], c_type)
                if old_hist:
                    old_hist['status'] = 'cancelled'
                    old_hist['end_time'] = now.isoformat()
                    old_hist['duration'] = calculate_duration(old_hist['issue_time'], now.isoformat())

            new_custom = {
                "type": c_type, "area": c_area,
                "issueTime": now.isoformat(),
                "expireTime": target_expire_dt.isoformat() if target_expire_dt and "Watch" not in c_type and "Emergency" not in c_type else None
            }
            
            issuance_msg = f"{zh_name} 在 {format_zh_time(now)}發出。"
            iss_en_msg = f"{en_name} has been issued at {format_en_time(now)}."
            if new_custom["expireTime"]:
                issuance_msg = f"{zh_name} 在 {format_zh_time(now)}發出，有效時間至{format_zh_time(target_expire_dt)}。"
                iss_en_msg = f"{en_name} has been issued at {format_en_time(now)}, and is valid until {format_en_time(target_expire_dt)}."

            _, en_area = translate_areas(c_area)
            final_announcement = custom_announcement if custom_announcement else get_template_announcement(c_type, en_area)
            
            full_msg = f"{issuance_msg}\n{iss_en_msg}"
            if final_announcement:
                full_msg += f"\n\n📢 **Announcement / 特別報告:**\n{final_announcement}"
                history['announcements'].append({"time": now.isoformat(), "text": final_announcement})
                
            messages.append(full_msg)
            current_customs[c_type] = new_custom
            
            history['custom_warnings'].append({
                "id": f"CUST-{int(now.timestamp())}", "code": c_type,
                "zh_name": zh_name, "en_name": en_name,
                "issue_time": now.isoformat(), "expire_time": new_custom['expireTime'],
                "status": "active"
            })

        elif action == 'EXTEND' and target_custom:
            if target_expire_dt:
                target_custom['expireTime'] = target_expire_dt.isoformat()
                messages.append(f"{zh_name} 有效時間延長至{format_zh_time(target_expire_dt)}。\n{en_name} has been extended until {format_en_time(target_expire_dt)}.")
                hist_item = get_active_history(history['custom_warnings'], c_type)
                if hist_item: hist_item['expire_time'] = target_expire_dt.isoformat()

        elif action == 'CANCEL' and target_custom:
            messages.append(f"{zh_name} 在{format_zh_time(now)}取消。\n{en_name} has been cancelled at {format_en_time(now)}.")
            hist_item = get_active_history(history['custom_warnings'], c_type)
            if hist_item:
                hist_item['status'] = 'cancelled'
                hist_item['end_time'] = now.isoformat()
                hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())
            del current_customs[c_type]

    # Auto Cancel logic
    for c_key in list(current_customs.keys()):
        c_warn = current_customs[c_key]
        zh_c, en_c = get_warning_identifiers(c_warn['type'], c_warn.get('area', 'None'))
        is_official_upg = False
        if "Watch" in c_warn['type']:
            rcode = official_en.get("WRAIN", {}).get("code", "")
            if (c_warn['type'] == 'White Rainstorm Watch' and rcode in ["A", "R", "B"]) or \
               (c_warn['type'] == 'Red Rainstorm Watch' and rcode in ["R", "B"]) or \
               (c_warn['type'] == 'Black Rainstorm Watch' and rcode == "B"):
                messages.append(f"🛑 {zh_c} 因應天文台正式發出相應暴雨警告，在{format_zh_time(now)}自動取消。\n{en_c} has been automatically cancelled at {format_en_time(now)} due to official HKO upgrade.")
                is_official_upg = True
                hist_item = get_active_history(history['custom_warnings'], c_key)
                if hist_item:
                    hist_item['status'] = 'cancelled'
                    hist_item['end_time'] = now.isoformat()
                    hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())
                del current_customs[c_key]

        if not is_official_upg and c_warn.get('expireTime'):
            exp_dt = parse_time(c_warn['expireTime'])
            if exp_dt and now >= exp_dt:
                messages.append(f"{zh_c} 有效時間在{format_zh_time(exp_dt)}終止。\n{en_c} valid until {format_en_time(exp_dt)} has terminated.")
                hist_item = get_active_history(history['custom_warnings'], c_key)
                if hist_item:
                    hist_item['status'] = 'expired'
                    hist_item['end_time'] = exp_dt.isoformat()
                    hist_item['duration'] = calculate_duration(hist_item['issue_time'], exp_dt.isoformat())
                del current_customs[c_key]

    # 3. Official Warnings
    for code, en_warn in official_en.items():
        prev_w = prev_official.get(code, {})
        action_code = en_warn.get('actionCode', 'ISSUE')
        zh_n = official_tc.get(code, {}).get('name', en_warn.get('name'))
        en_n = en_warn.get('name')
        
        if not prev_w or en_warn.get('updateTime') != prev_w.get('updateTime'):
            tc_detail = fetch_warning_info_text(code, 'tc')
            en_detail = fetch_warning_info_text(code, 'en')
            
            if not tc_detail:
                iss_t = parse_time(en_warn.get('issueTime'))
                exp_t = parse_time(en_warn.get('expireTime'))
                if action_code == 'CANCEL':
                    tc_detail = f"{zh_n} 在{format_zh_time(now)}取消。"
                    en_detail = f"{en_n} has been cancelled at {format_en_time(now)}."
                elif action_code in ['EXTEND', 'REISSUE']:
                    tc_detail = f"{zh_n} 有效時間延長/更新至{format_zh_time(exp_t)}。"
                    en_detail = f"{en_n} has been updated/extended until {format_en_time(exp_t)}."
                else:
                    tc_detail = f"{zh_n} 在 {format_zh_time(iss_t)}發出。"
                    en_detail = f"{en_n} has been issued at {format_en_time(iss_t)}."

            messages.append(f"**[{action_code}] {zh_n} | {en_n}**\n{tc_detail}\n\n{en_detail}")
            
            if action_code == 'ISSUE':
                old_hist = get_active_history(history['official_warnings'], code)
                if old_hist:
                    old_hist['status'] = 'replaced'
                    old_hist['end_time'] = now.isoformat()
                    old_hist['duration'] = calculate_duration(old_hist['issue_time'], now.isoformat())
                    
                history['official_warnings'].append({
                    "id": f"OFF-{code}-{int(now.timestamp())}", "code": code,
                    "zh_name": zh_n, "en_name": en_n,
                    "issue_time": en_warn.get('issueTime', now.isoformat()),
                    "expire_time": en_warn.get('expireTime'),
                    "status": "active"
                })
                
            elif action_code in ['EXTEND', 'UPDATE', 'REISSUE']:
                hist_item = get_active_history(history['official_warnings'], code)
                if hist_item: 
                    hist_item['expire_time'] = en_warn.get('expireTime')
                
            elif action_code == 'CANCEL':
                hist_item = get_active_history(history['official_warnings'], code)
                if hist_item:
                    hist_item['status'] = 'cancelled'
                    hist_item['end_time'] = en_warn.get('issueTime', now.isoformat())
                    hist_item['duration'] = calculate_duration(hist_item['issue_time'], hist_item['end_time'])

    for code, prev_w in prev_official.items():
        if code not in official_en:
            hist_item = get_active_history(history['official_warnings'], code)
            if hist_item:
                hist_item['status'] = 'ended'
                hist_item['end_time'] = now.isoformat()
                hist_item['duration'] = calculate_duration(hist_item['issue_time'], now.isoformat())

    has_image_update_only = (in_red_chance or in_blk_chance) and action == 'NONE'
    if has_image_update_only and not messages:
        messages.append("📊 預測機率已手動更新。\nForecast probabilities manually updated.")

    next_official_state = {}
    for k, v in official_en.items():
        v_copy = dict(v)
        v_copy['tc_name'] = official_tc.get(k, {}).get('name', v.get('name'))
        next_official_state[k] = v_copy

    if messages: post_to_discord(messages, official_en, official_tc, current_customs, chances, current_mesos)
    save_json(STATE_FILE, {"official": next_official_state, "custom": current_customs, "chances": chances, "mesoscale": current_mesos})
    save_json(HISTORY_FILE, history)

if __name__ == "__main__":
    main()
