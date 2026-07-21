import random

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
FRUITS = {
    "apple": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/15/Red_Apple.jpg/320px-Red_Apple.jpg",
    "banana": "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8a/Banana-Single.jpg/320px-Banana-Single.jpg",
    "mango": "https://upload.wikimedia.org/wikipedia/commons/thumb/6/62/Mango_Alphonso.jpg/320px-Mango_Alphonso.jpg",
    "grape": "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a7/Table_grapes_on_white.jpg/320px-Table_grapes_on_white.jpg",
    "orange": "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c4/Orange-Fruit-Pieces.jpg/320px-Orange-Fruit-Pieces.jpg",
    "watermelon": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/29/Watermelon_cross_BNC.jpg/320px-Watermelon_cross_BNC.jpg",
    "pineapple": "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ed/Pineapple_and_cross_section.jpg/320px-Pineapple_and_cross_section.jpg",
    "strawberry": "https://upload.wikimedia.org/wikipedia/commons/thumb/9/95/PerfectStrawberry.jpg/320px-PerfectStrawberry.jpg",
    "pear": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/Pears.jpg/320px-Pears.jpg",
    "peach": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b6/Autumn_Red_peaches.jpg/320px-Autumn_Red_peaches.jpg",
    "kiwi": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/28/Kiwi_aka.jpg/320px-Kiwi_aka.jpg",
    "lemon": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Lemon.jpg/320px-Lemon.jpg",
    "cherry": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/45/Cherry_Stella444.jpg/320px-Cherry_Stella444.jpg",
    "coconut": "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/Kokosnuss.jpg/320px-Kokosnuss.jpg",
    "papaya": "https://upload.wikimedia.org/wikipedia/commons/thumb/1/1a/Carica_papaya_fruits.jpg/320px-Carica_papaya_fruits.jpg",
}
_fruit_games = {}  # {channel_id: {"round", "score", "fruit"}}


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
    return FRUITS[fruit]


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
