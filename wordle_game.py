import random

# Danh sách từ 5 chữ cái để chơi (có thể thêm bớt tùy ý)
WORDS = [
    "apple", "beach", "chair", "dance", "eagle", "flame", "grape",
    "house", "input", "juice", "knife", "lemon", "mango", "night",
    "ocean", "piano", "queen", "river", "stone", "table", "unity",
    "voice", "water", "xenon", "youth", "zebra", "bread", "cloud",
    "dream", "fruit", "glass", "heart", "image", "joker", "koala",
    "light", "music", "novel", "orbit", "peach", "quiet", "robot",
    "smile", "trust", "urban", "value", "world", "yield", "zonal",
    "amber", "brave", "crown", "delta", "earth", "faith", "giant",
]

MAX_GUESSES = 6

# Lưu game đang diễn ra cho từng kênh: {channel_id: {"word": str, "guesses": int, "player": user_id}}
active_games = {}


def start_game(channel_id, player_id):
    word = random.choice(WORDS)
    active_games[channel_id] = {"word": word, "guesses": 0, "player": player_id}
    return word


def end_game(channel_id):
    if channel_id in active_games:
        del active_games[channel_id]


def is_game_active(channel_id):
    return channel_id in active_games


def check_guess(channel_id, guess):
    """
    Trả về (kết quả emoji dạng str, đã đoán đúng chưa: bool, hết lượt chưa: bool)
    """
    game = active_games[channel_id]
    word = game["word"]
    guess = guess.lower()

    result = []
    word_chars = list(word)

    # Bước 1: đánh dấu 🟩 (đúng vị trí)
    for i, ch in enumerate(guess):
        if i < len(word) and ch == word[i]:
            result.append("🟩")
            word_chars[i] = None  # đã dùng, không cho match lần 2
        else:
            result.append(None)

    # Bước 2: đánh dấu 🟨 (đúng chữ, sai vị trí) hoặc ⬜ (sai)
    for i, ch in enumerate(guess):
        if result[i] is not None:
            continue
        if i < len(word) and ch in word_chars:
            result[i] = "🟨"
            word_chars[word_chars.index(ch)] = None
        else:
            result[i] = "⬜"

    game["guesses"] += 1
    correct = guess == word
    out_of_guesses = game["guesses"] >= MAX_GUESSES

    return "".join(result), correct, out_of_guesses
