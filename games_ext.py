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
    'guess_meme': 3,
    'guess_language': 5,
}

# Thưởng Deion khi thắng minigame (rất thấp vì 1 Aura cũ = 0.0001 Deion, không phải game chính như Chess)
GAME_WIN_REWARD = {
    'wordle': 0.15,
    'minesweeper': 0.1,
    'guess_country': 0.0010,
    'guess_meme': 0.0010,
    'guess_language': 0.0015,
}

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
    return state

def minesweeper_active(cid, user_id):
    game = _mine_games.get(_mine_key(cid, user_id))
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
        face, header_color = '😎', (30, 150, 60)
    elif game.get('done'):
        face, header_color = '💥', (200, 40, 40)
    else:
        face, header_color = '🙂', (30, 30, 30)

    # --- Header LCD-style: số bom còn lại + kích thước + mặt cười ---
    draw.rounded_rectangle([_MINE_PAD, 8, _MINE_PAD + 78, 8 + 28], radius=6, fill=(15, 15, 15))
    draw.text((_MINE_PAD + 10, 12), f'💣{max(0, remaining_bombs):03d}', font=header_font, fill=(255, 60, 60))
    size_label = f'{rows}x{cols}'
    draw.text((w - _MINE_PAD - len(size_label) * 10 - 6, 12), size_label, font=coord_font, fill=(90, 90, 90))
    draw.text((w // 2 - 12, 8), face, font=header_font, fill=header_color)

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
MEME_MAX_GUESSES = 6
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
    _meme_games[_meme_key(cid, user_id)] = {
        'name': entry['name'],
        'url': entry['url'],
        'guesses': [],
        'revealed_letters': 0,
        'done': False,
        'won': False,
    }
    return entry

def guess_meme_active(cid, user_id):
    game = _meme_games.get(_meme_key(cid, user_id))
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
    """Trả (ok, reason, correct, done, won, answer)."""
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

    # lộ thêm ~1/6 số chữ cái mỗi lần đoán sai
    total_letters = sum(1 for c in game['name'] if c.isalnum())
    step = max(1, total_letters // MEME_MAX_GUESSES)
    game['revealed_letters'] = min(total_letters, game['revealed_letters'] + step)

    done = len(game['guesses']) >= MEME_MAX_GUESSES
    game['done'] = done
    game['won'] = False
    answer = game['name'] if done else None
    return (True, None, False, done, False, answer)


# ============================================================
# 🈴 GUESS-LANGUAGE — đoán loại chữ viết/ngôn ngữ, 15 giây/lượt
# ============================================================
_lang_games = {}  # key: (channel_id, user_id) -> state
LANGUAGE_TIME_LIMIT = 15  # giây

SCRIPT_DATA = [
    {'sample': 'Xin chào, thế giới!', 'answer': 'Chữ Latinh (Latin)',
     'note': 'Bảng chữ cái Latin (ABC...) — hệ chữ phổ biến nhất thế giới, dùng cho tiếng Việt, Anh, Pháp...'},
    {'sample': '你好，世界！', 'answer': 'Chữ Hán (Trung Quốc)',
     'note': 'Chữ tượng hình, mỗi ký tự thường mang một nghĩa riêng, dùng ở Trung Quốc, Đài Loan.'},
    {'sample': 'こんにちは世界', 'answer': 'Chữ Nhật (Kana/Kanji)',
     'note': 'Tiếng Nhật kết hợp Hiragana, Katakana (chữ mềm/cứng) và Kanji (chữ Hán mượn).'},
    {'sample': '안녕하세요 세계', 'answer': 'Chữ Hàn (Hangul)',
     'note': 'Hangul do vua Sejong sáng tạo thế kỷ 15, các nét ghép thành khối vuông.'},
    {'sample': 'Привет, мир!', 'answer': 'Chữ Kirin (Cyrillic)',
     'note': 'Bảng chữ Kirin (Cyrillic) dùng ở Nga và nhiều nước Đông Âu, Trung Á.'},
    {'sample': 'مرحبا بالعالم', 'answer': 'Chữ Ả Rập (Arabic)',
     'note': 'Viết nối liền từ phải sang trái, dùng ở khối Ả Rập, một phần Trung Đông.'},
    {'sample': 'שלום עולם', 'answer': 'Chữ Do Thái (Hebrew)',
     'note': 'Cũng viết từ phải sang trái, dùng cho tiếng Hebrew ở Israel.'},
    {'sample': 'สวัสดีชาวโลก', 'answer': 'Chữ Thái (Thai)',
     'note': 'Chữ Thái không có khoảng cách giữa các từ trong câu, có dấu thanh phía trên/dưới.'},
    {'sample': 'नमस्ते दुनिया', 'answer': 'Chữ Devanagari (Hindi)',
     'note': 'Devanagari có nét ngang nối phía trên chữ, dùng cho tiếng Hindi, Phạn ở Ấn Độ.'},
    {'sample': 'Γειά σου Κόσμε', 'answer': 'Chữ Hy Lạp (Greek)',
     'note': 'Chữ Hy Lạp là nguồn gốc của cả bảng chữ Latin lẫn Kirin.'},
    {'sample': 'Γεια σας κόσμε', 'answer': 'Chữ Hy Lạp (Greek)',
     'note': 'Chữ Hy Lạp là nguồn gốc của cả bảng chữ Latin lẫn Kirin.'},
    {'sample': 'สวัสดีครับ', 'answer': 'Chữ Thái (Thai)',
     'note': 'Chữ Thái không có khoảng cách giữa các từ trong câu, có dấu thanh phía trên/dưới.'},
]

def _lang_key(cid, user_id):
    return (cid, user_id)

def guess_language_start(cid, user_id):
    """Trả (entry, choices) — choices là list 4 đáp án đã xáo trộn, có đúng 1 đáp án đúng."""
    entry = random.choice(SCRIPT_DATA)
    wrong_pool = list({e['answer'] for e in SCRIPT_DATA if e['answer'] != entry['answer']})
    sample_size = min(3, len(wrong_pool))
    wrongs = random.sample(wrong_pool, sample_size)
    choices = wrongs + [entry['answer']]
    random.shuffle(choices)
    correct_index = choices.index(entry['answer'])
    _lang_games[_lang_key(cid, user_id)] = {
        'entry': entry,
        'choices': choices,
        'correct_index': correct_index,
        'done': False,
        'created_at': time.time(),
    }
    return entry, choices

def guess_language_active(cid, user_id):
    game = _lang_games.get(_lang_key(cid, user_id))
    return game is not None and not game['done']

def guess_language_end(cid, user_id):
    _lang_games.pop(_lang_key(cid, user_id), None)

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

