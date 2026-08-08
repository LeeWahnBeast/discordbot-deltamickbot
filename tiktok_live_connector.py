import asyncio
import time
import json
import discord
import feedparser
import games as _g  # tái dùng kết nối Firestore đã khởi tạo sẵn (_firestore_db)
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent

CHANNEL_ID = 1528570574807236688
ROLE = "<@&1534358042496335942>"
USERNAME = "tahnuyo_0"

# Đổi thành instance RSSHub bạn tự host (khuyến nghị mạnh).
# Public rsshub.app hay bị TikTok chặn -> feed rỗng, im lặng không lỗi.
RSSHUB_BASE = "https://rsshub.app"

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


async def _video_loop(bot):
    global _last_video, _video_state_loaded

    url = f"{RSSHUB_BASE}/tiktok/user/{USERNAME}"

    while True:
        try:
            if not _video_state_loaded:
                # Lấy state đã lưu lần chạy trước (Firestore, hoặc file JSON nếu chưa nối Firestore)
                _last_video = await asyncio.to_thread(_load_last_video)
                _video_state_loaded = True
                print(f"[tiktok] đã load state trước đó: {_last_video}")

            feed = feedparser.parse(url)

            if feed.bozo:
                print(f"[tiktok] feed lỗi parse: {feed.bozo_exception}")

            if not feed.entries:
                print(f"[tiktok] feed rỗng, status={getattr(feed, 'status', '?')} - "
                      f"khả năng rsshub bị chặn / cần cookie")
            else:
                post = feed.entries[0]
                print(f"[tiktok] entry mới nhất: {post.link}")

                if post.link != _last_video:
                    _last_video = post.link
                    await asyncio.to_thread(_save_last_video, post.link)

                    ch = bot.get_channel(CHANNEL_ID)
                    if ch is None:
                        print(f"[tiktok] LỖI: không tìm thấy channel {CHANNEL_ID}")
                    else:
                        # Lấy giờ đăng thật từ feed nếu có, không thì dùng giờ hiện tại
                        if getattr(post, "published_parsed", None):
                            posted_unix = int(time.mktime(post.published_parsed))
                        else:
                            posted_unix = int(time.time())

                        e = discord.Embed(
                            title="🤣 delta mommy vừa up cái video xỉn rượu kìa🤣🤣🤣",
                            description=f"Ohhh shiiii🤣🤣🥀🥀 {ROLE}\n\n"
                                        f"Thằng delta ỉa cái vid nhảm cho m xem r kìa🤣🤣🤣\n\n"
                                        f"Đăng lúc: <t:{posted_unix}:F> (<t:{posted_unix}:R>)",
                            color=0xFF0050,
                            url=post.link
                        )
                        await ch.send(content=ROLE, embed=e)
        except Exception as ex:
            print(f"[tiktok] exception trong video loop: {ex}")

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
