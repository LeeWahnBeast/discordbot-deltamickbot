import asyncio
import time
import json
import discord
import yt_dlp
import games as _g  # tái dùng kết nối Firestore đã khởi tạo sẵn (_firestore_db)
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent

CHANNEL_ID = 1528570574807236688
ROLE = "<@&1534358042496335942>"
USERNAME = "tahnuyo_0"

FIRESTORE_COLLECTION = "tiktok_state"
FIRESTORE_DOC_ID = "last_video"
TIKTOK_STATE_FILE = "tiktok_last_video.json"  # fallback khi chưa có Firestore

_sent_live = False
_last_video = None
_video_state_loaded = False  # đánh dấu đã load state (Firestore/file) chưa


def _load_last_video():
    if _g._firestore_db is not None:
        try:
            doc = _g._firestore_db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOC_ID).get()
            if doc.exists:
                return doc.to_dict().get("link")
            return None
        except Exception as ex:
            print(f"[tiktok] lỗi đọc Firestore: {ex!r}")
    try:
        with open(TIKTOK_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f).get("link")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _save_last_video(link):
    if _g._firestore_db is not None:
        try:
            _g._firestore_db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOC_ID).set(
                {"link": link, "updated_at": int(time.time())}
            )
            return
        except Exception as ex:
            print(f"[tiktok] lỗi ghi Firestore: {ex!r}")
    try:
        with open(TIKTOK_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"link": link}, f)
    except Exception as ex:
        print(f"[tiktok] lỗi ghi file fallback: {ex!r}")


def _fetch_latest_video():
    """Lấy video mới nhất của USERNAME trực tiếp từ TikTok bằng yt-dlp (không cần RSSHub/Puppeteer)."""
    profile_url = f"https://www.tiktok.com/@{USERNAME}"
    ydl_opts = {
        "extract_flat": True,   # chỉ lấy danh sách, không tải video thật
        "playlistend": 1,       # chỉ cần video mới nhất
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(profile_url, download=False)
    entries = (info or {}).get("entries") or []
    if not entries:
        return None
    entry = entries[0]
    link = entry.get("webpage_url") or entry.get("url")
    if link and link.startswith("//"):
        link = "https:" + link
    return {
        "link": link,
        "title": entry.get("title"),
        "timestamp": entry.get("timestamp"),
    }


async def _video_loop(bot):
    global _last_video, _video_state_loaded

    while True:
        try:
            if not _video_state_loaded:
                # Lấy state đã lưu lần chạy trước (Firestore, hoặc file JSON nếu chưa nối Firestore)
                _last_video = await asyncio.to_thread(_load_last_video)
                _video_state_loaded = True
                print(f"[tiktok] đã load state trước đó: {_last_video}")

            video = await asyncio.to_thread(_fetch_latest_video)

            if not video or not video.get("link"):
                print("[tiktok] không lấy được video nào (yt-dlp trả về rỗng)")
            else:
                link = video["link"]
                print(f"[tiktok] video mới nhất: {link}")

                if link != _last_video:
                    _last_video = link
                    await asyncio.to_thread(_save_last_video, link)

                    ch = bot.get_channel(CHANNEL_ID)
                    if ch is None:
                        print(f"[tiktok] LỖI: không tìm thấy channel {CHANNEL_ID}")
                    else:
                        # Gửi link thẳng để Discord tự tạo embed video preview (thumbnail, nút mở TikTok...)
                        await ch.send(
                            f"{ROLE}\n\n"
                            f"🤣 delta mommy vừa up cái video xỉn rượu kìa🤣🤣🤣\n\n"
                            f"{link}"
                        )
        except Exception as ex:
            print(f"[tiktok] exception trong video loop: {ex!r}")

        await asyncio.sleep(60)


async def setup(bot):
    global _sent_live
    client = TikTokLiveClient(unique_id="@" + USERNAME)

    @client.on(ConnectEvent)
    async def on_connect(event):
        global _sent_live
        if _sent_live:
            return
        _sent_live = True
        ch = bot.get_channel(CHANNEL_ID)
        if ch is None:
            print(f"[tiktok] LỖI: không tìm thấy channel {CHANNEL_ID} khi live")
            return
        live_unix = int(time.time())
        e = discord.Embed(
            title="🥀🥀🥀 delta mommy asmr trên live kìa",
            description=f"Vào nghe nói lẹ các {ROLE}\n\n"
                        f"Live lúc: <t:{live_unix}:F> (<t:{live_unix}:R>)",
            color=0xFF0050,
            url=f"https://www.tiktok.com/@{USERNAME}/live"
        )
        await ch.send(content=ROLE, embed=e)

    async def _live_loop():
        while True:
            try:
                await client.start()
            except Exception as ex:
                print(f"[tiktok] live client lỗi, reconnect sau 30s: {ex}")
            await asyncio.sleep(30)

    asyncio.create_task(_live_loop())
    asyncio.create_task(_video_loop(bot))
