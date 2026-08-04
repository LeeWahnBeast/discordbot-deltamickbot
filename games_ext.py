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
# ⏱️ GIỚI HẠN 40 PHÚT/VÁN — áp dụng chung cho MỌI minigame
# ============================================================
SESSION_TIMEOUT_SECONDS = 40 * 60

def _session_mark(state):
    """Gọi khi start 1 ván — gắn mốc thời gian bắt đầu vào state (dict)."""
    state['started_at'] = time.time()
    return state

def _session_alive(state):
    """True nếu ván (state dict có 'started_at') chưa quá 40 phút."""
    if state is None:
        return False
    return time.time() - state.get('started_at', time.time()) < SESSION_TIMEOUT_SECONDS

# ============================================================
# 🎟️ HỆ THỐNG VÉ (currency riêng, KHÔNG phải Deion/Elo)
# ============================================================
VE_ICON = '🎟️'
VE_FILE = 've_data.json'
_ve_cache = {uid: d.get('ve', 0) for uid, d in _g._firestore_load_collection('ve', VE_FILE).items()}

def get_ve(user_id):
    if user_id == _g.BOT_OWNER_ID:
        return _g.INFINITE_AMOUNT
    return _ve_cache.get(user_id, 10)  # user mới toanh thì tặng sẵn 10 Vé cho có cái mà cày

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
    'guess_meme': 3,
    'guess_language': 5,
}

# Thưởng Deion khi thắng = 30% giá Vé của game đó (bỏ số lẻ vô nghĩa 0.1/0.0001 cũ)
REWARD_RATE = 0.30
GAME_WIN_REWARD = {g: round(cost * REWARD_RATE, 2) for g, cost in GAME_VE_COST.items()}

# 🎟️ Vé thưởng khi thắng — áp cho MỌI game, kể cả chess_bot & jackpot (trước đây không có)
VE_WIN_REWARD = {'wordle': 1, 'minesweeper': 2, 'guess_country': 3, 'guess_meme': 2,
                 'guess_language': 2, 'chess_bot': 5, 'jackpot': 1}

def award_win(game_type, user_id, deion_mult=1.0):
    """Cộng Deion + Vé thưởng khi thắng, đồng thời tick tiến độ quest. Trả (deion, ve) đã cộng."""
    deion = round(GAME_WIN_REWARD.get(game_type, 0) * deion_mult, 2)
    ve = VE_WIN_REWARD.get(game_type, 0)
    if deion:
        _g.add_deion(user_id, deion)
        quest_notify_earn(user_id, deion)
    if ve:
        add_ve(user_id, ve)
    quest_notify_win(user_id, game_type)
    return deion, ve

# Số lượt chơi FREE mỗi ngày cho mỗi game (tái dùng hệ _daily_usage của games.py)
_g.DAILY_FREE_GAMES.setdefault('wordle', 3)
_g.DAILY_FREE_GAMES.setdefault('minesweeper', 3)
_g.DAILY_FREE_GAMES.setdefault('guess_country', 3)
_g.DAILY_FREE_GAMES.setdefault('guess_meme', 3)
_g.DAILY_FREE_GAMES.setdefault('guess_language', 5)

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
    _wordle_games[_wordle_key(cid, user_id)] = _session_mark({
        'word': word,
        'guesses': [],  # list of (guess_str, feedback_str) feedback: G/Y/B per letter
        'done': False,
        'won': False,
    })
    quest_notify_play(user_id, 'wordle')
    return word

def wordle_active(cid, user_id):
    game = _wordle_games.get(_wordle_key(cid, user_id))
    if game is not None and not _session_alive(game):
        game['done'] = True
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
# 💣 MINESWEEPER (v2 — seed tuỳ chỉnh, size NxN tuỳ chỉnh, chord,
# lệnh nhập song ngữ Anh/Việt, render lại đẹp hơn)
# ============================================================
_mine_games = {}  # key: (channel_id, user_id) -> state

# Giới hạn kích thước bàn cờ (để ảnh không bị quá to/quá bé)
MINE_MIN_SIZE = 5
MINE_MAX_SIZE = 16
MINE_DEFAULT_SIZE = 9
MINE_DEFAULT_BOMBS = 10
MINE_BOMB_RATIO = 0.14  # tỉ lệ bom mặc định nếu không chỉ định số bom

def _mine_key(cid, user_id):
    return (cid, user_id)

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))

def _mine_neighbors(game, r, c):
    rows, cols = game['rows'], game['cols']
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = r + dr, c + dc
            if 0 <= nr < rows and 0 <= nc < cols:
                yield nr, nc

def minesweeper_bounds(cid, user_id):
    """Trả (rows, cols, bombs_count) của ván đang chơi (để main.py hiển thị thông báo lỗi)."""
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is None:
        return (MINE_DEFAULT_SIZE, MINE_DEFAULT_SIZE, MINE_DEFAULT_BOMBS)
    return (game['rows'], game['cols'], game['bombs_count'])

def minesweeper_start(cid, user_id, rows=None, cols=None, bombs=None, seed=None):
    """
    Tạo ván mới. Bom CHƯA được rải ngay (rải "lười" ở lượt mở ô đầu tiên)
    để đảm bảo ô đầu tiên người chơi mở luôn an toàn — giống Minesweeper cổ điển.
    `seed`: nếu truyền vào, bàn cờ sẽ được tạo lại y hệt mỗi khi dùng cùng seed.
    """
    rows = _clamp(rows or MINE_DEFAULT_SIZE, MINE_MIN_SIZE, MINE_MAX_SIZE)
    cols = _clamp(cols or MINE_DEFAULT_SIZE, MINE_MIN_SIZE, MINE_MAX_SIZE)
    area = rows * cols
    max_bombs = max(1, area - 9)  # luôn chừa ít nhất vùng an toàn quanh ô mở đầu
    if bombs is None:
        bombs = round(area * MINE_BOMB_RATIO)
    bombs = _clamp(int(bombs), 1, max_bombs)
    rng = random.Random(seed) if seed is not None else random.Random()
    state = {
        'rows': rows,
        'cols': cols,
        'bombs_count': bombs,
        'seed': seed,
        'rng': rng,
        'bombs': None,       # None = chưa rải bom (chờ nước mở đầu tiên)
        'counts': {},
        'revealed': set(),
        'flagged': set(),
        'done': False,
        'won': False,
        'moves': 0,
        'started_at': time.time(),
    }
    _mine_games[_mine_key(cid, user_id)] = state
    quest_notify_play(user_id, 'minesweeper')
    return state

def minesweeper_active(cid, user_id):
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is not None and not _session_alive(game):
        game['done'] = True
    return game is not None and not game['done']

def minesweeper_end(cid, user_id):
    _mine_games.pop(_mine_key(cid, user_id), None)

def _mine_place_bombs(game, safe_r, safe_c):
    rows, cols, bombs_count, rng = game['rows'], game['cols'], game['bombs_count'], game['rng']
    safe_zone = {(safe_r, safe_c)}
    safe_zone.update(_mine_neighbors(game, safe_r, safe_c))
    all_cells = [(r, c) for r in range(rows) for c in range(cols)]
    candidates = [cell for cell in all_cells if cell not in safe_zone]
    if len(candidates) < bombs_count:
        candidates = [cell for cell in all_cells if cell != (safe_r, safe_c)]
    bombs = set(rng.sample(candidates, min(bombs_count, len(candidates))))
    game['bombs'] = bombs
    counts = {}
    for r in range(rows):
        for c in range(cols):
            if (r, c) in bombs:
                continue
            counts[(r, c)] = sum(1 for nr, nc in _mine_neighbors(game, r, c) if (nr, nc) in bombs)
    game['counts'] = counts

def _mine_flood_reveal(game, r, c):
    stack = [(r, c)]
    while stack:
        cr, cc = stack.pop()
        if (cr, cc) in game['revealed']:
            continue
        game['revealed'].add((cr, cc))
        if game['counts'].get((cr, cc), 0) == 0:
            for nr, nc in _mine_neighbors(game, cr, cc):
                if (nr, nc) not in game['revealed'] and (nr, nc) not in game['bombs']:
                    stack.append((nr, nc))

def _mine_check_coord(game, row, col):
    rows, cols = game['rows'], game['cols']
    if not (0 <= row < rows and 0 <= col < cols):
        return f'❌ Tọa độ ngoài bảng (hàng 1-{rows}, cột A-{chr(64 + cols)}).'
    return None

def minesweeper_reveal(cid, user_id, row, col):
    """row/col 0-indexed. Trả (ok, reason, exploded, won)."""
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Minesweeper nào đang chơi.', False, False)
    err = _mine_check_coord(game, row, col)
    if err:
        return (False, err, False, False)
    if (row, col) in game['flagged']:
        return (False, '❌ Ô này đang bị cắm cờ, gỡ cờ trước đã.', False, False)
    if (row, col) in game['revealed']:
        return (False, '❌ Ô này đã mở rồi.', False, False)

    if game['bombs'] is None:
        _mine_place_bombs(game, row, col)
    game['moves'] += 1

    if (row, col) in game['bombs']:
        game['revealed'] |= game['bombs']
        game['done'] = True
        game['won'] = False
        return (True, None, True, False)

    _mine_flood_reveal(game, row, col)
    total_safe = game['rows'] * game['cols'] - game['bombs_count']
    if len(game['revealed']) >= total_safe:
        game['done'] = True
        game['won'] = True
        return (True, None, False, True)
    return (True, None, False, False)

def minesweeper_toggle_flag(cid, user_id, row, col):
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Minesweeper nào đang chơi.')
    err = _mine_check_coord(game, row, col)
    if err:
        return (False, err)
    if (row, col) in game['revealed']:
        return (False, '❌ Ô này đã mở rồi, không cắm cờ được.')
    coord_label = f'{chr(65 + col)}{row + 1}'
    if (row, col) in game['flagged']:
        game['flagged'].discard((row, col))
        return (True, f'🚩 Đã gỡ cờ ô **{coord_label}**.')
    game['flagged'].add((row, col))
    return (True, f'🚩 Đã cắm cờ ô **{coord_label}**.')

def minesweeper_chord(cid, user_id, row, col):
    """
    "Dò xung quanh" (chord) — nước đi mới: nếu ô đã mở có số N và đã cắm đủ N cờ
    xung quanh, tự động mở hết các ô còn lại quanh nó. Trả (ok, reason, exploded, won).
    """
    game = _mine_games.get(_mine_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Minesweeper nào đang chơi.', False, False)
    err = _mine_check_coord(game, row, col)
    if err:
        return (False, err, False, False)
    if (row, col) not in game['revealed']:
        return (False, '❌ Phải mở ô này trước rồi mới dò xung quanh được.', False, False)
    n = game['counts'].get((row, col), 0)
    if n == 0:
        return (False, '⚠️ Ô này không có số, không cần dò xung quanh.', False, False)
    neighbors = list(_mine_neighbors(game, row, col))
    flagged_count = sum(1 for nb in neighbors if nb in game['flagged'])
    if flagged_count != n:
        return (True, f'⚠️ Số cờ quanh ô này ({flagged_count}) chưa khớp số **{n}**, chưa thể dò.', False, False)
    game['moves'] += 1
    for nb in neighbors:
        if nb in game['flagged'] or nb in game['revealed']:
            continue
        if nb in game['bombs']:
            game['revealed'] |= game['bombs']
            game['done'] = True
            game['won'] = False
            return (True, None, True, False)
        _mine_flood_reveal(game, *nb)
    total_safe = game['rows'] * game['cols'] - game['bombs_count']
    if len(game['revealed']) >= total_safe:
        game['done'] = True
        game['won'] = True
        return (True, None, False, True)
    return (True, None, False, False)

# --- Nhập lệnh song ngữ Anh/Việt: "b3", "open b3"/"mo b3", "flag b3"/"co b3", "chord b3"/"do b3" ---
_MINE_OPEN_WORDS = {'o', 'open', 'mo', 'm'}
_MINE_FLAG_WORDS = {'f', 'flag', 'co', 'cam'}
_MINE_CHORD_WORDS = {'d', 'do', 'chord', 'x'}

def mine_parse_command(text):
    """
    Trả (action, coord_text) với action trong {'open','flag','chord'}.
    Nếu không có từ khoá hành động -> mặc định 'open'.
    """
    parts = text.strip().split()
    if not parts:
        return (None, None)
    if len(parts) == 1:
        return ('open', parts[0])
    keyword = _strip_accents(parts[0])
    coord = parts[-1]
    if keyword in _MINE_FLAG_WORDS:
        return ('flag', coord)
    if keyword in _MINE_CHORD_WORDS:
        return ('chord', coord)
    if keyword in _MINE_OPEN_WORDS:
        return ('open', coord)
    # không nhận ra từ khoá -> coi cả chuỗi là toạ độ (bỏ qua phần thừa), mặc định mở ô
    return ('open', parts[0])

def mine_coord_to_rc(text):
    """Parse 'B3' hoặc 'b3' -> (row=2, col=1). Trả None nếu sai định dạng."""
    if not text:
        return None
    text = text.strip().upper()
    if len(text) < 2:
        return None
    col_char = text[0]
    row_part = text[1:]
    if not col_char.isalpha() or not row_part.isdigit():
        return None
    col = ord(col_char) - 65
    row = int(row_part) - 1
    return (row, col)

# --- Vẽ ảnh minesweeper (render mới: viền bo góc, số rõ hơn, có toạ độ A-Z / 1-99) ---
_MINE_CELL = 28
_MINE_PAD = 14
_MINE_HEADER_H = 40
_MINE_COORD_MARGIN = 20
_MINE_BG = (235, 235, 240)
_MINE_HIDDEN = (176, 196, 222)
_MINE_HIDDEN_ALT = (168, 188, 214)
_MINE_HIDDEN_EDGE_LIGHT = (214, 226, 240)
_MINE_HIDDEN_EDGE_DARK = (120, 140, 168)
_MINE_REVEALED = (240, 240, 235)
_MINE_REVEALED_ALT = (231, 231, 224)
_MINE_NUM_COLOR = {
    1: (25, 90, 220), 2: (30, 140, 60), 3: (215, 40, 40), 4: (100, 30, 150),
    5: (150, 60, 20), 6: (20, 150, 150), 7: (30, 30, 30), 8: (110, 110, 110),
}

def _mine_font(size, bold=True):
    names = (
        ('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
        if bold else ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',)
    )
    for path in names:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()

def _draw_mini_bomb(draw, cx, cy, radius=7, color=(20, 20, 20)):
    """Vẽ icon quả bom nhỏ bằng hình khối (không dùng emoji vì font không hỗ trợ)."""
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=color)
    fx0, fy0 = cx + radius * 0.55, cy - radius * 0.55
    fx1, fy1 = cx + radius * 1.4, cy - radius * 1.4
    draw.line([fx0, fy0, fx1, fy1], fill=(120, 80, 40), width=2)
    draw.ellipse([fx1 - 3, fy1 - 3, fx1 + 3, fy1 + 3], fill=(255, 180, 60))
    draw.ellipse([cx - radius * 0.45, cy - radius * 0.45, cx - radius * 0.1, cy - radius * 0.1], fill=(255, 255, 255))

def _draw_face(draw, cx, cy, radius, state):
    """Vẽ mặt trạng thái (happy/win/dead) bằng hình khối thay vì emoji."""
    bg = (250, 210, 90) if state != 'dead' else (230, 90, 90)
    draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=bg, outline=(60, 60, 60), width=2)
    eye_dx, eye_dy, eye_r = radius * 0.35, radius * 0.15, radius * 0.14
    if state == 'dead':
        for sign in (-1, 1):
            ex, ey = cx + sign * eye_dx, cy - eye_dy
            draw.line([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=(30, 30, 30), width=2)
            draw.line([ex - eye_r, ey + eye_r, ex + eye_r, ey - eye_r], fill=(30, 30, 30), width=2)
        draw.arc([cx - radius * 0.5, cy + radius * 0.05, cx + radius * 0.5, cy + radius * 0.75], start=200, end=340, fill=(30, 30, 30), width=2)
    elif state == 'win':
        for sign in (-1, 1):
            ex = cx + sign * eye_dx
            draw.rectangle([ex - eye_r * 1.5, cy - eye_dy - eye_r, ex + eye_r * 1.5, cy - eye_dy + eye_r], fill=(20, 20, 20))
        draw.line([cx - eye_dx * 0.5, cy - eye_dy, cx + eye_dx * 0.5, cy - eye_dy], fill=(20, 20, 20), width=2)
        draw.arc([cx - radius * 0.5, cy - radius * 0.15, cx + radius * 0.5, cy + radius * 0.45], start=20, end=160, fill=(30, 30, 30), width=2)
    else:
        for sign in (-1, 1):
            ex, ey = cx + sign * eye_dx, cy - eye_dy
            draw.ellipse([ex - eye_r, ey - eye_r, ex + eye_r, ey + eye_r], fill=(30, 30, 30))
        draw.arc([cx - radius * 0.5, cy - radius * 0.15, cx + radius * 0.5, cy + radius * 0.45], start=20, end=160, fill=(30, 30, 30), width=2)

def minesweeper_board_image(cid, user_id):
    game = _mine_games[_mine_key(cid, user_id)]
    rows, cols = game['rows'], game['cols']
    cell = _MINE_CELL
    ox, oy = _MINE_PAD + _MINE_COORD_MARGIN, _MINE_PAD + _MINE_HEADER_H + _MINE_COORD_MARGIN
    w = ox + cols * cell + _MINE_PAD
    h = oy + rows * cell + _MINE_PAD
    img = Image.new('RGB', (w, h), _MINE_BG)
    draw = ImageDraw.Draw(img)
    coord_font = _mine_font(13)
    num_font = _mine_font(15)
    header_font = _mine_font(18)

    bombs_placed = game['bombs'] if game['bombs'] is not None else set()
    remaining_bombs = game['bombs_count'] - len(game['flagged'])
    if game.get('won'):
        face_state, header_color = 'win', (30, 150, 60)
    elif game.get('done'):
        face_state, header_color = 'dead', (200, 40, 40)
    else:
        face_state, header_color = 'happy', (30, 30, 30)

    # --- Header LCD-style: số bom còn lại (icon vẽ tay) + kích thước + mặt trạng thái (icon vẽ tay) ---
    draw.rounded_rectangle([_MINE_PAD, 8, _MINE_PAD + 80, 8 + 28], radius=6, fill=(15, 15, 15))
    _draw_mini_bomb(draw, _MINE_PAD + 18, 22, radius=8, color=(230, 230, 230))
    draw.text((_MINE_PAD + 30, 12), f'{max(0, remaining_bombs):03d}', font=header_font, fill=(255, 60, 60))
    size_label = f'{rows}x{cols}'
    draw.text((w - _MINE_PAD - len(size_label) * 10 - 6, 12), size_label, font=coord_font, fill=(90, 90, 90))
    _draw_face(draw, w // 2, 22, radius=14, state=face_state)

    # --- Toạ độ cột (A, B, C, ...) ---
    for c in range(cols):
        label = chr(65 + c)
        cx = ox + c * cell + cell // 2 - 5
        draw.text((cx, oy - _MINE_COORD_MARGIN + 2), label, font=coord_font, fill=(90, 90, 90))
    # --- Toạ độ hàng (1, 2, 3, ...) ---
    for r in range(rows):
        label = str(r + 1)
        cy = oy + r * cell + cell // 2 - 7
        draw.text((ox - _MINE_COORD_MARGIN + 2, cy), label, font=coord_font, fill=(90, 90, 90))

    for r in range(rows):
        for c in range(cols):
            x0, y0 = ox + c * cell, oy + r * cell
            x1, y1 = x0 + cell, y0 + cell
            revealed = (r, c) in game['revealed']
            flagged = (r, c) in game['flagged']
            checker = (r + c) % 2 == 0
            if revealed:
                base = _MINE_REVEALED if checker else _MINE_REVEALED_ALT
                draw.rectangle([x0, y0, x1, y1], fill=base, outline=(200, 200, 195))
                if (r, c) in bombs_placed:
                    draw.rectangle([x0, y0, x1, y1], fill=(230, 90, 90))
                    draw.ellipse([x0 + 6, y0 + 6, x1 - 6, y1 - 6], fill=(20, 20, 20))
                    draw.ellipse([x0 + 9, y0 + 9, x0 + 13, y0 + 13], fill=(255, 255, 255))
                else:
                    n = game['counts'].get((r, c), 0)
                    if n > 0:
                        color = _MINE_NUM_COLOR.get(n, (0, 0, 0))
                        tw = draw.textlength(str(n), font=num_font)
                        draw.text((x0 + cell / 2 - tw / 2, y0 + cell / 2 - 8), str(n), font=num_font, fill=color)
            else:
                base = _MINE_HIDDEN if checker else _MINE_HIDDEN_ALT
                draw.rectangle([x0, y0, x1, y1], fill=base)
                draw.line([x0 + 1, y0 + 1, x1 - 2, y0 + 1], fill=_MINE_HIDDEN_EDGE_LIGHT, width=2)
                draw.line([x0 + 1, y0 + 1, x0 + 1, y1 - 2], fill=_MINE_HIDDEN_EDGE_LIGHT, width=2)
                draw.line([x0 + 1, y1 - 1, x1 - 1, y1 - 1], fill=_MINE_HIDDEN_EDGE_DARK, width=2)
                draw.line([x1 - 1, y0 + 1, x1 - 1, y1 - 1], fill=_MINE_HIDDEN_EDGE_DARK, width=2)
                if flagged:
                    fx, fy = x0 + cell * 0.32, y0 + cell * 0.22
                    draw.line([fx, fy, fx, y1 - cell * 0.2], fill=(40, 40, 40), width=2)
                    draw.polygon([(fx, fy), (fx, fy + cell * 0.28), (fx + cell * 0.32, fy + cell * 0.14)], fill=(220, 30, 30))

    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# ============================================================
# 🌍 GUESS-COUNTRY (v2 — đếm ngược 15s/gợi ý, hết gợi ý là thua)
# ============================================================
_country_games = {}  # key: (channel_id, user_id) -> state
COUNTRY_TIME_LIMIT = 15  # giây mỗi gợi ý

# name, gợi ý theo thứ tự tăng dần độ dễ (được lộ dần mỗi 15 giây)
COUNTRY_DATA = [
    {'name': 'Việt Nam', 'flag': '🇻🇳', 'hints': ['Có món phở nổi tiếng thế giới', 'Hình chữ S trên bản đồ', 'Thủ đô là Hà Nội']},
    {'name': 'Nhật Bản', 'flag': '🇯🇵', 'hints': ['Biểu tượng hoa anh đào', 'Có núi Phú Sĩ', 'Thủ đô là Tokyo']},
    {'name': 'Hàn Quốc', 'flag': '🇰🇷', 'hints': ['Nổi tiếng với K-pop', 'Món kim chi truyền thống', 'Thủ đô là Seoul']},
    {'name': 'Trung Quốc', 'flag': '🇨🇳', 'hints': ['Có Vạn Lý Trường Thành', 'Dân số đông nhất nhì thế giới', 'Thủ đô là Bắc Kinh']},
    {'name': 'Thái Lan', 'flag': '🇹🇭', 'hints': ['Được gọi là đất nước Chùa Vàng', 'Món Tom Yum cay nồng', 'Thủ đô là Bangkok']},
    {'name': 'Pháp', 'flag': '🇫🇷', 'hints': ['Có tháp Eiffel', 'Nổi tiếng bánh mì baguette và rượu vang', 'Thủ đô là Paris']},
    {'name': 'Ý', 'flag': '🇮🇹', 'hints': ['Quê hương của pizza và pasta', 'Hình dáng như chiếc ủng trên bản đồ', 'Thủ đô là Roma']},
    {'name': 'Đức', 'flag': '🇩🇪', 'hints': ['Nổi tiếng xe hơi và bia', 'Có lễ hội Oktoberfest', 'Thủ đô là Berlin']},
    {'name': 'Tây Ban Nha', 'flag': '🇪🇸', 'hints': ['Nổi tiếng đấu bò và flamenco', 'Món paella truyền thống', 'Thủ đô là Madrid']},
    {'name': 'Anh', 'flag': '🇬🇧', 'hints': ['Có đồng hồ Big Ben', 'Uống trà chiều là văn hóa đặc trưng', 'Thủ đô là London']},
    {'name': 'Mỹ', 'flag': '🇺🇸', 'hints': ['Có tượng Nữ thần Tự do', 'Quê hương Hollywood', 'Thủ đô là Washington D.C.'] },
    {'name': 'Brazil', 'flag': '🇧🇷', 'hints': ['Nổi tiếng bóng đá và Carnival', 'Có tượng Chúa Cứu Thế khổng lồ', 'Thủ đô là Brasília']},
    {'name': 'Ai Cập', 'flag': '🇪🇬', 'hints': ['Có kim tự tháp cổ đại', 'Sông Nile chảy qua', 'Thủ đô là Cairo']},
    {'name': 'Ấn Độ', 'flag': '🇮🇳', 'hints': ['Có đền Taj Mahal', 'Món cà ri cay đặc trưng', 'Thủ đô là New Delhi']},
    {'name': 'Nga', 'flag': '🇷🇺', 'hints': ['Quốc gia rộng nhất thế giới', 'Có Quảng trường Đỏ', 'Thủ đô là Moscow']},
    {'name': 'Úc', 'flag': '🇦🇺', 'hints': ['Có chuột túi kangaroo', 'Nhà hát Opera Sydney nổi tiếng', 'Vừa là quốc gia vừa là lục địa']},
    {'name': 'Canada', 'flag': '🇨🇦', 'hints': ['Nổi tiếng lá phong đỏ', 'Có thác Niagara', 'Thủ đô là Ottawa']},
    {'name': 'Mexico', 'flag': '🇲🇽', 'hints': ['Món taco và burrito nổi tiếng', 'Có kim tự tháp Maya cổ', 'Thủ đô là Mexico City']},
    {'name': 'Indonesia', 'flag': '🇮🇩', 'hints': ['Quốc gia vạn đảo', 'Có đền Borobudur', 'Thủ đô là Jakarta']},
    {'name': 'Singapore', 'flag': '🇸🇬', 'hints': ['Tượng Sư Tử Biển Merlion', 'Đảo quốc nhỏ nhưng cực giàu', 'Còn gọi là Đảo Quốc Sư Tử']},
    {'name': 'Malaysia', 'flag': '🇲🇾', 'hints': ['Có tháp đôi Petronas', 'Món nasi lemak nổi tiếng', 'Thủ đô là Kuala Lumpur']},
    {'name': 'Philippines', 'flag': '🇵🇭', 'hints': ['Quốc gia có hơn 7000 đảo', 'Từng là thuộc địa Tây Ban Nha và Mỹ', 'Thủ đô là Manila']},
    {'name': 'Campuchia', 'flag': '🇰🇭', 'hints': ['Có đền Angkor Wat', 'Láng giềng của Việt Nam', 'Thủ đô là Phnom Penh']},
    {'name': 'Lào', 'flag': '🇱🇦', 'hints': ['Đất nước không giáp biển', 'Sông Mekong chảy qua', 'Thủ đô là Vientiane']},
    {'name': 'Myanmar', 'flag': '🇲🇲', 'hints': ['Có chùa vàng Shwedagon', 'Trước đây gọi là Miến Điện', 'Thủ đô là Naypyidaw']},
    {'name': 'Thổ Nhĩ Kỳ', 'flag': '🇹🇷', 'hints': ['Nằm giữa hai lục địa Á-Âu', 'Có thánh đường Hagia Sophia', 'Thủ đô là Ankara']},
    {'name': 'Hà Lan', 'flag': '🇳🇱', 'hints': ['Nổi tiếng hoa tulip và cối xay gió', 'Có nhiều kênh đào', 'Thủ đô là Amsterdam']},
    {'name': 'Bỉ', 'flag': '🇧🇪', 'hints': ['Nổi tiếng socola và bia', 'Có khoai tây chiên trứ danh', 'Thủ đô là Brussels']},
    {'name': 'Thụy Sĩ', 'flag': '🇨🇭', 'hints': ['Nổi tiếng đồng hồ và socola', 'Có núi Alps hùng vĩ', 'Thủ đô là Bern']},
    {'name': 'Thụy Điển', 'flag': '🇸🇪', 'hints': ['Quê hương ban nhạc ABBA', 'Có đồ nội thất IKEA', 'Thủ đô là Stockholm']},
    {'name': 'Na Uy', 'flag': '🇳🇴', 'hints': ['Nổi tiếng vịnh hẹp Fjord', 'Xứ sở của cực quang', 'Thủ đô là Oslo']},
    {'name': 'Đan Mạch', 'flag': '🇩🇰', 'hints': ['Quê hương của Lego', 'Có nàng tiên cá bằng đồng', 'Thủ đô là Copenhagen']},
    {'name': 'Ba Lan', 'flag': '🇵🇱', 'hints': ['Quê hương Copernicus', 'Có thành phố cổ Krakow', 'Thủ đô là Warsaw']},
    {'name': 'Bồ Đào Nha', 'flag': '🇵🇹', 'hints': ['Nổi tiếng bóng đá và cá mòi', 'Quê hương Cristiano Ronaldo', 'Thủ đô là Lisbon']},
    {'name': 'Hy Lạp', 'flag': '🇬🇷', 'hints': ['Cái nôi của Olympic', 'Có đảo Santorini xanh trắng', 'Thủ đô là Athens']},
    {'name': 'Áo', 'flag': '🇦🇹', 'hints': ['Quê hương của Mozart', 'Có cung điện Schönbrunn', 'Thủ đô là Vienna']},
    {'name': 'Ireland', 'flag': '🇮🇪', 'hints': ['Biểu tượng cỏ ba lá xanh', 'Có lễ hội St. Patrick', 'Thủ đô là Dublin']},
    {'name': 'Phần Lan', 'flag': '🇫🇮', 'hints': ['Được coi là quê hương Ông già Noel', 'Đất nước hạnh phúc nhất thế giới', 'Thủ đô là Helsinki']},
    {'name': 'Ukraine', 'flag': '🇺🇦', 'hints': ['Từng thuộc Liên Xô', 'Có món súp Borsch truyền thống', 'Thủ đô là Kyiv']},
    {'name': 'Israel', 'flag': '🇮🇱', 'hints': ['Có Bức tường Than khóc', 'Vùng Đất Thánh của 3 tôn giáo', 'Thủ đô là Jerusalem']},
    {'name': 'Ả Rập Xê Út', 'flag': '🇸🇦', 'hints': ['Có thánh địa Mecca', 'Xuất khẩu dầu mỏ lớn nhất', 'Thủ đô là Riyadh']},
    {'name': 'UAE', 'flag': '🇦🇪', 'hints': ['Có tòa tháp Burj Khalifa', 'Thành phố Dubai xa hoa', 'Thủ đô là Abu Dhabi']},
    {'name': 'Iran', 'flag': '🇮🇷', 'hints': ['Từng gọi là Ba Tư (Persia)', 'Nổi tiếng thảm dệt tay', 'Thủ đô là Tehran']},
    {'name': 'Pakistan', 'flag': '🇵🇰', 'hints': ['Có núi K2 cao thứ 2 thế giới', 'Tách ra từ Ấn Độ năm 1947', 'Thủ đô là Islamabad']},
    {'name': 'Bangladesh', 'flag': '🇧🇩', 'hints': ['Đất nước sông ngòi dày đặc', 'Xuất khẩu dệt may lớn', 'Thủ đô là Dhaka']},
    {'name': 'Nepal', 'flag': '🇳🇵', 'hints': ['Có đỉnh Everest cao nhất thế giới', 'Nơi sinh của Đức Phật', 'Thủ đô là Kathmandu']},
    {'name': 'New Zealand', 'flag': '🇳🇿', 'hints': ['Quê hương phim Chúa Nhẫn', 'Có chim Kiwi không biết bay', 'Thủ đô là Wellington']},
    {'name': 'Nam Phi', 'flag': '🇿🇦', 'hints': ['Quê hương Nelson Mandela', 'Có Mũi Hảo Vọng', 'Thủ đô là Pretoria']},
    {'name': 'Argentina', 'flag': '🇦🇷', 'hints': ['Quê hương Messi và Maradona', 'Điệu nhảy Tango nổi tiếng', 'Thủ đô là Buenos Aires']},
]

def _country_key(cid, user_id):
    return (cid, user_id)

_COUNTRY_FLAG_BY_NAME = {e['name']: e['flag'] for e in COUNTRY_DATA}

def guess_country_flag(name):
    return _COUNTRY_FLAG_BY_NAME.get(name, '🌍')

def _strip_accents(s):
    s = unicodedata.normalize('NFD', s)
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn').lower().strip()

def guess_country_start(cid, user_id):
    entry = random.choice(COUNTRY_DATA)
    _country_games[_country_key(cid, user_id)] = _session_mark({
        'entry': entry,
        'guesses': [],
        'hints_revealed': 1,
        'done': False,
        'won': False,
    })
    quest_notify_play(user_id, 'guess_country')
    return entry

def guess_country_active(cid, user_id):
    game = _country_games.get(_country_key(cid, user_id))
    if game is not None and not _session_alive(game):
        game['done'] = True
    return game is not None and not game['done']

def guess_country_end(cid, user_id):
    _country_games.pop(_country_key(cid, user_id), None)

def guess_country_current_hints(cid, user_id):
    game = _country_games.get(_country_key(cid, user_id))
    if game is None:
        return []
    return game['entry']['hints'][:game['hints_revealed']]

def guess_country_guess(cid, user_id, guess):
    """Trả (ok, reason, correct, done, won, answer). Đoán sai KHÔNG kết thúc ván
    (đồng hồ đếm ngược mới là thứ quyết định thắng/thua qua guess_country_tick)."""
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
    return (True, None, False, False, False, None)

def guess_country_tick(cid, user_id):
    """
    Gọi mỗi COUNTRY_TIME_LIMIT (15s) khi chưa đoán ra. Trả (done, revealed_new, answer):
    - hết gợi ý để lộ thêm  -> (True, False, tên_đúng)  : ván kết thúc, thua.
    - còn gợi ý             -> (False, True, None)       : vừa lộ thêm 1 gợi ý mới.
    - ván đã kết thúc rồi   -> (True, False, None)
    """
    game = _country_games.get(_country_key(cid, user_id))
    if game is None or game['done']:
        return (True, False, None)
    total_hints = len(game['entry']['hints'])
    if game['hints_revealed'] < total_hints:
        game['hints_revealed'] += 1
        return (False, True, None)
    game['done'] = True
    game['won'] = False
    return (True, False, game['entry']['name'])


# ============================================================
# 🖼️ GUESS-MEME (dựa vào https://api.imgflip.com/get_memes)
# ============================================================
import urllib.request
import json as _json

IMGFLIP_API = 'https://api.imgflip.com/get_memes'
_meme_list_cache = []
_meme_list_fetched_at = 0
MEME_LIST_TTL = 6 * 3600  # cache 6 tiếng, khỏi spam API

def _fetch_meme_list():
    """Lấy danh sách meme phổ biến từ imgflip, có cache theo thời gian."""
    global _meme_list_cache, _meme_list_fetched_at
    if _meme_list_cache and time.time() - _meme_list_fetched_at < MEME_LIST_TTL:
        return _meme_list_cache
    try:
        req = urllib.request.Request(IMGFLIP_API, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = _json.loads(resp.read())
        if data.get('success'):
            memes = data['data']['memes']
            _meme_list_cache = memes
            _meme_list_fetched_at = time.time()
            return memes
    except Exception as e:
        print(f'[guess_meme] Lỗi lấy danh sách meme: {type(e).__name__}: {e}')
    return _meme_list_cache  # trả cache cũ (có thể rỗng) nếu fetch lỗi

_meme_games = {}  # key: (channel_id, user_id) -> state
MEME_TIME_LIMIT = 15  # giây mỗi lần lộ thêm chữ
MEME_REVEAL_STEPS = 6  # tổng số lần lộ chữ cho tới khi lộ hết (~ mỗi 15s 1 lần)
# Chỉ lấy trong top N meme phổ biến nhất để tránh mấy cái tên meme quá lạ/khó đoán
MEME_POOL_SIZE = 60

def _meme_key(cid, user_id):
    return (cid, user_id)

def _meme_masked_name(name, revealed_count):
    """Che tên meme bằng dấu _ , chỉ lộ revealed_count ký tự đầu của mỗi từ dần dần."""
    words = name.split(' ')
    total_letters = sum(len(w) for w in words)
    shown = 0
    out_words = []
    for w in words:
        out_chars = []
        for ch in w:
            if not ch.isalnum():
                out_chars.append(ch)
                continue
            if shown < revealed_count:
                out_chars.append(ch)
                shown += 1
            else:
                out_chars.append('▢')
        out_words.append(''.join(out_chars))
    return ' '.join(out_words)

def guess_meme_start(cid, user_id):
    """Trả None nếu không lấy được danh sách meme (lỗi mạng/API)."""
    memes = _fetch_meme_list()
    if not memes:
        return None
    pool = memes[:MEME_POOL_SIZE]
    entry = random.choice(pool)
    _meme_games[_meme_key(cid, user_id)] = _session_mark({
        'name': entry['name'],
        'url': entry['url'],
        'guesses': [],
        'revealed_letters': 0,
        'done': False,
        'won': False,
    })
    quest_notify_play(user_id, 'guess_meme')
    return entry

def guess_meme_active(cid, user_id):
    game = _meme_games.get(_meme_key(cid, user_id))
    if game is not None and not _session_alive(game):
        game['done'] = True
    return game is not None and not game['done']

def guess_meme_end(cid, user_id):
    _meme_games.pop(_meme_key(cid, user_id), None)

def guess_meme_masked(cid, user_id):
    game = _meme_games.get(_meme_key(cid, user_id))
    if game is None:
        return ''
    return _meme_masked_name(game['name'], game['revealed_letters'])

def guess_meme_url(cid, user_id):
    game = _meme_games.get(_meme_key(cid, user_id))
    return game['url'] if game else None

def guess_meme_guess(cid, user_id, guess):
    """Trả (ok, reason, correct, done, won, answer). Đoán sai KHÔNG kết thúc ván
    (đồng hồ đếm ngược mới là thứ quyết định thắng/thua qua guess_meme_tick)."""
    game = _meme_games.get(_meme_key(cid, user_id))
    if game is None or game['done']:
        return (False, '❌ Không có ván Đoán Meme nào đang chơi.', False, True, False, None)
    guess = guess.strip()
    if not guess:
        return (False, '❌ Nhập tên meme đi bạn ơi.', False, False, False, None)

    correct = _strip_accents(guess) == _strip_accents(game['name'])
    game['guesses'].append(guess)
    if correct:
        game['done'] = True
        game['won'] = True
        return (True, None, True, True, True, game['name'])
    return (True, None, False, False, False, None)

def guess_meme_tick(cid, user_id):
    """
    Gọi mỗi MEME_TIME_LIMIT (15s) khi chưa đoán ra. Trả (done, revealed_new, answer):
    - đã lộ hết chữ cái  -> (True, False, tên_đúng) : ván kết thúc, thua.
    - còn chữ để lộ      -> (False, True, None)      : vừa lộ thêm chữ.
    - ván đã kết thúc rồi -> (True, False, None)
    """
    game = _meme_games.get(_meme_key(cid, user_id))
    if game is None or game['done']:
        return (True, False, None)
    total_letters = sum(1 for c in game['name'] if c.isalnum())
    if game['revealed_letters'] < total_letters:
        step = max(1, total_letters // MEME_REVEAL_STEPS)
        game['revealed_letters'] = min(total_letters, game['revealed_letters'] + step)
        return (False, True, None)
    game['done'] = True
    game['won'] = False
    return (True, False, game['name'])


# ============================================================
# 🈴 GUESS-LANGUAGE — đoán loại chữ viết/ngôn ngữ, 15 giây/lượt
# ============================================================
_lang_games = {}  # key: (channel_id, user_id) -> state
LANGUAGE_TIME_LIMIT = 15  # giây

LANGUAGE_DATA = [
    {'country': 'Việt Nam', 'flag': '🇻🇳', 'answer': 'Tiếng Việt', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Việt Nam là Tiếng Việt.'},
    {'country': 'Nhật Bản', 'flag': '🇯🇵', 'answer': 'Tiếng Nhật', 'region': 'Đông Á', 'note': 'Ngôn ngữ chính thức của Nhật Bản là Tiếng Nhật.'},
    {'country': 'Hàn Quốc', 'flag': '🇰🇷', 'answer': 'Tiếng Hàn', 'region': 'Đông Á', 'note': 'Ngôn ngữ chính thức của Hàn Quốc là Tiếng Hàn.'},
    {'country': 'Trung Quốc', 'flag': '🇨🇳', 'answer': 'Tiếng Trung', 'region': 'Đông Á', 'note': 'Ngôn ngữ chính thức của Trung Quốc là Tiếng Trung.'},
    {'country': 'Thái Lan', 'flag': '🇹🇭', 'answer': 'Tiếng Thái', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Thái Lan là Tiếng Thái.'},
    {'country': 'Pháp', 'flag': '🇫🇷', 'answer': 'Tiếng Pháp', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Pháp là Tiếng Pháp.'},
    {'country': 'Ý', 'flag': '🇮🇹', 'answer': 'Tiếng Ý', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Ý là Tiếng Ý.'},
    {'country': 'Đức', 'flag': '🇩🇪', 'answer': 'Tiếng Đức', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Đức là Tiếng Đức.'},
    {'country': 'Tây Ban Nha', 'flag': '🇪🇸', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Tây Ban Nha là Tiếng Tây Ban Nha.'},
    {'country': 'Anh', 'flag': '🇬🇧', 'answer': 'Tiếng Anh', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Anh là Tiếng Anh.'},
    {'country': 'Mỹ', 'flag': '🇺🇸', 'answer': 'Tiếng Anh', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Mỹ là Tiếng Anh.'},
    {'country': 'Brazil', 'flag': '🇧🇷', 'answer': 'Tiếng Bồ Đào Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Brazil là Tiếng Bồ Đào Nha.'},
    {'country': 'Ai Cập', 'flag': '🇪🇬', 'answer': 'Tiếng Ả Rập', 'region': 'Bắc Phi', 'note': 'Ngôn ngữ chính thức của Ai Cập là Tiếng Ả Rập.'},
    {'country': 'Ấn Độ', 'flag': '🇮🇳', 'answer': 'Tiếng Hindi', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Ấn Độ là Tiếng Hindi.'},
    {'country': 'Nga', 'flag': '🇷🇺', 'answer': 'Tiếng Nga', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Nga là Tiếng Nga.'},
    {'country': 'Úc', 'flag': '🇦🇺', 'answer': 'Tiếng Anh', 'region': 'Châu Đại Dương', 'note': 'Ngôn ngữ chính thức của Úc là Tiếng Anh.'},
    {'country': 'Canada', 'flag': '🇨🇦', 'answer': 'Tiếng Anh', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Canada là Tiếng Anh.'},
    {'country': 'Mexico', 'flag': '🇲🇽', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Mexico là Tiếng Tây Ban Nha.'},
    {'country': 'Indonesia', 'flag': '🇮🇩', 'answer': 'Tiếng Indonesia', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Indonesia là Tiếng Indonesia.'},
    {'country': 'Singapore', 'flag': '🇸🇬', 'answer': 'Tiếng Anh', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Singapore là Tiếng Anh.'},
    {'country': 'Malaysia', 'flag': '🇲🇾', 'answer': 'Tiếng Malay', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Malaysia là Tiếng Malay.'},
    {'country': 'Philippines', 'flag': '🇵🇭', 'answer': 'Tiếng Filipino', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Philippines là Tiếng Filipino.'},
    {'country': 'Campuchia', 'flag': '🇰🇭', 'answer': 'Tiếng Khmer', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Campuchia là Tiếng Khmer.'},
    {'country': 'Lào', 'flag': '🇱🇦', 'answer': 'Tiếng Lào', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Lào là Tiếng Lào.'},
    {'country': 'Myanmar', 'flag': '🇲🇲', 'answer': 'Tiếng Miến Điện', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Myanmar là Tiếng Miến Điện.'},
    {'country': 'Thổ Nhĩ Kỳ', 'flag': '🇹🇷', 'answer': 'Tiếng Thổ Nhĩ Kỳ', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Thổ Nhĩ Kỳ là Tiếng Thổ Nhĩ Kỳ.'},
    {'country': 'Hà Lan', 'flag': '🇳🇱', 'answer': 'Tiếng Hà Lan', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Hà Lan là Tiếng Hà Lan.'},
    {'country': 'Bỉ', 'flag': '🇧🇪', 'answer': 'Tiếng Hà Lan', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Bỉ là Tiếng Hà Lan.'},
    {'country': 'Thụy Sĩ', 'flag': '🇨🇭', 'answer': 'Tiếng Đức', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Thụy Sĩ là Tiếng Đức.'},
    {'country': 'Thụy Điển', 'flag': '🇸🇪', 'answer': 'Tiếng Thụy Điển', 'region': 'Bắc Âu', 'note': 'Ngôn ngữ chính thức của Thụy Điển là Tiếng Thụy Điển.'},
    {'country': 'Na Uy', 'flag': '🇳🇴', 'answer': 'Tiếng Na Uy', 'region': 'Bắc Âu', 'note': 'Ngôn ngữ chính thức của Na Uy là Tiếng Na Uy.'},
    {'country': 'Đan Mạch', 'flag': '🇩🇰', 'answer': 'Tiếng Đan Mạch', 'region': 'Bắc Âu', 'note': 'Ngôn ngữ chính thức của Đan Mạch là Tiếng Đan Mạch.'},
    {'country': 'Ba Lan', 'flag': '🇵🇱', 'answer': 'Tiếng Ba Lan', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Ba Lan là Tiếng Ba Lan.'},
    {'country': 'Bồ Đào Nha', 'flag': '🇵🇹', 'answer': 'Tiếng Bồ Đào Nha', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Bồ Đào Nha là Tiếng Bồ Đào Nha.'},
    {'country': 'Hy Lạp', 'flag': '🇬🇷', 'answer': 'Tiếng Hy Lạp', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Hy Lạp là Tiếng Hy Lạp.'},
    {'country': 'Áo', 'flag': '🇦🇹', 'answer': 'Tiếng Đức', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Áo là Tiếng Đức.'},
    {'country': 'Ireland', 'flag': '🇮🇪', 'answer': 'Tiếng Anh', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Ireland là Tiếng Anh.'},
    {'country': 'Phần Lan', 'flag': '🇫🇮', 'answer': 'Tiếng Phần Lan', 'region': 'Bắc Âu', 'note': 'Ngôn ngữ chính thức của Phần Lan là Tiếng Phần Lan.'},
    {'country': 'Ukraine', 'flag': '🇺🇦', 'answer': 'Tiếng Ukraine', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Ukraine là Tiếng Ukraine.'},
    {'country': 'Israel', 'flag': '🇮🇱', 'answer': 'Tiếng Hebrew', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Israel là Tiếng Hebrew.'},
    {'country': 'Ả Rập Xê Út', 'flag': '🇸🇦', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Ả Rập Xê Út là Tiếng Ả Rập.'},
    {'country': 'UAE', 'flag': '🇦🇪', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của UAE là Tiếng Ả Rập.'},
    {'country': 'Iran', 'flag': '🇮🇷', 'answer': 'Tiếng Ba Tư', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Iran là Tiếng Ba Tư.'},
    {'country': 'Pakistan', 'flag': '🇵🇰', 'answer': 'Tiếng Urdu', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Pakistan là Tiếng Urdu.'},
    {'country': 'Bangladesh', 'flag': '🇧🇩', 'answer': 'Tiếng Bengal', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Bangladesh là Tiếng Bengal.'},
    {'country': 'Nepal', 'flag': '🇳🇵', 'answer': 'Tiếng Nepal', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Nepal là Tiếng Nepal.'},
    {'country': 'New Zealand', 'flag': '🇳🇿', 'answer': 'Tiếng Anh', 'region': 'Châu Đại Dương', 'note': 'Ngôn ngữ chính thức của New Zealand là Tiếng Anh.'},
    {'country': 'Nam Phi', 'flag': '🇿🇦', 'answer': 'Tiếng Anh', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Nam Phi là Tiếng Anh.'},
    {'country': 'Argentina', 'flag': '🇦🇷', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Argentina là Tiếng Tây Ban Nha.'},
    {'country': 'Chile', 'flag': '🇨🇱', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Chile là Tiếng Tây Ban Nha.'},
    {'country': 'Colombia', 'flag': '🇨🇴', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Colombia là Tiếng Tây Ban Nha.'},
    {'country': 'Peru', 'flag': '🇵🇪', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Peru là Tiếng Tây Ban Nha.'},
    {'country': 'Venezuela', 'flag': '🇻🇪', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Venezuela là Tiếng Tây Ban Nha.'},
    {'country': 'Cuba', 'flag': '🇨🇺', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Cuba là Tiếng Tây Ban Nha.'},
    {'country': 'Ecuador', 'flag': '🇪🇨', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Ecuador là Tiếng Tây Ban Nha.'},
    {'country': 'Bolivia', 'flag': '🇧🇴', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Bolivia là Tiếng Tây Ban Nha.'},
    {'country': 'Paraguay', 'flag': '🇵🇾', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Paraguay là Tiếng Tây Ban Nha.'},
    {'country': 'Uruguay', 'flag': '🇺🇾', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Nam Mỹ', 'note': 'Ngôn ngữ chính thức của Uruguay là Tiếng Tây Ban Nha.'},
    {'country': 'Panama', 'flag': '🇵🇦', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Panama là Tiếng Tây Ban Nha.'},
    {'country': 'Costa Rica', 'flag': '🇨🇷', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Costa Rica là Tiếng Tây Ban Nha.'},
    {'country': 'Guatemala', 'flag': '🇬🇹', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Guatemala là Tiếng Tây Ban Nha.'},
    {'country': 'Honduras', 'flag': '🇭🇳', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Honduras là Tiếng Tây Ban Nha.'},
    {'country': 'El Salvador', 'flag': '🇸🇻', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của El Salvador là Tiếng Tây Ban Nha.'},
    {'country': 'Nicaragua', 'flag': '🇳🇮', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Nicaragua là Tiếng Tây Ban Nha.'},
    {'country': 'Dominican Republic', 'flag': '🇩🇴', 'answer': 'Tiếng Tây Ban Nha', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Dominican Republic là Tiếng Tây Ban Nha.'},
    {'country': 'Jamaica', 'flag': '🇯🇲', 'answer': 'Tiếng Anh', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Jamaica là Tiếng Anh.'},
    {'country': 'Haiti', 'flag': '🇭🇹', 'answer': 'Tiếng Pháp', 'region': 'Bắc Mỹ', 'note': 'Ngôn ngữ chính thức của Haiti là Tiếng Pháp.'},
    {'country': 'Maroc', 'flag': '🇲🇦', 'answer': 'Tiếng Ả Rập', 'region': 'Bắc Phi', 'note': 'Ngôn ngữ chính thức của Maroc là Tiếng Ả Rập.'},
    {'country': 'Algeria', 'flag': '🇩🇿', 'answer': 'Tiếng Ả Rập', 'region': 'Bắc Phi', 'note': 'Ngôn ngữ chính thức của Algeria là Tiếng Ả Rập.'},
    {'country': 'Tunisia', 'flag': '🇹🇳', 'answer': 'Tiếng Ả Rập', 'region': 'Bắc Phi', 'note': 'Ngôn ngữ chính thức của Tunisia là Tiếng Ả Rập.'},
    {'country': 'Libya', 'flag': '🇱🇾', 'answer': 'Tiếng Ả Rập', 'region': 'Bắc Phi', 'note': 'Ngôn ngữ chính thức của Libya là Tiếng Ả Rập.'},
    {'country': 'Sudan', 'flag': '🇸🇩', 'answer': 'Tiếng Ả Rập', 'region': 'Bắc Phi', 'note': 'Ngôn ngữ chính thức của Sudan là Tiếng Ả Rập.'},
    {'country': 'Iraq', 'flag': '🇮🇶', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Iraq là Tiếng Ả Rập.'},
    {'country': 'Jordan', 'flag': '🇯🇴', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Jordan là Tiếng Ả Rập.'},
    {'country': 'Lebanon', 'flag': '🇱🇧', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Lebanon là Tiếng Ả Rập.'},
    {'country': 'Syria', 'flag': '🇸🇾', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Syria là Tiếng Ả Rập.'},
    {'country': 'Kuwait', 'flag': '🇰🇼', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Kuwait là Tiếng Ả Rập.'},
    {'country': 'Qatar', 'flag': '🇶🇦', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Qatar là Tiếng Ả Rập.'},
    {'country': 'Oman', 'flag': '🇴🇲', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Oman là Tiếng Ả Rập.'},
    {'country': 'Yemen', 'flag': '🇾🇪', 'answer': 'Tiếng Ả Rập', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Yemen là Tiếng Ả Rập.'},
    {'country': 'Nigeria', 'flag': '🇳🇬', 'answer': 'Tiếng Anh', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Nigeria là Tiếng Anh.'},
    {'country': 'Kenya', 'flag': '🇰🇪', 'answer': 'Tiếng Swahili', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Kenya là Tiếng Swahili.'},
    {'country': 'Tanzania', 'flag': '🇹🇿', 'answer': 'Tiếng Swahili', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Tanzania là Tiếng Swahili.'},
    {'country': 'Ethiopia', 'flag': '🇪🇹', 'answer': 'Tiếng Amharic', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Ethiopia là Tiếng Amharic.'},
    {'country': 'Ghana', 'flag': '🇬🇭', 'answer': 'Tiếng Anh', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Ghana là Tiếng Anh.'},
    {'country': 'Senegal', 'flag': '🇸🇳', 'answer': 'Tiếng Pháp', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Senegal là Tiếng Pháp.'},
    {'country': 'Bờ Biển Ngà', 'flag': '🇨🇮', 'answer': 'Tiếng Pháp', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Bờ Biển Ngà là Tiếng Pháp.'},
    {'country': 'Cameroon', 'flag': '🇨🇲', 'answer': 'Tiếng Pháp', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Cameroon là Tiếng Pháp.'},
    {'country': 'Congo', 'flag': '🇨🇩', 'answer': 'Tiếng Pháp', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Congo là Tiếng Pháp.'},
    {'country': 'Angola', 'flag': '🇦🇴', 'answer': 'Tiếng Bồ Đào Nha', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Angola là Tiếng Bồ Đào Nha.'},
    {'country': 'Mozambique', 'flag': '🇲🇿', 'answer': 'Tiếng Bồ Đào Nha', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Mozambique là Tiếng Bồ Đào Nha.'},
    {'country': 'Zimbabwe', 'flag': '🇿🇼', 'answer': 'Tiếng Anh', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Zimbabwe là Tiếng Anh.'},
    {'country': 'Zambia', 'flag': '🇿🇲', 'answer': 'Tiếng Anh', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Zambia là Tiếng Anh.'},
    {'country': 'Uganda', 'flag': '🇺🇬', 'answer': 'Tiếng Anh', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Uganda là Tiếng Anh.'},
    {'country': 'Rwanda', 'flag': '🇷🇼', 'answer': 'Tiếng Kinyarwanda', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Rwanda là Tiếng Kinyarwanda.'},
    {'country': 'Madagascar', 'flag': '🇲🇬', 'answer': 'Tiếng Malagasy', 'region': 'Châu Phi', 'note': 'Ngôn ngữ chính thức của Madagascar là Tiếng Malagasy.'},
    {'country': 'Mông Cổ', 'flag': '🇲🇳', 'answer': 'Tiếng Mông Cổ', 'region': 'Đông Á', 'note': 'Ngôn ngữ chính thức của Mông Cổ là Tiếng Mông Cổ.'},
    {'country': 'Kazakhstan', 'flag': '🇰🇿', 'answer': 'Tiếng Kazakh', 'region': 'Trung Á', 'note': 'Ngôn ngữ chính thức của Kazakhstan là Tiếng Kazakh.'},
    {'country': 'Uzbekistan', 'flag': '🇺🇿', 'answer': 'Tiếng Uzbek', 'region': 'Trung Á', 'note': 'Ngôn ngữ chính thức của Uzbekistan là Tiếng Uzbek.'},
    {'country': 'Afghanistan', 'flag': '🇦🇫', 'answer': 'Tiếng Pashto', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Afghanistan là Tiếng Pashto.'},
    {'country': 'Sri Lanka', 'flag': '🇱🇰', 'answer': 'Tiếng Sinhala', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Sri Lanka là Tiếng Sinhala.'},
    {'country': 'Bhutan', 'flag': '🇧🇹', 'answer': 'Tiếng Dzongkha', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Bhutan là Tiếng Dzongkha.'},
    {'country': 'Maldives', 'flag': '🇲🇻', 'answer': 'Tiếng Dhivehi', 'region': 'Nam Á', 'note': 'Ngôn ngữ chính thức của Maldives là Tiếng Dhivehi.'},
    {'country': 'Brunei', 'flag': '🇧🇳', 'answer': 'Tiếng Malay', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Brunei là Tiếng Malay.'},
    {'country': 'Đông Timor', 'flag': '🇹🇱', 'answer': 'Tiếng Bồ Đào Nha', 'region': 'Đông Nam Á', 'note': 'Ngôn ngữ chính thức của Đông Timor là Tiếng Bồ Đào Nha.'},
    {'country': 'Papua New Guinea', 'flag': '🇵🇬', 'answer': 'Tiếng Anh', 'region': 'Châu Đại Dương', 'note': 'Ngôn ngữ chính thức của Papua New Guinea là Tiếng Anh.'},
    {'country': 'Fiji', 'flag': '🇫🇯', 'answer': 'Tiếng Anh', 'region': 'Châu Đại Dương', 'note': 'Ngôn ngữ chính thức của Fiji là Tiếng Anh.'},
    {'country': 'Iceland', 'flag': '🇮🇸', 'answer': 'Tiếng Iceland', 'region': 'Bắc Âu', 'note': 'Ngôn ngữ chính thức của Iceland là Tiếng Iceland.'},
    {'country': 'Estonia', 'flag': '🇪🇪', 'answer': 'Tiếng Estonia', 'region': 'Bắc Âu', 'note': 'Ngôn ngữ chính thức của Estonia là Tiếng Estonia.'},
    {'country': 'Latvia', 'flag': '🇱🇻', 'answer': 'Tiếng Latvia', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Latvia là Tiếng Latvia.'},
    {'country': 'Lithuania', 'flag': '🇱🇹', 'answer': 'Tiếng Lithuania', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Lithuania là Tiếng Lithuania.'},
    {'country': 'Séc', 'flag': '🇨🇿', 'answer': 'Tiếng Séc', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Séc là Tiếng Séc.'},
    {'country': 'Slovakia', 'flag': '🇸🇰', 'answer': 'Tiếng Slovak', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Slovakia là Tiếng Slovak.'},
    {'country': 'Hungary', 'flag': '🇭🇺', 'answer': 'Tiếng Hungary', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Hungary là Tiếng Hungary.'},
    {'country': 'Romania', 'flag': '🇷🇴', 'answer': 'Tiếng Romania', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Romania là Tiếng Romania.'},
    {'country': 'Bulgaria', 'flag': '🇧🇬', 'answer': 'Tiếng Bulgaria', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Bulgaria là Tiếng Bulgaria.'},
    {'country': 'Serbia', 'flag': '🇷🇸', 'answer': 'Tiếng Serbia', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Serbia là Tiếng Serbia.'},
    {'country': 'Croatia', 'flag': '🇭🇷', 'answer': 'Tiếng Croatia', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Croatia là Tiếng Croatia.'},
    {'country': 'Slovenia', 'flag': '🇸🇮', 'answer': 'Tiếng Slovenia', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Slovenia là Tiếng Slovenia.'},
    {'country': 'Bosnia', 'flag': '🇧🇦', 'answer': 'Tiếng Bosnia', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Bosnia là Tiếng Bosnia.'},
    {'country': 'Albania', 'flag': '🇦🇱', 'answer': 'Tiếng Albania', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Albania là Tiếng Albania.'},
    {'country': 'Armenia', 'flag': '🇦🇲', 'answer': 'Tiếng Armenia', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Armenia là Tiếng Armenia.'},
    {'country': 'Georgia', 'flag': '🇬🇪', 'answer': 'Tiếng Georgia', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Georgia là Tiếng Georgia.'},
    {'country': 'Azerbaijan', 'flag': '🇦🇿', 'answer': 'Tiếng Azerbaijan', 'region': 'Trung Đông', 'note': 'Ngôn ngữ chính thức của Azerbaijan là Tiếng Azerbaijan.'},
    {'country': 'Belarus', 'flag': '🇧🇾', 'answer': 'Tiếng Belarus', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Belarus là Tiếng Belarus.'},
    {'country': 'Moldova', 'flag': '🇲🇩', 'answer': 'Tiếng Romania', 'region': 'Đông Âu', 'note': 'Ngôn ngữ chính thức của Moldova là Tiếng Romania.'},
    {'country': 'Malta', 'flag': '🇲🇹', 'answer': 'Tiếng Malta', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Malta là Tiếng Malta.'},
    {'country': 'Luxembourg', 'flag': '🇱🇺', 'answer': 'Tiếng Luxembourg', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Luxembourg là Tiếng Luxembourg.'},
    {'country': 'Monaco', 'flag': '🇲🇨', 'answer': 'Tiếng Pháp', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Monaco là Tiếng Pháp.'},
    {'country': 'Andorra', 'flag': '🇦🇩', 'answer': 'Tiếng Catalan', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của Andorra là Tiếng Catalan.'},
    {'country': 'San Marino', 'flag': '🇸🇲', 'answer': 'Tiếng Ý', 'region': 'Nam Âu', 'note': 'Ngôn ngữ chính thức của San Marino là Tiếng Ý.'},
    {'country': 'Liechtenstein', 'flag': '🇱🇮', 'answer': 'Tiếng Đức', 'region': 'Châu Âu', 'note': 'Ngôn ngữ chính thức của Liechtenstein là Tiếng Đức.'},
    {'country': 'Đài Loan', 'flag': '🇹🇼', 'answer': 'Tiếng Trung', 'region': 'Đông Á', 'note': 'Ngôn ngữ chính thức của Đài Loan là Tiếng Trung.'},
    {'country': 'Hồng Kông', 'flag': '🇭🇰', 'answer': 'Tiếng Quảng Đông', 'region': 'Đông Á', 'note': 'Ngôn ngữ chính thức của Hồng Kông là Tiếng Quảng Đông.'},
]

def _lang_key(cid, user_id):
    return (cid, user_id)

def guess_language_start(cid, user_id):
    """Trả (entry, choices) — choices là list 4 đáp án đã xáo trộn, có đúng 1 đáp án đúng."""
    entry = random.choice(LANGUAGE_DATA)
    wrong_pool = list({e['answer'] for e in LANGUAGE_DATA if e['answer'] != entry['answer']})
    sample_size = min(3, len(wrong_pool))
    wrongs = random.sample(wrong_pool, sample_size)
    choices = wrongs + [entry['answer']]
    random.shuffle(choices)
    correct_index = choices.index(entry['answer'])
    _lang_games[_lang_key(cid, user_id)] = _session_mark({
        'entry': entry,
        'choices': choices,
        'correct_index': correct_index,
        'done': False,
        'hint_stage': 0,  # 0 = chỉ cờ, 1 = +khu vực, 2 = +tên nước
        'created_at': time.time(),
    })
    quest_notify_play(user_id, 'guess_language')
    return entry, choices

def guess_language_hints(cid, user_id):
    """Trả list các dòng gợi ý đã lộ tính tới hiện tại (dùng để hiển thị dưới câu hỏi)."""
    game = _lang_games.get(_lang_key(cid, user_id))
    if game is None:
        return []
    entry = game['entry']
    stage = game['hint_stage']
    hints = [f"🚩 Cờ: {entry['flag']}"]
    if stage >= 1:
        hints.append(f"🌍 Khu vực: {entry['region']}")
    if stage >= 2:
        hints.append(f"🏳️ Tên nước: {entry['country']}")
    return hints

def guess_language_tick(cid, user_id):
    """Gọi mỗi vài giây để lộ thêm gợi ý dần. Trả True nếu vừa lộ thêm gợi ý mới."""
    game = _lang_games.get(_lang_key(cid, user_id))
    if game is None or game['done']:
        return False
    if game['hint_stage'] < 2:
        game['hint_stage'] += 1
        return True
    return False

def guess_language_active(cid, user_id):
    game = _lang_games.get(_lang_key(cid, user_id))
    if game is not None and not _session_alive(game):
        game['done'] = True
    return game is not None and not game['done']

def guess_language_end(cid, user_id):
    _lang_games.pop(_lang_key(cid, user_id), None)

def guess_language_final_label(cid, user_id):
    game = _lang_games.get(_lang_key(cid, user_id))
    if game is None:
        return ''
    entry = game['entry']
    return f"{entry['flag']} {entry['country']}"

def guess_language_answer(cid, user_id, choice_index):
    """
    choice_index: -1 nếu hết giờ (không chọn gì). Trả (ok, correct, answer, note).
    """
    game = _lang_games.get(_lang_key(cid, user_id))
    if game is None or game['done']:
        return (False, False, None, None)
    game['done'] = True
    correct = choice_index == game['correct_index']
    return (True, correct, game['entry']['answer'], game['entry']['note'])


# ============================================================
# 🗿 RANDOM ELLIOT SIGMA — random câu nói vui
# ============================================================
ELLIOT_SIGMA_PHRASES = [
    'Tao mét mẹ bây giờ',
    'Tao mồ côi',
    'Rasio',
    'Tuất',
    'Tao là vị thần của mày',
    'Tao bú sữa mẹ',
    '7 học',
    'Son',
    'Im đi',
    'Ăn cứt chó',
]

def random_elliot_sigma():
    return random.choice(ELLIOT_SIGMA_PHRASES)


# ============================================================
# 🎰 JACKPOT — cược Deion, cược càng cao càng dễ thua
# ============================================================
JACKPOT_MIN_BET = 0.1
# (ngưỡng cược, tỉ lệ thắng) — cược càng cao thì rơi vào ngưỡng tỉ lệ thắng càng thấp
JACKPOT_TIERS = [
    (1, 0.50),
    (3, 0.42),
    (7, 0.34),
    (15, 0.24),
    (30, 0.16),
]
JACKPOT_FLOOR_CHANCE = 0.08  # cược siêu to vẫn còn tí máu, không về mo
JACKPOT_PAYOUT_MULT = 0.8  # thắng thì lời thêm 80% tiền cược

def jackpot_win_chance(bet):
    for threshold, chance in JACKPOT_TIERS:
        if bet <= threshold:
            return chance
    return JACKPOT_FLOOR_CHANCE

def jackpot_play(user_id, bet):
    """Trả (ok, reason, won, win_chance, new_balance, payout)."""
    balance = _g.get_deion(user_id)
    if bet is None or bet < JACKPOT_MIN_BET:
        return (False, f'❌ Cược tối thiểu là **{JACKPOT_MIN_BET} Deion** thôi bạn êi, làm gì có ai cược 0 đồng 🤨', False, 0, balance, 0)
    if bet > balance:
        return (False, f'❌ Cược **{bet} Deion** mà ví có **{balance}**? Xạo lồn vừa thôi 🤡 lấy đâu ra mà cược dữ vậy', False, 0, balance, 0)
    win_chance = jackpot_win_chance(bet)
    won = random.random() < win_chance
    quest_notify_play(user_id, 'jackpot')
    if won:
        payout = round(bet * JACKPOT_PAYOUT_MULT, 2)
        new_balance = _g.add_deion(user_id, payout)
        quest_notify_earn(user_id, payout)
    else:
        payout = round(bet, 2)
        new_balance = _g.add_deion(user_id, -bet)
        _g.add_deion(_g.TAX_RECIPIENT_ID, bet)  # nhà cái (chủ bot) ẵm trọn, không ai thoát
        quest_notify_spend(user_id, bet)
    return (True, None, won, win_chance, new_balance, payout)


# ============================================================
# 🎫 CUSTOM CODE — ai cũng tạo code được, deion trừ thẳng từ ví người tạo
# ============================================================
CUSTOM_CODE_FILE = 'custom_codes_data.json'
_CUSTOM_CODE_DOC_ID = 0  # tất cả code gộp chung 1 "document" (vì code là chuỗi, không phải user_id)
CUSTOM_CODE_NAME_MAX_LEN = 32
CUSTOM_CODE_MAX_HOURS = 24 * 30  # tối đa 30 ngày

def _load_custom_codes():
    data = _g._firestore_load_collection('custom_codes', CUSTOM_CODE_FILE)
    return data.get(_CUSTOM_CODE_DOC_ID, {})

_custom_codes = _load_custom_codes()

def _save_custom_codes():
    _g._firestore_save_doc('custom_codes', _CUSTOM_CODE_DOC_ID, _custom_codes)

def create_custom_code(creator_id, name, deion_per_use, hours_valid, max_uses=None):
    """Trả (ok, reason)."""
    name = (name or '').strip()
    if not name:
        return (False, '❌ Đặt tên code đi chứ, để trống ai mà nhập được 🤨')
    if len(name) > CUSTOM_CODE_NAME_MAX_LEN:
        return (False, f'❌ Tên code dài quá, tối đa {CUSTOM_CODE_NAME_MAX_LEN} ký tự thôi bạn êi.')
    if name in _custom_codes and not _custom_codes[name].get('disabled'):
        return (False, f'❌ Code **{name}** có người tạo rồi và còn sống, đổi tên khác đi.')
    if name in _g.REDEEM_CODES:
        return (False, f'❌ Tên **{name}** trùng code hệ thống rồi, đổi tên khác đi bạn êi.')
    if deion_per_use is None or deion_per_use <= 0:
        return (False, '❌ Số Deion tặng mỗi lượt nhập phải lớn hơn 0 chớ.')
    if hours_valid is None or hours_valid <= 0:
        return (False, '❌ Thời hạn code phải lớn hơn 0 giờ.')
    if hours_valid > CUSTOM_CODE_MAX_HOURS:
        return (False, f'❌ Thời hạn tối đa là {CUSTOM_CODE_MAX_HOURS} giờ (30 ngày) thôi.')
    if max_uses is not None and max_uses <= 0:
        return (False, '❌ Số lượt nhập phải lớn hơn 0 (bỏ trống nếu muốn không giới hạn).')
    balance = _g.get_deion(creator_id)
    if balance < deion_per_use:
        return (False, f'❌ Ví có **{balance} Deion** mà đòi tặng **{deion_per_use}**/lượt? Lấy đâu ra mà tạo code sang vậy 🤡')
    now = time.time()
    _custom_codes[name] = {
        'creator_id': creator_id,
        'deion': round(float(deion_per_use), 2),
        'created_at': now,
        'expires_at': now + hours_valid * 3600,
        'max_uses': max_uses,
        'used_by': [],
        'disabled': False,
        'disabled_reason': None,
    }
    _save_custom_codes()
    return (True, None)

def _custom_code_check_valid(name):
    """Kiểm tra 1 code còn dùng được không, tự động vô hiệu hoá nếu hết hạn/hết deion/hết lượt.
    Trả (entry_or_None, reason_neu_invalid_or_None)."""
    entry = _custom_codes.get(name)
    if entry is None:
        return (None, None)
    if entry.get('disabled'):
        return (entry, f"❌ Code này đã bị vô hiệu hoá. Lý do: {entry.get('disabled_reason') or 'Không rõ'}")
    if time.time() > entry['expires_at']:
        entry['disabled'] = True
        entry['disabled_reason'] = 'Hết hạn'
        _save_custom_codes()
        return (entry, '❌ Code này đã bị vô hiệu hoá. Lý do: Hết hạn')
    if entry['max_uses'] is not None and len(entry['used_by']) >= entry['max_uses']:
        entry['disabled'] = True
        entry['disabled_reason'] = 'Đã hết lượt nhập'
        _save_custom_codes()
        return (entry, '❌ Code này đã bị vô hiệu hoá. Lý do: Đã hết lượt nhập')
    creator_balance = _g.get_deion(entry['creator_id'])
    if creator_balance < entry['deion']:
        entry['disabled'] = True
        entry['disabled_reason'] = 'Hết Deion của người tạo code'
        _save_custom_codes()
        return (entry, '❌ Code này đã bị vô hiệu hoá. Lý do: Hết Deion của người tạo code')
    return (entry, None)

def redeem_custom_code(user_id, name):
    """
    Trả (found, ok, reason, deion_amount).
    found=False -> code này không tồn tại trong hệ thống custom code (để caller fallback qua REDEEM_CODES).
    found=True, ok=False -> code có tồn tại nhưng không nhập được (kèm reason).
    found=True, ok=True -> nhập thành công, deion_amount là số Deion nhận được.
    """
    name = (name or '').strip()
    entry, invalid_reason = _custom_code_check_valid(name)
    if entry is None:
        return (False, False, None, None)
    if invalid_reason:
        return (True, False, invalid_reason, None)
    if user_id == entry['creator_id']:
        return (True, False, '❌ Code của mày tự tạo thì tự nhập làm gì, lừa bản thân à 🤡', None)
    if user_id in entry['used_by']:
        return (True, False, '❌ Nhập rồi còn nhập lại, tham vừa thôi 🙅', None)
    amount = entry['deion']
    _g.add_deion(entry['creator_id'], -amount)
    _g.add_deion(user_id, amount)
    entry['used_by'].append(user_id)
    if entry['max_uses'] is not None and len(entry['used_by']) >= entry['max_uses']:
        entry['disabled'] = True
        entry['disabled_reason'] = 'Đã hết lượt nhập'
    _save_custom_codes()
    quest_notify_redeem_code(user_id)
    quest_notify_earn(user_id, amount)
    return (True, True, None, amount)


# ============================================================
# 📜 QUEST / NHIỆM VỤ HÀNG NGÀY — pool 16 loại, mỗi ngày random 3, reset lúc 0h
# ============================================================
QUEST_REWARD_DEION = 10   # Deion nhận khi hoàn thành xong 1 nhiệm vụ

# Câu ragebait mới — chỉ dùng nội bộ cho nv "tag + cà khịa" trong quest, không xúc phạm ngoại hình/gia đình thật
QUEST_TAG_LINES = ['con chó ngu', 'mày béo hơn tao', 'có 90% não là cứt', 'ai hỏi kid tao là trùm elliot sigma']
QUEST_RANDOM_PHRASES = ['meow', 'i am femboy', 'i am tsundere', 'tôi là con gái']
QUEST_GAY_FEMBOY_LINE = 'tôi bị gay còn là femboy'

def _quest_spend_goal():
    return random.randint(10, 100000)

# Mỗi quest: id, mô tả (có thể là hàm nếu cần goal random), goal, kind (loại counter theo dõi)
QUEST_POOL = [
    {'id': 'tag_line', 'goal': 3, 'kind': 'tag_line',
     'desc': lambda g: f'📢 Nhắn 1 câu cà khịa (VD: "{QUEST_TAG_LINES[0]}") **kèm tag 1 người** trong server ({g} lần)'},
    {'id': 'random_phrase', 'goal': 3, 'kind': 'random_phrase',
     'desc': lambda g: f'🗣️ Random nói 1 trong: {", ".join(QUEST_RANDOM_PHRASES)} ({g} lần)'},
    {'id': 'use_command', 'goal': 3, 'kind': 'use_command',
     'desc': lambda g: f'🎮 Sài 1 lệnh (slash command) bất kỳ của bot ({g} lần)'},
    {'id': 'gay_femboy', 'goal': 3, 'kind': 'gay_femboy',
     'desc': lambda g: f'🌈 Nói "Tôi Bị Gay Còn Là Femboy" ({g} lần)'},
    {'id': 'play_language', 'goal': 20, 'kind': 'play_language',
     'desc': lambda g: f'🈴 Chơi Đoán Ngôn Ngữ (`/doan-ngon-ngu`) hơn {g} lần'},
    {'id': 'spend_deion', 'goal': None, 'kind': 'spend_deion',
     'desc': lambda g: f'💸 Tiêu tổng cộng **{g}** Deion (mua shop / cược jackpot / tạo code...)'},
    {'id': 'win_any_game', 'goal': 3, 'kind': 'win_any_game',
     'desc': lambda g: f'🏆 Thắng {g} ván minigame bất kỳ'},
    {'id': 'play_wordle', 'goal': 5, 'kind': 'play_wordle',
     'desc': lambda g: f'🟩 Chơi Wordle {g} lần'},
    {'id': 'play_minesweeper', 'goal': 5, 'kind': 'play_minesweeper',
     'desc': lambda g: f'💣 Chơi Dò Mìn {g} lần'},
    {'id': 'play_country', 'goal': 5, 'kind': 'play_country',
     'desc': lambda g: f'🌍 Chơi Đoán Quốc Gia {g} lần'},
    {'id': 'play_meme', 'goal': 5, 'kind': 'play_meme',
     'desc': lambda g: f'🖼️ Chơi Đoán Meme {g} lần'},
    {'id': 'win_chess_bot', 'goal': 1, 'kind': 'win_chess_bot',
     'desc': lambda g: f'♟️ Thắng {g} ván cờ vs Bot'},
    {'id': 'play_jackpot', 'goal': 3, 'kind': 'play_jackpot',
     'desc': lambda g: f'🎰 Cược Jackpot {g} lần'},
    {'id': 'earn_deion', 'goal': 50, 'kind': 'earn_deion',
     'desc': lambda g: f'🤑 Kiếm tổng cộng **{g}** Deion (thắng game, nhập code...)'},
    {'id': 'use_shop', 'goal': 1, 'kind': 'use_shop',
     'desc': lambda g: f'🛒 Mua {g} vật phẩm ở Tạp Hoá'},
    {'id': 'redeem_code', 'goal': 1, 'kind': 'redeem_code',
     'desc': lambda g: f'🎁 Nhập {g} code nhận Deion'},
]
QUEST_POOL_BY_ID = {q['id']: q for q in QUEST_POOL}

_daily_quests = {}  # user_id -> {'day':.., 'slots':[{'id','goal','progress','done'}]*3, 'swapped': bool}

def _quest_make_slot(qdef):
    goal = _quest_spend_goal() if qdef['id'] == 'spend_deion' else qdef['goal']
    return {'id': qdef['id'], 'goal': goal, 'progress': 0, 'done': False}

def _quest_new_day(user_id):
    picks = random.sample(QUEST_POOL, 3)
    state = {'day': _g._today_key(), 'slots': [_quest_make_slot(q) for q in picks], 'swapped': False}
    _daily_quests[user_id] = state
    return state

def quest_state(user_id):
    st = _daily_quests.get(user_id)
    if st is None or st['day'] != _g._today_key():
        return _quest_new_day(user_id)
    return st

def quest_swap(user_id):
    """Đổi cả 3 nhiệm vụ hôm nay — chỉ được đổi 1 lần/ngày. Trả True nếu đổi thành công."""
    st = quest_state(user_id)
    if st['swapped']:
        return False
    picks = random.sample(QUEST_POOL, 3)
    st['slots'] = [_quest_make_slot(q) for q in picks]
    st['swapped'] = True
    return True

def quest_desc_line(slot):
    qdef = QUEST_POOL_BY_ID[slot['id']]
    return qdef['desc'](slot['goal'])

def quest_bar(user_id):
    st = quest_state(user_id)
    total_goal = sum(s['goal'] for s in st['slots'])
    total_progress = sum(min(s['progress'], s['goal']) for s in st['slots'])
    pct = int(100 * total_progress / total_goal) if total_goal else 0
    filled = pct // 10
    bar = '🟩' * filled + '⬜' * (10 - filled)
    return f'{bar} {pct}%'

def quest_reset_timestamp():
    """Unix timestamp của 0h ngày mai (giờ UTC), dùng cho Discord <t:...:R>."""
    now = time.gmtime()
    tomorrow_midnight = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 0, 0, 0, 0, 0, 0)) + 86400
    return int(tomorrow_midnight)

def _quest_bump_kind(user_id, kind, amount=1):
    """Gọi từ mọi nơi trong code khi có hành động liên quan tới 1 loại quest. Trả list slot vừa hoàn thành."""
    st = quest_state(user_id)
    completed = []
    for slot in st['slots']:
        if slot['done']:
            continue
        qdef = QUEST_POOL_BY_ID[slot['id']]
        if qdef['kind'] != kind:
            continue
        slot['progress'] += amount
        if slot['progress'] >= slot['goal']:
            slot['done'] = True
            _g.add_deion(user_id, QUEST_REWARD_DEION)
            completed.append(slot)
    return completed

# ---- các hook được gọi từ main.py / games.py khi có hành động tương ứng ----
def quest_check_message(user_id, content, has_mention):
    """Gọi từ on_message. Trả list slot vừa hoàn thành (rỗng nếu không có)."""
    c = content.strip().lower()
    done = []
    if has_mention and any(line in c for line in QUEST_TAG_LINES):
        done += _quest_bump_kind(user_id, 'tag_line')
    if c in (p.lower() for p in QUEST_RANDOM_PHRASES):
        done += _quest_bump_kind(user_id, 'random_phrase')
    if c == QUEST_GAY_FEMBOY_LINE:
        done += _quest_bump_kind(user_id, 'gay_femboy')
    return done

def quest_check_command(user_id):
    return _quest_bump_kind(user_id, 'use_command')

def quest_notify_play(user_id, game_type):
    """Gọi mỗi khi 1 ván minigame kết thúc (thắng/thua đều tính là 'chơi')."""
    kind_map = {'wordle': 'play_wordle', 'minesweeper': 'play_minesweeper',
                'guess_country': 'play_country', 'guess_meme': 'play_meme',
                'guess_language': 'play_language', 'jackpot': 'play_jackpot'}
    kind = kind_map.get(game_type)
    return _quest_bump_kind(user_id, kind) if kind else []

def quest_notify_win(user_id, game_type):
    done = _quest_bump_kind(user_id, 'win_any_game')
    if game_type == 'chess_bot':
        done += _quest_bump_kind(user_id, 'win_chess_bot')
    return done

def quest_notify_spend(user_id, amount):
    return _quest_bump_kind(user_id, 'spend_deion', amount)

def quest_notify_earn(user_id, amount):
    return _quest_bump_kind(user_id, 'earn_deion', amount)

def quest_notify_shop(user_id):
    return _quest_bump_kind(user_id, 'use_shop')

def quest_notify_redeem_code(user_id):
    return _quest_bump_kind(user_id, 'redeem_code')
