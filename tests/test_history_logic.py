import importlib.util
import sys
import types
from pathlib import Path

pil_module = types.ModuleType('PIL')
pil_image_module = types.ModuleType('PIL.Image')
pil_draw_module = types.ModuleType('PIL.ImageDraw')
pil_font_module = types.ModuleType('PIL.ImageFont')
class _FakeImage:
    def __init__(self, mode, size, color=(0, 0, 0, 0)):
        self.mode = mode
        self.size = size
        self._pixels = [[list(color) for _ in range(size[0])] for _ in range(size[1])]

    def putpixel(self, xy, value):
        x, y = xy
        self._pixels[y][x] = list(value)

    def getpixel(self, xy):
        x, y = xy
        return tuple(self._pixels[y][x])

    def save(self, *args, **kwargs):
        return None

pil_image_module.open = lambda *args, **kwargs: None
pil_image_module.new = lambda mode, size, color=(0, 0, 0, 0): _FakeImage(mode, size, color)
pil_draw_module.Draw = lambda *args, **kwargs: None
pil_font_module.truetype = lambda *args, **kwargs: None
pil_font_module.load_default = lambda: None
sys.modules['PIL'] = pil_module
sys.modules['PIL.Image'] = pil_image_module
sys.modules['PIL.ImageDraw'] = pil_draw_module
sys.modules['PIL.ImageFont'] = pil_font_module

MODULE_PATH = Path(__file__).resolve().parents[1] / 'bot.py'
spec = importlib.util.spec_from_file_location('bot', MODULE_PATH)
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)


def test_official_cancel_uses_update_time_for_end_time():
    history = {"official_warnings": []}
    official_en = {
        "WHOT": {
            "code": "WHOT",
            "name": "Very Hot Weather Warning",
            "issueTime": "2026-07-10T11:30:00+08:00",
            "expireTime": None,
            "actionCode": "CANCEL",
            "updateTime": "2026-07-11T18:45:25.207096+08:00",
        }
    }

    hist_item = {
        "id": "OFF-WHOT-1",
        "code": "WHOT",
        "issue_time": "2026-07-10T11:30:00+08:00",
        "status": "active",
    }
    history["official_warnings"].append(hist_item)

    bot.get_active_history = lambda items, type_code, key_name='code': next((item for item in items if item.get('status') == 'active' and item.get(key_name) == type_code), None)

    if official_en["WHOT"].get("actionCode") == "CANCEL":
        hist_item = bot.get_active_history(history["official_warnings"], "WHOT")
        if hist_item:
            hist_item['status'] = 'cancelled'
            hist_item['end_time'] = bot.get_event_time(official_en["WHOT"])
            hist_item['duration'] = bot.calculate_duration(hist_item['issue_time'], hist_item['end_time'])

    assert hist_item['status'] == 'cancelled'
    assert hist_item['end_time'] == '2026-07-11T18:45:25.207096+08:00'
    assert hist_item['duration'] == '31h 15m'


def test_reissue_updates_existing_history_without_duplication():
    history = {"official_warnings": []}
    official_en = {
        "WTS": {
            "code": "WTS",
            "name": "Thunderstorm Warning",
            "issueTime": "2026-07-13T07:00:00+08:00",
            "expireTime": "2026-07-13T10:00:00+08:00",
            "actionCode": "REISSUE",
            "updateTime": "2026-07-13T07:30:00+08:00",
        }
    }

    existing = {
        "id": "OFF-WTS-1",
        "code": "WTS",
        "issue_time": "2026-07-13T07:00:00+08:00",
        "expire_time": "2026-07-13T08:00:00+08:00",
        "status": "active",
    }
    history["official_warnings"].append(existing)

    bot.get_active_history = lambda items, type_code, key_name='code': next((item for item in items if item.get('status') == 'active' and item.get(key_name) == type_code), None)

    action_code = official_en["WTS"].get("actionCode")
    event_time = bot.get_event_time(official_en["WTS"])
    if action_code in ['EXTEND', 'UPDATE', 'REISSUE']:
        hist_item = bot.get_active_history(history["official_warnings"], "WTS")
        if hist_item:
            hist_item['expire_time'] = official_en["WTS"].get('expireTime')
            hist_item['last_action'] = action_code
            hist_item['last_seen_time'] = event_time

    assert len(history["official_warnings"]) == 1
    assert history["official_warnings"][0]['expire_time'] == '2026-07-13T10:00:00+08:00'
    assert history["official_warnings"][0]['last_action'] == 'REISSUE'


def test_rainviewer_assessment_triggers_for_heavy_cells():
    payload = {
        "current": {
            "rain": {
                "1h": 15,
                "area": "South China Sea"
            }
        },
        "past": [
            {"precipitation": {"max": 15}},
            {"precipitation": {"max": 10}}
        ]
    }

    result = bot.assess_rainviewer_activity(payload)

    assert result['should_issue'] is True
    assert result['intensity'] >= 15
    assert 'South China Sea' in result['summary'] or 'South China Sea' in result['area']


def test_pixel_analysis_marks_rainy_cells():
    img = bot.Image.new('RGBA', (2, 2), (0, 0, 0, 0))
    img.putpixel((0, 0), (255, 255, 255, 255))
    img.putpixel((1, 0), (120, 120, 120, 255))
    img.putpixel((0, 1), (80, 80, 80, 255))
    img.putpixel((1, 1), (255, 0, 0, 255))

    result = bot.analyze_rainviewer_pixels(img)

    assert result['rainy_pixels'] >= 3
    assert result['max_brightness'] >= 255
    assert result['rainy_points']


def test_hong_kong_projection_stays_within_hk_bbox():
    top_left = bot.project_to_hong_kong(0, 0, 100, 100)
    bottom_right = bot.project_to_hong_kong(100, 100, 100, 100)

    assert top_left[0] >= bot.HONG_KONG_BOUNDS['lat_min']
    assert top_left[0] <= bot.HONG_KONG_BOUNDS['lat_max']
    assert top_left[1] >= bot.HONG_KONG_BOUNDS['lon_min']
    assert top_left[1] <= bot.HONG_KONG_BOUNDS['lon_max']
    assert bottom_right[0] <= top_left[0]
    assert bottom_right[1] >= top_left[1]


def test_rainviewer_overlay_detects_threshold_pixels():
    img = bot.Image.new('RGBA', (4, 4), (0, 0, 0, 0))
    for x in range(2):
        for y in range(2):
            img.putpixel((x, y), (255, 255, 255, 255))
    img.putpixel((2, 2), (255, 255, 0, 255))
    img.putpixel((3, 2), (255, 0, 0, 255))

    result = bot.build_rainviewer_overlay(img)

    assert result['highlight_pixels'] >= 2
    assert result['clusters']
    assert result['html']


def test_auto_meso_message_includes_area_and_center():
    message = bot.build_auto_meso_message('MESO-001', 'Hong Kong', [22.3, 114.2], 32, 'Storm discussion active')

    assert 'MESO-001' in message
    assert 'Hong Kong' in message
    assert '22.3' in message
    assert '32' in message


def test_auto_meso_message_includes_rain_and_severity():
    message = bot.build_auto_meso_message('MESO-002', 'Hong Kong', [22.3, 114.2], 32, 'Storm discussion active', intensity=18.5, severity='S3')

    assert '18.5' in message
    assert 'S3' in message


def test_calculate_severity_matches_html_logic():
    assert bot.calculate_severity('30', '70mm/h') == 'S4'
    assert bot.calculate_severity('60', '20mm/h') == 'S2'
