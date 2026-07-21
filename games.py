import random
import io
import urllib.request
import urllib.parse
import json
import chess  # pip install chess
from PIL import Image, ImageDraw, ImageFont  # đã có sẵn vì bạn dùng PIL cho gen_smoke.py

# ============ FOLK VALLEY RANKING (dùng chung cho flag & fruit) ============
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


# ============ ĐOÁN TRÁI CÂY ============
# CHỈ lưu tên file Wikimedia — dựng URL qua Special:FilePath để luôn ra đúng ảnh
# (URL thumb "upload.wikimedia.org/.../thumb/x/xx/..." cũ bị sai mã hash nên ảnh không hiện)
FRUITS = {
    "apple": "Red_Apple.jpg",
    "banana": "Banana-Single.jpg",
    "mango": "Mango_Alphonso.jpg",
    "grape": "Table_grapes_on_white.jpg",
    "orange": "Orange-Fruit-Pieces.jpg",
    "watermelon": "Watermelon_cross_BNC.jpg",
    "pineapple": "Pineapple_and_cross_section.jpg",
    "strawberry": "PerfectStrawberry.jpg",
    "pear": "Pears.jpg",
    "peach": "Autumn_Red_peaches.jpg",
    "kiwi": "Kiwi_aka.jpg",
    "lemon": "Lemon.jpg",
    "cherry": "Cherry_Stella444.jpg",
    "coconut": "Kokosnuss.jpg",
    "papaya": "Carica_papaya_fruits.jpg",
}
_fruit_games = {}  # {channel_id: {"round", "score", "fruit"}}


def _fruit_image_url(filename):
    return f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width=320"


def fruit_active(cid):
    return cid in _fruit_games


def fruit_start(cid):
    _fruit_games[cid] = {"round": 0, "score": 0, "fruit": None}
    return fruit_next(cid)


def fruit_next(cid):
    game = _fruit_games[cid]
    if game["round"] >= ROUNDS_PER_GAME:
        return None
    fruit = random.choice(list(FRUITS.keys()))
    game["fruit"] = fruit
    game["round"] += 1
    return _fruit_image_url(FRUITS[fruit])


def fruit_check(cid, guess):
    game = _fruit_games[cid]
    correct = guess.strip().lower() == game["fruit"]
    if correct:
        game["score"] += 1
    return correct, game["round"] < ROUNDS_PER_GAME


def fruit_answer(cid):
    return _fruit_games[cid]["fruit"]


def fruit_progress(cid):
    g = _fruit_games[cid]
    return g["round"], ROUNDS_PER_GAME, g["score"]


def fruit_end(cid):
    _fruit_games.pop(cid, None)


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
import time

_chess_games = {}  # {channel_id: {"board", "is_pvp", "player_id"/"white_id"+"black_id", "player_color", "last_move_at"}}
_PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}
CHESS_STALE_SECONDS = 30 * 60  # ván không hoạt động >30 phút coi như "ma", tự dọn


def _touch(cid):
    if cid in _chess_games:
        _chess_games[cid]["last_move_at"] = time.time()


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
    return existed


def chess_start(cid, player_id):
    """Bắt đầu ván vs Bot — người chơi luôn cầm Trắng"""
    _chess_games[cid] = {
        "board": chess.Board(), "is_pvp": False,
        "player_id": player_id, "player_color": chess.WHITE,
        "last_move_at": time.time(),
    }


def chess_start_pvp(cid, white_id, black_id):
    """Bắt đầu ván PvP giữa 2 người thật"""
    _chess_games[cid] = {
        "board": chess.Board(), "is_pvp": True,
        "white_id": white_id, "black_id": black_id,
        "last_move_at": time.time(),
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


def chess_player_id(cid):
    """Chỉ dùng cho chế độ vs Bot"""
    return _chess_games[cid]["player_id"]


# ============ HỆ THỐNG ELO (giống chess.com) ============
DEFAULT_ELO = 800
BOT_ELO = 1200  # Elo cố định của bot AI (đánh giá nông 1 nước, ngang trình độ mới chơi)
K_FACTOR = 32
HINT_ELO_PENALTY = 100

_user_elo = {}  # {user_id: elo}


def get_elo(user_id):
    return _user_elo.get(user_id, DEFAULT_ELO)


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
        _user_elo[id_a] = new_a
    if id_b is not None:
        _user_elo[id_b] = new_b

    return new_a, new_b, delta_a, delta_b


def apply_hint_penalty(user_id):
    """Trừ Elo khi dùng gợi ý. Trả về Elo mới."""
    current = get_elo(user_id)
    new_elo = max(100, current - HINT_ELO_PENALTY)
    _user_elo[user_id] = new_elo
    return new_elo


def chess_resign(cid, resigner_id):
    """Người chơi đầu hàng. Trả về id người thắng (None nếu là vs Bot và bot 'thắng')."""
    game = _chess_games[cid]
    if game["is_pvp"]:
        winner_id = game["black_id"] if resigner_id == game["white_id"] else game["white_id"]
        return winner_id
    return None  # vs bot: không có id thắng thật, xử lý riêng ở caller


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
        label = f"{to_name} (ăn {PIECE_NAME_VN[captured.piece_type]})" if captured else to_name
        options.append((to_name, label))
    return options


def chess_make_move(cid, from_square_name, to_square_name):
    """Thực hiện nước đi được chọn từ dropdown. Trả về outcome hoặc None nếu ván tiếp tục."""
    game = _chess_games[cid]
    board = game["board"]
    from_sq = chess.parse_square(from_square_name)
    to_sq = chess.parse_square(to_square_name)
    move = None
    for m in board.legal_moves:
        if m.from_square == from_sq and m.to_square == to_sq:
            if m.promotion and m.promotion != chess.QUEEN:
                continue
            move = m
            break
    if move is None:
        return None
    board.push(move)
    _touch(cid)
    return board.outcome()


_SQUARE_PX = 60
_BOARD_PX = _SQUARE_PX * 8
_LIGHT = (240, 217, 181)
_DARK = (181, 136, 99)

# Bộ ảnh quân cờ "Cburnett" (chuẩn Lichess/Wikipedia dùng, giấy phép GPL/CC-BY-SA — dùng tự do)
# Chỉ lưu TÊN FILE — dựng URL qua Special:FilePath để Wikimedia tự tìm đúng ảnh,
# tránh lỗi đoán sai hash thư mục thumbnail (nguyên nhân quân Trắng trước đây bị lỗi không hiện ảnh).
_PIECE_FILENAMES = {
    (chess.PAWN, True): "Chess_plt45.svg",
    (chess.KNIGHT, True): "Chess_nlt45.svg",
    (chess.BISHOP, True): "Chess_blt45.svg",
    (chess.ROOK, True): "Chess_rlt45.svg",
    (chess.QUEEN, True): "Chess_qlt45.svg",
    (chess.KING, True): "Chess_klt45.svg",
    (chess.PAWN, False): "Chess_pdt45.svg",
    (chess.KNIGHT, False): "Chess_ndt45.svg",
    (chess.BISHOP, False): "Chess_bdt45.svg",
    (chess.ROOK, False): "Chess_rdt45.svg",
    (chess.QUEEN, False): "Chess_qdt45.svg",
    (chess.KING, False): "Chess_kdt45.svg",
}

_piece_image_cache = {}  # {(piece_type, color): PIL.Image} — tải 1 lần, dùng lại mãi


def _get_piece_image(piece_type, color):
    """Tải & cache ảnh quân cờ PNG qua Wikimedia Special:FilePath (luôn ra đúng ảnh,
    không phụ thuộc việc đoán đúng hash thư mục thumbnail). Chỉ tải mạng lần đầu
    tiên cho mỗi loại quân; các lần sau lấy từ RAM cache."""
    key = (piece_type, color)
    if key in _piece_image_cache:
        return _piece_image_cache[key]

    filename = _PIECE_FILENAMES[key]
    png_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{filename}?width={_SQUARE_PX * 2}"

    try:
        req = urllib.request.Request(png_url, headers={"User-Agent": "DiscordChessBot/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            img = Image.open(io.BytesIO(resp.read())).convert("RGBA")
        img = img.resize((_SQUARE_PX, _SQUARE_PX), Image.LANCZOS)
        _piece_image_cache[key] = img
        return img
    except Exception as e:
        print(f"[chess] Không tải được ảnh quân cờ {key}: {e}")
        _piece_image_cache[key] = None
        return None


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


_PIECE_LETTER_FALLBACK = {chess.PAWN: "P", chess.KNIGHT: "N", chess.BISHOP: "B",
                          chess.ROOK: "R", chess.QUEEN: "Q", chess.KING: "K"}


def _draw_piece(img, draw, cx, cy, piece, font):
    """Vẽ quân cờ bằng ảnh PNG thật; nếu tải ảnh lỗi thì rơi về icon chữ (không bao giờ crash)."""
    piece_img = _get_piece_image(piece.piece_type, piece.color)
    if piece_img is not None:
        top_left = (int(cx - _SQUARE_PX / 2), int(cy - _SQUARE_PX / 2))
        img.paste(piece_img, top_left, piece_img)
    else:
        radius = _SQUARE_PX * 0.38
        is_white = piece.color == chess.WHITE
        fill = "#f5f5f5" if is_white else "#2b2b2b"
        outline = "#2b2b2b" if is_white else "#f5f5f5"
        draw.ellipse([cx - radius, cy - radius, cx + radius, cy + radius], fill=fill, outline=outline, width=3)
        draw.text((cx, cy), _PIECE_LETTER_FALLBACK[piece.piece_type], font=font, fill=outline, anchor="mm")


def chess_board_image(cid):
    """Vẽ bàn cờ ra ảnh PNG dùng ảnh quân cờ thật (cache sẵn sau lần tải đầu)."""
    board = _chess_games[cid]["board"]
    img = Image.new("RGBA", (_BOARD_PX, _BOARD_PX + 24), "white")
    draw = ImageDraw.Draw(img)
    piece_font = _chess_font(28)
    coord_font = _chess_font(14)

    for row in range(8):
        for col in range(8):
            x0, y0 = col * _SQUARE_PX, row * _SQUARE_PX
            color = _LIGHT if (row + col) % 2 == 0 else _DARK
            draw.rectangle([x0, y0, x0 + _SQUARE_PX, y0 + _SQUARE_PX], fill=color)
            sq = chess.square(col, 7 - row)
            piece = board.piece_at(sq)
            if piece:
                _draw_piece(img, draw, x0 + _SQUARE_PX / 2, y0 + _SQUARE_PX / 2, piece, piece_font)

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


def chess_bot_move(cid):
    """Bot đi 1 nước — đánh giá nông (1 ply), rất nhẹ CPU. Trả về outcome hoặc None."""
    game = _chess_games[cid]
    board = game["board"]
    bot_color = not game["player_color"]

    best_score = None
    best_moves = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            score = 1000
        else:
            score = _material_score(board, bot_color) + (0.5 if board.is_check() else 0)
        board.pop()
        if best_score is None or score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)

    board.push(random.choice(best_moves))
    return board.outcome()


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
        else:
            winner_name = white_name if outcome.winner == chess.WHITE else black_name
            result_line = f"🎉 {winner_name} thắng! Chiếu bí!"

        return (
            f"{result_line}\n\n"
            f"⚪ {white_name}: {new_white} Elo ({sign_w})\n"
            f"⚫ {black_name}: {new_black} Elo ({sign_b})"
        )

    # --- vs Bot ---
    player_id = game["player_id"]
    player_elo = get_elo(player_id)
    player_color = game["player_color"]

    if outcome.winner is None:
        score_player = 0.5
    else:
        score_player = 1 if outcome.winner == player_color else 0

    new_player_elo, _, d_player, _ = update_elo(player_id, player_elo, None, BOT_ELO, score_player)
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
        sign_w = f"+{d_white}" if d_white >= 0 else str(d_white)
        sign_b = f"+{d_black}" if d_black >= 0 else str(d_black)
        return (
            f"🏳️ {resigner_name} đã đầu hàng! {winner_name} thắng!\n\n"
            f"⚪ {white_name}: {new_white} Elo ({sign_w})\n"
            f"⚫ {black_name}: {new_black} Elo ({sign_b})"
        )

    player_id = game["player_id"]
    player_elo = get_elo(player_id)
    new_player_elo, _, d_player, _ = update_elo(player_id, player_elo, None, BOT_ELO, 0)
    sign = f"+{d_player}" if d_player >= 0 else str(d_player)
    return f"🏳️ Bạn đã đầu hàng! Bot thắng.\n\nElo của bạn: {new_player_elo} ({sign})"


def chess_hint(cid, hinter_id):
    """Gợi ý nước đi tốt nhất theo đánh giá vật chất nông (dùng lại logic của bot).
    Trừ Elo người xin gợi ý. Trả về (text_gợi_ý, elo_mới)."""
    game = _chess_games[cid]
    board = game["board"]
    mover_color = board.turn

    best_score = None
    best_moves = []
    for move in board.legal_moves:
        board.push(move)
        if board.is_checkmate():
            score = 1000
        else:
            score = _material_score(board, mover_color) + (0.5 if board.is_check() else 0)
        board.pop()
        if best_score is None or score > best_score:
            best_score = score
            best_moves = [move]
        elif score == best_score:
            best_moves.append(move)

    move = random.choice(best_moves)
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
    return f"⚪ **{player_name}** — {get_elo(player_id)} Elo\n⚫ **Bot** — {BOT_ELO} Elo"


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
