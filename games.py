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
AURA_FILE = 'aura_data.json'
AURA_ICON = '<:mango:1529287058072408195>'
TAX_RATE = 0.05
TAX_RECIPIENT_ID = 1210771747889090571
BOT_OWNER_ID = TAX_RECIPIENT_ID
INFINITE_AMOUNT = 999999999

def _apply_purchase_tax(price):
    tax = max(1, round(price * TAX_RATE))
    add_aura(TAX_RECIPIENT_ID, tax)
    return tax
_aura_cache = {uid: d.get('balance', 0) for uid, d in _firestore_load_collection('aura', AURA_FILE).items()}

def get_aura(user_id):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    return _aura_cache.get(user_id, 0)

def add_aura(user_id, amount):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    if amount > 0 and _has_double_aura_buff(user_id):
        amount *= 2
    new_balance = get_aura(user_id) + amount
    _aura_cache[user_id] = new_balance
    _firestore_save_doc('aura', user_id, {'balance': new_balance})
    return new_balance

AURA_PLUS_FILE = 'aura_plus_data.json'
AURA_PLUS_ICON = AURA_ICON
AURA_PLUS_PER_GAME = 0.1
AURA_PLUS_EXCHANGE_RATE = 10
AURA_PLUS_EXCHANGE_FEE = 0.8
_aura_plus_cache = {uid: d.get('balance', 0.0) for uid, d in _firestore_load_collection('aura_plus', AURA_PLUS_FILE).items()}

def get_aura_plus(user_id):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    return round(_aura_plus_cache.get(user_id, 0.0), 2)

def add_aura_plus(user_id, amount):
    if user_id == BOT_OWNER_ID:
        return INFINITE_AMOUNT
    new_balance = round(get_aura_plus(user_id) + amount, 2)
    _aura_plus_cache[user_id] = new_balance
    _firestore_save_doc('aura_plus', user_id, {'balance': new_balance})
    return new_balance

def award_game_completion_aura_plus(user_id):
    return add_aura_plus(user_id, AURA_PLUS_PER_GAME)

def exchange_aura_plus_to_aura(user_id, aura_plus_amount):
    if aura_plus_amount <= 0 or get_aura_plus(user_id) < aura_plus_amount:
        return None
    gross_aura = aura_plus_amount * AURA_PLUS_EXCHANGE_RATE
    net_aura = gross_aura * (1 - AURA_PLUS_EXCHANGE_FEE)
    add_aura_plus(user_id, -aura_plus_amount)
    new_aura_balance = add_aura(user_id, net_aura)
    return {'spent': aura_plus_amount, 'received': net_aura, 'aura_after': new_aura_balance, 'aura_plus_after': get_aura_plus(user_id)}

def exchange_aura_to_aura_plus(user_id, aura_amount):
    if aura_amount <= 0 or get_aura(user_id) < aura_amount:
        return None
    gross_aura_plus = aura_amount / AURA_PLUS_EXCHANGE_RATE
    net_aura_plus = round(gross_aura_plus * (1 - AURA_PLUS_EXCHANGE_FEE), 2)
    add_aura(user_id, -aura_amount)
    new_aura_plus_balance = add_aura_plus(user_id, net_aura_plus)
    return {'spent': aura_amount, 'received': net_aura_plus, 'aura_after': get_aura(user_id), 'aura_plus_after': new_aura_plus_balance}

def folk_valley_rank(score, total=5):
    if score <= 1:
        return ('🐓 GÀ', 'Con gà mổ lúa cũng đoán giỏi hơn thế này.\n*"Gieo hạt sai mùa // rồi trách đất không màu mỡ."*', 9133628)
    elif score == 2:
        return ('🌽 TẬP SỰ ĐỒNG QUÊ', 'Còn non như bắp mới trổ, nhưng có tương lai.\n*"Cày chưa hết ruộng // mà đã mơ mùa gặt."*', 13934615)
    elif score == 3:
        return ('🌾 ỔN ÁP', 'Không tệ! Cỏ trong Folk Valley cũng gật gù đồng ý.\n*"Đo hai lần, đoán một lần // rồi hỏi con bò xem nó nhớ gì."*', 7315504)
    elif score == 4:
        return ('🚜 LÃO NÔNG THẦN TỐC', 'Gần chạm đỉnh! Kho thóc đang thì thầm tên bạn.\n*"Nếu chưa hỏng thì cũng nên nâng cấp phần mềm chuồng trại."*', 4160800)
    else:
        return ('✨ THẦN THÁNH FOLK VALLEY', 'Hoàn hảo. Đến chim trong Folk Valley cũng ngừng hót để cúi đầu.\n*"Gốc rễ vẫn nhớ // dù dữ liệu đã đổi mùa."*', 16766720)
WORDS = ['apple', 'beach', 'chair', 'dance', 'eagle', 'flame', 'grape', 'house', 'input', 'juice', 'knife', 'lemon', 'mango', 'night', 'ocean', 'piano', 'queen', 'river', 'stone', 'table', 'unity', 'voice', 'water', 'youth', 'zebra', 'bread', 'cloud', 'dream', 'fruit', 'glass', 'heart', 'image', 'koala', 'light', 'music', 'novel', 'orbit', 'peach', 'quiet', 'robot', 'smile', 'trust', 'value', 'world', 'brave', 'crown', 'delta', 'earth', 'faith', 'giant']
WORDLE_MAX_GUESSES = 6
_wordle_games = {}

def wordle_active(cid):
    return cid in _wordle_games

def wordle_start(cid, owner_id):
    if daily_games_left_today('wordle', owner_id) <= 0:
        return (None, False)
    _consume_daily_slot('wordle', owner_id)
    word = random.choice(WORDS)
    _wordle_games[cid] = {'word': word, 'guesses': 0, 'owner_id': owner_id}
    return (word, True)

def wordle_word(cid):
    return _wordle_games[cid]['word']

def wordle_end(cid):
    _wordle_games.pop(cid, None)

def wordle_check(cid, guess):
    game = _wordle_games[cid]
    word = game['word']
    guess = guess.lower()
    result = []
    chars = list(word)
    for i, ch in enumerate(guess):
        if ch == word[i]:
            result.append('🟩')
            chars[i] = None
        else:
            result.append(None)
    for i, ch in enumerate(guess):
        if result[i] is not None:
            continue
        if ch in chars:
            result[i] = '🟨'
            chars[chars.index(ch)] = None
        else:
            result[i] = '⬜'
    game['guesses'] += 1
    correct = guess == word
    done = game['guesses'] >= WORDLE_MAX_GUESSES
    return (''.join(result), correct, done)
FLAG_EASY = {'vietnam': 'vn', 'japan': 'jp', 'china': 'cn', 'usa': 'us', 'united states': 'us', 'france': 'fr', 'germany': 'de', 'italy': 'it', 'spain': 'es', 'uk': 'gb', 'united kingdom': 'gb', 'brazil': 'br', 'canada': 'ca', 'russia': 'ru', 'india': 'in', 'korea': 'kr', 'australia': 'au', 'mexico': 'mx', 'egypt': 'eg', 'thailand': 'th'}
FLAG_MEDIUM = {'portugal': 'pt', 'netherlands': 'nl', 'belgium': 'be', 'switzerland': 'ch', 'sweden': 'se', 'norway': 'no', 'poland': 'pl', 'greece': 'gr', 'turkey': 'tr', 'indonesia': 'id', 'malaysia': 'my', 'philippines': 'ph', 'singapore': 'sg', 'argentina': 'ar', 'chile': 'cl', 'colombia': 'co', 'saudi arabia': 'sa', 'south africa': 'za', 'new zealand': 'nz', 'ukraine': 'ua'}
FLAG_HARD = {'finland': 'fi', 'denmark': 'dk', 'austria': 'at', 'czech republic': 'cz', 'hungary': 'hu', 'romania': 'ro', 'iceland': 'is', 'peru': 'pe', 'cuba': 'cu', 'nigeria': 'ng', 'pakistan': 'pk', 'bangladesh': 'bd', 'iran': 'ir', 'iraq': 'iq', 'israel': 'il', 'uae': 'ae', 'morocco': 'ma', 'kenya': 'ke', 'ethiopia': 'et', 'myanmar': 'mm'}
FLAG_INSANE = {'bhutan': 'bt', 'brunei': 'bn', 'eswatini': 'sz', 'lesotho': 'ls', 'tuvalu': 'tv', 'nauru': 'nr', 'kiribati': 'ki', 'palau': 'pw', 'andorra': 'ad', 'liechtenstein': 'li', 'san marino': 'sm', 'monaco': 'mc', 'moldova': 'md', 'tajikistan': 'tj', 'kyrgyzstan': 'kg', 'turkmenistan': 'tm', 'djibouti': 'dj', 'comoros': 'km', 'suriname': 'sr', 'guyana': 'gy'}
FLAG_MYTHIC = {'tonga': 'to', 'micronesia': 'fm', 'marshall islands': 'mh', 'sao tome and principe': 'st', 'vanuatu': 'vu', 'solomon islands': 'sb', 'niue': 'nu', 'cook islands': 'ck', 'transnistria': 'md', 'abkhazia': 'ge', 'somaliland': 'so', 'western sahara': 'eh'}
FLAG_POOLS = {'easy': FLAG_EASY, 'medium': FLAG_MEDIUM, 'hard': FLAG_HARD, 'insane': FLAG_INSANE, 'mythic': FLAG_MYTHIC}
FLAG_AURA_PER_DIFFICULTY = {'easy': 6, 'medium': 10, 'hard': 14, 'insane': 20, 'mythic': 28}
FLAG_UNLOCK_SCORE_MYTHIC = 500
ROUNDS_PER_GAME = 5
DAILY_FREE_GAMES = {'flag': 5, 'chess_bot': 5, 'wordle': 5, 'minesweeper': 10}
_flag_games = {}
_daily_usage = {}
_flag_lifetime_score = {}

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

def flag_games_played_today(user_id):
    return daily_games_played_today('flag', user_id)

def flag_games_left_today(user_id):
    return daily_games_left_today('flag', user_id)

def flag_add_daily_slot(user_id):
    daily_add_slot('flag', user_id)

def flag_active(cid):
    return cid in _flag_games

def flag_start(cid, owner_id, difficulty):
    if difficulty == 'mythic' and (not flag_mythic_unlocked(owner_id)):
        return (None, False)
    if daily_games_left_today('flag', owner_id) <= 0:
        return (None, False)
    _consume_daily_slot('flag', owner_id)
    _flag_games[cid] = {'pool': FLAG_POOLS[difficulty], 'round': 0, 'score': 0, 'country': None, 'owner_id': owner_id, 'difficulty': difficulty}
    return (flag_next(cid), True)

def flag_next(cid):
    game = _flag_games[cid]
    if game['round'] >= ROUNDS_PER_GAME:
        return None
    country = random.choice(list(game['pool'].keys()))
    game['country'] = country
    game['round'] += 1
    return f'https://flagcdn.com/w320/{game['pool'][country]}.png'

def flag_check(cid, guesser_id, guess):
    game = _flag_games[cid]
    if guesser_id != game['owner_id']:
        return ('not_owner', game['round'] < ROUNDS_PER_GAME)
    correct = guess.strip().lower() == game['country']
    if correct:
        game['score'] += 1
        _flag_lifetime_score[guesser_id] = _flag_lifetime_score.get(guesser_id, 0) + 1
    return (correct, game['round'] < ROUNDS_PER_GAME)

def flag_aura_reward(cid):
    return FLAG_AURA_PER_DIFFICULTY[_flag_games[cid]['difficulty']]

def flag_answer(cid):
    return _flag_games[cid]['country']

def flag_progress(cid):
    g = _flag_games[cid]
    return (g['round'], ROUNDS_PER_GAME, g['score'])

def flag_owner(cid):
    return _flag_games[cid]['owner_id']

def flag_end(cid):
    _flag_games.pop(cid, None)

# ==================== ĐÁNH GIÁ ẢNH (/danhgia) ====================
DANHGIA_LOW_COMMENTS = ['💀 Bố cục hơi lụi, ánh sáng cũng chưa tới, cần chỉnh lại nhiều.', '😬 Màu sắc bị ám, khung hình chưa cân, làm lại đi bạn ơi.', '📉 Thiếu điểm nhấn, nhìn hơi phẳng, chưa có gì bắt mắt.', '🫠 Ánh sáng gắt quá làm mất chi tiết, bố cục cũng lệch tâm.', '🥲 Ảnh bị rung nhẹ, độ tương phản chưa tốt, cần cải thiện kỹ thuật.']
DANHGIA_MID_COMMENTS = ['🙂 Ổn áp, bố cục tạm được nhưng ánh sáng có thể chỉnh thêm chút.', '📸 Màu sắc hài hoà, chỉ tiếc góc chụp chưa tối ưu lắm.', '👌 Khá là ổn, thêm chút chỉnh sáng là lên hạng ngay.', '😌 Chủ thể rõ ràng, nhưng phông nền hơi rối, có thể tối giản hơn.', '🌤️ Ánh sáng tự nhiên đẹp, bố cục theo quy tắc 1/3 khá chuẩn rồi đó.']
DANHGIA_HIGH_COMMENTS = ['🔥 Bố cục cực chuẩn, ánh sáng mềm mại, không có gì để chê!', '✨ Màu sắc hài hoà xuất sắc, chủ thể nổi bật rõ ràng.', '🏆 Đỉnh của chóp! Góc chụp sáng tạo, ánh sáng và bố cục đều top.', '💎 Cân bằng sáng tối cực kỳ tinh tế, nhìn như ảnh chuyên nghiệp.', '🌟 Từng chi tiết đều được chăm chút, đây là ảnh xịn thật sự!']
DANHGIA_TIER_LABEL = {'low': ('📉 Cần cải thiện', 15158332), 'mid': ('🙂 Ổn áp', 15844367), 'high': ('🏆 Xuất sắc', 3066993)}

def danhgia_generate(image_url):
    score = random.randint(1, 10)
    if score <= 4:
        tier = 'low'
        comment = random.choice(DANHGIA_LOW_COMMENTS)
    elif score <= 7:
        tier = 'mid'
        comment = random.choice(DANHGIA_MID_COMMENTS)
    else:
        tier = 'high'
        comment = random.choice(DANHGIA_HIGH_COMMENTS)
    tier_label, color = DANHGIA_TIER_LABEL[tier]
    return {'score': score, 'comment': comment, 'tier_label': tier_label, 'color': color, 'image_url': image_url}
# ==================== HẾT ĐÁNH GIÁ ẢNH ====================

# ==================== TỰ ĐỘNG CHẤM ART TRONG FORUM ====================
ART_FORUM_CHANNEL_ID = 1528613139027988649
ART_RATED_THREADS_FILE = 'art_rated_threads.json'
_art_rated_threads = set(_firestore_load_collection('art_rated_threads', ART_RATED_THREADS_FILE).keys())

def art_thread_already_rated(thread_id):
    return int(thread_id) in _art_rated_threads

def art_thread_mark_rated(thread_id):
    _art_rated_threads.add(int(thread_id))
    _firestore_save_doc('art_rated_threads', thread_id, {'rated': True})
# ==================== HẾT TỰ ĐỘNG CHẤM ART TRONG FORUM ====================

LOTTERY_PROVINCES = ['Folk Valley', 'Ohio', 'Thành phố Delta', 'Shess Cex', 'Larp', 'Oliver Mango', 'Penaldo Pasta', 'Tỉnh Beast', 'Sinecraft Mex', 'Meow Meow']
LOTTERY_WEEKDAY_LABELS = ['Thứ hai', 'Thứ ba', 'Thứ tư', 'Thứ năm', 'Thứ sáu', 'Thứ bảy', 'Chủ nhật']
LOTTERY_WEEKDAY_PROVINCES = {
    0: ['Folk Valley', 'Ohio', 'Thành phố Delta'],
    1: ['Shess Cex', 'Larp', 'Oliver Mango'],
    2: ['Penaldo Pasta', 'Tỉnh Beast', 'Sinecraft Mex'],
    3: ['Meow Meow', 'Folk Valley', 'Ohio'],
    4: ['Thành phố Delta', 'Shess Cex', 'Larp'],
    5: ['Oliver Mango', 'Penaldo Pasta', 'Tỉnh Beast'],
    6: ['Sinecraft Mex', 'Meow Meow', 'Folk Valley'],
}
LOTTERY_TICKET_PRICE = 10
LOTTERY_CHECK_PRICE = 50
LOTTERY_STOCK_TOTAL = 150
LOTTERY_SALE_CLOSE_HOUR = 16
LOTTERY_WIN_CHANCE = 0.02
LOTTERY_PRIZES = [
    ('dac_biet', 'Giải Đặc Biệt', 50000),
    ('nhat', 'Giải Nhất', 10000),
    ('nhi', 'Giải Nhì', 5000),
    ('ba', 'Giải Ba', 1000),
    ('bon', 'Giải Bốn', 500),
    ('nam', 'Giải Năm', 20),
]
LOTTERY_BOARD_STRUCTURE = [
    ('Giải tám', 1, 2), ('Giải bảy', 1, 3), ('Giải sáu', 3, 4), ('Giải năm', 1, 4),
    ('Giải tư', 7, 5), ('Giải ba', 2, 5), ('Giải nhì', 1, 5), ('Giải nhất', 1, 5),
    ('Giải Đặc Biệt', 1, 6),
]
LOTTERY_TICKETS_FILE = 'lottery_tickets.json'
LOTTERY_STOCK_FILE = 'lottery_stock.json'
_lottery_tickets = _firestore_load_collection('lottery_tickets', LOTTERY_TICKETS_FILE)
_lottery_stock_state = _firestore_load_collection('lottery_stock', LOTTERY_STOCK_FILE)
_lottery_next_ticket_id = max(_lottery_tickets.keys(), default=0) + 1

def _vn_today_key():
    return time.strftime('%Y-%m-%d', time.gmtime(time.time() + 7 * 3600))

def _vn_now():
    return time.gmtime(time.time() + 7 * 3600)

def lottery_today_provinces():
    return LOTTERY_WEEKDAY_PROVINCES[_vn_now().tm_wday]

def lottery_today_label():
    now = _vn_now()
    weekday = LOTTERY_WEEKDAY_LABELS[now.tm_wday]
    date_str = time.strftime('%d/%m/%Y', now)
    return (weekday, date_str)

def lottery_sale_open():
    return _vn_now().tm_hour < LOTTERY_SALE_CLOSE_HOUR

def lottery_seconds_until_sale_change():
    now_vn = time.time() + 7 * 3600
    day_start_vn = now_vn - (now_vn % 86400)
    close_ts_vn = day_start_vn + LOTTERY_SALE_CLOSE_HOUR * 3600
    if now_vn < close_ts_vn:
        target = close_ts_vn
    else:
        target = day_start_vn + 86400
    return max(0, int(target - now_vn))

def _lottery_province_board(province, day_key):
    rng = random.Random(f'{province}|{day_key}')
    board = []
    for label, count, digits in LOTTERY_BOARD_STRUCTURE:
        numbers = [f'{rng.randint(0, 10 ** digits - 1):0{digits}d}' for _ in range(count)]
        board.append((label, numbers))
    return board

def _lottery_ensure_stock_cycle():
    day_key = _vn_today_key()
    state = _lottery_stock_state.get(0)
    if state is None or state.get('day_key') != day_key:
        state = {'remaining': LOTTERY_STOCK_TOTAL, 'day_key': day_key}
        _lottery_stock_state[0] = state
        _firestore_save_doc('lottery_stock', 0, state)
    return state

def lottery_stock_remaining():
    return _lottery_ensure_stock_cycle()['remaining']

def lottery_seconds_until_restock():
    return lottery_seconds_until_sale_change()

def lottery_buy(user_id):
    global _lottery_next_ticket_id
    if not lottery_sale_open():
        return {'ok': False, 'reason': f'❌ Đại lý vé số đã đóng cửa lúc {LOTTERY_SALE_CLOSE_HOUR}h chiều rồi! Quay lại vào **0h ngày mai** nhé. (còn **{lottery_seconds_until_sale_change() // 3600}h{(lottery_seconds_until_sale_change() % 3600) // 60}p**)'}
    state = _lottery_ensure_stock_cycle()
    if state['remaining'] <= 0:
        return {'ok': False, 'reason': '❌ Hết vé số hôm nay rồi! Mai quay lại nhé.'}
    balance = get_aura(user_id)
    if balance < LOTTERY_TICKET_PRICE:
        return {'ok': False, 'reason': f'❌ Không đủ Aura! Cần **{LOTTERY_TICKET_PRICE}**, bạn có **{balance}**.'}
    add_aura(user_id, -LOTTERY_TICKET_PRICE)
    _apply_purchase_tax(LOTTERY_TICKET_PRICE)
    state['remaining'] -= 1
    _firestore_save_doc('lottery_stock', 0, state)
    province = random.choice(lottery_today_provinces())
    number = f'{random.randint(0, 999999):06d}'
    ticket_id = _lottery_next_ticket_id
    _lottery_next_ticket_id += 1
    ticket = {'id': ticket_id, 'owner_id': user_id, 'province': province, 'number': number, 'day_key': _vn_today_key(), 'bought_at': time.time(), 'checked': False, 'prize_label': None, 'prize_amount': 0}
    _lottery_tickets[ticket_id] = ticket
    _firestore_save_doc('lottery_tickets', ticket_id, ticket)
    return {'ok': True, 'ticket': ticket, 'remaining': state['remaining']}

def lottery_user_tickets(user_id, unchecked_only=False):
    tickets = [t for t in _lottery_tickets.values() if t['owner_id'] == user_id]
    if unchecked_only:
        tickets = [t for t in tickets if not t['checked']]
    tickets.sort(key=lambda t: t['bought_at'])
    return tickets

def lottery_get_ticket(ticket_id):
    return _lottery_tickets.get(ticket_id)

def lottery_result_announced(ticket):
    if ticket['day_key'] != _vn_today_key():
        return True
    return not lottery_sale_open()

def lottery_board_table(province, day_key):
    board = _lottery_province_board(province, day_key)
    label_width = max((len(label) for label, _ in board))
    rows = [f'{label.ljust(label_width)} : {"  ".join(numbers)}' for label, numbers in board]
    return '```\n' + '\n'.join(rows) + '\n```'

def lottery_check_ticket(ticket_id):
    ticket = _lottery_tickets.get(ticket_id)
    if ticket is None:
        return None
    if ticket['checked']:
        return ticket
    if not lottery_result_announced(ticket):
        return None
    rng = random.Random(f"draw|{ticket['id']}|{ticket['province']}|{ticket['day_key']}|{ticket['number']}")
    won = rng.random() < LOTTERY_WIN_CHANCE
    if won:
        prize_key, label, amount = rng.choice(LOTTERY_PRIZES)
    else:
        label, amount = (None, 0)
    ticket['checked'] = True
    ticket['prize_label'] = label
    ticket['prize_amount'] = amount
    if amount > 0:
        add_aura(ticket['owner_id'], amount)
    _firestore_save_doc('lottery_tickets', ticket_id, ticket)
    return ticket

def lottery_check_all(user_id):
    tickets = lottery_user_tickets(user_id, unchecked_only=True)
    results = [lottery_check_ticket(t['id']) for t in tickets]
    return [r for r in results if r is not None]

def lottery_check_by_id(user_id, ticket_id):
    ticket = _lottery_tickets.get(ticket_id)
    if ticket is None:
        return {'ok': False, 'reason': f'❌ Không tìm thấy vé số **#{ticket_id}**.'}
    if ticket['owner_id'] != user_id:
        return {'ok': False, 'reason': '❌ Đây không phải vé số của bạn!'}
    if ticket['checked']:
        return {'ok': False, 'reason': f"⚠️ Vé **#{ticket_id}** đã được dò rồi (kết quả: {ticket['prize_label'] or 'không trúng'})."}
    if not lottery_result_announced(ticket):
        remain = lottery_seconds_until_sale_change()
        return {'ok': False, 'reason': f'⏳ Vé **#{ticket_id}** chưa có kết quả — KQXS công bố lúc {LOTTERY_SALE_CLOSE_HOUR}h chiều nay (còn **{remain // 3600}h{(remain % 3600) // 60}p**).'}
    balance = get_aura(user_id)
    if balance < LOTTERY_CHECK_PRICE:
        return {'ok': False, 'reason': f'❌ Không đủ Aura để kiểm tra! Cần **{LOTTERY_CHECK_PRICE}**, bạn có **{balance}**.'}
    add_aura(user_id, -LOTTERY_CHECK_PRICE)
    ticket = lottery_check_ticket(ticket_id)
    return {'ok': True, 'ticket': ticket}

WHATUINTO_LABELS = [('Femboy', 'Mềm mại bên ngoài, hỗn loạn bên trong. Bạn là hiện thân của "tưởng vậy mà không phải vậy".'), ('Tomboy', 'Năng lượng xắn tay áo, không ngại dơ. Bạn chọn hành động thay vì drama.'), ('Tsundere', '"Không phải tôi thích đâu nhé!" — trong khi tay đã làm sẵn hết rồi.'), ('Mommy ASMR', 'Giọng nói của bạn có thể ru cả server ngủ. Năng lượng chăm sóc tối thượng.'), ('Yandere ASMR', 'Ngọt ngào đến đáng ngờ. Ai chọc bạn giận thì... thôi khỏi nói.'), ('Vợ hàng xóm', 'Huyền thoại khu phố, ai cũng biết tên nhưng chẳng ai dám hỏi thẳng.'), ('Folk Valley', 'Bạn thuộc về nơi cỏ cây biết nói và gà biết deploy code.'), ('Scambodia', 'Chuyên gia lừa đảo... tình cảm. Cẩn thận, coi chừng mất ví lẫn mất tim.')]

def whatuinto_roll():
    label, caption = random.choice(WHATUINTO_LABELS)
    percent = random.randint(60, 99)
    return (label, caption, percent)
_chess_games = {}
_PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
CHESS_STALE_SECONDS = 30 * 60
CHESS_TIME_MODES = {'bullet': {'label': '⚡ Cờ đạn (Bullet)', 'base': 2 * 60, 'increment': 1}, 'blitz': {'label': '🔥 Cờ chớp (Blitz)', 'base': 5 * 60, 'increment': 2}, 'rapid': {'label': '🚀 Cờ nhanh (Rapid)', 'base': 15 * 60, 'increment': 5}, 'classical': {'label': '🏛️ Cờ tiêu chuẩn (Classical)', 'base': 60 * 60, 'increment': 10}}
CHESS_DEFAULT_TIME_MODE = 'rapid'

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

def chess_start(cid, player_id, bot_elo=1200):
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
BOT_LEVELS = {800: {'label': '🟢 Dễ', 'random_chance': 0.5}, 1200: {'label': '🟡 Vừa', 'random_chance': 0.15}, 1600: {'label': '🔴 Khó', 'random_chance': 0.0}}
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
    'elo_100': {'emoji': '🥶', 'name': 'Mua Tài (100 Elo)', 'currency': 'aura', 'price': 50, 'stock': 8, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '📈 +100 Elo ngay lập tức, không cần thắng, không cần chơi, không cần liêm sỉ.\n🐐 Messi mà thấy giá này chắc cũng phải khóc vì rẻ.'},
    'elo10': {'emoji': '💠', 'name': '10 Elo', 'currency': 'aura', 'price': 5, 'stock': 20, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '📈 +10 Elo bé xíu, dành cho người mua tài mà vẫn muốn giữ chút liêm sỉ.\n🐜 Chưa đủ để flex nhưng đủ để tự lừa bản thân là đang tiến bộ.'},
    'hint_free': {'emoji': '💡', 'name': 'Gợi Ý Miễn Phí', 'currency': 'aura', 'price': 120, 'stock': 5, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '🎯 Dùng 1 lần — hỏi bài mà không bị trừ điểm, sung sướng như quay cóp trót lọt.\n🧠 Não bạn nghỉ hưu sớm, bot lo hết.'},
    'flag_slot': {'emoji': '🎟️', 'name': 'Slot Vé Game', 'currency': 'aura', 'price': 80, 'stock': 6, 'rarity': 'common', 'appear_chance': 1.0, 'desc': '📈 +1 lượt chơi hôm nay cho /wordle, /flag VÀ cờ vua vs Bot (vượt giới hạn 5 vé/ngày mỗi loại).\n🌾 Nghiện game thì Folk Valley không cản, chỉ cần trả tiền vé.'},
    'aura_500': {'emoji': '💰', 'name': 'Túi Aura (500)', 'currency': 'elo', 'price': 250, 'stock': 5, 'rarity': 'uncommon', 'appear_chance': 0.75, 'desc': '💸 Bán 250 Elo lấy 500 Aura — vay nóng lãi cắt cổ nhưng tự nguyện.\n🏦 Tín dụng đen phiên bản cờ vua, không ai ép bạn cả.'},
    'shield_timeout': {'emoji': '🛡️', 'name': 'Khiên Hết Giờ', 'currency': 'aura', 'price': 350, 'stock': 3, 'rarity': 'uncommon', 'appear_chance': 0.75, 'desc': '🎯 Dùng 1 lần — cộng free 60 giây để nghĩ nước đi cho thiên tài chậm tiêu.\n🐢 Rùa cũng có ngày về đích, miễn là mua đủ khiên.'},
    'trong_tai': {'emoji': '⚖️', 'name': 'Trọng Tài Chess (PvP)', 'currency': 'aura', 'price': 450, 'stock': 3, 'rarity': 'uncommon', 'appear_chance': 0.6, 'desc': '🎯 Dùng 1 lần — mua đứt ông trọng tài trận PvP tiếp theo.\n🛡️ Thổi còi thiên vị bạn công khai giữa thanh thiên bạch nhật.\n🤫 "Đây là quyết định cuối cùng, không khiếu nại" — trọng tài, vừa nhận phong bì.'},
    'double_aura': {'emoji': '✨', 'name': 'Nhân Đôi Aura (24 giờ)', 'currency': 'elo', 'price': 300, 'stock': 4, 'rarity': 'rare', 'appear_chance': 0.4, 'desc': '⏳ x2 Aura trong 24 giờ — bán Elo lấy Aura như bán nhà lấy vàng mã.\n🤑 Tư bản đích thực, không màng liêm sỉ chỉ màng lợi nhuận.'},
    'cu_cai': {'emoji': '🥕', 'name': 'Củ Cải', 'currency': 'aura', 'price': 500, 'stock': 2, 'rarity': 'rare', 'appear_chance': 0.35, 'desc': '🎯 Dùng 1 lần — nhét củ cải vào não Chess Bot:\n🤯 IQ bot rớt về âm, đi cờ như đang say rượu ngoài quán nhậu.\n♟️ Thua ván này thì thôi khỏi chơi cờ luôn đi bạn ơi. 💀🥶'},
    'mango_mustard': {'emoji': '🥭', 'name': 'Mango Mustard', 'currency': 'aura', 'price': 666, 'stock': 1, 'rarity': 'legendary', 'appear_chance': 0.15, 'desc': '🎯 Dùng 1 lần — sốt mù tạt xoài huyền thoại, không ai hiểu công thức nhưng ai cũng sợ.\n💥 Ăn vào +50 Aura NGAY LẬP TỨC vì can đảm thử món này xứng đáng được thưởng.\n🤢 Tác dụng phụ: ám ảnh vị giác vĩnh viễn.'},
    'ronaldo_pasta': {'emoji': '🍝', 'name': 'Ronaldo Pasta', 'currency': 'elo', 'price': 500, 'stock': 1, 'rarity': 'legendary', 'appear_chance': 0.15, 'desc': '🎯 Dùng 1 lần — đĩa mì Ý SIUUUU chính hiệu, ăn vào tự tin thái quá.\n📈 +150 Elo NGAY LẬP TỨC vì tự tin cũng là một loại sức mạnh.\n⚠️ Cảnh báo: có thể khiến bạn ăn mừng quá lố sau mỗi nước đi.'},
    'role_gubby': {'emoji': '🐹', 'name': 'Role Gubby', 'currency': 'aura', 'price': 3100, 'stock': 1, 'rarity': 'legendary', 'appear_chance': 0.2, 'desc': '🎖️ Vĩnh viễn thành Gubby chính hiệu, không hoàn không đổi trả.\n🐹 Một khi đã Gubby thì Gubby cả đời, hối hận cũng muộn rồi.'},
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
    return _user_buffs.setdefault(user_id, {'cu_cai': 0, 'trong_tai': 0, 'double_aura_until': 0, 'gubby_role': False, 'hint_free': 0, 'shield_timeout': 0})

def _has_double_aura_buff(user_id):
    buffs = _user_buffs.get(user_id)
    return bool(buffs) and time.time() < buffs.get('double_aura_until', 0)

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
    current = get_aura(user_id) if currency == 'aura' else get_elo(user_id)
    currency_label = 'Aura' if currency == 'aura' else 'Elo'
    if current < price:
        return {'ok': False, 'reason': f'❌ Không đủ {currency_label}! Cần **{price}**, bạn chỉ có **{current}**.', 'item': item, 'balance_after': current}
    if currency == 'aura':
        balance_after = add_aura(user_id, -price)
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
    elif item_key == 'double_aura':
        base = max(time.time(), buffs['double_aura_until'])
        buffs['double_aura_until'] = base + 24 * 3600
    elif item_key == 'role_gubby':
        buffs['gubby_role'] = True
    elif item_key == 'trong_tai':
        buffs['trong_tai'] += 1
    elif item_key == 'hint_free':
        buffs['hint_free'] += 1
    elif item_key == 'aura_500':
        add_aura(user_id, 500)
    elif item_key == 'shield_timeout':
        buffs['shield_timeout'] += 1
    elif item_key == 'flag_slot':
        daily_add_slot('flag', user_id)
        daily_add_slot('chess_bot', user_id)
        daily_add_slot('wordle', user_id)
    elif item_key == 'mango_mustard':
        add_aura(user_id, 50)
    elif item_key == 'ronaldo_pasta':
        _set_elo(user_id, get_elo(user_id) + 150)
    _shop_stock[item_key] -= 1
    receipt = _add_receipt(user_id, item_key, item, currency, price, balance_after)
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
    if buffs['cu_cai'] > 0:
        lines.append(f"🥕 Củ Cải: còn **{buffs['cu_cai']}**")
    if buffs['trong_tai'] > 0:
        lines.append(f"⚖️ Trọng Tài: còn **{buffs['trong_tai']}**")
    if buffs['hint_free'] > 0:
        lines.append(f"💡 Gợi Ý Miễn Phí: còn **{buffs['hint_free']}**")
    if buffs['shield_timeout'] > 0:
        lines.append(f"🛡️ Khiên Hết Giờ: còn **{buffs['shield_timeout']}**")
    if _has_double_aura_buff(user_id):
        remain = buffs['double_aura_until'] - time.time()
        h, rem = divmod(int(remain), 3600)
        m = rem // 60
        lines.append(f'✨ Nhân Đôi Aura: còn **{h}h{m:02d}m**')
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

def chess_board_image(cid):
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
    buf = io.BytesIO()
    img.convert('RGB').save(buf, format='PNG')
    buf.seek(0)
    return buf

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
    game = _chess_games[cid]
    if game['is_pvp']:
        white_id, black_id = (game['white_id'], game['black_id'])
        white_elo, black_elo = (get_elo(white_id), get_elo(black_id))
        if outcome.winner is None:
            score_white = 0.5
        elif outcome.winner == chess.WHITE:
            score_white = 1
        else:
            score_white = 0
        new_white, new_black, d_white, d_black = update_elo(white_id, white_elo, black_id, black_elo, score_white)
        white_name = display_names[True] if display_names else f'<@{white_id}>'
        black_name = display_names[False] if display_names else f'<@{black_id}>'
        sign_w = f'+{d_white}' if d_white >= 0 else str(d_white)
        sign_b = f'+{d_black}' if d_black >= 0 else str(d_black)
        if outcome.winner is None:
            result_line = '🤝 Hòa!'
            add_aura(white_id, -150)
            add_aura(black_id, -150)
            aura_line = f'\n\n{AURA_ICON} Hòa cờ: cả hai bị trừ **150 Aura**.'
        else:
            winner_id = white_id if outcome.winner == chess.WHITE else black_id
            winner_name = white_name if outcome.winner == chess.WHITE else black_name
            result_line = f'🎉 {winner_name} thắng! Chiếu bí!'
            new_winner_aura = add_aura(winner_id, 100)
            aura_line = f'\n\n{AURA_ICON} {winner_name} nhận **+100 Aura** (số dư: {new_winner_aura}).'
        return f'{result_line}\n\n⚪ {white_name}: {new_white} Elo ({sign_w})\n⚫ {black_name}: {new_black} Elo ({sign_b}){aura_line}'
    player_id = game['player_id']
    player_elo = get_elo(player_id)
    player_color = game['player_color']
    if outcome.winner is None:
        score_player = 0.5
    else:
        score_player = 1 if outcome.winner == player_color else 0
    new_player_elo, _, d_player, _ = update_elo(player_id, player_elo, None, game['bot_elo'], score_player)
    sign = f'+{d_player}' if d_player >= 0 else str(d_player)
    if outcome.winner is None:
        result_line = '🤝 Hòa!'
    elif score_player == 1:
        result_line = '🎉 Bạn thắng! Bot chịu thua.'
    else:
        result_line = '🤖 Bot chiếu bí! Bạn thua rồi.'
    return f'{result_line}\n\nElo của bạn: {new_player_elo} ({sign})'

def chess_resign_text(cid, resigner_id, display_names=None):
    game = _chess_games[cid]
    if game['is_pvp']:
        white_id, black_id = (game['white_id'], game['black_id'])
        white_elo, black_elo = (get_elo(white_id), get_elo(black_id))
        score_white = 0 if resigner_id == white_id else 1
        new_white, new_black, d_white, d_black = update_elo(white_id, white_elo, black_id, black_elo, score_white)
        white_name = display_names[True] if display_names else f'<@{white_id}>'
        black_name = display_names[False] if display_names else f'<@{black_id}>'
        resigner_name = white_name if resigner_id == white_id else black_name
        winner_name = black_name if resigner_id == white_id else white_name
        winner_id = black_id if resigner_id == white_id else white_id
        new_winner_aura = add_aura(winner_id, 100)
        sign_w = f'+{d_white}' if d_white >= 0 else str(d_white)
        sign_b = f'+{d_black}' if d_black >= 0 else str(d_black)
        return f'🏳️ {resigner_name} đã đầu hàng! {winner_name} thắng!\n\n⚪ {white_name}: {new_white} Elo ({sign_w})\n⚫ {black_name}: {new_black} Elo ({sign_b})\n\n{AURA_ICON} {winner_name} nhận **+100 Aura** (số dư: {new_winner_aura}).'
    player_id = game['player_id']
    player_elo = get_elo(player_id)
    new_player_elo, _, d_player, _ = update_elo(player_id, player_elo, None, game['bot_elo'], 0)
    sign = f'+{d_player}' if d_player >= 0 else str(d_player)
    return f'🏳️ Bạn đã đầu hàng! Bot thắng.\n\nElo của bạn: {new_player_elo} ({sign})'

def chess_timeout_text(cid, timed_out_color, display_names=None):
    game = _chess_games[cid]
    white_id, black_id = (game['white_id'], game['black_id'])
    white_elo, black_elo = (get_elo(white_id), get_elo(black_id))
    score_white = 0 if timed_out_color == chess.WHITE else 1
    new_white, new_black, d_white, d_black = update_elo(white_id, white_elo, black_id, black_elo, score_white)
    white_name = display_names[True] if display_names else f'<@{white_id}>'
    black_name = display_names[False] if display_names else f'<@{black_id}>'
    loser_name = white_name if timed_out_color == chess.WHITE else black_name
    winner_name = black_name if timed_out_color == chess.WHITE else white_name
    winner_id = black_id if timed_out_color == chess.WHITE else white_id
    new_winner_aura = add_aura(winner_id, 100)
    sign_w = f'+{d_white}' if d_white >= 0 else str(d_white)
    sign_b = f'+{d_black}' if d_black >= 0 else str(d_black)
    return f'⏰ {loser_name} đã hết giờ! {winner_name} thắng!\n\n⚪ {white_name}: {new_white} Elo ({sign_w})\n⚫ {black_name}: {new_black} Elo ({sign_b})\n\n{AURA_ICON} {winner_name} nhận **+100 Aura** (số dư: {new_winner_aura}).'

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
    return f'⚪ **{player_name}** — {get_elo(player_id)} Elo\n⚫ **Bot ({bot_label})** — {bot_elo} Elo'
_chess_draw_offers = {}

def chess_offer_draw(cid, offerer_id):
    _chess_draw_offers[cid] = offerer_id

def chess_get_draw_offer(cid):
    return _chess_draw_offers.get(cid)

def chess_clear_draw_offer(cid):
    _chess_draw_offers.pop(cid, None)

def chess_accept_draw_text(cid, display_names=None):
    game = _chess_games[cid]
    white_id, black_id = (game['white_id'], game['black_id'])
    white_name = display_names[True] if display_names else f'<@{white_id}>'
    black_name = display_names[False] if display_names else f'<@{black_id}>'
    return f'🤝 {white_name} và {black_name} đã đồng ý hòa. Ván cờ kết thúc, Elo giữ nguyên.'
_chess_draw_offers = {}

def chess_offer_draw(cid, offerer_id):
    _chess_draw_offers[cid] = offerer_id

def chess_get_draw_offer(cid):
    return _chess_draw_offers.get(cid)

def chess_clear_draw_offer(cid):
    _chess_draw_offers.pop(cid, None)

def chess_accept_draw_text(cid, display_names=None):
    game = _chess_games[cid]
    white_id, black_id = (game['white_id'], game['black_id'])
    white_name = display_names[True] if display_names else f'<@{white_id}>'
    black_name = display_names[False] if display_names else f'<@{black_id}>'
    return f'🤝 {white_name} và {black_name} đã đồng ý kết thúc ván. Elo giữ nguyên, không tính thắng thua.'

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
REDEEM_CODES = {
    'ChaoNgayMoiVuiVe': {'aura': 50, 'aura_plus': 0.9},
    'DeltaMickLaConCho': {'aura': 190, 'aura_plus': 5},
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
    if 'aura' in entry:
        add_aura(user_id, entry['aura'])
        reward_lines.append(f"{AURA_ICON} +{entry['aura']} Aura")
    if 'aura_plus' in entry:
        add_aura_plus(user_id, entry['aura_plus'])
        reward_lines.append(f"+{entry['aura_plus']} Aura+")
    used['codes'].append(code)
    _firestore_save_doc('redeem_codes', user_id, used)
    return {'ok': True, 'reward_lines': reward_lines}

def top_aura(n=10):
    items = [(uid, bal) for uid, bal in _aura_cache.items() if uid != BOT_OWNER_ID and bal > 0]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:n]

def top_elo(n=10):
    items = [(uid, elo) for uid, elo in _elo_cache.items() if uid != BOT_OWNER_ID]
    items.sort(key=lambda x: x[1], reverse=True)
    return items[:n]

# ==================== MINESWEEPER (DÒ MÌN) ====================
MINESWEEPER_MIN_SIZE = 5
MINESWEEPER_MAX_SIZE = 12
MINESWEEPER_DEFAULT_SIZE = 8
MINESWEEPER_MINE_RATIO = 0.15625
MINESWEEPER_AURA_REWARD = 2000
MINESWEEPER_AURA_PLUS_REWARD = 10
MINESWEEPER_BASE_MINE_COUNT = max(3, round(MINESWEEPER_DEFAULT_SIZE * MINESWEEPER_DEFAULT_SIZE * MINESWEEPER_MINE_RATIO))
MINESWEEPER_FAST_MULT = 1.3
MINESWEEPER_QUICK_MULT = 1.1
_minesweeper_games = {}
_minesweeper_game_seq = 0
MINESWEEPER_STATS_FILE = 'minesweeper_stats.json'
_minesweeper_stats_cache = {int(uid): d for uid, d in _firestore_load_collection('minesweeper_stats', MINESWEEPER_STATS_FILE).items()}

def minesweeper_mine_count(size):
    return max(3, round(size * size * MINESWEEPER_MINE_RATIO))

def minesweeper_active(cid):
    return cid in _minesweeper_games

def minesweeper_games_left_today(user_id):
    return daily_games_left_today('minesweeper', user_id)

def minesweeper_parse_size(text, default=MINESWEEPER_DEFAULT_SIZE):
    if not text:
        return (default, True)
    text = text.strip().lower().replace(' ', '')
    if 'x' in text:
        parts = text.split('x')
    elif '*' in text:
        parts = text.split('*')
    else:
        parts = [text, text]
    if len(parts) != 2:
        return (None, False)
    try:
        w, h = (int(parts[0]), int(parts[1]))
    except ValueError:
        return (None, False)
    if w != h:
        return (None, False)
    if not MINESWEEPER_MIN_SIZE <= w <= MINESWEEPER_MAX_SIZE:
        return (None, False)
    return (w, True)

def minesweeper_start(cid, owner_id, size=MINESWEEPER_DEFAULT_SIZE, seed=None):
    global _minesweeper_game_seq
    if daily_games_left_today('minesweeper', owner_id) <= 0:
        return (None, False, None)
    _consume_daily_slot('minesweeper', owner_id)
    if seed is None:
        seed = random.randint(10 ** 11, 10 ** 12 - 1)
    mine_count = minesweeper_mine_count(size)
    board = [[0] * size for _ in range(size)]
    _minesweeper_game_seq += 1
    game_id = _minesweeper_game_seq
    # Mìn chưa được đặt ngay — sẽ sinh ra khi mở ô đầu tiên, đảm bảo luôn an toàn (chuẩn Minesweeper cổ điển).
    _minesweeper_games[cid] = {'game_id': game_id, 'owner_id': owner_id, 'board': board, 'mines': set(), 'mine_count': mine_count, 'revealed': set(), 'flags': set(), 'size': size, 'over': False, 'won': False, 'seed': seed, 'created_at': time.time(), 'start_time': None, 'elapsed': None, 'first_click_done': False}
    return (game_id, True, seed)

def minesweeper_parse_seed(text):
    if not text:
        return (None, True)
    text = text.strip()
    if not text.isdigit():
        return (None, False)
    val = int(text)
    if not 0 <= val <= 10 ** 15:
        return (None, False)
    return (val, True)

def minesweeper_end(cid, game_id=None):
    if game_id is not None:
        current = _minesweeper_games.get(cid)
        if current is None or current.get('game_id') != game_id:
            return
    _minesweeper_games.pop(cid, None)

def minesweeper_force_reset(cid):
    return _minesweeper_games.pop(cid, None) is not None

def minesweeper_game(cid):
    return _minesweeper_games.get(cid)

def _minesweeper_generate_board(game, safe_r, safe_c):
    """Sinh bãi mìn ngay khi người chơi mở ô đầu tiên, loại trừ ô đó và 8 ô lân cận để không bao giờ thua ngay phát đầu."""
    size = game['size']
    rng = random.Random(game['seed'])
    safe_zone = {(safe_r + dr, safe_c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1)}
    candidates = [(r, c) for r in range(size) for c in range(size) if (r, c) not in safe_zone]
    mine_count = min(game['mine_count'], len(candidates))
    mines = set(rng.sample(candidates, mine_count))
    board = [[0] * size for _ in range(size)]
    for r, c in mines:
        board[r][c] = -1
    for r in range(size):
        for c in range(size):
            if board[r][c] == -1:
                continue
            count = sum(((r + dr, c + dc) in mines for dr in (-1, 0, 1) for dc in (-1, 0, 1) if not (dr == 0 and dc == 0)))
            board[r][c] = count
    game['board'] = board
    game['mines'] = mines
    game['mine_count'] = mine_count
    game['first_click_done'] = True
    game['start_time'] = time.time()

def _minesweeper_flood_reveal(game, r, c):
    size = game['size']
    stack = [(r, c)]
    while stack:
        cr, cc = stack.pop()
        if (cr, cc) in game['revealed'] or not (0 <= cr < size and 0 <= cc < size):
            continue
        if (cr, cc) in game['flags']:
            continue
        game['revealed'].add((cr, cc))
        if game['board'][cr][cc] == 0:
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = (cr + dr, cc + dc)
                    if (nr, nc) not in game['revealed'] and 0 <= nr < size and (0 <= nc < size):
                        stack.append((nr, nc))

def _minesweeper_finish_check(game):
    size = game['size']
    total_safe = size * size - len(game['mines'])
    if len(game['revealed']) >= total_safe:
        game['over'] = True
        game['won'] = True
        game['elapsed'] = round(time.time() - game['start_time'], 1) if game['start_time'] else None
        return True
    return False

def minesweeper_reveal(cid, game_id, r, c):
    game = _minesweeper_games.get(cid)
    if game is None or game.get('game_id') != game_id:
        return 'gone'
    size = game['size']
    if not (0 <= r < size and 0 <= c < size):
        return 'invalid'
    if (r, c) in game['flags']:
        return 'noop'
    if (r, c) in game['revealed']:
        # Ô đã mở rồi → thử "chord": nếu số cờ quanh ô khớp với số ghi trên ô, tự mở hết các ô lân cận còn lại.
        val = game['board'][r][c]
        if val <= 0:
            return 'noop'
        neighbors = [(r + dr, c + dc) for dr in (-1, 0, 1) for dc in (-1, 0, 1) if not (dr == 0 and dc == 0)]
        neighbors = [(nr, nc) for nr, nc in neighbors if 0 <= nr < size and 0 <= nc < size]
        flagged = sum((1 for n in neighbors if n in game['flags']))
        if flagged != val:
            return 'noop'
        hit_mine = False
        for nr, nc in neighbors:
            if (nr, nc) in game['flags'] or (nr, nc) in game['revealed']:
                continue
            if (nr, nc) in game['mines']:
                game['revealed'].add((nr, nc))
                hit_mine = True
            else:
                _minesweeper_flood_reveal(game, nr, nc)
        if hit_mine:
            game['over'] = True
            return 'boom'
        return 'win' if _minesweeper_finish_check(game) else 'ok'
    if not game['first_click_done']:
        _minesweeper_generate_board(game, r, c)
    if game['board'][r][c] == -1:
        game['revealed'].add((r, c))
        game['over'] = True
        return 'boom'
    _minesweeper_flood_reveal(game, r, c)
    return 'win' if _minesweeper_finish_check(game) else 'ok'

def minesweeper_toggle_flag(cid, game_id, r, c):
    game = _minesweeper_games.get(cid)
    if game is None or game.get('game_id') != game_id:
        return 'gone'
    size = game['size']
    if not (0 <= r < size and 0 <= c < size):
        return 'invalid'
    if (r, c) in game['revealed']:
        return 'noop'
    if (r, c) in game['flags']:
        game['flags'].discard((r, c))
    else:
        game['flags'].add((r, c))
    return 'ok'

def minesweeper_reward(game):
    """Thưởng tăng theo độ khó (số mìn) so với bàn mặc định 8x8, cộng thêm bonus tốc độ nếu thắng nhanh."""
    scale = game['mine_count'] / MINESWEEPER_BASE_MINE_COUNT
    elapsed = game.get('elapsed')
    mult = 1.0
    if elapsed is not None:
        allowance = game['size'] * game['size'] * 1.5
        if elapsed <= allowance * 0.5:
            mult = MINESWEEPER_FAST_MULT
        elif elapsed <= allowance:
            mult = MINESWEEPER_QUICK_MULT
    aura = max(1, round(MINESWEEPER_AURA_REWARD * scale * mult))
    aura_plus = round(MINESWEEPER_AURA_PLUS_REWARD * scale * mult, 2)
    return (aura, aura_plus, elapsed, mult)

def _minesweeper_stats_get(user_id):
    return _minesweeper_stats_cache.setdefault(user_id, {'wins': 0, 'total_aura': 0, 'best_time': None, 'best_time_size': None})

def _minesweeper_record_win(user_id, game, aura, elapsed):
    stats = _minesweeper_stats_get(user_id)
    stats['wins'] = stats.get('wins', 0) + 1
    stats['total_aura'] = stats.get('total_aura', 0) + aura
    if elapsed is not None and (stats.get('best_time') is None or elapsed < stats['best_time']):
        stats['best_time'] = elapsed
        stats['best_time_size'] = game['size']
    _firestore_save_doc('minesweeper_stats', user_id, stats)

def award_minesweeper_win(user_id, game):
    aura, aura_plus, elapsed, mult = minesweeper_reward(game)
    new_aura = add_aura(user_id, aura)
    new_aura_plus = add_aura_plus(user_id, aura_plus)
    _minesweeper_record_win(user_id, game, aura, elapsed)
    return (new_aura, new_aura_plus, aura, aura_plus, elapsed, mult)

def top_minesweeper(n=10):
    items = [(uid, d.get('wins', 0), d.get('total_aura', 0)) for uid, d in _minesweeper_stats_cache.items() if d.get('wins', 0) > 0]
    items.sort(key=lambda x: (x[1], x[2]), reverse=True)
    return items[:n]

_MS_CELL_PX = 48
_MS_BORDER_PX = 22
_MS_HEADER_PX = 100
_MS_BG = (108, 117, 125)
_MS_BG_DARK = (74, 81, 87)
_MS_BG_LIGHT = (138, 146, 153)
_MS_PANEL = (68, 74, 80)
_MS_NUM_COLORS = {1: (34, 90, 214), 2: (43, 140, 66), 3: (214, 45, 32), 4: (28, 42, 130), 5: (135, 30, 20), 6: (26, 130, 140), 7: (20, 20, 20), 8: (110, 110, 110)}

def _ms_bevel_rect(draw, x0, y0, x1, y1, raised=True):
    light = _MS_BG_LIGHT if raised else _MS_BG_DARK
    dark = _MS_BG_DARK if raised else _MS_BG_LIGHT
    draw.rectangle([x0, y0, x1, y1], fill=_MS_BG)
    t = 3
    draw.polygon([(x0, y0), (x1, y0), (x1 - t, y0 + t), (x0 + t, y0 + t), (x0 + t, y1 - t), (x0, y1)], fill=light)
    draw.polygon([(x1, y0), (x1, y1), (x0, y1), (x0 + t, y1 - t), (x1 - t, y1 - t), (x1 - t, y0 + t)], fill=dark)

def _ms_digit_segments(digit):
    segs = {'0': 'abcdef', '1': 'bc', '2': 'abged', '3': 'abgcd', '4': 'fgbc', '5': 'afgcd', '6': 'afgedc', '7': 'abc', '8': 'abcdefg', '9': 'abcfgd', '-': 'g', ' ': ''}
    return segs.get(digit, '')

def _ms_draw_7seg(draw, x, y, digit, w=22, h=38):
    on_color = (255, 40, 40)
    off_color = (35, 8, 8)
    seg_on = set(_ms_digit_segments(digit))
    t = 4
    coords = {'a': (x + t, y, x + w - t, y + t), 'g': (x + t, y + h // 2 - t // 2, x + w - t, y + h // 2 + t // 2), 'd': (x + t, y + h - t, x + w - t, y + h), 'f': (x, y + t, x + t, y + h // 2), 'b': (x + w - t, y + t, x + w, y + h // 2), 'e': (x, y + h // 2, x + t, y + h - t), 'c': (x + w - t, y + h // 2, x + w, y + h - t)}
    for seg, box in coords.items():
        draw.rectangle(box, fill=on_color if seg in seg_on else off_color)

def _ms_draw_counter(draw, x, y, value):
    value = max(-99, min(999, value))
    text = f'{value:03d}' if value >= 0 else f'-{abs(value):02d}'
    text = text[-3:].rjust(3, '0') if value >= 0 else text
    draw.rectangle([x - 3, y - 3, x + 77, y + 49], fill=(20, 20, 22))
    draw.rectangle([x, y, x + 74, y + 46], fill=(12, 12, 14))
    for i, ch in enumerate(text):
        _ms_draw_7seg(draw, x + 6 + i * 24, y + 4, ch)

def _ms_draw_face(draw, cx, cy, r, state):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(247, 213, 90), outline=(40, 30, 10), width=2)
    if state == 'dead':
        eye_color = (30, 30, 30)
        for ex in (cx - r * 0.35, cx + r * 0.35):
            draw.line([(ex - 5, cy - 6), (ex + 5, cy + 4)], fill=eye_color, width=3)
            draw.line([(ex - 5, cy + 4), (ex + 5, cy - 6)], fill=eye_color, width=3)
        draw.arc([cx - r * 0.5, cy + r * 0.05, cx + r * 0.5, cy + r * 0.55], 200, 340, fill=eye_color, width=3)
    elif state == 'win':
        draw.ellipse([cx - r * 0.4, cy - r * 0.15, cx - r * 0.15, cy + r * 0.1], fill=(30, 30, 30))
        draw.ellipse([cx + r * 0.15, cy - r * 0.15, cx + r * 0.4, cy + r * 0.1], fill=(30, 30, 30))
        draw.arc([cx - r * 0.45, cy - r * 0.1, cx + r * 0.45, cy + r * 0.5], 20, 160, fill=(30, 30, 30), width=3)
    else:
        draw.ellipse([cx - r * 0.4, cy - r * 0.15, cx - r * 0.15, cy + r * 0.1], fill=(30, 30, 30))
        draw.ellipse([cx + r * 0.15, cy - r * 0.15, cx + r * 0.4, cy + r * 0.1], fill=(30, 30, 30))
        draw.arc([cx - r * 0.35, cy + r * 0.05, cx + r * 0.35, cy + r * 0.4], 0, 180, fill=(30, 30, 30), width=3)

def minesweeper_col_label(c):
    label = ''
    c += 1
    while c > 0:
        c, rem = divmod(c - 1, 26)
        label = chr(65 + rem) + label
    return label

def minesweeper_render_image(cid):
    game = _minesweeper_games[cid]
    size = game['size']
    cell = _MS_CELL_PX
    board_px = cell * size
    coord_margin = 26
    width = board_px + _MS_BORDER_PX * 2 + coord_margin
    height = board_px + _MS_BORDER_PX * 2 + _MS_HEADER_PX + coord_margin
    img = Image.new('RGB', (width, height), _MS_PANEL)
    draw = ImageDraw.Draw(img)
    font = _chess_font(15)
    font_small = _chess_font(13)
    flags_used = len(game['flags'])
    remaining = game['mine_count'] - flags_used
    _ms_draw_counter(draw, _MS_BORDER_PX, 18, remaining)
    if game['over'] and (not game['won']):
        face_state = 'dead'
    elif game['won']:
        face_state = 'win'
    else:
        face_state = 'normal'
    _ms_draw_face(draw, width // 2, 18 + 23, 22, face_state)
    _ms_draw_counter(draw, width - _MS_BORDER_PX - 74, 18, len(game['revealed']))
    board_x0 = coord_margin + _MS_BORDER_PX
    board_y0 = _MS_HEADER_PX + coord_margin
    for c in range(size):
        label = minesweeper_col_label(c)
        draw.text((board_x0 + c * cell + cell / 2, board_y0 - coord_margin / 2), label, font=font_small, fill=(210, 210, 210), anchor='mm')
    for r in range(size):
        draw.text((coord_margin / 2 + 4, board_y0 + r * cell + cell / 2), str(r + 1), font=font_small, fill=(210, 210, 210), anchor='mm')
    reveal_all = game['over'] and (not game['won'])
    for r in range(size):
        for c in range(size):
            x0 = board_x0 + c * cell
            y0 = board_y0 + r * cell
            x1, y1 = (x0 + cell, y0 + cell)
            is_revealed = (r, c) in game['revealed']
            is_flag = (r, c) in game['flags']
            is_mine = (r, c) in game['mines']
            if is_revealed:
                draw.rectangle([x0, y0, x1, y1], fill=(198, 198, 198), outline=(150, 150, 150))
                if is_mine:
                    fill = (255, 60, 60) if game['won'] is False and game['over'] else (198, 198, 198)
                    draw.rectangle([x0, y0, x1, y1], fill=fill)
                    mcx, mcy = (x0 + cell / 2, y0 + cell / 2)
                    mr = cell * 0.28
                    draw.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], fill=(20, 20, 20))
                    for ang in range(0, 360, 45):
                        import math
                        rad = math.radians(ang)
                        draw.line([(mcx, mcy), (mcx + mr * 1.6 * math.cos(rad), mcy + mr * 1.6 * math.sin(rad))], fill=(20, 20, 20), width=2)
                else:
                    val = game['board'][r][c]
                    if val > 0:
                        draw.text((x0 + cell / 2, y0 + cell / 2), str(val), font=font, fill=_MS_NUM_COLORS.get(val, (0, 0, 0)), anchor='mm')
            else:
                _ms_bevel_rect(draw, x0, y0, x1, y1, raised=True)
                if is_flag:
                    fx, fy = (x0 + cell / 2, y0 + cell / 2)
                    draw.line([(fx - 2, fy - cell * 0.28), (fx - 2, fy + cell * 0.28)], fill=(40, 30, 10), width=3)
                    draw.polygon([(fx - 2, fy - cell * 0.28), (fx - 2, fy - cell * 0.02), (fx + cell * 0.22, fy - cell * 0.15)], fill=(214, 45, 32))
                elif reveal_all and is_mine:
                    mcx, mcy = (x0 + cell / 2, y0 + cell / 2)
                    mr = cell * 0.24
                    draw.ellipse([mcx - mr, mcy - mr, mcx + mr, mcy + mr], fill=(20, 20, 20))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf
# ==================== HẾT MINESWEEPER ====================
