import random
import io
import time
import os
import base64
import urllib.request
import urllib.parse
import json
import chess  # pip install chess
from PIL import Image, ImageDraw, ImageFont

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


def _firestore_save_doc(collection_name, user_id, data):
    """Ghi 1 document lên Firestore (không block nếu lỗi — chỉ log cảnh báo)."""
    if _firestore_db is None:
        return
    try:
        _firestore_db.collection(collection_name).document(str(user_id)).set(data)
    except Exception as e:
        print(f"[firestore] Lỗi ghi '{collection_name}/{user_id}': {e!r}")


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


_BUILTIN_PIECE_SPRITES_B64 = {
    "K_w": "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",
    "K_b": "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",
    "Q_w": "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",
    "Q_b": "iVBORw0KGgoAAAANSUhEUgAAAHgAAAB4CAYAAAA5ZDbSAAAbsklEQVR42u1de3QU13n/3TszuwJpkQCxIIHEQxLmIR4yGCEg2LFDYoOTxq1tUp/GxGntPBwrbu3WaU3i2M0pcVoXE6fBbf4gzWnTE9P2xI6dphCfxjaWwMYgzFsSBiReegXESpZ2d+be/rH3rq5G+5hZdiUh9jtnjoSYuY/vd7/n/e4MkKUsZSlLWcpSlrKUpSxlKUtZylKWspSlLGUpSyNO5Aabq5wvF9eYJ+0GAVbOkwlgqbiyNEYkVpJfXMnuGzOkj7Lx2CWLiStV4gDKATwKYDWAAvH3KwD2APgxgOZrBDjdYx6TlEhlai4BUFVyLYCAYnPtVzeAx9LQj5v53FA2WKpHyfBKIWlVAGYIcAIuHUIiJOivAfwDAI9Nqrjyew6AuwCEAbztog+qjHkqgLUAbhHaQgPQLv5vTKt/N178HQB2AbgIwBTM+RhAE4B/FmA7WZBUac8EYCmOVayLiXssAJ+0tZFMKKaLsTWJsXKxUC4C+F8At9+AkcogYKUa+wvBYJ7gagFwqwOGyTZ3i+eStaves0sZV7IFuQbA6STtMgBPK2O6oYCWTHxUYYYqcUyRLinRbQAWJpBk+beF4l7mAmAG4BKA+Q7ar1RUcKIxS83xNYeaYcyBO1c4OU6ACIufvwLgjWPbZERwj7IomAOAmdLH5+NEF7K/HABv2MaUbOF0i7mOCMgjsapkBulBABMEE5zYPQvA3cIB4wmeyRH3c5dj0gGMS+JUVQFYL8bixB9gYo5/Ypv7qAdYhgjqRVwwkwL4TBKg7P1J5nwiCbMuA+hLIeTpA9CVZFGujWGPnXjbn1F+zzR/rwlgIlY6V7xPS1GxusOBeADMdjloOdYyJaGgkiV+Ngh7yhwyVKrpiwAO2dqCra+yFDxjIp7zDCN/U8pkEcWxKAAwB8Ak8fcuAKeEvbFL3HCqfk2AuxvAIy4ySlR40W2KOUgkyW7JyWKz87dM8JcD+D2Aj0QGLiP8lavGEJmfd2M4FXtE5kh3oB0ogPcUz5M7uKRT82SC9okSo55WGMbiOFemEoYVJ5BO2ddfOXSw1D4YgL0O+CEF7ptx+Puu4L2R7vhadl4I4FXb4MPiUr3gV8W98QYh//a3CgBOGCXvq06S9CCKrb7ooO2Lim0lSZIbNUkWjf2SY37WAT8KAbxm88Ilf9W+fqnwl6ZDcomwHxLcUIwJSgDUcGZcnABfDqpCqBw3YdJrCcKkWKZnMYD/UcIxdbzdAH4t4tpk5kr25xVzcxMmXRFzjQWITKyMB/C60m48/oYU/nrSkQqVD3/V4cplysS/kUDS5ES/HiPRES9OTZboSORA/r0yfilVP3DpbMZKdLA4wKp8+mqCPmSbjyngMoea7OF0qWoDwDEHeV27tO0VzgJJsHJlqtJMkis+6zBVGS8l+iObZ8rF32gK7clU5UdJeMIA/E2CVKXkyUQA+1zYdsmTY4o9vibpXezQTtodizCApQ7t5ScB/EbYQ2bLEZ8HsCAFr1+VkkO2sXEAHyK13TRdSYlesI3VEnP4DYDbHNr1KkXimQs+mwAWXYsUUyX156ZjdSWucwCwOrilIuRSpe1jACuQ+h6rH0BvDIA/xtDqDqd8oWJMfTat0AlgSYL5xQJ4nUvPXBWke5KZmJFOgHMMrpFqEI6EGuuNA/AA3FdKyLndrKQgVYbnCOlxywc5jgdEG1xpMyi0BcXgPeNMp31TymTJh0+5ZKwELCxWtBumjReeqn18fwwgP0UTsyxGYkCCsixFFTcBwBdi8DBHzMHNYuwS6pbCff78VDKgnQB8FEAjBldCJAOLADiASL2TmwwQU2ycKm1+J+ooAcD21Kb8fblLgGXff4hIJYd9nIYLYCVPmgWviAv+cgAnhKN1LRm26IS+LBoJOvTwOCJ7vU5DGknjhV2LlSzY7QJgdXvvQwzd/LcURyvHRTwp+94dJ0nTJ+bgxgFUw0UnkYrE4E/TYWblxMeLDIpMdDAkro54Vaxmt4F4QQyAZZtdijQ6Ld2pFLnpeABfUjxRp6U6y2yOoB3gghQTSa8hcRUKUxId/y0wSUuliJx4kQJyoo3zLgBTUlSnUwD0J/DKn3EYLsn4cGOcEIQpSYP7bc8kC4++m8Dr7VfmTlzOvVBZOImk+JcApjnlL3Wo84mI774gMijHxARj7YbkAvh0is6LkeSZz4odFtPh2OdhYHeI2MYqN+3nO1zkpkhK3J1kbkYKWhKI7BmPt3nlksKC538mMLjkwma7lmQ5iQUC7I4Y9rcFQIlLmwkAsxLYedn2pxzG1hTAzxNIm/zbzxVV5zRmtRLYx5kuFrfkzQwArTHscIfg8XzbwslYeGtPO6oVjGHbz58JteakGoEoGxChJADvcNiWX8TV8QCRfzvoQq3+NAnAIURqo+Fwzprg0U9tTpvk4S5bO8NanSmrC36kTM6+s/RHDlecHPQCBxmdbluIEk/aFin2nCXwGfoVR0tLsmCuJBlbSFH5xKH0fh5Dd5AkL1/CQJXHNavdVKSZAzhpa0tKuY7IyYIpcexKLHJS1hIvyWCnWSJpYiL+Pqwp7pntgEcPOEi2EDgvzeHCsXpB8EqVTtlnowvepR1gpgwiiMGVjNIBmAVgi4tBJnOyZJ/3Y6B2yU6WLYnhpJJime1Ze0LCAHBvjIRJLOAMFwBvQaT0iWHw2WVNaJaTDvrMGEnmlGKgPMaKkfQwhfebzDECgFVIvPkvVVgPBqow9DjtvYHkpxvk/70eZ2HJtteKPpOFMCYiVR9w4LCtx0A1DIsxpjOCt9ckiNciwTLn3ILIBrg9ZUaUCX0PwGTbSk0lxCCCKbkA/iBBms6LyCZDMlso/+9mWw7cnk78rOgz7KA9j0PV/H1bWtbeZ5vgrdscddoBBoDjcdqjYkUuRuScDkfiuiTDxZjvFo6PpfxN/ix36BmrDlS5rQ059qkAPufCWUxUFCdN17eEY2fF4ZmdpyMCsGobPkji1XJEKi5vR+KTDB4HtlomLuYictQ01v0rXObANUSOf8YCZKXoy3LYppGA10zw4JuKrY236Panw/6mK2A+kGQgcjJbAfgS9O0EYJUJD2LwLpdMVixLoL7jqeHltmSHtItfcuEkxlPRcq55itfMkwjOAYwiyhfxaSInRAbxfxfD4ZIMuA/uqhr6MHBCQj1x/w6cl+TKe95RxiXbm42Bs79Or3tjLGA5ru85HNdVuN//zqgEBzCwN5moL0uop5Vx7I+bPC5HZKvvixg41iFtZrGLdKG8p0g8aykS9kVEqkHc2EAjzrxXAPjzOPO2m7wjGHizwagAmCl2mCfJEY8Xqtob416Pyz5lJkhta2GSTFc8gKdioCyXizY/n4Id9MRYiB4A28TcnWyhfpCu2JemsY0DDpghHY2VAJ6K4WgYLvvliOwYrRNqD+LfuYh/vghxkiN54lmItj4l0o7cJZ+MGA7mk2LOyY7KMhsv6WgAWK7GYw7dehkqPCk8V0uJB90ehjOFCt2gjGO+wiynEsxszxIRhuVg6FajU4ClybhFWczEZdhJRgPAamB+3iHAXHjT3xcMsVJQ0aqEbBB2l2KghjqVgvb5oo0i0SZPgUeGohV04VROcLDgZF/nENnvdRoFDIsNhhjUcYcD05SY8OuKlBgpjJ8hsve8SiQ3FiRJiyZKHy4QbawSbbIUAZYFBY8KVc8cjIcr0nspXaCkA2A5+D64S45L1fgsIrVTXEkXcpdz4Ii8JmEOIuUsLAUJZuLZOUp8TVPQZNLhmy/m5nQskmcnEdlo0NLhaNE0L5STLtolSgy9FQOb36n4AASR4y+b0uBPfBGRYyepntzTxfWiEsu6qe5ozIB2vWaS6ufTGKiKdHrcRQb9D2DggHUqF4O7M1SJxsOu4fm/RGS/mrsYD1MSN8mO+4wIqVuHZ+D8JWTqfc2IVAxaaQBppC4LwH8h8va7VHjwEdzVsg0bqbVa+1yu3lgr+VqkmI9wGyxFrcEF7yS4JJ2Sl45QKdnWoZM2SBoWGka4jVRekJLWLcJMhUlOtg4zDc5o0mip3J+WLcJMAQwlzZZ9IXZqApL2LcJMSPARRA5cZ8kd9SJyknPUS3BAgIysJLsWjMBoluCMqpobgDJi2tL9UQ7pQX6ggD0i8Rwh7vwczvlISjC1Oad8tAIsqxcaM+0ZE0KGXFGOMQbGmGPQCCHQNA2U0kGA268Me9yNNh6OSoAl9Smx8TXHtxI8FUzTNJMynVIKj8cDSikIIdD1yHTls4wxhEIhMMZgWRYsKz5fdV0fAnYaQFd51JcJIPQMqBsgsjfcCOAmuNjZUQGUAKiMVBmq6zpKS0tRVFSEKVOmoLCwEFOmTEFBQQF8Ph/y8vIwfvx45OXlgVIKTdPg9UY2q4LBICzLAmMMPT096O3tRU9PD3p6enDlyhV0dHSgs7MTHR0duHjxIlpaWmCaZsKFJMfsUtolwCcFz9LumGZKguXe8NxkdlgCqmlalOl2yfH5fKisrMTSpUtRWVmJsrIyFBYWYtKkSZgwYQLy8vKgaenNzVuWhZ6eHnR3d+Py5cvo7OxEc3Mzjh49ioaGBhw5cgSBQACmaQ4aM6UUuq7DsiwnYMvFfwyRA/YjnnFxQgYiRzy+hcjhKjPWQiKEgFI6SFIBwO/3o7i4GAsXLsTq1atRXV2Nm266CePGjRtkI+0OkmVZUdWr2mP5jGqnVcarfXPOo9KuaVpcR40xhr6+Ppw8eRJ79+5FXV0djh49igsXLqC9vX2IZCfwB2Qx/bcAPK/wblQDLDeqZwKoQ6T8hQGgKoNVWrRoEWpqarB8+XIsX74cS5cuHcJcdSHEcqwySXa7K4Gz39PQ0ID9+/fj/fffx969e3H48OGYvoRoS2q2S4gcWDuDxC8jHzUAS0+QIfLG2ZfsalrXdcybNw/33Xcf1q1bh9mzZ2PatGmDJCQUCoEQAo/HExNI0zQRCoXQ2tqK1tZWXLx4ERcuXMDFixfR3d0dVa39/f1RCZJ2VNf1qAbJycnBxIkTkZ+fj4KCAkybNg3FxcUoKipCaWkpZsyYAY/HE3XQ7KCGQiFwzqPOXNRGXbqE06dPY/fu3di5cydOnDhht+OSJ98A8E/I0FvyMykCEuQfE0K+BsDyer304YcfJg899BAqKythGMYgwEzThKZpg/5uWRYuXbqEjo4OnDlzBg0NDTh58iQaGxvx0Ucfobe315FHnYrnrus6cnNzMWfOHMydOxc33XQTqqqqMHPmTEyZMgVFRUWDQA2Hw7AsC7quD1oQ4XAYR44cwY4dO/CTn/yEB4NBBkDjnG9HpCaNZirrl0mAZcmLQQj5F875g4899hj74Q9/SAAQVeXaHaTm5uaoI/Phhx/i2LFjaGpqGuKAJQqn3CQ77F66k/Br7ty5mD9/PpYsWYLKykosWbIE5eXlQxw11RYD4LW1tfyll16ihJCfcc4fweAKkuuOJIe9AP51x44dnHNuhkIhrlJfXx+vq6vjmzdv5mvXruUlJSWcEDJkY1zXda5pGqeUckJIzHvSfcl+KKVc0zSu63rMe0pKSvitt97KN2/ezOvq6nhfX9+gOYo5mzt27OAA/g0DBYbX/TYpEWpM37Rp06/b2to455ydP3+e79q1i9fW1vKZM2dyTdOGMM4wDK7rehRQjJLSHAm4ruvcMIwh/69pGp85cyavra3lu3bt4ufPn+ecc9bW1sY3bdr0BgBd8IQMl4RlmqR3OK26uvrdioqK2fv372cnTpzQ7GGTDJ0ynB7MWNo0Vpp03rx51vLly2lTU9NH+/btW43kn++5LkkTdmiTWOmmYRhsNElmJiTdMAy12vNBwYNhq5gcTv0vnSvu8Xh+xRjbYFkW83q9tLi4+LqRVjdSfeHCBQSDQaZpGqWUvh4KhT5HIghn+kXhIwKw7I/n5+fPvnr1an1FRcXUF198kS9atIgk85CvN6KU4vDhw/zxxx8nTU1NlyZMmLCqu7v7NEbmq3DDO3cRFn1569atnHNuMsb4WCMxJ3Pr1q0cwJfEnG+Iz8sS0zQpBioIqbDDY01Fq6XEH4g5D3tIpI/E5DVNY5qmFW3fvh3z58+3Fi5cqI9BFU2OHj1qbt++Xdc0rUjTtMMYgeMoIxFky1MQTwB43uv1WsXFxdoYdbKsYDCoIXLm6h9HImOljxDAFoCllFIEg0Fy+vTpsepvEEopGGNL4f5NAdclwJQQwjjndwH4FGOMU0qppmnXXXLDSdLDsizKGJMvMf8kIeT/OOcZ21gY8USH+HkngN6cnByu6/qgg1qUUm4YBtc0jV9PCRBCCNc0jRuGwSml9vw5y8nJkR8ASeVDXNeHz8E5J16vt9zr9bZs2bKFBwIB88CBA/w73/kOX7NmDff7/UOYNhrz0IiRj7aPz+/38zVr1vBnnnmGHzhwgPf09IS3bNnCx40b92Z5eblXZLPImEJY7I/+fMOGDZxzbtrjxkOHDvGXX36ZP/LII7yqqiohc+XOjtxZSufukrp7ZO8n0XM333wz/8pXvsJffvllfujQoVihsblhwwYOYIPgxbBI8XDYYAKAFxQULOvs7NwI5d1YpmnCsixomobFixdj8eLFAICOjg60trbi+PHjqK+vR319PU6cOBGtzogXUsWqbwbi7+/a94vVjYJ4z8gqkAULFmDlypVYuXIlFixYgJKSEhQWFkbvkwUMyua/zGDdjci7rIfFDpNhWkQWIeQHAJ7knPMXXniB3H///ZgxY0b0pnjVEJJZgUAAR48exeHDh3HkyBGcOnUK7e3tuHLlCq5evYre3l709/enZcA5OTnIzc3FhAkTUFBQAL/fj7KyMixatAiVlZWorKyEz+cbUqgQryqltbUVO3fu5E888QQhhNTfe++9n9i5c6c1VgCWXuNbiLw53QKgVVRU4NZbb0VNTQ3Wrl07pBpCrfiIVeQm6dy5c7h06RI6OzvR1dWFrq4udHd3R2ud+/v7EQwGB5X1yHIcr9eLnJwc5OXlITc3F/n5+Zg8eTIKCwsxefJkFBUVYfr06TH7tRcB2rVGU1MT3nnnHdTV1eGtt95Cc3OzPADQgMibbccEwHLPcx2AVwkh4wAwQghV1WxJSQlmz56NZcuWYd26dVi9enW0YN3OVFnkJu16rGK4dJKUSglkvCLA3t5eHDhwALt27cKePXvQ3NyMc+fOqaqdc84JgHOc88WIfMEFmU58ZLomiyPyDsjdlNKVjDELgCZBEbHiIJtKCIHP50NVVRVqampQXV2NiooKFBYWwu/3x2SuWhMtF4IsHohXYqvG3dL2qrVcuq7HLKZnjEVPPrS0tKChoQF1dXXYt28furq6hhTByxhfLBYOgGiats2yrMeRwWK74QBYfcP5mwCs3NxcjVKKQCAwxDGKBbak8ePHo6KiAuXl5SgrK4uWs06fPh3FxcXw+/1pl2TTNNHe3o4LFy7g/PnzOHfuHFpaWnDq1Ck0NTWhubkZH3/8cUwnTIIqTzdI8vl8jDFGe3t72xB5W/2pTIOccQnWdf2bpmlu3bhxI/v2t7+tEULw3nvv4Re/+AXefvvtQUySkmP3YmMdCtN1Hfn5+cjPz4fP50Nubi78fj+mTp2KiRMnRh2kcePGIScnB4ZhRCXSsiyEw2H09/ejr68v6qhdvnwZbW1taG9vR29vLwKBQLTGOtbZJDlWNYMVDoeHLM61a9di48aNWLFiBeec47nnnuOvvPLKg5TSf2eM6Rh4U+71lrUjAPCoz+fjJ0+eNO37pWfPnuXbtm3j69ev57Nnz45bRSkvXde5x+OJWaCX6UvTNO7xeGKOyX7vnDlz+Pr16/m2bdv42bNnuW2/2zx+/DgvLS2tBYBly5YZmQRBHwYJPkgICWuaRgFw0zQjRUmahtLSUtTW1qK2thbnzp3Dnj178P777+PgwYM4ePAgrly5kjDejWdX7b87zR/bf7d7zPGOlxYUFKCqqgpVVVVYsWIF1qxZM8j7tp2qILquM6/Xe3W4jt5kEmAqVuh/3nPPPfz8+fP96mpmjPH+/n4eDAYHpXwCgQA/fvw4f/311/nTTz/N77zzTj5t2rSY0hIvy2UYBvd4PNwwjISXvMdp/tswDF5UVMTvuusuvnnzZv7GG2/w48eP80AgMGgOwWCQ9/f326XXOnPmjPXAAw+cBzBTAEwzDULGY2CPx7MgFAq9Nn78+LI77rjD3Lhxo3bLLbeQuXPnDrKz4XA4emjbLkHBYBCnTp3CoUOH0NTUhBMnTuDs2bPo7u5GIBCInu+120C3ZBgG8vLykJeXB5/Ph/z8fMyaNQvz5s1DeXk5li5dirKyspjhkjxMrtp7AGhsbMR7773HX3nlFeu3v/2t3tfX911CyLOc84yXzg5bosMwjCXhcPhlRF5tjylTpuD222/nq1atYtXV1aS6unrQ212TJRIkBQIBtLe3o729PZrs6OnpiYLe29sLxhjC4TBCoRAAwOPxREGQh8R9Ph98Ph8mTZoUDcn8fj98Pl/MftXa5xiJGL5v3z5eX1/P6+vr6Ztvvkm6urrk//1HeXn5Q83NzSEMw+Y/GUZ1zQFM1HW9FsDXTNOcBPEC8IkTJ2LOnDmspqbGuu2222hNTQ2dOnUqiRWHypSmZKxd2tNNUioTJVbEATleX1/Pfve737H6+nrt9OnT9PLly9Fh67r+ewDbTdP8PiIf8yRjCWA1qwUAXsMwyiml95mmuc6yrNmInCOO5oIXLVpkrl69mi5fvpzMnTuXTJ06FX6/Hzk5OUkzTlIDqJKf6AC4/dB4ogxZX18fOjo60NbWhsbGRr5//36+Z88edvjwYT0YDKq3XjQM4zSldDdjbGc4HG4WwALDWDo7EnXRQ9JzhmFUUkpXmqZ5i2VZtwBYYnc+5syZg4qKCsyaNYuVlpby0tJSlJSUEL/fT+Q7OtI4Hy6zVe3t7bylpYW3tLSgtbWVnDlzhjY2NiJGmRED0KBp2n5d199njO0Nh8NHnMx/LAE8xMvG4E/TAZFvJkynlM4nhKyilK60LGs+YywHtqpE+bIV8ZMVFBRYkydP5vn5+UQc6iZ5eXnQdR2GYRD1JSzhcJhbliWTGfzy5cvo7u7mnZ2dpLu7WwsEAlQ6bmrmTWplSmm/pmnHGGP7OOfvMsZOALiAgS+xSv9Dfi6AjxSTRwNRRYXb03Zafn6+LxgMLiCEVHHOFzLGysLhsJ9zPhGRL5rkwf0HPZJRGJFvBl8lhFw2DKOdUnqKEHKUc37Q6/Ue6+7uDsTwghPN5YYFWB0PUWxUXAY988wz9Pnnny8BUMwYKySE+DnnhZZlFQDwMcZyAfg45+ME+BQDZ3KDou0QIaQfQIBS2gsgoGnaZUJIJ+e8g1LaCeDCU0891frss88m++AXscXMo4ah10vSxL4ATIfPeQQAVMncyVP1lvK7k6yfHUB+vTDues2U2S/V4XFj94iyCKCAx0ejVN4oAKd7bmP6xF+WspSlLGUpS1nKUpaylKUsZQkA8P/gUab6d0vDBgAAAABJRU5ErkJggg==",
    "B_w": "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",
    "B_b": "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",
    "N_w": "iVBORw0KGgoAAAANSUhEUgAAAHgAAAB4CAYAAAA5ZDbSAAAUx0lEQVR42u1da3AU5Zp+vu6ZXIaoCSjBcCmI3ERRQC4SRYpS1BW8RPQIsq6FhXvwlMBxQd0StVyvcCxxRctyLYvV1VW03JKACEc9RrFcL4CAoiArJyRIiKAEAjGXme5nf8z3Nl+aCQRJMpNJv1VdIWEu3f18z3v/3gYCCSSQQAIJJJBAAgkkkEACCSSQQAIJJJBAAgkkkEACCaQ5UWl+bbb+twOAAdypAYqlgVEn+Tn+91ud8YbaKQYujcME5kTYZ75+MoCzAfwMoC7NNVaHMBW9AcwEMA/AmN+xEOV1/QAsB9AAIApgC4AJKbioO4VYBtv2GAyOAngTwJktVLEC3GUAKozPcfXPvwPo25nVdTLB7QrgGw1EzKeqvwMw9DjAyN8nAfgVAJVSUaWUqwFu1J+1oBM4lykJcH8AuzUYDgBalmWCXQZgUDPgyGcUATjoYy2VUvK7C2AbgFBw29sf4IEA9mlQHNu2TXCi+u/rAZzqe5/87AHgB/2emFKKlmVxzpw5LCwspLFgosdYKIG0IcCDAVRrENzBgwdz6tSpiUB+WTPQPMIA/kvstv4MPvnkkyTJCRMmEAD1onEBTG2lUCyQEwB4EIBfBeDzzz+fP//8M++44w4Bx9UgOwD+0fcZl+v/i+nX8Z577iFJxmIxzpw5Uxgsanuu7/2ySALA2xDgswBUaoCd/Px87tq1i4cOHeKoUaP8AFUBmA5gCoA/ANigF4EDgOPHj+ehQ4cYi8VIkg899JBoAnn/fwLoBSC3mXMK6fMKwG5FgHMBfKGBjAHgmjVrSJLr169nbm4uLcsyQW5yKKVc27bZpUsXfvLJJyTJ+vp6kuTzzz8vat4Mv7YD+BjAGwCeADADwIUAMps5xyCsagWQX9AANwLgFVdcwcbGRpLkE088QQDMyMhgOBx2w+FwVI5QKORmZGQQAG+55RZPNTuOQ5J85ZVXCIDhcJi2bdOyLD/gcvyqQ7U3ANym42/li7ODJMnvELlpVyKeTvTCnA8//JCO47Curo5FRUWJQPGOSCTCLVu2kCRd16XruiTJ7777jpFIhL7Eh2NZViwUCkVt2260LMtJAPphAO9pc9DPd74dRn2rFDkHaiZvADBMA2CXlJRg8uTJAICysjIsWbIEBw4cgG3bIAmlFEgiMzMTkydPxlVXXZXwC1atWoXVq1e7ZWVlaufOnWrPnj2orq42XyK5ayqlYFmW5bouSC8FvhvA/wBYBuBz47yVXjABwMdhsIt4UeAjAPkA3IyMDKu8vBw9evSA67qwrOObQQG9mb+xvr4e1dXVqqamBgcPHsSuXbuwceNGbNiwAevWrUN1dTVc9wheoVDIJUnHcUTLHADwN223NxhOWVCOPIZIZunfzETF6NGjPTuqbzKj0SgdxznqiMVintecSI73/67rsqamhh9++CHnzZvHkSNH8tRTT/XUtW3bjlKq0eeo/Yf2/lOJLCnrYBUCqATghkIhBwBffPFFD1g/GP6jpeI4jmsuCsdxmn3/2rVref/99/O8885rYr8ty3KM3ysBzDbADbztZgB+3WAKBwwYwMrKyoQAt6W4rstYLNYE9KqqKr755pu86KKLPKB1yGYWRd7T6dYO54S1h/c8S6tmJxQKEQCfffZZkmQ0Gj0hhrY20NFotImaX7FiBceMGWMC7eBIQWQPgOIA5KbgjgNQo71mFwDHjRvHmpqao2xmMoAWDWJqkYaGBi5evJgFBQUem5VSorYbAfyLz8vudCIXPQTAT8JeAMzNzeXGjRu9m7lv3z5u27bNS3gkW0ygt2/fzuuvv95ks2t40491ZudL6eT+Z+I127bNcDjM119/3UszPvXUU8zLy2NGRgaHDRvGrVu3trtNbk59mwvuscceY1ZWViKQ/70zslhU81xhrtR+FyxYQNd1WVdX51WRcKRcyMsuuywlAE7E5nfeeYf5+flm5UtA/ktnUtfieBQi3jPlimq+8cYbveLAM8884+WOpXCvlOLgwYNZW1ubVHuciM3iiH3++efs27evCbLEzXf74v20BtgC8JwkC5RS7Nq1K8vKykiS33//PU855RQqpTzmCsOHDRvGxsbGE45920ME5E2bNrFXr15meVKqX1PTPU6WC7tQJ/EdKc4vXrzYu1HTp09vAqrhpXLatGleuJKKIue1fv169urVi0opYbJUqoams9MlAP8VRnF+1KhRrK6upuu63LJlC7t162b2TzWxwatWrUopG3wskFeuXMlIJOIPoT5HvKdMpRuT5WL+IKrLsizats3ly5d7N2fJkiUeewVUAbqoqChlmducupbrMZr9CGBhuiVCZLV2BbDZyP7w6quvpuu6bGhoIEnOmzePSilK8V4WQSQSYWlpaZuw15/EaG0Pe8aMGabTFQNwSCd30sYei+d4t3Y4YpZlMSMjw0toCMBz584lAGZnZzMcDnvsffDBBz3115rOlakRWhtkcQT37t3Lc845x0xrEsCXOg9gpYNqVgD6ANhpVmLmzp17VJixevXqJrYXAGfPnn1Uh0Zryt69e7l37942VdUlJSUMhUJij8Xp+lM6sFhszGK9gmNKKfbs2ZPl5eVNmCPgLVu2jFOmTOE111zDV199tU3Ale98++23OXz4cA4fPpwrVqxok/havkuiA8Ph+juAgo6cAJGTHgagXroeYTSkm5Ua82ZIYb8tbrgsloMHD3LgwIGepujTp0+b5Lul3lxWVsbc3FyJ78XheqAjJ0CkA7FE7I9SikOHDuX+/fubdW5M0P0LoDUZ9dNPP7GwsJC2bdO2bebk5LCurq7Nsl0k+cgjj4jDFdP+yA7E+7M7nKqWfPM1iHdJxsT2LFu27LhOTVtmquR7t27d6pX7ADAvL6/NABYW796920uAGM0Cd3W05Ic0iZ8KYK1mb1SKBclOM4oafuONN7weaQAcPXp0m8bZoo0effRRM2wSFmd3xKTGzVIKtCyLWVlZ/Oyzz5KaiXJd1+vFuummmwiAmZmZBMD58+e3eYbLdV3u2LGDPXv29GfrbvFpvpR3rrIAfG+sVM6YMeO4nY3tVd779NNPGYlEPPsbDoe97S5tufiExbfffrsZF7uIt+F2CDssK3COFL8ty2K3bt349ddfJ71Q4DgOGxoaOG7cOG8bDABOnDjRK1W2pfkQ87R582bq3jOJiasBjEx1FktSo5uO8bykxqxZs5IOrnz3gw8+6OW7LctiKBTia6+91mZee3NAT5gwwR8yPZLqIZOsvAf0CTvinUpSI1nOlQD33nvvNVHNANi7d2+vFt0evoF/Q5wOmaTSdFqqqmphb08A5QBcOfGHHnooqeAKczdt2sQzzjjD7GkmAPbt2/eorFp7AFxWVsaCggJhsaOrTWPaQk231moh4jvv+9i27bqua/ft2xe33347SJqbuNpNXNeFbduoqKjAtGnTsG/fPliW1WTvkeM4iEaj7eeB6s1yffr0wfjx40ES2h6HEJ9UALTyZjarlcDtJs4VAJskZs6ciYKCghZvHGtNicVisCwLFRUVKC4uxtatWwXcJivNsizYtt2uAMu5TZgwAUopuK4rN+daHNlpmXK2dwGMMQu9e/fm7t27vdgzGTa3oqKCo0ePNluAHLMNCAALCwvbfYuMfM+2bdvYo0cP83waEG9IbNXMlnWS73UBnIH4jnhS6+Jbb701Kex1XRehUAg//vgjrrvuOnz11VewbRuO47j6fP8GoF5eHw6HkZWV1b6JgjhrMWjQIPTv39/7G4AMABNTKXUpLv1dmhkxpRRPP/10VlVVtbtjJcxYt24dzzrrrEQ9yu8AGAWgzuzUlP1P7Xm+4vwtWLDAX0Z8q7UdLesk3ufonPMNAGDbNknizjvvRH5+PkgiFoshFou1qZNFEo7jwLIsvP/++7jyyiuxY8cOP3NX6ZRgjs60AQAikQhCoRAcxzlq43ibhh1aq02cOBGWZZn352wAXbRmVKlgey8zVqCbm5vL7du3J0xqtAVDTLu5dOlSbxaHbwvJfwOI6PO9w7TBxcXF7Zrk8EtNTQ1zc3NN/2C/1jKtxuLfy2BH//xnzV4AUMXFxSgsLIRt26iurkZJSQlKSkpw4MABz/a0lghrGxsbcffdd+O2227Db7/9Bh2mybUtAfBP2u4qxGdieqHIoEGDTBvY7pKTk4PRo0cDgKVLqnkAzk92wkPuRn8AdbILITs7m++++y5JsrS0lEOGDGEoFGI4HOaQIUO4du3aVmGy7N0lycrKSk6aNCnRNk6ZLCstMWF9zn+FMdF26dKlSatwyX14+OGHpUletro8ley8tHzxfFPdjRkzho7jsKamhgMGDDhqzNHAgQN5+PDhVmtz/eijjzh48GACYCgUMsE9oFkri9EcWfyDpFIty+LmzZuTlmmT61i5cqVcg+Sl39UeddK8adtkg1IqBoCPP/641x1pMMrbQAaAH3zwwe9ijD+eXrRoEbOzsxN5ytsQHysMg73i7V8KoFYALigo8KpIyUyjfvvtt8zOzqZSytH36UfEJ9+3ipq2fod6dnQXQk/txapQKOTNqJLMkKTlaIw28v9saWxLEpZloby8HMXFxbj33ntRV1cHpZTrOI5cxxrt9P0vjjy3gQYLxgKI6O5O65JLLkFmZmbyCuf6HnTv3h2DBg0CSaXtcF+dW0gKg2VB9ES83YQAnKysLNbU1HieocSh4XCY4XCYANi/f3/vNS1ViSZrly1b5u3c09tbhLVRxPfhZiYouckN6gLgE/3eKAC+8sorSe8wESZPmTLFr6avTZYdFoC7A/g/E+BffvnFO/kvvviCF1xwgWd/R44cyS+//NILSaS741hAy43/9ddfOWvWrOZGJVQivuepOY0kla4iAI1KKUcpxby8PP7www9Jr1NLeDZ//nwhhJQP/zVZDJYvPAW6LQeAk5GRwZ07dzZZmfv27WNpaSk//vjjJuC3JD42N1XLnCpt083RRatxZHq7fZzzXaoZEgPAadOmeUPVUqEJ8LnnnvMGruHIyOOkhUjCknUScliWxU8//fSoMMYPZENDA9evX881a9Zww4YN3s01b7K8t6SkhHl5eaaXHDO85AXGeYSOU6c+W4dzrnRxvPXWW0lNcPgX8sqVK8WUuXpn5WfJDJPkhr5rxpQvvvhiE3DNEYOO47C2ttbrZpRj3rx5rK+v93LBopaXL1/OnJwcf4updD5c3EInUW7QmzCa7y+44ALW1tYmnb2mGdq4caM0JLjak640QqWkhUmP6RNyAXD69OkJWSGAi52RTkYZeiZ7hEVdrVixgl26dPFPeafOSuW10PmQRThJO2GuNN+//PLLSXWuEgFcVVXlOaZG6fDMZHvSl5mJjt69e7OystJjrl9djxgxgrZte8DKjruFCxd6F7xhwwZ27drVBFeGmcxOsMCOZUaUdgQ3wdi6OXbs2KRNzztefD9ixAh/7boo2aXDiA6VPBbLttBEIs9ekFKd/BQGl5eXe5kpI3nRCOCPCex/S3yE12HM4YpEIu3S//x77fDll1/un09yUzJz0vKld+ubGLUsi+FwmHfddRf37NnDxsZGRqNRRqNRHj58uIk3LGMa+vXrx4qKCpLkDTfc4DHbCIP+bLBWnYB/cI94+KIx5s+fn3DYaLJFNJxMAzDM0l3JzEmLh5oP4Fv4HkmXk5PDc889l2PHjuXw4cNZUFDQZHO33HR5/I08k8HXWvPcCaxgMyV5s7ZhTeZfHj58OCVHMAnA9913n//pMIuSXXSwjBSgPC/Q0eGMbMuQw0HTR9axe/furKqq4ooVK7xWVqMR/GOdfWrpE0/kJlyuwyiv8T4/P99LaqQauKa5ePbZZ4UAssBfTTbApgNwEYCtaPqomyYHfGORhg4dyocffphZWVlmfzAB7AIw4AQuLmQ4ffuFBUophsNhlpSUpJzdTQTw22+/TZ8mfP84cX67h02n6QTEOsQfYrEf8aFnNYg/zOoX/wIw/i1qqVGHNjhB5k6EfvahOFVKKb700kspkdBoCcClpaX+B3J+ngoMbi7hMEi7+ZcCGI/4lLcibRvlImJapbuGavrjCYArr/kHE1wxAYsWLUpp5vpTtd98843fwdxksDdlNogfz9t9BImfe1QB3bzXQo9ZVvXVWkN4A9YA8NFHH016IeFEAa6srJQdj2Ztu2uy23eOFYvavkP+9mfEuxxLEX8O0Z+MCzmRUOg6A1xvLLHJ3FR0qpqT2tpaSc8KwOVIsyeWn4hanmh47jGx5zLBJxXDoeNJfX29zJyWp7BV6kJJhwPYRtPn/7b0SZ+ilsf7vWUAfPrppzuMWk4kDQ0NMm9aAN6L+BiqlHG02oPd/RDfYN7EW37mmWc6NLhSbDn77LPNkuF+xMcvnxTAHWEIl7D7VMSf9N1Pq+WQ4zhYuHAh5syZ4/VtddgVbFnIzs72a6wMdAIR1J7355cfeOCBDs9cMx6++OKLTQb/BuCKDkTEkwL3WgFXvOWpU6d6fdIdzaFqLlyaOHGiWfSPIj5M7qQAtjqAaj4dwOOixhzHwdChQ/H0008feaHq+LO1lVKIRCJ+FZ3ZWgxJVW/bBXCrDhccAFZmZiZeeOEF9OjRw7Nd6SKGDZZ+7qx0BdjS6cwzAMwQIF3XxZ133omioqKkjIZoZ4BhMFilI4MB4BIA51iW5ZK0zzzzTMyePTspQ13aQ8LhsB9MO10ZLPtMb0a8EUCRxM0334w+ffqkJXsByPZac/We9EpOZfc7D8ClSikVjUbRpUsXTJo0ydvzlI6S4LqYjgwWFXUxgNM0U1X//v1x4YUXevOvOomkJcByTiP1qiYAjBgxAtnZ2U12K6apiu40DB6qL5oAMHLkyLRVzcdQ0UhHgOUqC+R3pRSGDBkCpVRnUs9p6WSZG8xz5G+hUAhdu3ZFXV1dWqvoBHMz3XQEmIi3zIbNCx8zZkzaAivS2Ngotlile5iUrQGWvmrU19d3NrXc0p7wDgWwXNx+xDswW+UiO7BUnSyTU1HniZq+CfEJ8jlIsRG77bDIHQArAcw7WYcr1Y1aBPGCg4s0fXJ2M5jUA/g53S+0M6vmVrt+1QFWs+qkALsIJJBAAgkkkEACCSSQQAIJJJBAAgkkkEACSQ/5f5oQm5c2x0HxAAAAAElFTkSuQmCC",
    "N_b": "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",
    "R_w": "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",
    "R_b": "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",
    "P_w": "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