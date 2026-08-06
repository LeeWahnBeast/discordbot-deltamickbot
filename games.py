import random
import io
import time
import os
import base64
import collections
import re
import unicodedata
from piece_sprites_data import _BUILTIN_PIECE_SPRITES_B64
import urllib.request
import urllib.parse
import json
import chess
from PIL import Image, ImageDraw, ImageFont
_firestore_db = None
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    _cred_json = os.environ.get('FIREBASE_CREDENTIALS')
    if _cred_json:
        cred = credentials.Certificate(json.loads(_cred_json))
        firebase_admin.initialize_app(cred)
        _firestore_db = firestore.client()
        print('[firestore] Đã kết nối Firestore thành công.')
    else:
        print('[firestore] Chưa có biến môi trường FIREBASE_CREDENTIALS — dùng RAM/file JSON tạm thời.')
except Exception as e:
    print(f'[firestore] Không kết nối được Firestore, dùng RAM/file JSON tạm thời: {e!r}')

def _firestore_load_collection(collection_name, fallback_file):
    if _firestore_db is not None:
        try:
            docs = _firestore_db.collection(collection_name).stream()
            return {int(doc.id): doc.to_dict() for doc in docs}
        except Exception as e:
            print(f"[firestore] Lỗi đọc collection '{collection_name}': {e!r}")
    try:
        with open(fallback_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def _firestore_save_doc(collection_name, user_id, data):
    if _firestore_db is None:
        return
    try:
        _firestore_db.collection(collection_name).document(str(user_id)).set(data)
    except Exception as e:
        print(f"[firestore] Lỗi ghi '{collection_name}/{user_id}': {e!r}")

def _firestore_delete_doc(collection_name, doc_id):
    if _firestore_db is None:
        return
    try:
        _firestore_db.collection(collection_name).document(str(doc_id)).delete()
    except Exception as e:
        print(f"[firestore] Lỗi xóa '{collection_name}/{doc_id}': {e!r}")
DEION_FILE = 'deion_data.json'
DEION_ICON = '<:deltamickcoin:1532181698995818728>'
TAX_RATE = 0.05
TAX_RECIPIENT_ID = 1210771747889090571
BOT_OWNER_ID = TAX_RECIPIENT_ID
INFINITE_AMOUNT = 999999999

def _apply_purchase_tax(price):
    tax = max(1, round(price * TAX_RATE))
    add_deion(TAX_RECIPIENT_ID, tax)
    return tax
_deion_cache = {uid: d.get('balance', 0) for uid, d in _firestore_load_collection('deion', DEION_FILE).items()}

def get_deion(user_id):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    return round(_deion_cache.get(user_id, 0), 2)

def add_deion(user_id, amount):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    if amount > 0 and _has_double_deion_buff(user_id):
        amount *= 2
    new_balance = round(get_deion(user_id) + amount, 2)
    _deion_cache[user_id] = new_balance
    _firestore_save_doc('deion', user_id, {'balance': new_balance})
    return new_balance

DAILY_FREE_GAMES = {'chess_bot': 5}
_daily_usage = {}

def _today_key():
    return time.strftime('%Y-%m-%d', time.gmtime())

def flag_lifetime_score(user_id):
    return _flag_lifetime_score.get(user_id, 0)

def flag_mythic_unlocked(user_id):
    return flag_lifetime_score(user_id) >= FLAG_UNLOCK_SCORE_MYTHIC

def _get_daily_usage(game_type, user_id):
    day = _today_key()
    usage = _daily_usage.setdefault(game_type, {}).setdefault(user_id, {'day': day, 'count': 0, 'extra_slots': 0})
    if usage['day'] != day:
        usage['day'] = day
        usage['count'] = 0
        usage['extra_slots'] = 0
    return usage

def daily_games_played_today(game_type, user_id):
    return _get_daily_usage(game_type, user_id)['count']

def daily_games_left_today(game_type, user_id):
    usage = _get_daily_usage(game_type, user_id)
    limit = DAILY_FREE_GAMES[game_type] + usage['extra_slots']
    return max(0, limit - usage['count'])

def daily_add_slot(game_type, user_id):
    _get_daily_usage(game_type, user_id)['extra_slots'] += 1

def _consume_daily_slot(game_type, user_id):
    _get_daily_usage(game_type, user_id)['count'] += 1

_chess_games = {}
_PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
CHESS_STALE_SECONDS = 30 * 60
CHESS_TIME_MODES = {'bullet': {'label': '⚡ Cờ đạn (Bullet)', 'base': 2 * 60, 'increment': 1}, 'blitz': {'label': '🔥 Cờ chớp (Blitz)', 'base': 5 * 60, 'increment': 2}, 'rapid': {'label': '🚀 Cờ nhanh (Rapid)', 'base': 15 * 60, 'increment': 5}, 'classical': {'label': '🏛️ Cờ tiêu chuẩn (Classical)', 'base': 60 * 60, 'increment': 10}}
CHESS_DEFAULT_TIME_MODE = 'rapid'

def _sign(d):
    return f'+{d}' if d >= 0 else str(d)

def _fmt_clock(seconds):
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    return f'{m}:{s:02d}'

def chess_remaining_seconds(cid, color):
    game = _chess_games[cid]
    if not game.get('is_pvp') or 'clocks' not in game:
        return None
    base = game['clocks'][color]
    if game['board'].turn == color and game.get('clock_running_since'):
        elapsed = time.time() - game['clock_running_since']
        return base - elapsed
    return base

def chess_check_timeout(cid):
    game = _chess_games.get(cid)
    if game is None or not game.get('is_pvp') or 'clocks' not in game:
        return None
    turn_color = game['board'].turn
    remaining = chess_remaining_seconds(cid, turn_color)
    if remaining is not None and remaining <= 0:
        return turn_color
    return None

def _touch(cid):
    if cid in _chess_games:
        _chess_games[cid]['last_move_at'] = time.time()

def chess_touch(cid):
    _touch(cid)

def chess_active(cid):
    game = _chess_games.get(cid)
    if game is None:
        return False
    if time.time() - game.get('last_move_at', 0) > CHESS_STALE_SECONDS:
        _chess_games.pop(cid, None)
        return False
    return True

def chess_force_reset(cid):
    existed = cid in _chess_games
    _chess_games.pop(cid, None)
    _chess_invites.pop(cid, None)
    _chess_draw_offers.pop(cid, None)
    return existed

CHESS_DEFAULT_BOT_ELO = 300  # Cấp 5 (Delfish) — mức mặc định khi không chọn

def chess_start(cid, player_id, bot_elo=CHESS_DEFAULT_BOT_ELO):
    if daily_games_left_today('chess_bot', player_id) <= 0:
        return (False, False)
    _consume_daily_slot('chess_bot', player_id)
    dumbed = shop_consume_cu_cai(player_id)
    _chess_games[cid] = {'board': chess.Board(), 'is_pvp': False, 'player_id': player_id, 'player_color': chess.WHITE, 'last_move_at': time.time(), 'bot_elo': bot_elo, 'last_move': None, 'bot_dumbed': dumbed}
    return (dumbed, True)

def chess_start_pvp(cid, white_id, black_id, time_mode=CHESS_DEFAULT_TIME_MODE):
    cfg = CHESS_TIME_MODES[time_mode]
    ref_white = shop_consume_trong_tai(white_id)
    ref_black = shop_consume_trong_tai(black_id)
    shield_white = shop_consume_shield_timeout(white_id)
    clocks = {chess.WHITE: cfg['base'] + (60 if shield_white else 0), chess.BLACK: cfg['base']}
    _chess_games[cid] = {'board': chess.Board(), 'is_pvp': True, 'white_id': white_id, 'black_id': black_id, 'last_move_at': time.time(), 'last_move': None, 'time_mode': time_mode, 'clocks': clocks, 'increment': cfg['increment'], 'clock_running_since': time.time(), 'referee_favors': chess.WHITE if ref_white else chess.BLACK if ref_black else None}
    return (ref_white, ref_black, shield_white)

def chess_is_pvp(cid):
    return _chess_games[cid]['is_pvp']

def chess_current_turn_id(cid):
    game = _chess_games[cid]
    board = game['board']
    return game['white_id'] if board.turn == chess.WHITE else game['black_id']

def chess_end(cid):
    _chess_games.pop(cid, None)
    _chess_draw_offers.pop(cid, None)

def chess_player_id(cid):
    return _chess_games[cid]['player_id']
DEFAULT_ELO = 800
K_FACTOR = 32
HINT_ELO_PENALTY = 100
# Bot cờ vua tên "Delfish", 12 cấp độ (0-11), độ mạnh tăng dần theo Elo.
# random_chance: xác suất bot đi nước ngẫu nhiên thay vì nước tốt nhất (càng cao càng dễ).
BOT_LEVELS = {
    50:   {'label': '🐟 Delfish · Cấp 0 (Người mới)', 'random_chance': 1.00},
    100:  {'label': '🐟 Delfish · Cấp 1',             'random_chance': 0.90},
    150:  {'label': '🐟 Delfish · Cấp 2',             'random_chance': 0.80},
    200:  {'label': '🐟 Delfish · Cấp 3',             'random_chance': 0.70},
    250:  {'label': '🐟 Delfish · Cấp 4',             'random_chance': 0.60},
    300:  {'label': '🐟 Delfish · Cấp 5',             'random_chance': 0.50},
    350:  {'label': '🐟 Delfish · Cấp 6',             'random_chance': 0.40},
    400:  {'label': '🐟 Delfish · Cấp 7',             'random_chance': 0.30},
    500:  {'label': '🐟 Delfish · Cấp 8',             'random_chance': 0.20},
    1500: {'label': '🐟 Delfish · Cấp 9',             'random_chance': 0.10},
    2000: {'label': '🐟 Delfish · Cấp 10',            'random_chance': 0.05},
    3500: {'label': '🐟 Delfish · Cấp 11',            'random_chance': 0.00},
}
ELO_FILE = 'chess_elo.json'
_elo_cache = {uid: d.get('elo', DEFAULT_ELO) for uid, d in _firestore_load_collection('elo', ELO_FILE).items()}

def get_elo(user_id):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    return _elo_cache.get(user_id, DEFAULT_ELO)

def _set_elo(user_id, new_elo):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    _elo_cache[user_id] = new_elo
    _firestore_save_doc('elo', user_id, {'elo': new_elo})
    return new_elo
SHOP_RESTOCK_SECONDS = 5 * 60
SHOP_ITEMS = {
    'elo_100': {'emoji': '🥶', 'name': 'Mua Tài (100 Elo)', 'currency': 'deion', 'price': 0.5, 'stock': 8, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '📈 +100 Elo ngay lập tức, không cần thắng, không cần chơi, không cần liêm sỉ.\n🐐 Messi mà thấy giá này chắc cũng phải khóc vì rẻ.'},
    'elo10': {'emoji': '💠', 'name': '10 Elo', 'currency': 'deion', 'price': 0.1, 'stock': 20, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '📈 +10 Elo bé xíu, dành cho người mua tài mà vẫn muốn giữ chút liêm sỉ.\n🐜 Chưa đủ để flex nhưng đủ để tự lừa bản thân là đang tiến bộ.'},
    'hint_free': {'emoji': '💡', 'name': 'Gợi Ý Miễn Phí', 'currency': 'deion', 'price': 1.5, 'stock': 5, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '🎯 Dùng 1 lần — hỏi bài mà không bị trừ điểm, sung sướng như quay cóp trót lọt.\n🧠 Não bạn nghỉ hưu sớm, bot lo hết.'},
    'chess_slot': {'emoji': '🎟️', 'name': 'Slot Vé Cờ Vua', 'currency': 'deion', 'price': 1, 'stock': 6, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '📈 +1 lượt đấu Bot hôm nay (vượt giới hạn 5 vé/ngày).\n♟️ Nghiện cờ thì Delta Mick Bot không cản, chỉ cần trả tiền vé.'},
    've_1': {'emoji': '🎫', 'name': 'Túi Vé Nhỏ (+1)', 'currency': 'deion', 'price': 0.3, 'stock': 15, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '🎟️ +1 Vé — dùng để mua thêm lượt chơi Wordle/Minesweeper/Đoán Quốc Gia khi hết free.\n🎮 Ghiền game thì mua vé, đơn giản vậy thôi.'},
    've_5': {'emoji': '🎫', 'name': 'Túi Vé Vừa (+5)', 'currency': 'deion', 'price': 1.2, 'stock': 10, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '🎟️ +5 Vé cùng lúc — mua sỉ rẻ hơn mua lẻ.\n📦 Dân chơi hệ tích trữ vé chính hiệu.'},
    've_10': {'emoji': '🎫', 'name': 'Túi Vé Lớn (+10)', 'currency': 'deion', 'price': 2.0, 'stock': 6, 'rarity': 'uncommon', 'appear_chance': 0.8, 'desc': '🎟️ +10 Vé nguyên bịch — thỏa sức cày Đoán Quốc Gia.\n💪 Full combo cả 3 minigame không lo hết vé.'},
    'deion_5': {'emoji': '💰', 'name': 'Túi Deion (5)', 'currency': 'elo', 'price': 200, 'stock': 5, 'rarity': 'uncommon', 'appear_chance': 0.75, 'desc': '💸 Bán 200 Elo lấy 5 Deion — vay nóng lãi cắt cổ nhưng tự nguyện.\n🏦 Tín dụng đen phiên bản cờ vua, không ai ép bạn cả.'},
    'shield_timeout': {'emoji': '🛡️', 'name': 'Khiên Hết Giờ', 'currency': 'deion', 'price': 4, 'stock': 3, 'rarity': 'uncommon', 'appear_chance': 0.75, 'desc': '🎯 Dùng 1 lần — cộng free 60 giây để nghĩ nước đi cho thiên tài chậm tiêu.\n🐢 Rùa cũng có ngày về đích, miễn là mua đủ khiên.'},
    'trong_tai': {'emoji': '⚖️', 'name': 'Trọng Tài Chess (PvP)', 'currency': 'deion', 'price': 5, 'stock': 3, 'rarity': 'uncommon', 'appear_chance': 0.6, 'desc': '🎯 Dùng 1 lần — mua đứt ông trọng tài trận PvP tiếp theo.\n🛡️ Thổi còi thiên vị bạn công khai giữa thanh thiên bạch nhật.\n🤫 "Đây là quyết định cuối cùng, không khiếu nại" — trọng tài, vừa nhận phong bì.'},
    'double_deion': {'emoji': '✨', 'name': 'Nhân Đôi Deion (24 giờ)', 'currency': 'elo', 'price': 150, 'stock': 4, 'rarity': 'rare', 'appear_chance': 0.4, 'desc': '⏳ x2 Deion trong 24 giờ — bán Elo lấy Deion như bán nhà lấy vàng mã.\n🤑 Tư bản đích thực, không màng liêm sỉ chỉ màng lợi nhuận.'},
    'cu_cai': {'emoji': '🥕', 'name': 'Củ Cải', 'currency': 'deion', 'price': 6, 'stock': 2, 'rarity': 'rare', 'appear_chance': 0.35, 'desc': '🎯 Dùng 1 lần — nhét củ cải vào não Chess Bot:\n🤯 IQ bot rớt về âm, đi cờ như đang say rượu ngoài quán nhậu.\n♟️ Thua ván này thì thôi khỏi chơi cờ luôn đi bạn ơi. 💀🥶'},
    'mango_mustard': {'emoji': '🥭', 'name': 'Mango Mustard', 'currency': 'deion', 'price': 8, 'stock': 1, 'rarity': 'legendary', 'appear_chance': 0.15, 'desc': '🎯 Dùng 1 lần — sốt mù tạt xoài huyền thoại, không ai hiểu công thức nhưng ai cũng sợ.\n💥 Ăn vào +0.5 Deion NGAY LẬP TỨC vì can đảm thử món này xứng đáng được thưởng.\n🤢 Tác dụng phụ: ám ảnh vị giác vĩnh viễn.'},
    'ronaldo_pasta': {'emoji': '🍝', 'name': 'Ronaldo Pasta', 'currency': 'elo', 'price': 500, 'stock': 1, 'rarity': 'legendary', 'appear_chance': 0.15, 'desc': '🎯 Dùng 1 lần — đĩa mì Ý SIUUUU chính hiệu, ăn vào tự tin thái quá.\n📈 +150 Elo NGAY LẬP TỨC vì tự tin cũng là một loại sức mạnh.\n⚠️ Cảnh báo: có thể khiến bạn ăn mừng quá lố sau mỗi nước đi.'},
    'role_gubby': {'emoji': '🐹', 'name': 'Role Gubby', 'currency': 'deion', 'price': 40, 'stock': 1, 'rarity': 'legendary', 'appear_chance': 0.2, 'desc': '🎖️ Vĩnh viễn thành Gubby chính hiệu, không hoàn không đổi trả.\n🐹 Một khi đã Gubby thì Gubby cả đời, hối hận cũng muộn rồi.'},
}
RARITY_LABEL = {'common': '⚪ Thường', 'uncommon': '🟢 Ít gặp', 'rare': '🔵 Hiếm', 'legendary': '🟣 Huyền thoại'}
_user_buffs = {}
_shop_stock = {}
_shop_available = {}
_shop_stock_cycle = None
_receipts = {}

def _ensure_stock_cycle():
    global _shop_stock_cycle
    cycle = shop_current_cycle()
    if _shop_stock_cycle != cycle:
        _shop_stock_cycle = cycle
        _shop_stock.clear()
        _shop_available.clear()
        rng = random.Random(cycle)
        for key, item in SHOP_ITEMS.items():
            available = rng.random() < item['appear_chance']
            _shop_available[key] = available
            _shop_stock[key] = item['stock'] if available else 0

def shop_stock_left(item_key):
    _ensure_stock_cycle()
    return _shop_stock.get(item_key, 0)

def shop_item_available(item_key):
    _ensure_stock_cycle()
    return _shop_available.get(item_key, False)

def _get_buffs(user_id):
    return _user_buffs.setdefault(user_id, {'cu_cai': 0, 'trong_tai': 0, 'double_deion_until': 0, 'gubby_role': False, 'hint_free': 0, 'shield_timeout': 0})

def _has_double_deion_buff(user_id):
    buffs = _user_buffs.get(user_id)
    return bool(buffs) and time.time() < buffs.get('double_deion_until', 0)

def shop_current_cycle():
    return int(time.time() // SHOP_RESTOCK_SECONDS)

def shop_seconds_until_restock():
    elapsed = time.time() % SHOP_RESTOCK_SECONDS
    return int(SHOP_RESTOCK_SECONDS - elapsed)

def shop_list():
    _ensure_stock_cycle()
    return SHOP_ITEMS

_RECEIPTS_MAX_PER_USER = 30

def _add_receipt(user_id, item_key, item, cost_currency, cost, balance_after):
    entry = {
        'time': time.time(), 'item_key': item_key, 'item_name': item['name'],
        'emoji': item['emoji'], 'currency': cost_currency, 'cost': cost,
        'balance_after': balance_after,
    }
    history = _receipts.setdefault(user_id, [])
    history.append(entry)
    if len(history) > _RECEIPTS_MAX_PER_USER:
        del history[0:len(history) - _RECEIPTS_MAX_PER_USER]
    return entry

def get_receipts(user_id):
    return list(reversed(_receipts.get(user_id, [])))

def shop_buy(user_id, item_key):
    _ensure_stock_cycle()
    item = SHOP_ITEMS.get(item_key)
    if item is None:
        return {'ok': False, 'reason': '❌ Vật phẩm không tồn tại.', 'item': None, 'balance_after': None}
    if not _shop_available.get(item_key, False) or _shop_stock.get(item_key, 0) <= 0:
        return {'ok': False, 'reason': f"❌ **{item['name']}** đã hết hàng đợt này! Chờ restock sau **{shop_seconds_until_restock() // 60} phút** nhé.", 'item': item, 'balance_after': None}
    currency = item['currency']
    price = item['price']
    current = get_deion(user_id) if currency == 'deion' else get_elo(user_id)
    currency_label = 'Deion' if currency == 'deion' else 'Elo'
    if current < price:
        return {'ok': False, 'reason': f'❌ Không đủ {currency_label}! Cần **{price}**, bạn chỉ có **{current}**.', 'item': item, 'balance_after': current}
    if currency == 'deion':
        balance_after = add_deion(user_id, -price)
        _apply_purchase_tax(price)
    else:
        balance_after = _set_elo(user_id, get_elo(user_id) - price)
    buffs = _get_buffs(user_id)
    if item_key == 'elo_100':
        _set_elo(user_id, get_elo(user_id) + 100)
    elif item_key == 'elo10':
        _set_elo(user_id, get_elo(user_id) + 10)
    elif item_key == 'cu_cai':
        buffs['cu_cai'] += 1
    elif item_key == 'double_deion':
        base = max(time.time(), buffs['double_deion_until'])
        buffs['double_deion_until'] = base + 24 * 3600
    elif item_key == 'role_gubby':
        buffs['gubby_role'] = True
    elif item_key == 'trong_tai':
        buffs['trong_tai'] += 1
    elif item_key == 'hint_free':
        buffs['hint_free'] += 1
    elif item_key == 'deion_5':
        add_deion(user_id, 5)
    elif item_key == 'shield_timeout':
        buffs['shield_timeout'] += 1
    elif item_key == 'chess_slot':
        daily_add_slot('chess_bot', user_id)
    elif item_key == 've_1':
        _ext.add_ve(user_id, 1)
    elif item_key == 've_5':
        _ext.add_ve(user_id, 5)
    elif item_key == 've_10':
        _ext.add_ve(user_id, 10)
    elif item_key == 'mango_mustard':
        add_deion(user_id, 0.5)
    elif item_key == 'ronaldo_pasta':
        _set_elo(user_id, get_elo(user_id) + 150)
    _shop_stock[item_key] -= 1
    receipt = _add_receipt(user_id, item_key, item, currency, price, balance_after)
    if currency == 'deion':
        _ext.quest_notify_spend(user_id, price)
    _ext.quest_notify_shop(user_id)
    return {'ok': True, 'reason': None, 'item': item, 'balance_after': balance_after, 'receipt': receipt}

def shop_consume_cu_cai(user_id):
    buffs = _user_buffs.get(user_id)
    if not buffs or buffs.get('cu_cai', 0) <= 0:
        return False
    buffs['cu_cai'] -= 1
    return True

def shop_consume_trong_tai(user_id):
    buffs = _user_buffs.get(user_id)
    if not buffs or buffs.get('trong_tai', 0) <= 0:
        return False
    buffs['trong_tai'] -= 1
    return True

def shop_consume_hint_free(user_id):
    buffs = _user_buffs.get(user_id)
    if not buffs or buffs.get('hint_free', 0) <= 0:
        return False
    buffs['hint_free'] -= 1
    return True

def shop_consume_shield_timeout(user_id):
    buffs = _user_buffs.get(user_id)
    if not buffs or buffs.get('shield_timeout', 0) <= 0:
        return False
    buffs['shield_timeout'] -= 1
    return True

def shop_inventory_text(user_id):
    buffs = _get_buffs(user_id)
    lines = []
    ve_count = _ext.get_ve(user_id)
    if ve_count > 0:
        lines.append(f'🎟️ Vé: còn **{ve_count}**')
    if buffs['cu_cai'] > 0:
        lines.append(f"🥕 Củ Cải: còn **{buffs['cu_cai']}**")
    if buffs['trong_tai'] > 0:
        lines.append(f"⚖️ Trọng Tài: còn **{buffs['trong_tai']}**")
    if buffs['hint_free'] > 0:
        lines.append(f"💡 Gợi Ý Miễn Phí: còn **{buffs['hint_free']}**")
    if buffs['shield_timeout'] > 0:
        lines.append(f"🛡️ Khiên Hết Giờ: còn **{buffs['shield_timeout']}**")
    if _has_double_deion_buff(user_id):
        remain = buffs['double_deion_until'] - time.time()
        h, rem = divmod(int(remain), 3600)
        m = rem // 60
        lines.append(f'✨ Nhân Đôi Deion: còn **{h}h{m:02d}m**')
    if buffs['gubby_role']:
        lines.append('🐹 Role Gubby: đã sở hữu vĩnh viễn')
    return '\n'.join(lines) if lines else '_Chưa có vật phẩm/buff nào đang hoạt động._'

def _expected_score(elo_a, elo_b):
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))

def update_elo(id_a, elo_a, id_b, elo_b, score_a):
    expected_a = _expected_score(elo_a, elo_b)
    expected_b = 1 - expected_a
    score_b = 1 - score_a
    delta_a = round(K_FACTOR * (score_a - expected_a))
    delta_b = round(K_FACTOR * (score_b - expected_b))
    new_a = max(100, elo_a + delta_a)
    new_b = max(100, elo_b + delta_b)
    if id_a is not None:
        _elo_cache[id_a] = new_a
        _firestore_save_doc('elo', id_a, {'elo': new_a})
    if id_b is not None:
        _elo_cache[id_b] = new_b
        _firestore_save_doc('elo', id_b, {'elo': new_b})
    return (new_a, new_b, delta_a, delta_b)

def apply_hint_penalty(user_id):
    current = get_elo(user_id)
    new_elo = max(100, current - HINT_ELO_PENALTY)
    _elo_cache[user_id] = new_elo
    _firestore_save_doc('elo', user_id, {'elo': new_elo})
    return new_elo
PIECE_NAME_VN = {chess.PAWN: 'Tốt', chess.KNIGHT: 'Mã', chess.BISHOP: 'Tượng', chess.ROOK: 'Xe', chess.QUEEN: 'Hậu', chess.KING: 'Vua'}

def chess_from_options(cid):
    board = _chess_games[cid]['board']
    seen = {}
    for move in board.legal_moves:
        if move.from_square not in seen:
            piece = board.piece_at(move.from_square)
            name = PIECE_NAME_VN[piece.piece_type]
            seen[move.from_square] = f'{name} {chess.square_name(move.from_square)}'
    return [(chess.square_name(sq), label) for sq, label in seen.items()]

def chess_to_options(cid, from_square_name):
    board = _chess_games[cid]['board']
    from_sq = chess.parse_square(from_square_name)
    options = []
    for move in board.legal_moves:
        if move.from_square != from_sq:
            continue
        if move.promotion and move.promotion != chess.QUEEN:
            continue
        to_name = chess.square_name(move.to_square)
        captured = board.piece_at(move.to_square)
        if captured:
            label = f'{to_name} (ăn {PIECE_NAME_VN[captured.piece_type]})'
        elif board.is_en_passant(move):
            label = f'{to_name} (ăn Tốt qua đường)'
        else:
            label = to_name
        options.append((to_name, label))
    return options

def chess_make_move(cid, from_square_name, to_square_name):
    game = _chess_games[cid]
    board = game['board']
    from_sq = chess.parse_square(from_square_name)
    to_sq = chess.parse_square(to_square_name)
    move = next((m for m in board.legal_moves if m.from_square == from_sq and m.to_square == to_sq and (not (m.promotion and m.promotion != chess.QUEEN))), None)
    if move is None:
        return (False, None, None)
    mover_color = board.turn
    scored = _score_all_moves(board, mover_color)
    annotation = _annotate_move(board, move, mover_color, scored)
    board.push(move)
    game['last_move'] = move
    _touch(cid)
    if game.get('is_pvp') and 'clocks' in game:
        now = time.time()
        elapsed = now - game['clock_running_since']
        game['clocks'][mover_color] = max(0, game['clocks'][mover_color] - elapsed) + game['increment']
        game['clock_running_since'] = now
    return (True, board.outcome(claim_draw=True), annotation)
_SQUARE_PX = 60
_BOARD_PX = _SQUARE_PX * 8
_LIGHT = (240, 217, 181)
_DARK = (181, 136, 99)
_LASTMOVE_LIGHT = (205, 210, 106)
_LASTMOVE_DARK = (170, 162, 58)
_PIECE_UNICODE = {(chess.PAWN, True): '♙', (chess.KNIGHT, True): '♘', (chess.BISHOP, True): '♗', (chess.ROOK, True): '♖', (chess.QUEEN, True): '♕', (chess.KING, True): '♔', (chess.PAWN, False): '♟', (chess.KNIGHT, False): '♞', (chess.BISHOP, False): '♝', (chess.ROOK, False): '♜', (chess.QUEEN, False): '♛', (chess.KING, False): '♚'}
_PIECE_LETTER = {chess.KING: 'K', chess.QUEEN: 'Q', chess.ROOK: 'R', chess.BISHOP: 'B', chess.KNIGHT: 'N', chess.PAWN: 'P'}
_PIECE_KEY_INFO = {}
for _pt, _letter in _PIECE_LETTER.items():
    _PIECE_KEY_INFO[f'{_letter}_w'] = (_pt, chess.WHITE)
    _PIECE_KEY_INFO[f'{_letter}_b'] = (_pt, chess.BLACK)
PIECE_KEY_LABELS = {'K_w': 'Vua Trắng', 'Q_w': 'Hậu Trắng', 'R_w': 'Xe Trắng', 'B_w': 'Tượng Trắng', 'N_w': 'Mã Trắng', 'P_w': 'Tốt Trắng', 'K_b': 'Vua Đen', 'Q_b': 'Hậu Đen', 'R_b': 'Xe Đen', 'B_b': 'Tượng Đen', 'N_b': 'Mã Đen', 'P_b': 'Tốt Đen'}
PIECE_THEME_FILE = 'chess_piece_themes.json'
_piece_theme_cache = {uid: d for uid, d in _firestore_load_collection('chess_piece_theme', PIECE_THEME_FILE).items()}
_PIECE_SPRITE_CACHE_MAX = 64
_piece_sprite_cache = collections.OrderedDict()

def _piece_key(piece_type, color):
    return f'{_PIECE_LETTER[piece_type]}_{('w' if color == chess.WHITE else 'b')}'

def get_piece_theme_url(user_id, piece_type, color):
    d = _piece_theme_cache.get(user_id)
    return d.get(_piece_key(piece_type, color)) if d else None

def set_piece_theme(user_id, key, url):
    raw = _fetch_image_bytes(url)
    if raw is None:
        return False
    try:
        img = Image.open(io.BytesIO(raw)).convert('RGBA').resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        stored_value = 'b64:' + base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception as e:
        print(f'[custom_chess] Ảnh tải được nhưng không đọc được (không phải ảnh hợp lệ?) từ {url}: {e!r}')
        return False
    d = _piece_theme_cache.setdefault(user_id, {})
    d[key] = stored_value
    _firestore_save_doc('chess_piece_theme', user_id, d)
    _piece_sprite_cache.pop(stored_value, None)
    return True

def set_piece_theme_bytes(user_id, key, raw):
    try:
        img = Image.open(io.BytesIO(raw)).convert('RGBA').resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        stored_value = 'b64:' + base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception as e:
        print(f'[custom_chess] File tải lên nhưng không đọc được (không phải ảnh hợp lệ?): {e!r}')
        return False
    d = _piece_theme_cache.setdefault(user_id, {})
    d[key] = stored_value
    _firestore_save_doc('chess_piece_theme', user_id, d)
    _piece_sprite_cache.pop(stored_value, None)
    return True

def clear_piece_theme(user_id, key=None):
    d = _piece_theme_cache.get(user_id)
    if not d:
        return False
    if key is None:
        _piece_theme_cache.pop(user_id, None)
        _firestore_save_doc('chess_piece_theme', user_id, {})
        return True
    existed = d.pop(key, None) is not None
    _firestore_save_doc('chess_piece_theme', user_id, d)
    return existed

def _fetch_image_bytes(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.read()
    except Exception as e:
        print(f'[custom_chess] Không tải được ảnh từ {url}: {e!r}')
        return None

def _load_piece_sprite(value):
    if value in _piece_sprite_cache:
        _piece_sprite_cache.move_to_end(value)
        return _piece_sprite_cache[value]
    try:
        if value.startswith('b64:'):
            raw = base64.b64decode(value[4:])
        else:
            raw = _fetch_image_bytes(value)
            if raw is None:
                raise ValueError('fetch failed')
        sprite = Image.open(io.BytesIO(raw)).convert('RGBA').resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
    except Exception as e:
        print(f'[custom_chess] Không đọc được ảnh: {e!r}')
        _piece_sprite_cache[value] = None
        _piece_sprite_cache.move_to_end(value)
        if len(_piece_sprite_cache) > _PIECE_SPRITE_CACHE_MAX:
            _piece_sprite_cache.popitem(last=False)
        return None
    _piece_sprite_cache[value] = sprite
    _piece_sprite_cache.move_to_end(value)
    if len(_piece_sprite_cache) > _PIECE_SPRITE_CACHE_MAX:
        _piece_sprite_cache.popitem(last=False)
    return sprite

def preview_piece_sprite(url):
    _piece_sprite_cache.pop(url, None)
    return _load_piece_sprite(url)

def piece_theme_preview_image(user_id):
    pad = 4
    label_h = 16
    cell = _SQUARE_PX
    cols, rows = (6, 2)
    w = cols * (cell + pad) + pad
    h = rows * (cell + pad + label_h) + pad
    img = Image.new('RGBA', (w, h), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    font = _chess_font(11)
    names = {chess.KING: 'Vua', chess.QUEEN: 'Hậu', chess.ROOK: 'Xe', chess.BISHOP: 'Tượng', chess.KNIGHT: 'Mã', chess.PAWN: 'Tốt'}
    cols_order = [chess.KING, chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT, chess.PAWN]
    rows_order = [chess.WHITE, chess.BLACK]
    for row_idx, color in enumerate(rows_order):
        for col_idx, piece_type in enumerate(cols_order):
            x = pad + col_idx * (cell + pad)
            y = pad + row_idx * (cell + pad + label_h)
            url = get_piece_theme_url(user_id, piece_type, color)
            sprite = _load_piece_sprite(url) if url else None
            if sprite is None:
                sprite = default_piece_sprite(piece_type, color)
            img.alpha_composite(sprite, (x, y))
            label = f'{names[piece_type]} {('Trắng' if color == chess.WHITE else 'Đen')}'
            draw.text((x + cell / 2, y + cell + 2), label, font=font, fill='white', anchor='ma')
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='PNG')
    buf.seek(0)
    return buf

def _chess_font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()

def _frac_to_px(points, ss):
    return [(px * ss, py * ss) for px, py in points]
_DEFAULT_PIECE_SPRITE_CACHE = {}

def default_piece_sprite(piece_type, color):
    key = (piece_type, color)
    if key in _DEFAULT_PIECE_SPRITE_CACHE:
        return _DEFAULT_PIECE_SPRITE_CACHE[key]
    letter = _PIECE_LETTER[piece_type]
    color_key = 'w' if color == chess.WHITE else 'b'
    b64_key = f'{letter}_{color_key}'
    raw = base64.b64decode(_BUILTIN_PIECE_SPRITES_B64[b64_key])
    sprite = Image.open(io.BytesIO(raw)).convert('RGBA').resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
    _DEFAULT_PIECE_SPRITE_CACHE[key] = sprite
    return sprite

def _render_board_img(cid):
    """Vẽ bàn cờ hiện tại, trả về đối tượng PIL.Image (RGBA) — dùng chung cho ảnh bàn cờ và ảnh kết quả."""
    game = _chess_games[cid]
    board = game['board']
    last_move = game.get('last_move')
    lastmove_squares = {last_move.from_square, last_move.to_square} if last_move else set()
    white_id = game['player_id'] if not game['is_pvp'] else game['white_id']
    black_id = None if not game['is_pvp'] else game['black_id']
    owner_id = {chess.WHITE: white_id, chess.BLACK: black_id}
    img = Image.new('RGBA', (_BOARD_PX, _BOARD_PX), _DARK)
    draw = ImageDraw.Draw(img)
    coord_font = _chess_font(13)
    for row in range(8):
        for col in range(8):
            x0, y0 = (col * _SQUARE_PX, row * _SQUARE_PX)
            sq = chess.square(col, 7 - row)
            is_light = (row + col) % 2 == 0
            if sq in lastmove_squares:
                color = _LASTMOVE_LIGHT if is_light else _LASTMOVE_DARK
            else:
                color = _LIGHT if is_light else _DARK
            draw.rectangle([x0, y0, x0 + _SQUARE_PX, y0 + _SQUARE_PX], fill=color)
            label_color = _DARK if is_light else _LIGHT
            if col == 0:
                draw.text((x0 + 3, y0 + 1), str(8 - row), font=coord_font, fill=label_color)
            if row == 7:
                draw.text((x0 + _SQUARE_PX - 11, y0 + _SQUARE_PX - 16), chr(ord('a') + col), font=coord_font, fill=label_color)
            piece = board.piece_at(sq)
            if piece is None:
                continue
            uid = owner_id[piece.color]
            url = get_piece_theme_url(uid, piece.piece_type, piece.color) if uid else None
            sprite = _load_piece_sprite(url) if url else None
            if sprite is None:
                sprite = default_piece_sprite(piece.piece_type, piece.color)
            img.alpha_composite(sprite, (x0, y0))
    return img

def chess_board_image(cid):
    buf = io.BytesIO()
    _render_board_img(cid).convert('RGB').save(buf, format='PNG')
    buf.seek(0)
    return buf

# ---- Ảnh thẻ kết quả (kiểu lichess: bàn cờ + banner kết quả phủ giữa) ----
CHESS_QUOTES = [
    ('Every chess master was once a beginner.', 'Irving Chernev'),
    ('Chess is life in miniature.', 'Garry Kasparov'),
    ('When you see a good move, look for a better one.', 'Emanuel Lasker'),
    ('Chess is the gymnasium of the mind.', 'Blaise Pascal'),
    ('Tactics flow from a superior position.', 'Bobby Fischer'),
    ('The pin is mightier than the sword.', 'Fred Reinfeld'),
    ('A bad plan is better than none at all.', 'Frank Marshall'),
    ('Chess is everything: art, science, and sport.', 'Anatoly Karpov'),
    ('In chess, as in life, opportunity strikes but once.', 'David Teasdale'),
]

def _wrap_lines(draw, text, font, max_width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        trial = f'{cur} {w}'.strip()
        if draw.textlength(trial, font=font) <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def chess_result_image(cid, title, subtitle, white_name, black_name):
    """title: 'white won' / 'black won' / 'draw'. subtitle: 'by resignation' / 'by checkmate' / v.v."""
    img = _render_board_img(cid).convert('RGBA')
    draw = ImageDraw.Draw(img)
    top, bottom = int(_BOARD_PX * 0.17), int(_BOARD_PX * 0.86)
    box = Image.new('RGBA', (_BOARD_PX, bottom - top), (250, 250, 248, 235))
    img.alpha_composite(box, (0, top))
    draw = ImageDraw.Draw(img)
    cx, y = _BOARD_PX // 2, top + 12
    f_title, f_sub, f_quote = (_chess_font(30), _chess_font(15), _chess_font(13))
    draw.text((cx, y), title, font=f_title, fill=(25, 25, 25), anchor='ma')
    y += 36
    draw.text((cx, y), subtitle, font=f_sub, fill=(95, 95, 95), anchor='ma')
    y += 34
    quote, author = random.choice(CHESS_QUOTES)
    for line in _wrap_lines(draw, quote, f_quote, _BOARD_PX * 0.72):
        draw.text((cx, y), line, font=f_quote, fill=(75, 75, 75), anchor='ma')
        y += 17
    draw.text((cx, y), f'-{author}', font=f_quote, fill=(75, 75, 75), anchor='ma')
    y += 30
    move_count = _chess_games[cid]['board'].fullmove_number
    info_lines = [f"Date: {time.strftime('%-d/%-m/%Y')}", f'Move Count: {move_count}', f'White: {white_name}', f'Black: {black_name}']
    x_left = int(_BOARD_PX * 0.10)
    for line in info_lines:
        draw.text((x_left, y), line, font=f_quote, fill=(20, 20, 20))
        y += 19
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='PNG')
    buf.seek(0)
    return buf

def _chess_elo_caption(white_name, black_name, new_white, new_black, d_white, d_black, extra=''):
    return f'⚪ {white_name}: {new_white} Elo ({_sign(d_white)})\n⚫ {black_name}: {new_black} Elo ({_sign(d_black)}){extra}'

_CHESS_TERMINATION_SUBTITLE = {
    chess.Termination.CHECKMATE: 'by checkmate',
    chess.Termination.STALEMATE: 'by stalemate',
    chess.Termination.INSUFFICIENT_MATERIAL: 'by insufficient material',
    chess.Termination.FIFTY_MOVES: 'by the 50-move rule',
    chess.Termination.THREEFOLD_REPETITION: 'by repetition',
}

def _material_score(board, color):
    score = 0
    for piece_type, value in _PIECE_VALUES.items():
        score += len(board.pieces(piece_type, color)) * value
        score -= len(board.pieces(piece_type, not color)) * value
    return score

def _score_all_moves(board, color):
    scored = []
    for move in board.legal_moves:
        board.push(move)
        score = 1000 if board.is_checkmate() else _material_score(board, color) + (0.5 if board.is_check() else 0)
        board.pop()
        scored.append((move, score))
    return scored
BRILLIANT_MARGIN = 3
BLUNDER_HANG_VALUE = 5
BLUNDER_MARGIN = 5

def _annotate_move(board, move, color, scored):
    played_score = next((s for m, s in scored if m == move))
    if played_score >= 900:
        return '!!'
    scores_desc = sorted((s for _, s in scored), reverse=True)
    best_score = scores_desc[0]
    second_score = scores_desc[1] if len(scores_desc) > 1 else best_score
    if played_score >= best_score and best_score - second_score >= BRILLIANT_MARGIN and (best_score > 0):
        return '!!'
    board.push(move)
    hang = 0
    if not board.is_game_over():
        for reply in board.legal_moves:
            captured = board.piece_at(reply.to_square)
            if captured:
                hang = max(hang, _PIECE_VALUES.get(captured.piece_type, 0))
    board.pop()
    if hang >= BLUNDER_HANG_VALUE or best_score - played_score >= BLUNDER_MARGIN:
        return '??'
    return None

def chess_bot_move(cid):
    game = _chess_games[cid]
    board = game['board']
    bot_color = not game['player_color']
    random_chance = 1.0 if game.get('bot_dumbed') else BOT_LEVELS[game['bot_elo']]['random_chance']
    scored = _score_all_moves(board, bot_color)
    best_score = max((s for _, s in scored))
    if random_chance > 0 and random.random() < random_chance:
        move = random.choice([m for m, _ in scored])
    else:
        move = random.choice([m for m, s in scored if s == best_score])
    annotation = _annotate_move(board, move, bot_color, scored)
    board.push(move)
    game['last_move'] = move
    return (board.outcome(claim_draw=True), annotation)

def chess_outcome_text(cid, outcome, display_names=None):
    """Ván kết thúc tự nhiên trên bàn (chiếu bí / hòa). Trả (image_buf, caption)."""
    game = _chess_games[cid]
    subtitle = _CHESS_TERMINATION_SUBTITLE.get(outcome.termination, 'draw')
    if game['is_pvp']:
        white_id, black_id = (game['white_id'], game['black_id'])
        white_name = display_names[True] if display_names else f'<@{white_id}>'
        black_name = display_names[False] if display_names else f'<@{black_id}>'
        score_white = 0.5 if outcome.winner is None else (1 if outcome.winner == chess.WHITE else 0)
        new_white, new_black, d_white, d_black = update_elo(white_id, get_elo(white_id), black_id, get_elo(black_id), score_white)
        if outcome.winner is None:
            title, extra = ('draw', '')
        else:
            winner_id = white_id if outcome.winner == chess.WHITE else black_id
            winner_name = white_name if outcome.winner == chess.WHITE else black_name
            title = 'white won' if outcome.winner == chess.WHITE else 'black won'
            new_winner_aura = add_deion(winner_id, 0.5)
            extra = f'\n\n{DEION_ICON} {winner_name} nhận **+0.5 Deion** (số dư: {new_winner_aura}).'
        caption = _chess_elo_caption(white_name, black_name, new_white, new_black, d_white, d_black, extra)
        return chess_result_image(cid, title, subtitle, white_name, black_name), caption
    player_id, player_color = (game['player_id'], game['player_color'])
    score_player = 0.5 if outcome.winner is None else (1 if outcome.winner == player_color else 0)
    new_player_elo, _, d_player, _ = update_elo(player_id, get_elo(player_id), None, game['bot_elo'], score_player)
    bot_label = BOT_LEVELS[game['bot_elo']]['label']
    player_name = display_names[True] if display_names else f'<@{player_id}>'
    white_name = player_name if player_color == chess.WHITE else bot_label
    black_name = bot_label if player_color == chess.WHITE else player_name
    ve_line = ''
    if outcome.winner is None:
        title = 'draw'
    elif score_player == 1:
        title = 'white won' if player_color == chess.WHITE else 'black won'
        _, ve = _ext.award_win('chess_bot', player_id, deion_mult=0)
        new_bal = add_deion(player_id, 0.5)
        ve_line = f'\n{DEION_ICON} +0.5 Deion, {_ext.VE_ICON} +{ve} Vé (số dư: {new_bal}).'
    else:
        title = 'black won' if player_color == chess.WHITE else 'white won'
    caption = f'Elo của bạn: {new_player_elo} ({_sign(d_player)}){ve_line}'
    return chess_result_image(cid, title, subtitle, white_name, black_name), caption

def _chess_win_by(cid, winner_color, subtitle, prefix_line, display_names=None):
    """Dùng chung cho đầu hàng & hết giờ (luôn PvP, luôn có màu thắng rõ ràng). Trả (image_buf, caption)."""
    game = _chess_games[cid]
    white_id, black_id = (game['white_id'], game['black_id'])
    white_name = display_names[True] if display_names else f'<@{white_id}>'
    black_name = display_names[False] if display_names else f'<@{black_id}>'
    score_white = 1 if winner_color == chess.WHITE else 0
    new_white, new_black, d_white, d_black = update_elo(white_id, get_elo(white_id), black_id, get_elo(black_id), score_white)
    winner_id = white_id if winner_color == chess.WHITE else black_id
    winner_name = white_name if winner_color == chess.WHITE else black_name
    new_winner_aura = add_deion(winner_id, 0.5)
    extra = f'\n\n{DEION_ICON} {winner_name} nhận **+0.5 Deion** (số dư: {new_winner_aura}).'
    caption = f'{prefix_line}\n\n' + _chess_elo_caption(white_name, black_name, new_white, new_black, d_white, d_black, extra)
    title = 'white won' if winner_color == chess.WHITE else 'black won'
    return chess_result_image(cid, title, subtitle, white_name, black_name), caption

def chess_resign_text(cid, resigner_id, display_names=None):
    """Trả (image_buf, caption)."""
    game = _chess_games[cid]
    if game['is_pvp']:
        is_white_resigning = resigner_id == game['white_id']
        winner_color = chess.BLACK if is_white_resigning else chess.WHITE
        resigner_name = display_names[is_white_resigning] if display_names else f'<@{resigner_id}>'
        return _chess_win_by(cid, winner_color, 'by resignation', f'🏳️ {resigner_name} đã đầu hàng!', display_names)
    player_id = game['player_id']
    new_player_elo, _, d_player, _ = update_elo(player_id, get_elo(player_id), None, game['bot_elo'], 0)
    bot_label = BOT_LEVELS[game['bot_elo']]['label']
    player_name = display_names[True] if display_names else f'<@{player_id}>'
    player_color = game['player_color']
    white_name = player_name if player_color == chess.WHITE else bot_label
    black_name = bot_label if player_color == chess.WHITE else player_name
    title = 'black won' if player_color == chess.WHITE else 'white won'
    caption = f'🏳️ Bạn đã đầu hàng! {bot_label} thắng.\n\nElo của bạn: {new_player_elo} ({_sign(d_player)})'
    return chess_result_image(cid, title, 'by resignation', white_name, black_name), caption

def chess_timeout_text(cid, timed_out_color, display_names=None):
    """Luôn PvP (bot không có đồng hồ). Trả (image_buf, caption)."""
    game = _chess_games[cid]
    loser_id = game['white_id'] if timed_out_color == chess.WHITE else game['black_id']
    loser_name = display_names[timed_out_color == chess.WHITE] if display_names else f'<@{loser_id}>'
    return _chess_win_by(cid, not timed_out_color, 'by timeout', f'⏰ {loser_name} đã hết giờ!', display_names)

def chess_hint(cid, hinter_id):
    game = _chess_games[cid]
    board = game['board']
    mover_color = board.turn
    scored = _score_all_moves(board, mover_color)
    best_score = max((s for _, s in scored))
    move = random.choice([m for m, s in scored if s == best_score])
    piece = board.piece_at(move.from_square)
    piece_name = PIECE_NAME_VN[piece.piece_type]
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)
    if shop_consume_hint_free(hinter_id):
        new_elo = get_elo(hinter_id)
        hint_text = f'💡 Gợi ý (miễn phí 🎟️): đi **{piece_name} {from_sq} → {to_sq}**'
    else:
        new_elo = apply_hint_penalty(hinter_id)
        hint_text = f'💡 Gợi ý: đi **{piece_name} {from_sq} → {to_sq}**'
    return (hint_text, new_elo)

def chess_header_text(cid, display_names=None):
    game = _chess_games[cid]
    if game['is_pvp']:
        white_id, black_id = (game['white_id'], game['black_id'])
        white_name = display_names[True] if display_names else f'<@{white_id}>'
        black_name = display_names[False] if display_names else f'<@{black_id}>'
        if 'clocks' in game:
            w_left = chess_remaining_seconds(cid, chess.WHITE)
            b_left = chess_remaining_seconds(cid, chess.BLACK)
            mode_label = CHESS_TIME_MODES[game['time_mode']]['label']
            w_mark = '⏳' if game['board'].turn == chess.WHITE else '⏸️'
            b_mark = '⏳' if game['board'].turn == chess.BLACK else '⏸️'
            return f'{mode_label}\n⚪ **{white_name}** — {get_elo(white_id)} Elo — {w_mark} `{_fmt_clock(w_left)}`\n⚫ **{black_name}** — {get_elo(black_id)} Elo — {b_mark} `{_fmt_clock(b_left)}`'
        return f'⚪ **{white_name}** — {get_elo(white_id)} Elo\n⚫ **{black_name}** — {get_elo(black_id)} Elo'
    player_id = game['player_id']
    player_name = display_names[True] if display_names else f'<@{player_id}>'
    bot_elo = game['bot_elo']
    bot_label = BOT_LEVELS[bot_elo]['label']
    return f'⚪ **{player_name}** — {get_elo(player_id)} Elo\n⚫ **{bot_label}** — {bot_elo} Elo'
_chess_draw_offers = {}

def chess_offer_draw(cid, offerer_id):
    _chess_draw_offers[cid] = offerer_id

def chess_get_draw_offer(cid):
    return _chess_draw_offers.get(cid)

def chess_clear_draw_offer(cid):
    _chess_draw_offers.pop(cid, None)

def chess_accept_draw_text(cid, display_names=None):
    """Trả (image_buf, caption). Hòa theo thỏa thuận không ảnh hưởng Elo."""
    game = _chess_games[cid]
    white_id, black_id = (game['white_id'], game['black_id'])
    white_name = display_names[True] if display_names else f'<@{white_id}>'
    black_name = display_names[False] if display_names else f'<@{black_id}>'
    caption = f'🤝 {white_name} và {black_name} đã đồng ý hòa. Ván cờ kết thúc, Elo giữ nguyên.'
    return chess_result_image(cid, 'draw', 'by agreement', white_name, black_name), caption
def chess_captured_text(cid):
    board = _chess_games[cid]['board']
    remaining = {chess.WHITE: {}, chess.BLACK: {}}
    for color in (chess.WHITE, chess.BLACK):
        for piece_type in _PIECE_VALUES:
            remaining[color][piece_type] = len(board.pieces(piece_type, color))
    start_counts = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}

    def captured_symbols(by_color):
        opp = not by_color
        symbols = []
        for piece_type, start in start_counts.items():
            missing = start - remaining[opp][piece_type]
            symbols.extend([_PIECE_UNICODE[piece_type, opp]] * missing)
        return ''.join(symbols)
    white_took = captured_symbols(chess.WHITE)
    black_took = captured_symbols(chess.BLACK)
    if not white_took and (not black_took):
        return None
    parts = []
    if white_took:
        parts.append(f'⚪ Trắng đã ăn: {white_took}')
    if black_took:
        parts.append(f'⚫ Đen đã ăn: {black_took}')
    return '  |  '.join(parts)
_chess_invites = {}

def chess_create_invite(cid, inviter_id, invitee_id):
    _chess_invites[cid] = {'inviter_id': inviter_id, 'invitee_id': invitee_id}

def chess_get_invite(cid):
    return _chess_invites.get(cid)

def chess_clear_invite(cid):
    _chess_invites.pop(cid, None)
WIKI_API = 'https://vi.wikipedia.org/w/api.php'
WIKI_SUMMARY_MAX = 700

def wiki_lookup(keyword):
    headers = {'User-Agent': 'TornadoAddonBot/1.0 (Discord bot; contact: n/a)'}
    try:
        search_params = urllib.parse.urlencode({'action': 'query', 'list': 'search', 'srsearch': keyword, 'format': 'json', 'srlimit': 1})
        req = urllib.request.Request(f'{WIKI_API}?{search_params}', headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            search_data = json.loads(resp.read())
        results = search_data.get('query', {}).get('search', [])
        if not results:
            print(f'[wiki] Không có kết quả search cho: {keyword}')
            return None
        title = results[0]['title']
        extract_params = urllib.parse.urlencode({'action': 'query', 'prop': 'extracts|pageimages', 'exintro': 1, 'explaintext': 1, 'piprop': 'thumbnail', 'pithumbsize': 400, 'titles': title, 'format': 'json'})
        req2 = urllib.request.Request(f'{WIKI_API}?{extract_params}', headers=headers)
        with urllib.request.urlopen(req2, timeout=8) as resp:
            extract_data = json.loads(resp.read())
        pages = extract_data.get('query', {}).get('pages', {})
        page = next(iter(pages.values()))
        summary = page.get('extract', '').strip()
        if not summary:
            print(f"[wiki] Bài '{title}' không có extract")
            return None
        if len(summary) > WIKI_SUMMARY_MAX:
            summary = summary[:WIKI_SUMMARY_MAX].rsplit(' ', 1)[0] + '...'
        thumbnail = page.get('thumbnail', {}).get('source')
        article_url = f'https://vi.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}'
        return (title, summary, thumbnail, article_url)
    except Exception as e:
        print(f"[wiki] Lỗi khi tra '{keyword}': {type(e).__name__}: {e}")
        return None

REDEEM_FILE = 'redeem_data.json'
# Deion là tiền tệ khó kiếm (0.5 Deion/trận thắng cờ PvP), nên code redeem chỉ cho một lượng nhỏ.
REDEEM_CODES = {
    'ChaoNgayMoiVuiVe': {'deion': 0.5},
    'DeltaMickLaConCho': {'deion': 2},
}
_redeem_cache = {int(uid): d for uid, d in _firestore_load_collection('redeem_codes', REDEEM_FILE).items()}

def redeem_code(user_id, code):
    code = code.strip()
    entry = REDEEM_CODES.get(code)
    if entry is None:
        return {'ok': False, 'reason': '❌ Code không tồn tại hoặc đã hết hạn.'}
    used = _redeem_cache.setdefault(user_id, {'codes': []})
    if code in used['codes']:
        return {'ok': False, 'reason': '❌ Bạn đã nhập code này rồi!'}
    reward_lines = []
    if 'deion' in entry:
        add_deion(user_id, entry['deion'])
        reward_lines.append(f"{DEION_ICON} +{entry['deion']} Deion")
    used['codes'].append(code)
    _firestore_save_doc('redeem_codes', user_id, used)
    _ext.quest_notify_redeem_code(user_id)
    if 'deion' in entry:
        _ext.quest_notify_earn(user_id, entry['deion'])
    return {'ok': True, 'reward_lines': reward_lines}

def top_deion(n=10):
    items = [(uid, bal) for uid, bal in _deion_cache.items() if uid != BOT_OWNER_ID and bal > 0]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:n]

def top_elo(n=10):
    items = [(uid, elo) for uid, elo in _elo_cache.items() if uid != BOT_OWNER_ID]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:n]

# Wordle / Minesweeper / Guess-country + hệ thống Vé riêng — xem games_ext.py
from games_ext import *  # noqa: F401,F403
import games_ext as _ext
