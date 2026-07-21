import random
import chess  # pip install chess

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
_chess_games = {}  # {channel_id: {"board": chess.Board, "player_id": int, "player_color": bool}}
_PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9}


def chess_active(cid):
    return cid in _chess_games


def chess_start(cid, player_id):
    _chess_games[cid] = {"board": chess.Board(), "player_id": player_id, "player_color": chess.WHITE}


def chess_end(cid):
    _chess_games.pop(cid, None)


def chess_player_id(cid):
    return _chess_games[cid]["player_id"]


def chess_render(cid):
    return str(_chess_games[cid]["board"])


def chess_player_move(cid, text):
    """Người chơi đi 1 nước (SAN vd 'e4', 'Nf3' hoặc UCI vd 'e2e4').
    Trả về (hợp lệ: bool, outcome: chess.Outcome hoặc None nếu ván tiếp tục)"""
    game = _chess_games[cid]
    board = game["board"]
    if board.turn != game["player_color"]:
        return False, None

    text = text.strip()
    move = None
    try:
        move = board.parse_san(text)
    except ValueError:
        try:
            candidate = chess.Move.from_uci(text.lower())
            if candidate in board.legal_moves:
                move = candidate
        except Exception:
            move = None

    if move is None:
        return False, None

    board.push(move)
    return True, board.outcome()


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


def chess_outcome_text(cid, outcome):
    player_color = _chess_games[cid]["player_color"]
    if outcome.winner is None:
        return "🤝 Hòa!"
    won = outcome.winner == player_color
    return "🎉 Bạn thắng! Bot chịu thua." if won else "🤖 Bot chiếu bí! Bạn thua rồi."
