"""
games_ext.py — Phần mở rộng cho games.py
Thêm: hệ thống Vé (currency riêng, tách Deion/Elo), Wordle, Minesweeper, Guess-country.

File này import ngược `games` để tái dùng Deion/Firestore/daily-slot,
nên phải import SAU khi games.py đã định nghĩa xong các hàm cần thiết
(games.py sẽ `from games_ext import *` ở cuối file).
"""
import random
import time
import unicodedata
import io
from PIL import Image, ImageDraw, ImageFont

import games as _g  # tái dùng get_deion/add_deion/_firestore_*/DEION_ICON

# ============================================================
# 🎟️ HỆ THỐNG VÉ (currency riêng, KHÔNG phải Deion/Elo)
# ============================================================
VE_ICON = '🎟️'
VE_FILE = 've_data.json'
_ve_cache = {uid: d.get('ve', 0) for uid, d in _g._firestore_load_collection('ve', VE_FILE).items()}

def get_ve(user_id):
    if user_id == _g.BOT_OWNER_ID:
        return _g.INFINITE_AMOUNT
    return _ve_cache.get(user_id, 0)

def add_ve(user_id, amount):
    if user_id == _g.BOT_OWNER_ID:
        return _g.INFINITE_AMOUNT
    new_balance = max(0, get_ve(user_id) + amount)
    _ve_cache[user_id] = new_balance
    _g._firestore_save_doc('ve', user_id, {'ve': new_balance})
    return new_balance

def spend_ve(user_id, amount):
    """Trừ vé nếu đủ, trả về True/False."""
    if user_id == _g.BOT_OWNER_ID:
        return True
    if get_ve(user_id) < amount:
        return False
    add_ve(user_id, -amount)
    return True

# Giá vé (số Vé) để mua thêm 1 lượt chơi mỗi ngày, khi đã hết lượt free.
GAME_VE_COST = {
    'wordle': 1,
    'minesweeper': 5,
    'guess_country': 10,
}

# Số lượt chơi FREE mỗi ngày cho mỗi game (tái dùng hệ _daily_usage của games.py)
_g.DAILY_FREE_GAMES.setdefault('wordle', 3)
_g.DAILY_FREE_GAMES.setdefault('minesweeper', 3)
_g.DAILY_FREE_GAMES.setdefault('guess_country', 3)

def can_play_or_reason(game_type, user_id):
    """
    Kiểm tra user có thể bắt đầu ván mới không.
    Nếu còn lượt free -> (True, None).
    Nếu hết free nhưng đủ vé -> tự động trừ vé và trả (True, 've') để báo đã dùng vé.
    Nếu hết free và không đủ vé -> (False, lý do).
    """
    left = _g.daily_games_left_today(game_type, user_id)
    if left > 0:
        return (True, None)
    cost = GAME_VE_COST[game_type]
    if get_ve(user_id) >= cost:
        spend_ve(user_id, cost)
        _g.daily_add_slot(game_type, user_id)
        return (True, 've')
    return (False, f'❌ Bạn đã hết lượt chơi free hôm nay và không đủ {VE_ICON} Vé (cần **{cost}**, bạn có **{get_ve(user_id)}**).\nMua thêm Vé ở `/tạp-hoá` → 🛒 Shop nhé!')


# ============================================================
# 🟩 WORDLE
# ============================================================
_wordle_games = {}  # key: (channel_id, user_id) -> state
WORDLE_MAX_GUESSES = 6
WORDLE_WORD_LEN = 5

# Danh sách từ mặc định (có thể mở rộng). Toàn bộ chữ hoa, không dấu, 5 ký tự.
WORDLE_WORDS = [
    'APPLE', 'BRAVE', 'CRANE', 'DRIFT', 'EAGLE', 'FROST', 'GHOST', 'HOUSE',
    'IVORY', 'JOKER', 'KNIFE', 'LEMON', 'MANGO', 'NIGHT', 'OCEAN', 'PLANT',
    'QUEEN', 'RIVER', 'STONE', 'TIGER', 'UNITY', 'VIVID', 'WATER', 'YOUTH',
    'ZEBRA', 'CHESS', 'PIXEL', 'CLOUD', 'FLAME', 'GRAPE',
]

def _wordle_key(cid, user_id):
    return (cid, user_id)

def wordle_start(cid, user_id):
    word = random.choice(WORDLE_WORDS)
    _wordle_games[_wordle_key(cid, user_id)] = {
        'word': word,
        'guesses': [],  # list of (guess_str, feedback_str) feedback: G/Y/B per letter
        'done': False,
        'won': False,
    }
    return word

def wordle_active(cid, user_id):
    game = _wordle_games.get(_wordle_key(cid, user_id))
    return game is not None and not game['done']

def wordle_end(cid, user_id):
    _wordle_games.pop(_wordle_key(cid, user_id), None)

def wordle_guess(cid, user_id, guess):
    """
    Trả (ok, reason, feedback, done, won).
    feedback: list ký tự 'G'(xanh lá, đúng vị trí) / 'Y'(vàng, sai vị trí) / 'B'(xám, không có).
    """
    game = _wordle_games.get(_wordle_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Wordle nào đang chơi. Dùng lệnh chơi lại nhé!', None, True, False)
    guess = guess.strip().upper()
    if len(guess) != WORDLE_WORD_LEN or not guess.isalpha():
        return (False, f'❌ Từ phải có đúng **{WORDLE_WORD_LEN} chữ cái** (A-Z).', None, False, False)

    word = game['word']
    feedback = ['B'] * WORDLE_WORD_LEN
    word_chars = list(word)
    # Bước 1: đánh dấu đúng vị trí (xanh lá)
    for i in range(WORDLE_WORD_LEN):
        if guess[i] == word_chars[i]:
            feedback[i] = 'G'
            word_chars[i] = None
    # Bước 2: đánh dấu sai vị trí (vàng)
    for i in range(WORDLE_WORD_LEN):
        if feedback[i] == 'G':
            continue
        if guess[i] in word_chars:
            feedback[i] = 'Y'
            word_chars[word_chars.index(guess[i])] = None

    game['guesses'].append((guess, feedback))
    won = guess == word
    done = won or len(game['guesses']) >= WORDLE_MAX_GUESSES
    game['done'] = done
    game['won'] = won
    return (True, None, feedback, done, won)

WORDLE_EMOJI = {'G': '🟩', 'Y': '🟨', 'B': '⬜'}

def wordle_render(cid, user_id):
    """Render bảng Wordle dạng text emoji (5x6 lưới)."""
    game = _wordle_games.get(_wordle_key(cid, user_id))
    if game is None:
        return '_(chưa có ván nào)_'
    lines = []
    for guess, feedback in game['guesses']:
        row_emoji = ''.join(WORDLE_EMOJI[f] for f in feedback)
        letters = ' '.join(guess)
        lines.append(f'{row_emoji}   `{letters}`')
    remaining = WORDLE_MAX_GUESSES - len(game['guesses'])
    for _ in range(remaining):
        lines.append('⚪⚪⚪⚪⚪')
    return '\n'.join(lines)

def wordle_answer(cid, user_id):
    game = _wordle_games.get(_wordle_key(cid, user_id))
    return game['word'] if game else None


# ============================================================
# 💣 MINESWEEPER
# ============================================================
_mine_games = {}  # key: (channel_id, user_id) -> state
MINE_COLS = 9
MINE_ROWS = 9
MINE_BOMBS = 10

def _mine_key(cid, user_id):
    return (cid, user_id)

def _mine_neighbors(r, c):
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < MINE_ROWS and 0 <= nc < MINE_COLS:
                yield nr, nc

def minesweeper_start(cid, user_id):
    bombs = set()
    while len(bombs) < MINE_BOMBS:
        bombs.add((random.randrange(MINE_ROWS), random.randrange(MINE_COLS)))
    counts = {}
    for r in range(MINE_ROWS):
        for c in range(MINE_COLS):
            if (r, c) in bombs:
                continue
            counts[(r, c)] = sum(1 for nr, nc in _mine_neighbors(r, c) if (nr, nc) in bombs)
    state = {
        'bombs': bombs,
        'counts': counts,
        'revealed': set(),
        'flagged': set(),
        'done': False,
        'won': False,
        'started_at': time.time(),
    }
    _mine_games[_mine_key(cid, user_id)] = state
    return state

def minesweeper_active(cid, user_id):
    game = _mine_games.get(_mine_key(cid, user_id))
    return game is not None and not game['done']

def minesweeper_end(cid, user_id):
    _mine_games.pop(_mine_key(cid, user_id), None)

def _mine_flood_reveal(game, r, c):
    stack = [(r, c)]
    while stack:
        cr, cc = stack.pop()
        if (cr, cc) in game['revealed']:
            continue
        game['revealed'].add((cr, cc))
        if game['counts'].get((cr, cc), 0) == 0:
            for nr, nc in _mine_neighbors(cr, cc):
                if (nr, nc) not in game['revealed'] and (nr, nc) not in game['bombs']:
                    stack.append((nr, nc))

def minesweeper_reveal(cid, user_id, row, col):
    """
    row/col 0-indexed. Trả (ok, reason, exploded, won).
    """
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Minesweeper nào đang chơi.', False, False)
    if not (0 <= row < MINE_ROWS and 0 <= col < MINE_COLS):
        return (False, f'❌ Tọa độ ngoài bảng (hàng 1-{MINE_ROWS}, cột A-{chr(64 + MINE_COLS)}).', False, False)
    if (row, col) in game['flagged']:
        return (False, '❌ Ô này đang bị cắm cờ, gỡ cờ trước đã.', False, False)
    if (row, col) in game['revealed']:
        return (False, '❌ Ô này đã mở rồi.', False, False)

    if (row, col) in game['bombs']:
        game['revealed'] |= game['bombs']
        game['done'] = True
        game['won'] = False
        return (True, None, True, False)

    _mine_flood_reveal(game, row, col)
    total_safe = MINE_ROWS * MINE_COLS - MINE_BOMBS
    if len(game['revealed']) >= total_safe:
        game['done'] = True
        game['won'] = True
        return (True, None, False, True)
    return (True, None, False, False)

def minesweeper_toggle_flag(cid, user_id, row, col):
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Minesweeper nào đang chơi.')
    if not (0 <= row < MINE_ROWS and 0 <= col < MINE_COLS):
        return (False, f'❌ Tọa độ ngoài bảng (hàng 1-{MINE_ROWS}, cột A-{chr(64 + MINE_COLS)}).')
    if (row, col) in game['revealed']:
        return (False, '❌ Ô này đã mở rồi, không cắm cờ được.')
    if (row, col) in game['flagged']:
        game['flagged'].discard((row, col))
        return (True, f'🚩 Đã gỡ cờ ô {chr(65 + col)}{row + 1}.')
    game['flagged'].add((row, col))
    return (True, f'🚩 Đã cắm cờ ô {chr(65 + col)}{row + 1}.')

# --- Vẽ ảnh minesweeper (style giống ảnh mẫu classic) ---
_MINE_CELL = 22
_MINE_PAD = 12
_MINE_HEADER_H = 34
_MINE_NUM_COLOR = {
    1: (0, 0, 230), 2: (0, 128, 0), 3: (220, 0, 0), 4: (0, 0, 128),
    5: (128, 0, 0), 6: (0, 128, 128), 7: (0, 0, 0), 8: (128, 128, 128),
}

def _mine_font(size):
    for path in ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

def minesweeper_board_image(cid, user_id):
    game = _mine_games[_mine_key(cid, user_id)]
    w = MINE_COLS * _MINE_CELL + _MINE_PAD * 2
    h = MINE_ROWS * _MINE_CELL + _MINE_PAD * 2 + _MINE_HEADER_H
    img = Image.new('RGB', (w, h), (192, 192, 192))
    draw = ImageDraw.Draw(img)
    font = _mine_font(14)
    header_font = _mine_font(16)

    # Header: bom còn lại + trạng thái
    remaining_bombs = MINE_BOMBS - len(game['flagged'])
    face = '😎' if game.get('won') else ('💥' if game.get('done') and not game.get('won') else '🙂')
    draw.rectangle([_MINE_PAD, 8, _MINE_PAD + 50, 8 + 24], fill=(0, 0, 0))
    draw.text((_MINE_PAD + 6, 10), f'{remaining_bombs:03d}', font=header_font, fill=(255, 0, 0))
    draw.text((w // 2 - 10, 8), face, font=header_font, fill=(0, 0, 0))

    ox, oy = _MINE_PAD, _MINE_PAD + _MINE_HEADER_H
    for r in range(MINE_ROWS):
        for c in range(MINE_COLS):
            x0, y0 = ox + c * _MINE_CELL, oy + r * _MINE_CELL
            x1, y1 = x0 + _MINE_CELL, y0 + _MINE_CELL
            revealed = (r, c) in game['revealed']
            flagged = (r, c) in game['flagged']
            if revealed:
                draw.rectangle([x0, y0, x1, y1], fill=(210, 210, 210), outline=(140, 140, 140))
                if (r, c) in game['bombs']:
                    draw.ellipse([x0 + 5, y0 + 5, x1 - 5, y1 - 5], fill=(0, 0, 0))
                else:
                    n = game['counts'].get((r, c), 0)
                    if n > 0:
                        color = _MINE_NUM_COLOR.get(n, (0, 0, 0))
                        draw.text((x0 + _MINE_CELL / 2 - 4, y0 + 3), str(n), font=font, fill=color)
            else:
                draw.rectangle([x0, y0, x1, y1], fill=(200, 200, 200), outline=(120, 120, 120))
                draw.line([x0, y0, x1, y0], fill=(240, 240, 240), width=2)
                draw.line([x0, y0, x0, y1], fill=(240, 240, 240), width=2)
                if flagged:
                    draw.polygon([(x0 + 6, y0 + 4), (x0 + 6, y0 + 12), (x0 + 15, y0 + 8)], fill=(220, 0, 0))
                    draw.line([x0 + 6, y0 + 4, x0 + 6, y0 + 18], fill=(0, 0, 0), width=2)

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# ============================================================
# 🌍 GUESS-COUNTRY
# ============================================================
_country_games = {}  # key: (channel_id, user_id) -> state
COUNTRY_MAX_GUESSES = 6

# name, gợi ý theo thứ tự tăng dần độ dễ (được lộ dần mỗi lần đoán sai)
COUNTRY_DATA = [
    {'name': 'Việt Nam', 'hints': ['Có món phở nổi tiếng thế giới', 'Hình chữ S trên bản đồ', 'Thủ đô là Hà Nội']},
    {'name': 'Nhật Bản', 'hints': ['Biểu tượng hoa anh đào', 'Có núi Phú Sĩ', 'Thủ đô là Tokyo']},
    {'name': 'Hàn Quốc', 'hints': ['Nổi tiếng với K-pop', 'Món kim chi truyền thống', 'Thủ đô là Seoul']},
    {'name': 'Trung Quốc', 'hints': ['Có Vạn Lý Trường Thành', 'Dân số đông nhất nhì thế giới', 'Thủ đô là Bắc Kinh']},
    {'name': 'Thái Lan', 'hints': ['Được gọi là đất nước Chùa Vàng', 'Món Tom Yum cay nồng', 'Thủ đô là Bangkok']},
    {'name': 'Pháp', 'hints': ['Có tháp Eiffel', 'Nổi tiếng bánh mì baguette và rượu vang', 'Thủ đô là Paris']},
    {'name': 'Ý', 'hints': ['Quê hương của pizza và pasta', 'Hình dáng như chiếc ủng trên bản đồ', 'Thủ đô là Roma']},
    {'name': 'Đức', 'hints': ['Nổi tiếng xe hơi và bia', 'Có lễ hội Oktoberfest', 'Thủ đô là Berlin']},
    {'name': 'Tây Ban Nha', 'hints': ['Nổi tiếng đấu bò và flamenco', 'Món paella truyền thống', 'Thủ đô là Madrid']},
    {'name': 'Anh', 'hints': ['Có đồng hồ Big Ben', 'Uống trà chiều là văn hóa đặc trưng', 'Thủ đô là London']},
    {'name': 'Mỹ', 'hints': ['Có tượng Nữ thần Tự do', 'Quê hương Hollywood', 'Thủ đô là Washington D.C.'] },
    {'name': 'Brazil', 'hints': ['Nổi tiếng bóng đá và Carnival', 'Có tượng Chúa Cứu Thế khổng lồ', 'Thủ đô là Brasília']},
    {'name': 'Ai Cập', 'hints': ['Có kim tự tháp cổ đại', 'Sông Nile chảy qua', 'Thủ đô là Cairo']},
    {'name': 'Ấn Độ', 'hints': ['Có đền Taj Mahal', 'Món cà ri cay đặc trưng', 'Thủ đô là New Delhi']},
    {'name': 'Nga', 'hints': ['Quốc gia rộng nhất thế giới', 'Có Quảng trường Đỏ', 'Thủ đô là Moscow']},
    {'name': 'Úc', 'hints': ['Có chuột túi kangaroo', 'Nhà hát Opera Sydney nổi tiếng', 'Vừa là quốc gia vừa là lục địa']},
    {'name': 'Canada', 'hints': ['Nổi tiếng lá phong đỏ', 'Có thác Niagara', 'Thủ đô là Ottawa']},
    {'name': 'Mexico', 'hints': ['Món taco và burrito nổi tiếng', 'Có kim tự tháp Maya cổ', 'Thủ đô là Mexico City']},
    {'name': 'Indonesia', 'hints': ['Quốc gia vạn đảo', 'Có đền Borobudur', 'Thủ đô là Jakarta']},
    {'name': 'Singapore', 'hints': ['Tượng Sư Tử Biển Merlion', 'Đảo quốc nhỏ nhưng cực giàu', 'Còn gọi là Đảo Quốc Sư Tử']},
]

def _country_key(cid, user_id):
    return (cid, user_id)

def _strip_accents(s):
    s = unicodedata.normalize('NFD', s)
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower().strip()

def guess_country_start(cid, user_id):
    entry = random.choice(COUNTRY_DATA)
    _country_games[_country_key(cid, user_id)] = {
        'entry': entry,
        'guesses': [],
        'hints_revealed': 1,
        'done': False,
        'won': False,
    }
    return entry

def guess_country_active(cid, user_id):
    game = _country_games.get(_country_key(cid, user_id))
    return game is not None and not game['done']

def guess_country_end(cid, user_id):
    _country_games.pop(_country_key(cid, user_id), None)

def guess_country_current_hints(cid, user_id):
    game = _country_games.get(_country_key(cid, user_id))
    if game is None:
        return []
    return game['entry']['hints'][:game['hints_revealed']]

def guess_country_guess(cid, user_id, guess):
    """Trả (ok, reason, correct, done, won, answer)."""
    game = _country_games.get(_country_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Đoán Quốc Gia nào đang chơi.', False, True, False, None)
    guess = guess.strip()
    if not guess:
        return (False, '❌ Nhập tên quốc gia đi bạn ơi.', False, False, False, None)

    correct = _strip_accents(guess) == _strip_accents(game['entry']['name'])
    game['guesses'].append(guess)
    if correct:
        game['done'] = True
        game['won'] = True
        return (True, None, True, True, True, game['entry']['name'])

    if game['hints_revealed'] < len(game['entry']['hints']):
        game['hints_revealed'] += 1
    done = len(game['guesses']) >= COUNTRY_MAX_GUESSES
    game['done'] = done
    game['won'] = False
    answer = game['entry']['name'] if done else None
    return (True, None, False, done, False, answer)
