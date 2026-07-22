import random
import io
import time
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import urllib.request
import urllib.parse
import json
import chess  # pip install chess
from PIL import Image, ImageDraw, ImageFont

# Pool riêng để ghi Firestore chạy nền (fire-and-forget), không chặn bot khi mạng
# chậm. Ghi lên Firestore luôn được gọi từ hàm sync (add_aura, chess_hint, set_piece_theme...)
# nên không thể await trực tiếp — thay vào đó đẩy qua thread, RAM cache đã cập nhật
# ngay trước đó nên user không phải chờ, kể cả khi Firestore rớt mạng vài giây.
_firestore_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="firestore-save")

# ============ FIRESTORE (lưu Aura + Elo bền vĩnh viễn, sống sót qua redeploy) ============
# File JSON cũ (aura_data.json, chess_elo.json) BAY MẤT mỗi lần Render redeploy vì
# container bị tạo lại từ đầu — filesystem không persist qua lần update code.
# Firestore tách hẳn khỏi container nên dữ liệu luôn còn dù deploy bao nhiêu lần.
#
# Cách hoạt động: đọc Firestore 1 lần lúc bot khởi động, nạp hết vào RAM (_aura_cache,
# _elo_cache) để mọi lệnh đọc tức thì không cần chờ mạng. Mỗi lần ghi thì cập nhật RAM
# ngay + đẩy lên Firestore. Nếu Firestore lỗi kết nối, bot vẫn chạy bình thường bằng
# RAM cache (không crash), chỉ in log cảnh báo.
_firestore_db = None
try:
    import firebase_admin
    from firebase_admin import credentials, firestore

    _cred_json = os.environ.get("FIREBASE_CREDENTIALS")
    if _cred_json:
        cred = credentials.Certificate(json.loads(_cred_json))
        firebase_admin.initialize_app(cred)
        _firestore_db = firestore.client()
        print("[firestore] Đã kết nối Firestore thành công.")
    else:
        print("[firestore] Chưa có biến môi trường FIREBASE_CREDENTIALS — dùng RAM/file JSON tạm thời.")
except Exception as e:
    print(f"[firestore] Không kết nối được Firestore, dùng RAM/file JSON tạm thời: {e!r}")


def _firestore_load_collection(collection_name, fallback_file):
    """Đọc toàn bộ 1 collection Firestore vào dict {user_id: data}.
    Nếu Firestore không sẵn sàng, đọc từ file JSON cũ để không mất dữ liệu đang có."""
    if _firestore_db is not None:
        try:
            docs = _firestore_db.collection(collection_name).stream()
            return {int(doc.id): doc.to_dict() for doc in docs}
        except Exception as e:
            print(f"[firestore] Lỗi đọc collection '{collection_name}': {e!r}")

    try:
        with open(fallback_file, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _firestore_save_doc_blocking(collection_name, user_id, data):
    """Phần ghi Firestore thật sự (chạy trong thread riêng, xem _firestore_save_doc)."""
    if _firestore_db is None:
        return
    try:
        _firestore_db.collection(collection_name).document(str(user_id)).set(data)
    except Exception as e:
        print(f"[firestore] Lỗi ghi '{collection_name}/{user_id}': {e!r}")


def _firestore_save_doc(collection_name, user_id, data):
    """Ghi 1 document lên Firestore — KHÔNG chờ kết quả (fire-and-forget qua thread
    pool riêng). RAM cache đã được cập nhật trước khi hàm này được gọi, nên chỗ gọi
    không cần chờ Firestore mới coi là 'đã lưu'. Quan trọng: nếu gọi .set() trực tiếp
    ở đây (đồng bộ) thì mọi callback Discord — kể cả không liên quan gì tới Firestore —
    sẽ bị đơ chung vì tất cả chạy trên cùng 1 event loop, dẫn tới 'Tương tác không
    thành công' do quá 3s không phản hồi kịp."""
    if _firestore_db is None:
        return
    _firestore_executor.submit(_firestore_save_doc_blocking, collection_name, user_id, data)


# ============ TIỀN TỆ AURA ============
AURA_FILE = "aura_data.json"  # fallback khi chưa cấu hình Firestore
AURA_ICON = "<:mango:1529287058072408195>"

_aura_cache = {uid: d.get("balance", 0) for uid, d in _firestore_load_collection("aura", AURA_FILE).items()}


def get_aura(user_id):
    return _aura_cache.get(user_id, 0)


def add_aura(user_id, amount):
    """Cộng (hoặc trừ nếu amount âm) Aura cho 1 người. Cho phép âm. Trả về số dư mới."""
    new_balance = get_aura(user_id) + amount
    _aura_cache[user_id] = new_balance
    _firestore_save_doc("aura", user_id, {"balance": new_balance})
    return new_balance

# ============ FOLK VALLEY RANKING (dùng chung cho flag) ============
def folk_valley_rank(score, total=5):
    if score <= 1:
        return ("🐓 GÀ",
            "Con gà mổ lúa cũng đoán giỏi hơn thế này.\n*\"Gieo hạt sai mùa // rồi trách đất không màu mỡ.\"*",
            0x8B5E3C)
    elif score == 2:
        return ("🌽 TẬP SỰ ĐỒNG QUÊ",
            "Còn non như bắp mới trổ, nhưng có tương lai.\n*\"Cày chưa hết ruộng // mà đã mơ mùa gặt.\"*",
            0xD4A017)
    elif score == 3:
        return ("🌾 ỔN ÁP",
            "Không tệ! Cỏ trong Folk Valley cũng gật gù đồng ý.\n*\"Đo hai lần, đoán một lần // rồi hỏi con bò xem nó nhớ gì.\"*",
            0x6FA030)
    elif score == 4:
        return ("🚜 LÃO NÔNG THẦN TỐC",
            "Gần chạm đỉnh! Kho thóc đang thì thầm tên bạn.\n*\"Nếu chưa hỏng thì cũng nên nâng cấp phần mềm chuồng trại.\"*",
            0x3F7D20)
    else:
        return ("✨ THẦN THÁNH FOLK VALLEY",
            "Hoàn hảo. Đến chim trong Folk Valley cũng ngừng hót để cúi đầu.\n*\"Gốc rễ vẫn nhớ // dù dữ liệu đã đổi mùa.\"*",
            0xFFD700)


# ============ WORDLE ============
WORDS = [
    "apple", "beach", "chair", "dance", "eagle", "flame", "grape",
    "house", "input", "juice", "knife", "lemon", "mango", "night",
    "ocean", "piano", "queen", "river", "stone", "table", "unity",
    "voice", "water", "youth", "zebra", "bread", "cloud", "dream",
    "fruit", "glass", "heart", "image", "koala", "light", "music",
    "novel", "orbit", "peach", "quiet", "robot", "smile", "trust",
    "value", "world", "brave", "crown", "delta", "earth", "faith", "giant",
]
WORDLE_MAX_GUESSES = 6
_wordle_games = {}  # {channel_id: {"word", "guesses"}}


def wordle_active(cid):
    return cid in _wordle_games


def wordle_start(cid):
    word = random.choice(WORDS)
    _wordle_games[cid] = {"word": word, "guesses": 0}
    return word


def wordle_word(cid):
    return _wordle_games[cid]["word"]


def wordle_end(cid):
    _wordle_games.pop(cid, None)


def wordle_check(cid, guess):
    game = _wordle_games[cid]
    word = game["word"]
    guess = guess.lower()
    result = []
    chars = list(word)

    for i, ch in enumerate(guess):
        if ch == word[i]:
            result.append("🟩")
            chars[i] = None
        else:
            result.append(None)

    for i, ch in enumerate(guess):
        if result[i] is not None:
            continue
        if ch in chars:
            result[i] = "🟨"
            chars[chars.index(ch)] = None
        else:
            result[i] = "⬜"

    game["guesses"] += 1
    correct = guess == word
    done = game["guesses"] >= WORDLE_MAX_GUESSES
    return "".join(result), correct, done


# ============ ĐOÁN CỜ (4 độ khó) ============
FLAG_EASY = {"vietnam": "vn", "japan": "jp", "china": "cn", "usa": "us", "united states": "us",
    "france": "fr", "germany": "de", "italy": "it", "spain": "es", "uk": "gb",
    "united kingdom": "gb", "brazil": "br", "canada": "ca", "russia": "ru", "india": "in",
    "korea": "kr", "australia": "au", "mexico": "mx", "egypt": "eg", "thailand": "th"}

FLAG_MEDIUM = {"portugal": "pt", "netherlands": "nl", "belgium": "be", "switzerland": "ch",
    "sweden": "se", "norway": "no", "poland": "pl", "greece": "gr", "turkey": "tr",
    "indonesia": "id", "malaysia": "my", "philippines": "ph", "singapore": "sg",
    "argentina": "ar", "chile": "cl", "colombia": "co", "saudi arabia": "sa",
    "south africa": "za", "new zealand": "nz", "ukraine": "ua"}

FLAG_HARD = {"finland": "fi", "denmark": "dk", "austria": "at", "czech republic": "cz",
    "hungary": "hu", "romania": "ro", "iceland": "is", "peru": "pe", "cuba": "cu",
    "nigeria": "ng", "pakistan": "pk", "bangladesh": "bd", "iran": "ir", "iraq": "iq",
    "israel": "il", "uae": "ae", "morocco": "ma", "kenya": "ke", "ethiopia": "et", "myanmar": "mm"}

FLAG_INSANE = {"bhutan": "bt", "brunei": "bn", "eswatini": "sz", "lesotho": "ls",
    "tuvalu": "tv", "nauru": "nr", "kiribati": "ki", "palau": "pw", "andorra": "ad",
    "liechtenstein": "li", "san marino": "sm", "monaco": "mc", "moldova": "md",
    "tajikistan": "tj", "kyrgyzstan": "kg", "turkmenistan": "tm", "djibouti": "dj",
    "comoros": "km", "suriname": "sr", "guyana": "gy"}

FLAG_POOLS = {"easy": FLAG_EASY, "medium": FLAG_MEDIUM, "hard": FLAG_HARD, "insane": FLAG_INSANE}
ROUNDS_PER_GAME = 5
_flag_games = {}  # {channel_id: {"pool", "round", "score", "country"}}


def flag_active(cid):
    return cid in _flag_games


def flag_start(cid, difficulty):
    _flag_games[cid] = {"pool": FLAG_POOLS[difficulty], "round": 0, "score": 0, "country": None}
    return flag_next(cid)


def flag_next(cid):
    game = _flag_games[cid]
    if game["round"] >= ROUNDS_PER_GAME:
        return None
    country = random.choice(list(game["pool"].keys()))
    game["country"] = country
    game["round"] += 1
    return f"https://flagcdn.com/w320/{game['pool'][country]}.png"


def flag_check(cid, guess):
    game = _flag_games[cid]
    correct = guess.strip().lower() == game["country"]
    if correct:
        game["score"] += 1
    return correct, game["round"] < ROUNDS_PER_GAME


def flag_answer(cid):
    return _flag_games[cid]["country"]


def flag_progress(cid):
    g = _flag_games[cid]
    return g["round"], ROUNDS_PER_GAME, g["score"]


def flag_end(cid):
    _flag_games.pop(cid, None)


# ============ /whatuinto — bói vui ngẫu nhiên ============
WHATUINTO_LABELS = [
    ("Femboy", "Mềm mại bên ngoài, hỗn loạn bên trong. Bạn là hiện thân của \"tưởng vậy mà không phải vậy\"."),
    ("Tomboy", "Năng lượng xắn tay áo, không ngại dơ. Bạn chọn hành động thay vì drama."),
    ("Tsundere", "\"Không phải tôi thích đâu nhé!\" — trong khi tay đã làm sẵn hết rồi."),
    ("Mommy ASMR", "Giọng nói của bạn có thể ru cả server ngủ. Năng lượng chăm sóc tối thượng."),
    ("Yandere ASMR", "Ngọt ngào đến đáng ngờ. Ai chọc bạn giận thì... thôi khỏi nói."),
    ("Vợ hàng xóm", "Huyền thoại khu phố, ai cũng biết tên nhưng chẳng ai dám hỏi thẳng."),
    ("Folk Valley", "Bạn thuộc về nơi cỏ cây biết nói và gà biết deploy code."),
    ("Scambodia", "Chuyên gia lừa đảo... tình cảm. Cẩn thận, coi chừng mất ví lẫn mất tim."),
]


def whatuinto_roll():
    """Trả về (label, caption, percent)"""
    label, caption = random.choice(WHATUINTO_LABELS)
    percent = random.randint(60, 99)
    return label, caption, percent


# ============ CỜ CARO (Tic-Tac-Toe) vs Bot ============
# Bàn cờ: list 9 phần tử, "" = trống, "X" = người chơi, "O" = bot
_ttt_games = {}  # {channel_id: {"board": list, "player_id": int, "turn": "X"/"O"}}

TTT_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),  # hàng ngang
    (0, 3, 6), (1, 4, 7), (2, 5, 8),  # hàng dọc
    (0, 4, 8), (2, 4, 6),             # chéo
]


def ttt_active(cid):
    return cid in _ttt_games


def ttt_start(cid, player_id):
    _ttt_games[cid] = {"board": [""] * 9, "player_id": player_id, "turn": "X"}


def ttt_end(cid):
    _ttt_games.pop(cid, None)


def ttt_board(cid):
    return _ttt_games[cid]["board"]


def _ttt_winner(board):
    for a, b, c in TTT_LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    if "" not in board:
        return "draw"
    return None


def _ttt_minimax(board, is_bot_turn, depth=0):
    """Bot = O (maximize), Người = X (minimize).
    Có tính độ sâu (thắng nhanh > thắng chậm) và random hoá giữa các nước ngang điểm
    để bot chơi đa dạng hơn, tránh việc người chơi thuộc lòng 1 nước đi để hoà mãi."""
    winner = _ttt_winner(board)
    if winner == "O":
        return 10 - depth, None
    if winner == "X":
        return depth - 10, None
    if winner == "draw":
        return 0, None

    moves = [i for i in range(9) if board[i] == ""]
    mark = "O" if is_bot_turn else "X"
    scored = []
    for m in moves:
        board[m] = mark
        score, _ = _ttt_minimax(board, not is_bot_turn, depth + 1)
        board[m] = ""
        scored.append((score, m))

    best = max(scored)[0] if is_bot_turn else min(scored)[0]
    best_moves = [m for s, m in scored if s == best]
    return best, random.choice(best_moves)


def ttt_player_move(cid, index):
    """Người chơi đánh vào ô index. Trả về (hợp lệ: bool, kết quả: None/"X"/"O"/"draw")"""
    game = _ttt_games[cid]
    board = game["board"]
    if board[index] != "" or game["turn"] != "X":
        return False, None

    board[index] = "X"
    result = _ttt_winner(board)
    if result:
        return True, result

    game["turn"] = "O"
    return True, None


def ttt_bot_move(cid):
    """Bot đánh nước đi tối ưu. Trả về kết quả: None/"X"/"O"/"draw" """
    game = _ttt_games[cid]
    board = game["board"]
    _, move = _ttt_minimax(board, True)
    board[move] = "O"
    result = _ttt_winner(board)
    game["turn"] = "X"
    return result


# ============ CỜ VUA vs Bot ============
# Dùng thư viện "chess" để quản lý luật + tính hợp lệ nước đi.
# Bot chỉ đánh giá nông 1 nước (vật chất + chiếu) thay vì minimax đệ quy sâu,
# để giữ CPU cực thấp — phù hợp máy chủ 0.1 CPU.

_chess_games = {}  # {channel_id: {"board", "is_pvp", "player_id"/"white_id"+"black_id", "player_color", "last_move_at"}}
_PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
CHESS_STALE_SECONDS = 30 * 60  # ván không hoạt động >30 phút coi như "ma", tự dọn


def _touch(cid):
    if cid in _chess_games:
        _chess_games[cid]["last_move_at"] = time.time()


def chess_touch(cid):
    """Làm mới thời điểm hoạt động cuối — gọi ở MỌI tương tác trong ván (chọn quân, xin
    gợi ý, xem hướng dẫn...), không chỉ lúc đi xong nước, để tránh bị coi là 'ván ma'
    và tự xoá dù người chơi vẫn đang thao tác."""
    _touch(cid)


def chess_active(cid):
    """Kiểm tra có ván đang chạy không. Nếu ván tồn tại nhưng đã quá cũ
    (bot từng restart/crash giữa chừng làm state bị kẹt) thì tự động dọn và coi như không có ván."""
    game = _chess_games.get(cid)
    if game is None:
        return False
    if time.time() - game.get("last_move_at", 0) > CHESS_STALE_SECONDS:
        _chess_games.pop(cid, None)
        return False
    return True


def chess_force_reset(cid):
    """Xóa cưỡng bức trạng thái ván cờ trong kênh này, dùng khi bot báo 'có ván' nhưng thực ra không có."""
    existed = cid in _chess_games
    _chess_games.pop(cid, None)
    _chess_invites.pop(cid, None)
    _chess_draw_offers.pop(cid, None)
    return existed


def chess_start(cid, player_id, bot_elo=1200):
    """Bắt đầu ván vs Bot — người chơi luôn cầm Trắng. bot_elo chọn độ khó (800/1200/1600)."""
    _chess_games[cid] = {
        "board": chess.Board(), "is_pvp": False,
        "player_id": player_id, "player_color": chess.WHITE,
        "last_move_at": time.time(), "bot_elo": bot_elo,
        "last_move": None,
    }


def chess_start_pvp(cid, white_id, black_id):
    """Bắt đầu ván PvP giữa 2 người thật"""
    _chess_games[cid] = {
        "board": chess.Board(), "is_pvp": True,
        "white_id": white_id, "black_id": black_id,
        "last_move_at": time.time(),
        "last_move": None,
    }


def chess_is_pvp(cid):
    return _chess_games[cid]["is_pvp"]


def chess_current_turn_id(cid):
    """Trả về user_id của người cần đi nước tiếp theo (chỉ dùng cho PvP)"""
    game = _chess_games[cid]
    board = game["board"]
    return game["white_id"] if board.turn == chess.WHITE else game["black_id"]


def chess_end(cid):
    _chess_games.pop(cid, None)
    _chess_draw_offers.pop(cid, None)


def chess_player_id(cid):
    """Chỉ dùng cho chế độ vs Bot"""
    return _chess_games[cid]["player_id"]


# ============ HỆ THỐNG ELO (giống chess.com) ============
DEFAULT_ELO = 800
K_FACTOR = 32
HINT_ELO_PENALTY = 100

# 3 mức độ khó bot — điều chỉnh xác suất bot chọn nước NGẪU NHIÊN thay vì nước tốt nhất.
# Elo càng cao thì bot càng ít đi ngẫu nhiên (chơi "chuẩn" hơn).
BOT_LEVELS = {
    800: {"label": "🟢 Dễ", "random_chance": 0.5},
    1200: {"label": "🟡 Vừa", "random_chance": 0.15},
    1600: {"label": "🔴 Khó", "random_chance": 0.0},
}

ELO_FILE = "chess_elo.json"  # fallback khi chưa cấu hình Firestore

_elo_cache = {uid: d.get("elo", DEFAULT_ELO) for uid, d in _firestore_load_collection("elo", ELO_FILE).items()}


def get_elo(user_id):
    return _elo_cache.get(user_id, DEFAULT_ELO)


def _expected_score(elo_a, elo_b):
    return 1 / (1 + 10 ** ((elo_b - elo_a) / 400))


def update_elo(id_a, elo_a, id_b, elo_b, score_a):
    """score_a: 1 = A thắng, 0.5 = hòa, 0 = A thua. Trả về (elo_a_mới, elo_b_mới, thay_đổi_a, thay_đổi_b)"""
    expected_a = _expected_score(elo_a, elo_b)
    expected_b = 1 - expected_a
    score_b = 1 - score_a

    delta_a = round(K_FACTOR * (score_a - expected_a))
    delta_b = round(K_FACTOR * (score_b - expected_b))

    new_a = max(100, elo_a + delta_a)
    new_b = max(100, elo_b + delta_b)

    if id_a is not None:
        _elo_cache[id_a] = new_a
        _firestore_save_doc("elo", id_a, {"elo": new_a})
    if id_b is not None:
        _elo_cache[id_b] = new_b
        _firestore_save_doc("elo", id_b, {"elo": new_b})

    return new_a, new_b, delta_a, delta_b


def apply_hint_penalty(user_id):
    """Trừ Elo khi dùng gợi ý. Trả về Elo mới."""
    current = get_elo(user_id)
    new_elo = max(100, current - HINT_ELO_PENALTY)
    _elo_cache[user_id] = new_elo
    _firestore_save_doc("elo", user_id, {"elo": new_elo})
    return new_elo


PIECE_NAME_VN = {
    chess.PAWN: "Tốt", chess.KNIGHT: "Mã", chess.BISHOP: "Tượng",
    chess.ROOK: "Xe", chess.QUEEN: "Hậu", chess.KING: "Vua",
}


def chess_from_options(cid):
    """Danh sách (giá_trị_ô, nhãn) các quân đang có nước đi hợp lệ — để đổ vào dropdown"""
    board = _chess_games[cid]["board"]
    seen = {}
    for move in board.legal_moves:
        if move.from_square not in seen:
            piece = board.piece_at(move.from_square)
            name = PIECE_NAME_VN[piece.piece_type]
            seen[move.from_square] = f"{name} {chess.square_name(move.from_square)}"
    return [(chess.square_name(sq), label) for sq, label in seen.items()]


def chess_to_options(cid, from_square_name):
    """Danh sách (giá_trị_ô, nhãn) các ô có thể đi tới từ 1 quân — để đổ vào dropdown.
    Phong cấp luôn tự động thành Hậu cho đơn giản."""
    board = _chess_games[cid]["board"]
    from_sq = chess.parse_square(from_square_name)
    options = []
    for move in board.legal_moves:
        if move.from_square != from_sq:
            continue
        if move.promotion and move.promotion != chess.QUEEN:
            continue  # bỏ phong cấp khác Hậu để danh sách gọn
        to_name = chess.square_name(move.to_square)
        captured = board.piece_at(move.to_square)
        if captured:
            label = f"{to_name} (ăn {PIECE_NAME_VN[captured.piece_type]})"
        elif board.is_en_passant(move):
            label = f"{to_name} (ăn Tốt qua đường)"
        else:
            label = to_name
        options.append((to_name, label))
    return options


def chess_make_move(cid, from_square_name, to_square_name):
    """Thực hiện nước đi được chọn từ dropdown.
    Trả về (True, outcome, annotation) nếu đi thành công (outcome=None nếu ván tiếp tục,
    annotation là '!!'/'??'/None), hoặc (False, None, None) nếu nước đi không còn hợp lệ
    (VD: bàn cờ đã đổi giữa lúc chọn)."""
    game = _chess_games[cid]
    board = game["board"]
    from_sq = chess.parse_square(from_square_name)
    to_sq = chess.parse_square(to_square_name)
    move = next(
        (m for m in board.legal_moves
         if m.from_square == from_sq and m.to_square == to_sq
         and not (m.promotion and m.promotion != chess.QUEEN)),
        None,
    )
    if move is None:
        return False, None, None

    mover_color = board.turn
    scored = _score_all_moves(board, mover_color)
    annotation = _annotate_move(board, move, mover_color, scored)

    board.push(move)
    game["last_move"] = move
    _touch(cid)
    return True, board.outcome(claim_draw=True), annotation


# ============ VẼ BÀN CỜ (PIL) + CUSTOM THEME QUÂN CỜ THEO TỪNG USER ============
# Quay lại PIL thay vì chess.svg+cairosvg vì chess.svg KHÔNG hỗ trợ ảnh quân custom
# (chỉ vẽ path SVG built-in cố định) — không có cách nào chèn ảnh riêng vào đó.
# Dùng PIL cho MỌI trường hợp (có theme hay không) để đồng bộ 1 code path, đồng thời
# bỏ được phụ thuộc cairosvg/libcairo2/Docker, quay về deploy Python buildpack bình
# thường trên Render — nhẹ hơn cho máy 0.1 CPU / 256MB RAM.
_SQUARE_PX = 60
_BOARD_PX = _SQUARE_PX * 8
_LIGHT = (240, 217, 181)
_DARK = (181, 136, 99)
_LASTMOVE_LIGHT = (205, 210, 106)
_LASTMOVE_DARK = (170, 162, 58)

_PIECE_UNICODE = {
    (chess.PAWN, True): "♙", (chess.KNIGHT, True): "♘", (chess.BISHOP, True): "♗",
    (chess.ROOK, True): "♖", (chess.QUEEN, True): "♕", (chess.KING, True): "♔",
    (chess.PAWN, False): "♟", (chess.KNIGHT, False): "♞", (chess.BISHOP, False): "♝",
    (chess.ROOK, False): "♜", (chess.QUEEN, False): "♛", (chess.KING, False): "♚",
}

# Custom quân cờ theo TỪNG QUÂN riêng lẻ: user dùng /custom_chess chọn 1 trong 12
# quân (qua dropdown) rồi dán link ảnh CHỈ CHO QUÂN ĐÓ (không cần sprite sheet cả bộ
# theo layout cố định như trước). Mỗi user build bộ quân của mình dần dần, quân nào
# chưa đặt thì tự rơi về Unicode mặc định.
_PIECE_LETTER = {chess.KING: "K", chess.QUEEN: "Q", chess.ROOK: "R",
                 chess.BISHOP: "B", chess.KNIGHT: "N", chess.PAWN: "P"}
_PIECE_KEY_INFO = {}  # {"K_w": (chess.KING, True), ...}
for _pt, _letter in _PIECE_LETTER.items():
    _PIECE_KEY_INFO[f"{_letter}_w"] = (_pt, chess.WHITE)
    _PIECE_KEY_INFO[f"{_letter}_b"] = (_pt, chess.BLACK)

PIECE_KEY_LABELS = {
    "K_w": "Vua Trắng", "Q_w": "Hậu Trắng", "R_w": "Xe Trắng", "B_w": "Tượng Trắng",
    "N_w": "Mã Trắng", "P_w": "Tốt Trắng",
    "K_b": "Vua Đen", "Q_b": "Hậu Đen", "R_b": "Xe Đen", "B_b": "Tượng Đen",
    "N_b": "Mã Đen", "P_b": "Tốt Đen",
}

PIECE_THEME_FILE = "chess_piece_themes.json"  # fallback khi chưa cấu hình Firestore
# {user_id: {"K_w": url, "Q_b": url, ...}} — chỉ lưu key của quân đã custom
_piece_theme_cache = {uid: d for uid, d in _firestore_load_collection("chess_piece_theme", PIECE_THEME_FILE).items()}
_piece_sprite_cache = {}  # {url: PIL.Image hoặc None} — cache ảnh đã tải, tránh tải lại mỗi lần vẽ bàn cờ


def _piece_key(piece_type, color):
    return f"{_PIECE_LETTER[piece_type]}_{'w' if color == chess.WHITE else 'b'}"


def get_piece_theme_url(user_id, piece_type, color):
    d = _piece_theme_cache.get(user_id)
    return d.get(_piece_key(piece_type, color)) if d else None


def set_piece_theme(user_id, key, url):
    """key dạng 'K_w', 'Q_b'... (xem PIECE_KEY_LABELS)."""
    d = _piece_theme_cache.setdefault(user_id, {})
    d[key] = url
    _firestore_save_doc("chess_piece_theme", user_id, d)


def clear_piece_theme(user_id, key=None):
    """key=None -> xóa toàn bộ bộ quân custom của user. Trả về True nếu có gì bị xóa."""
    d = _piece_theme_cache.get(user_id)
    if not d:
        return False
    if key is None:
        _piece_theme_cache.pop(user_id, None)
        _firestore_save_doc("chess_piece_theme", user_id, {})
        return True
    existed = d.pop(key, None) is not None
    _firestore_save_doc("chess_piece_theme", user_id, d)
    return existed


def _load_piece_sprite(url):
    """Tải 1 ảnh quân cờ đơn từ URL, resize về 60x60 RGBA.
    Trả về PIL.Image hoặc None nếu tải/đọc lỗi. Cache theo URL."""
    if url in _piece_sprite_cache:
        return _piece_sprite_cache[url]
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            raw = resp.read()
        sprite = Image.open(io.BytesIO(raw)).convert("RGBA").resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
    except Exception as e:
        print(f"[custom_chess] Không tải/đọc được ảnh từ {url}: {e!r}")
        _piece_sprite_cache[url] = None
        return None
    _piece_sprite_cache[url] = sprite
    return sprite


def preview_piece_sprite(url):
    """Dùng khi user vừa /custom_chess 1 link — ép tải mới để kiểm tra link sống không."""
    _piece_sprite_cache.pop(url, None)
    return _load_piece_sprite(url)


def piece_theme_preview_image(user_id):
    """Dựng 1 ảnh lưới 2x6 hiện toàn bộ 12 quân: quân đã custom thì hiện ảnh đã lưu,
    quân chưa custom thì hiện Unicode mặc định — để user xem tổng quan bộ quân của mình."""
    pad = 4
    label_h = 16
    cell = _SQUARE_PX
    cols, rows = 6, 2
    w = cols * (cell + pad) + pad
    h = rows * (cell + pad + label_h) + pad
    img = Image.new("RGBA", (w, h), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    font = _chess_font(11)
    names = {chess.KING: "Vua", chess.QUEEN: "Hậu", chess.ROOK: "Xe",
             chess.BISHOP: "Tượng", chess.KNIGHT: "Mã", chess.PAWN: "Tốt"}
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
            label = f"{names[piece_type]} {'Trắng' if color == chess.WHITE else 'Đen'}"
            draw.text((x + cell / 2, y + cell + 2), label, font=font, fill="white", anchor="ma")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _chess_font(size):
    for path in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                 "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
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


_DEFAULT_PIECE_SPRITE_CACHE = {}  # {(piece_type, color): PIL.Image} — vẽ 1 lần, dùng lại mãi


_PIECE_FILE = {
    chess.PAWN: "P", chess.ROOK: "R", chess.KNIGHT: "N",
    chess.BISHOP: "B", chess.QUEEN: "Q", chess.KING: "K",
}
_PIECES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "pieces")


def default_piece_sprite(piece_type, color):
    """Ảnh quân cờ mặc định khi user chưa /custom_chess — load PNG có sẵn trong
    assets/pieces/ (vd: wP.png, bN.png...) thay vì vẽ vector, resize 1 lần rồi
    cache theo (piece_type, color) trong RAM — mở file chỉ tốn 1 lần cho cả
    vòng đời bot, các lượt vẽ bàn cờ sau chỉ paste ảnh cache, gần như free CPU."""
    key = (piece_type, color)
    if key in _DEFAULT_PIECE_SPRITE_CACHE:
        return _DEFAULT_PIECE_SPRITE_CACHE[key]

    fname = f"{'w' if color == chess.WHITE else 'b'}{_PIECE_FILE[piece_type]}.png"
    path = os.path.join(_PIECES_DIR, fname)
    sprite = Image.open(path).convert("RGBA").resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
    _DEFAULT_PIECE_SPRITE_CACHE[key] = sprite
    return sprite


async def chess_preload_sprites(cid):
    """Tải trước (async, không chặn event loop) mọi ảnh custom quân cờ cần dùng để vẽ
    ván này. GỌI HÀM NÀY (await) TRƯỚC chess_board_image() ở mọi nơi vẽ bàn cờ.
    _load_piece_sprite dùng urllib đồng bộ (network I/O) — nếu gọi thẳng trong
    chess_board_image() (hàm sync) sẽ đóng băng toàn bộ bot vài giây mỗi lần vẽ,
    khiến Discord báo 'Tương tác không thành công' do quá 3s không phản hồi được.
    Chạy qua asyncio.to_thread để network I/O nằm ở thread riêng, loop chính rảnh
    để trả lời interaction khác. Đã cache theo URL nên các lần vẽ sau gần như free."""
    game = _chess_games.get(cid)
    if game is None:
        return
    board = game["board"]
    white_id = game["player_id"] if not game["is_pvp"] else game["white_id"]
    black_id = None if not game["is_pvp"] else game["black_id"]
    owner_id = {chess.WHITE: white_id, chess.BLACK: black_id}

    urls = set()
    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece is None:
            continue
        uid = owner_id[piece.color]
        url = get_piece_theme_url(uid, piece.piece_type, piece.color) if uid else None
        if url and url not in _piece_sprite_cache:
            urls.add(url)

    for url in urls:
        await asyncio.to_thread(_load_piece_sprite, url)


def chess_board_image(cid):
    """Vẽ bàn cờ ra ảnh PNG bằng PIL. Ô của nước đi gần nhất được tô sáng hơn.
    Mỗi quân dùng ảnh custom riêng (nếu người cầm màu đó đã set qua /custom_chess),
    quân nào chưa custom thì tự rơi về Unicode mặc định — không phải toàn-hoặc-không,
    2 người trong ván PvP có thể có bộ quân custom khác nhau, thậm chí lẫn quân
    custom và quân mặc định trong cùng 1 bộ."""
    game = _chess_games[cid]
    board = game["board"]
    last_move = game.get("last_move")
    lastmove_squares = {last_move.from_square, last_move.to_square} if last_move else set()

    white_id = game["player_id"] if not game["is_pvp"] else game["white_id"]
    black_id = None if not game["is_pvp"] else game["black_id"]
    owner_id = {chess.WHITE: white_id, chess.BLACK: black_id}

    img = Image.new("RGBA", (_BOARD_PX, _BOARD_PX + 24), "white")
    draw = ImageDraw.Draw(img)
    coord_font = _chess_font(14)

    for row in range(8):
        for col in range(8):
            x0, y0 = col * _SQUARE_PX, row * _SQUARE_PX
            sq = chess.square(col, 7 - row)
            is_light = (row + col) % 2 == 0
            if sq in lastmove_squares:
                color = _LASTMOVE_LIGHT if is_light else _LASTMOVE_DARK
            else:
                color = _LIGHT if is_light else _DARK
            draw.rectangle([x0, y0, x0 + _SQUARE_PX, y0 + _SQUARE_PX], fill=color)

            piece = board.piece_at(sq)
            if piece is None:
                continue
            uid = owner_id[piece.color]
            url = get_piece_theme_url(uid, piece.piece_type, piece.color) if uid else None
            sprite = _load_piece_sprite(url) if url else None
            if sprite is None:
                sprite = default_piece_sprite(piece.piece_type, piece.color)
            img.alpha_composite(sprite, (x0, y0))

    for col in range(8):
        draw.text((col * _SQUARE_PX + 4, _BOARD_PX + 4), chr(ord('a') + col), font=coord_font, fill="black")

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG")
    buf.seek(0)
    return buf


def _material_score(board, color):
    score = 0
    for piece_type, value in _PIECE_VALUES.items():
        score += len(board.pieces(piece_type, color)) * value
        score -= len(board.pieces(piece_type, not color)) * value
    return score


# ============ CHẤM ĐIỂM NƯỚC ĐI (dùng chung cho bot chọn nước / gợi ý / gắn nhãn !! ??) ============
# Chỉ đánh giá NÔNG 1 nước (vật chất + chiếu) — không đệ quy minimax sâu — để giữ
# CPU cực thấp (phù hợp máy chủ 0.1 CPU / 256MB RAM). Mọi nơi cần "nước nào tốt nhất"
# đều tái dùng CÙNG 1 lượt chấm điểm này thay vì tự lặp lại, vừa đỡ code vừa đỡ CPU.
def _score_all_moves(board, color):
    """Trả về [(move, điểm), ...] cho toàn bộ nước đi hợp lệ hiện tại, từ góc nhìn `color`."""
    scored = []
    for move in board.legal_moves:
        board.push(move)
        score = 1000 if board.is_checkmate() else _material_score(board, color) + (0.5 if board.is_check() else 0)
        board.pop()
        scored.append((move, score))
    return scored


BRILLIANT_MARGIN = 3   # hơn nước nhì ít nhất giá trị 1 Mã/Tượng -> "!!"
BLUNDER_HANG_VALUE = 5  # sau khi đi, để hở Xe/Hậu cho đối phương ăn miễn phí -> "??"
BLUNDER_MARGIN = 5      # bỏ lỡ phương án tốt hơn ít nhất giá trị 1 Xe -> "??"


def _annotate_move(board, move, color, scored):
    """Gắn nhãn !! (thiên tài) / ?? (ngớ ngẩn) cho nước vừa đi, hoặc None nếu là nước bình thường.
    Tái dùng `scored` đã chấm sẵn (không chấm lại) + nhìn thêm ĐÚNG 1 nước để bắt lỗi thí quân
    miễn phí — vẫn cực nhẹ CPU, không tìm kiếm đệ quy."""
    played_score = next(s for m, s in scored if m == move)
    if played_score >= 900:
        return "!!"  # chiếu bí luôn là nước thiên tài

    scores_desc = sorted((s for _, s in scored), reverse=True)
    best_score = scores_desc[0]
    second_score = scores_desc[1] if len(scores_desc) > 1 else best_score

    if played_score >= best_score and best_score - second_score >= BRILLIANT_MARGIN and best_score > 0:
        return "!!"

    board.push(move)
    hang = 0
    if not board.is_game_over():
        for reply in board.legal_moves:
            captured = board.piece_at(reply.to_square)
            if captured:
                hang = max(hang, _PIECE_VALUES.get(captured.piece_type, 0))
    board.pop()

    if hang >= BLUNDER_HANG_VALUE or best_score - played_score >= BLUNDER_MARGIN:
        return "??"
    return None


def chess_bot_move(cid):
    """Bot đi 1 nước — đánh giá nông (1 ply), rất nhẹ CPU. Độ khó điều chỉnh xác suất
    bot đi bừa thay vì đi nước tốt nhất (Dễ = hay đi bừa, Khó = luôn đi tốt nhất).
    Trả về (outcome, annotation) — annotation là '!!'/'??'/None."""
    game = _chess_games[cid]
    board = game["board"]
    bot_color = not game["player_color"]
    random_chance = BOT_LEVELS[game["bot_elo"]]["random_chance"]

    scored = _score_all_moves(board, bot_color)
    best_score = max(s for _, s in scored)

    if random_chance > 0 and random.random() < random_chance:
        move = random.choice([m for m, _ in scored])
    else:
        move = random.choice([m for m, s in scored if s == best_score])

    annotation = _annotate_move(board, move, bot_color, scored)
    board.push(move)
    game["last_move"] = move
    return board.outcome(claim_draw=True), annotation


def chess_outcome_text(cid, outcome, display_names=None):
    """display_names: dict {True: tên_trắng, False: tên_đen} — chỉ cần cho PvP.
    Trả về text kết quả kèm thay đổi Elo."""
    game = _chess_games[cid]

    if game["is_pvp"]:
        white_id, black_id = game["white_id"], game["black_id"]
        white_elo, black_elo = get_elo(white_id), get_elo(black_id)

        if outcome.winner is None:
            score_white = 0.5
        elif outcome.winner == chess.WHITE:
            score_white = 1
        else:
            score_white = 0

        new_white, new_black, d_white, d_black = update_elo(
            white_id, white_elo, black_id, black_elo, score_white
        )

        white_name = display_names[True] if display_names else f"<@{white_id}>"
        black_name = display_names[False] if display_names else f"<@{black_id}>"
        sign_w = f"+{d_white}" if d_white >= 0 else str(d_white)
        sign_b = f"+{d_black}" if d_black >= 0 else str(d_black)

        if outcome.winner is None:
            result_line = "🤝 Hòa!"
            add_aura(white_id, -150)
            add_aura(black_id, -150)
            aura_line = f"\n\n{AURA_ICON} Hòa cờ: cả hai bị trừ **150 Aura**."
        else:
            winner_id = white_id if outcome.winner == chess.WHITE else black_id
            winner_name = white_name if outcome.winner == chess.WHITE else black_name
            result_line = f"🎉 {winner_name} thắng! Chiếu bí!"
            new_winner_aura = add_aura(winner_id, 100)
            aura_line = f"\n\n{AURA_ICON} {winner_name} nhận **+100 Aura** (số dư: {new_winner_aura})."

        return (
            f"{result_line}\n\n"
            f"⚪ {white_name}: {new_white} Elo ({sign_w})\n"
            f"⚫ {black_name}: {new_black} Elo ({sign_b})"
            f"{aura_line}"
        )

    # --- vs Bot ---
    player_id = game["player_id"]
    player_elo = get_elo(player_id)
    player_color = game["player_color"]

    if outcome.winner is None:
        score_player = 0.5
    else:
        score_player = 1 if outcome.winner == player_color else 0

    new_player_elo, _, d_player, _ = update_elo(player_id, player_elo, None, game["bot_elo"], score_player)
    sign = f"+{d_player}" if d_player >= 0 else str(d_player)

    if outcome.winner is None:
        result_line = "🤝 Hòa!"
    elif score_player == 1:
        result_line = "🎉 Bạn thắng! Bot chịu thua."
    else:
        result_line = "🤖 Bot chiếu bí! Bạn thua rồi."

    return f"{result_line}\n\nElo của bạn: {new_player_elo} ({sign})"


def chess_resign_text(cid, resigner_id, display_names=None):
    """Xử lý đầu hàng — cập nhật Elo tương tự thua ván, trả về text hiển thị."""
    game = _chess_games[cid]

    if game["is_pvp"]:
        white_id, black_id = game["white_id"], game["black_id"]
        white_elo, black_elo = get_elo(white_id), get_elo(black_id)
        score_white = 0 if resigner_id == white_id else 1
        new_white, new_black, d_white, d_black = update_elo(
            white_id, white_elo, black_id, black_elo, score_white
        )
        white_name = display_names[True] if display_names else f"<@{white_id}>"
        black_name = display_names[False] if display_names else f"<@{black_id}>"
        resigner_name = white_name if resigner_id == white_id else black_name
        winner_name = black_name if resigner_id == white_id else white_name
        winner_id = black_id if resigner_id == white_id else white_id
        new_winner_aura = add_aura(winner_id, 100)
        sign_w = f"+{d_white}" if d_white >= 0 else str(d_white)
        sign_b = f"+{d_black}" if d_black >= 0 else str(d_black)
        return (
            f"🏳️ {resigner_name} đã đầu hàng! {winner_name} thắng!\n\n"
            f"⚪ {white_name}: {new_white} Elo ({sign_w})\n"
            f"⚫ {black_name}: {new_black} Elo ({sign_b})\n\n"
            f"{AURA_ICON} {winner_name} nhận **+100 Aura** (số dư: {new_winner_aura})."
        )

    player_id = game["player_id"]
    player_elo = get_elo(player_id)
    new_player_elo, _, d_player, _ = update_elo(player_id, player_elo, None, game["bot_elo"], 0)
    sign = f"+{d_player}" if d_player >= 0 else str(d_player)
    return f"🏳️ Bạn đã đầu hàng! Bot thắng.\n\nElo của bạn: {new_player_elo} ({sign})"


def chess_hint(cid, hinter_id):
    """Gợi ý nước đi tốt nhất theo đánh giá vật chất nông (dùng chung _score_all_moves với bot).
    Trừ Elo người xin gợi ý. Trả về (text_gợi_ý, elo_mới)."""
    game = _chess_games[cid]
    board = game["board"]
    mover_color = board.turn

    scored = _score_all_moves(board, mover_color)
    best_score = max(s for _, s in scored)
    move = random.choice([m for m, s in scored if s == best_score])

    piece = board.piece_at(move.from_square)
    piece_name = PIECE_NAME_VN[piece.piece_type]
    from_sq = chess.square_name(move.from_square)
    to_sq = chess.square_name(move.to_square)

    new_elo = apply_hint_penalty(hinter_id)
    hint_text = f"💡 Gợi ý: đi **{piece_name} {from_sq} → {to_sq}**"
    return hint_text, new_elo


def chess_header_text(cid, display_names=None):
    """Dòng hiển thị 2 người chơi + Elo, kiểu chess.com, đặt phía trên bàn cờ."""
    game = _chess_games[cid]
    if game["is_pvp"]:
        white_id, black_id = game["white_id"], game["black_id"]
        white_name = display_names[True] if display_names else f"<@{white_id}>"
        black_name = display_names[False] if display_names else f"<@{black_id}>"
        return f"⚪ **{white_name}** — {get_elo(white_id)} Elo\n⚫ **{black_name}** — {get_elo(black_id)} Elo"

    player_id = game["player_id"]
    player_name = display_names[True] if display_names else f"<@{player_id}>"
    bot_elo = game["bot_elo"]
    bot_label = BOT_LEVELS[bot_elo]["label"]
    return f"⚪ **{player_name}** — {get_elo(player_id)} Elo\n⚫ **Bot ({bot_label})** — {bot_elo} Elo"


# ============ CẦU HÒA (chỉ PvP — cần CẢ 2 BÊN đồng ý mới kết thúc ván) ============
_chess_draw_offers = {}  # {channel_id: offerer_id}


def chess_offer_draw(cid, offerer_id):
    _chess_draw_offers[cid] = offerer_id


def chess_get_draw_offer(cid):
    return _chess_draw_offers.get(cid)


def chess_clear_draw_offer(cid):
    _chess_draw_offers.pop(cid, None)


def chess_accept_draw_text(cid, display_names=None):
    """Cả 2 bên đồng ý hòa — không đổi Elo, không trừ Aura (khác với hòa do luật cờ:
    đó là hòa 'thương lượng', không tính là ván đấu thực sự phân định trình độ)."""
    game = _chess_games[cid]
    white_id, black_id = game["white_id"], game["black_id"]
    white_name = display_names[True] if display_names else f"<@{white_id}>"
    black_name = display_names[False] if display_names else f"<@{black_id}>"
    return f"🤝 {white_name} và {black_name} đã đồng ý hòa. Ván cờ kết thúc, Elo giữ nguyên."


# ============ MỜI ĐẤU CỜ VUA PvP ============
# ============ KẾT THÚC HÒA THUẬN (chỉ PvP — cần CẢ 2 BÊN đồng ý) ============
# Đấu Bot thì 1 người bấm "Kết thúc" là xong ngay (không có đối thủ thật để hỏi ý).
# PvP thì phải qua bước đề nghị + xác nhận, tránh 1 bên tự ý huỷ ván khi đang thua.
_chess_draw_offers = {}  # {channel_id: offerer_id}


def chess_offer_draw(cid, offerer_id):
    _chess_draw_offers[cid] = offerer_id


def chess_get_draw_offer(cid):
    return _chess_draw_offers.get(cid)


def chess_clear_draw_offer(cid):
    _chess_draw_offers.pop(cid, None)


def chess_accept_draw_text(cid, display_names=None):
    """Cả 2 bên đồng ý kết thúc/hòa — không đổi Elo, không trừ Aura (khác hòa theo luật cờ,
    vì đây là hòa 'thương lượng', không phân định được ai giỏi hơn)."""
    game = _chess_games[cid]
    white_id, black_id = game["white_id"], game["black_id"]
    white_name = display_names[True] if display_names else f"<@{white_id}>"
    black_name = display_names[False] if display_names else f"<@{black_id}>"
    return f"🤝 {white_name} và {black_name} đã đồng ý kết thúc ván. Elo giữ nguyên, không tính thắng thua."


# _PIECE_UNICODE đã định nghĩa ở phần vẽ bàn cờ phía trên — dùng chung cho cả
# vẽ ảnh (fallback khi không có theme) và hiển thị text (dòng "quân đã ăn").


def chess_captured_text(cid):
    """Trả về dòng text liệt kê quân mỗi bên đã ăn được của đối phương, VD:
    'Trắng đã ăn: ♟♟♞  |  Đen đã ăn: ♙♗'. Trả về None nếu chưa ai ăn quân nào."""
    board = _chess_games[cid]["board"]
    remaining = {chess.WHITE: {}, chess.BLACK: {}}
    for color in (chess.WHITE, chess.BLACK):
        for piece_type in _PIECE_VALUES:
            remaining[color][piece_type] = len(board.pieces(piece_type, color))

    start_counts = {chess.PAWN: 8, chess.KNIGHT: 2, chess.BISHOP: 2, chess.ROOK: 2, chess.QUEEN: 1}

    def captured_symbols(by_color):
        """Quân màu `by_color` đã ăn được — tức quân ĐỐI PHƯƠNG bị mất."""
        opp = not by_color
        symbols = []
        for piece_type, start in start_counts.items():
            missing = start - remaining[opp][piece_type]
            symbols.extend([_PIECE_UNICODE[(piece_type, opp)]] * missing)
        return "".join(symbols)

    white_took = captured_symbols(chess.WHITE)
    black_took = captured_symbols(chess.BLACK)
    if not white_took and not black_took:
        return None
    parts = []
    if white_took:
        parts.append(f"⚪ Trắng đã ăn: {white_took}")
    if black_took:
        parts.append(f"⚫ Đen đã ăn: {black_took}")
    return "  |  ".join(parts)


# ============ MỜI ĐẤU CỜ VUA PvP ============
_chess_invites = {}  # {channel_id: {"inviter_id": int, "invitee_id": int}}


def chess_create_invite(cid, inviter_id, invitee_id):
    _chess_invites[cid] = {"inviter_id": inviter_id, "invitee_id": invitee_id}


def chess_get_invite(cid):
    return _chess_invites.get(cid)


def chess_clear_invite(cid):
    _chess_invites.pop(cid, None)


# ============ /wiki — bách khoa toàn thư (Wikipedia tiếng Việt) ============
WIKI_API = "https://vi.wikipedia.org/w/api.php"
WIKI_SUMMARY_MAX = 700  # ký tự, tránh embed quá dài


def wiki_lookup(keyword):
    """Tra cứu tóm tắt bài viết trên Wikipedia tiếng Việt.
    Trả về (tiêu_đề, tóm_tắt, url_ảnh_hoặc_None, url_bài_viết) hoặc None nếu không tìm thấy."""
    headers = {"User-Agent": "TornadoAddonBot/1.0 (Discord bot; contact: n/a)"}
    try:
        # Bước 1: tìm bài viết khớp nhất với từ khóa
        search_params = urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": keyword,
            "format": "json", "srlimit": 1,
        })
        req = urllib.request.Request(f"{WIKI_API}?{search_params}", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            search_data = json.loads(resp.read())

        results = search_data.get("query", {}).get("search", [])
        if not results:
            print(f"[wiki] Không có kết quả search cho: {keyword}")
            return None
        title = results[0]["title"]

        # Bước 2: lấy tóm tắt + ảnh của bài viết đó
        extract_params = urllib.parse.urlencode({
            "action": "query", "prop": "extracts|pageimages",
            "exintro": 1, "explaintext": 1, "piprop": "thumbnail",
            "pithumbsize": 400, "titles": title, "format": "json",
        })
        req2 = urllib.request.Request(f"{WIKI_API}?{extract_params}", headers=headers)
        with urllib.request.urlopen(req2, timeout=8) as resp:
            extract_data = json.loads(resp.read())

        pages = extract_data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        summary = page.get("extract", "").strip()
        if not summary:
            print(f"[wiki] Bài '{title}' không có extract")
            return None
        if len(summary) > WIKI_SUMMARY_MAX:
            summary = summary[:WIKI_SUMMARY_MAX].rsplit(" ", 1)[0] + "..."

        thumbnail = page.get("thumbnail", {}).get("source")
        article_url = f"https://vi.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}"
        return title, summary, thumbnail, article_url
    except Exception as e:
        print(f"[wiki] Lỗi khi tra '{keyword}': {type(e).__name__}: {e}")
        return None

