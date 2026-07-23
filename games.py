import random
import io
import time
import os
import base64
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
AURA_FILE = 'aura_data.json'
AURA_ICON = '<:mango:1529287058072408195>'
_aura_cache = {uid: d.get('balance', 0) for uid, d in _firestore_load_collection('aura', AURA_FILE).items()}

def get_aura(user_id):
    return _aura_cache.get(user_id, 0)

def add_aura(user_id, amount):
    if amount > 0 and _has_double_aura_buff(user_id):
        amount *= 2
    new_balance = get_aura(user_id) + amount
    _aura_cache[user_id] = new_balance
    _firestore_save_doc('aura', user_id, {'balance': new_balance})
    return new_balance

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

def wordle_start(cid):
    word = random.choice(WORDS)
    _wordle_games[cid] = {'word': word, 'guesses': 0}
    return word

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
FLAG_POOLS = {'easy': FLAG_EASY, 'medium': FLAG_MEDIUM, 'hard': FLAG_HARD, 'insane': FLAG_INSANE}
ROUNDS_PER_GAME = 5
_flag_games = {}

def flag_active(cid):
    return cid in _flag_games

def flag_start(cid, difficulty):
    _flag_games[cid] = {'pool': FLAG_POOLS[difficulty], 'round': 0, 'score': 0, 'country': None}
    return flag_next(cid)

def flag_next(cid):
    game = _flag_games[cid]
    if game['round'] >= ROUNDS_PER_GAME:
        return None
    country = random.choice(list(game['pool'].keys()))
    game['country'] = country
    game['round'] += 1
    return f'https://flagcdn.com/w320/{game['pool'][country]}.png'

def flag_check(cid, guess):
    game = _flag_games[cid]
    correct = guess.strip().lower() == game['country']
    if correct:
        game['score'] += 1
    return (correct, game['round'] < ROUNDS_PER_GAME)

def flag_answer(cid):
    return _flag_games[cid]['country']

def flag_progress(cid):
    g = _flag_games[cid]
    return (g['round'], ROUNDS_PER_GAME, g['score'])

def flag_end(cid):
    _flag_games.pop(cid, None)
WHATUINTO_LABELS = [('Femboy', 'Mềm mại bên ngoài, hỗn loạn bên trong. Bạn là hiện thân của "tưởng vậy mà không phải vậy".'), ('Tomboy', 'Năng lượng xắn tay áo, không ngại dơ. Bạn chọn hành động thay vì drama.'), ('Tsundere', '"Không phải tôi thích đâu nhé!" — trong khi tay đã làm sẵn hết rồi.'), ('Mommy ASMR', 'Giọng nói của bạn có thể ru cả server ngủ. Năng lượng chăm sóc tối thượng.'), ('Yandere ASMR', 'Ngọt ngào đến đáng ngờ. Ai chọc bạn giận thì... thôi khỏi nói.'), ('Vợ hàng xóm', 'Huyền thoại khu phố, ai cũng biết tên nhưng chẳng ai dám hỏi thẳng.'), ('Folk Valley', 'Bạn thuộc về nơi cỏ cây biết nói và gà biết deploy code.'), ('Scambodia', 'Chuyên gia lừa đảo... tình cảm. Cẩn thận, coi chừng mất ví lẫn mất tim.')]

def whatuinto_roll():
    label, caption = random.choice(WHATUINTO_LABELS)
    percent = random.randint(60, 99)
    return (label, caption, percent)
_ttt_games = {}
TTT_LINES = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]

def ttt_active(cid):
    return cid in _ttt_games

def ttt_start(cid, player_id):
    _ttt_games[cid] = {'board': [''] * 9, 'player_id': player_id, 'turn': 'X'}

def ttt_end(cid):
    _ttt_games.pop(cid, None)

def ttt_board(cid):
    return _ttt_games[cid]['board']

def _ttt_winner(board):
    for a, b, c in TTT_LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    if '' not in board:
        return 'draw'
    return None

def _ttt_minimax(board, is_bot_turn, depth=0):
    winner = _ttt_winner(board)
    if winner == 'O':
        return (10 - depth, None)
    if winner == 'X':
        return (depth - 10, None)
    if winner == 'draw':
        return (0, None)
    moves = [i for i in range(9) if board[i] == '']
    mark = 'O' if is_bot_turn else 'X'
    scored = []
    for m in moves:
        board[m] = mark
        score, _ = _ttt_minimax(board, not is_bot_turn, depth + 1)
        board[m] = ''
        scored.append((score, m))
    best = max(scored)[0] if is_bot_turn else min(scored)[0]
    best_moves = [m for s, m in scored if s == best]
    return (best, random.choice(best_moves))

def ttt_player_move(cid, index):
    game = _ttt_games[cid]
    board = game['board']
    if board[index] != '' or game['turn'] != 'X':
        return (False, None)
    board[index] = 'X'
    result = _ttt_winner(board)
    if result:
        return (True, result)
    game['turn'] = 'O'
    return (True, None)

def ttt_bot_move(cid):
    game = _ttt_games[cid]
    board = game['board']
    _, move = _ttt_minimax(board, True)
    board[move] = 'O'
    result = _ttt_winner(board)
    game['turn'] = 'X'
    return result
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
    dumbed = shop_consume_cu_cai(player_id)
    _chess_games[cid] = {'board': chess.Board(), 'is_pvp': False, 'player_id': player_id, 'player_color': chess.WHITE, 'last_move_at': time.time(), 'bot_elo': bot_elo, 'last_move': None, 'bot_dumbed': dumbed}
    return dumbed

def chess_start_pvp(cid, white_id, black_id, time_mode=CHESS_DEFAULT_TIME_MODE):
    cfg = CHESS_TIME_MODES[time_mode]
    ref_white = shop_consume_trong_tai(white_id)
    ref_black = shop_consume_trong_tai(black_id)
    _chess_games[cid] = {'board': chess.Board(), 'is_pvp': True, 'white_id': white_id, 'black_id': black_id, 'last_move_at': time.time(), 'last_move': None, 'time_mode': time_mode, 'clocks': {chess.WHITE: cfg['base'], chess.BLACK: cfg['base']}, 'increment': cfg['increment'], 'clock_running_since': time.time(), 'referee_favors': chess.WHITE if ref_white else chess.BLACK if ref_black else None}
    return (ref_white, ref_black)

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
    return _elo_cache.get(user_id, DEFAULT_ELO)

def _set_elo(user_id, new_elo):
    _elo_cache[user_id] = new_elo
    _firestore_save_doc('elo', user_id, {'elo': new_elo})
    return new_elo
BUY_ELO_AURA_COST = 50
BUY_ELO_AMOUNT = 100
_buy_elo_receipts = {}

def chess_buy_elo(user_id):
    balance = get_aura(user_id)
    if balance < BUY_ELO_AURA_COST:
        return (False, get_elo(user_id), balance)
    new_aura = add_aura(user_id, -BUY_ELO_AURA_COST)
    new_elo = _set_elo(user_id, get_elo(user_id) + BUY_ELO_AMOUNT)
    _buy_elo_receipts.setdefault(user_id, []).append({'time': time.time(), 'cost': BUY_ELO_AURA_COST, 'amount': BUY_ELO_AMOUNT, 'elo_after': new_elo, 'aura_after': new_aura})
    return (True, new_elo, new_aura)
SHOP_RESTOCK_SECONDS = 5 * 60
SHOP_ITEMS = {'elo10': {'emoji': '💠', 'name': '10 Elo', 'currency': 'aura', 'price': 5, 'desc': '📈 Tăng ngay +10 Elo.'}, 'cu_cai': {'emoji': '🥕', 'name': 'Củ Cải', 'currency': 'aura', 'price': 500, 'desc': '🎯 Dùng 1 lần — khi chơi cờ với Chess Bot:\n🤯 Bot bị giảm 100% trí tuệ, đi mù hoàn toàn ngẫu nhiên.\n♟️ Tha hồ chiếu bí... nếu vẫn thua thì chịu. 🥶'}, 'double_aura': {'emoji': '✨', 'name': 'Nhân Đôi Aura (24 giờ)', 'currency': 'elo', 'price': 300, 'desc': '⏳ Tăng x2 Aura nhận được trong 24 giờ.'}, 'role_gubby': {'emoji': '🐹', 'name': 'Role Gubby', 'currency': 'aura', 'price': 1900, 'desc': '🎖️ Nhận role Gubby vĩnh viễn.'}, 'trong_tai': {'emoji': '⚖️', 'name': 'Trọng Tài Chess (PvP)', 'currency': 'aura', 'price': 450, 'desc': '🎯 Dùng 1 lần — trong trận PvP tiếp theo:\n🛡️ "Trọng tài" thiên vị bạn một chút...\n🤫 (hiệu ứng vui, không đổi luật cờ thật)'}}
_user_buffs = {}

def _get_buffs(user_id):
    return _user_buffs.setdefault(user_id, {'cu_cai': 0, 'trong_tai': 0, 'double_aura_until': 0, 'gubby_role': False})

def _has_double_aura_buff(user_id):
    buffs = _user_buffs.get(user_id)
    return bool(buffs) and time.time() < buffs.get('double_aura_until', 0)

def shop_current_cycle():
    return int(time.time() // SHOP_RESTOCK_SECONDS)

def shop_seconds_until_restock():
    elapsed = time.time() % SHOP_RESTOCK_SECONDS
    return int(SHOP_RESTOCK_SECONDS - elapsed)

def shop_list():
    return SHOP_ITEMS

def shop_buy(user_id, item_key):
    item = SHOP_ITEMS.get(item_key)
    if item is None:
        return {'ok': False, 'reason': '❌ Vật phẩm không tồn tại.', 'item': None, 'balance_after': None}
    currency = item['currency']
    price = item['price']
    current = get_aura(user_id) if currency == 'aura' else get_elo(user_id)
    currency_label = 'Aura' if currency == 'aura' else 'Elo'
    if current < price:
        return {'ok': False, 'reason': f'❌ Không đủ {currency_label}! Cần **{price}**, bạn chỉ có **{current}**.', 'item': item, 'balance_after': current}
    if currency == 'aura':
        balance_after = add_aura(user_id, -price)
    else:
        balance_after = _set_elo(user_id, get_elo(user_id) - price)
    buffs = _get_buffs(user_id)
    if item_key == 'elo10':
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
    return {'ok': True, 'reason': None, 'item': item, 'balance_after': balance_after}

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

def shop_inventory_text(user_id):
    buffs = _get_buffs(user_id)
    lines = []
    if buffs['cu_cai'] > 0:
        lines.append(f'🥕 Củ Cải: còn **{buffs['cu_cai']}**')
    if buffs['trong_tai'] > 0:
        lines.append(f'⚖️ Trọng Tài: còn **{buffs['trong_tai']}**')
    if _has_double_aura_buff(user_id):
        remain = buffs['double_aura_until'] - time.time()
        h, rem = divmod(int(remain), 3600)
        m = rem // 60
        lines.append(f'✨ Nhân Đôi Aura: còn **{h}h{m:02d}m**')
    if buffs['gubby_role']:
        lines.append('🐹 Role Gubby: đã sở hữu vĩnh viễn')
    return '\n'.join(lines) if lines else '_Chưa có vật phẩm/buff nào đang hoạt động._'

def get_buy_elo_receipts(user_id):
    return list(reversed(_buy_elo_receipts.get(user_id, [])))

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
_piece_sprite_cache = {}

def _piece_key(piece_type, color):
    return f'{_PIECE_LETTER[piece_type]}_{('w' if color == chess.WHITE else 'b')}'

def get_piece_theme_url(user_id, piece_type, color):
    d = _piece_theme_cache.get(user_id)
    return d.get(_piece_key(piece_type, color)) if d else None

def set_piece_theme(user_id, key, url):
    d = _piece_theme_cache.setdefault(user_id, {})
    d[key] = url
    _firestore_save_doc('chess_piece_theme', user_id, d)

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

def _load_piece_sprite(url):
    if url in _piece_sprite_cache:
        return _piece_sprite_cache[url]
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read()
        sprite = Image.open(io.BytesIO(raw)).convert('RGBA').resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
    except Exception as e:
        print(f'[custom_chess] Không tải/đọc được ảnh từ {url}: {e!r}')
        _piece_sprite_cache[url] = None
        return None
    _piece_sprite_cache[url] = sprite
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