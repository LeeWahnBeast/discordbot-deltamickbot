import random

# country_name: flagcdn 2-letter code
COUNTRIES = {
    "vietnam": "vn", "japan": "jp", "korea": "kr", "china": "cn",
    "usa": "us", "united states": "us", "canada": "ca", "mexico": "mx",
    "brazil": "br", "argentina": "ar", "france": "fr", "germany": "de",
    "italy": "it", "spain": "es", "portugal": "pt", "russia": "ru",
    "uk": "gb", "england": "gb", "united kingdom": "gb", "ireland": "ie",
    "netherlands": "nl", "belgium": "be", "switzerland": "ch",
    "sweden": "se", "norway": "no", "finland": "fi", "denmark": "dk",
    "poland": "pl", "greece": "gr", "turkey": "tr", "egypt": "eg",
    "india": "in", "thailand": "th", "singapore": "sg", "malaysia": "my",
    "indonesia": "id", "philippines": "ph", "australia": "au",
    "new zealand": "nz", "south africa": "za", "nigeria": "ng",
    "saudi arabia": "sa", "uae": "ae", "israel": "il", "iran": "ir",
    "iraq": "iq", "pakistan": "pk", "bangladesh": "bd", "cuba": "cu",
    "chile": "cl", "peru": "pe", "colombia": "co", "ukraine": "ua",
    "austria": "at", "czech republic": "cz", "hungary": "hu",
    "romania": "ro", "iceland": "is", "scotland": "gb-sct",
}

active_flag_games = {}  # {channel_id: {"country": name, "code": code}}


def start_flag_game(channel_id):
    country = random.choice(list(COUNTRIES.keys()))
    code = COUNTRIES[country]
    active_flag_games[channel_id] = {"country": country, "code": code}
    return f"https://flagcdn.com/w320/{code}.png"


def is_flag_game_active(channel_id):
    return channel_id in active_flag_games


def check_flag_guess(channel_id, guess):
    game = active_flag_games[channel_id]
    return guess.strip().lower() == game["country"]


def get_answer(channel_id):
    return active_flag_games[channel_id]["country"]


def end_flag_game(channel_id):
    if channel_id in active_flag_games:
        del active_flag_games[channel_id]
