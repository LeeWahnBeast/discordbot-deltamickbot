import asyncio
import time
import discord
import feedparser
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent
from firebase_admin import firestore

CHANNEL_ID = 1528570574807236688
ROLE = "<@&1534358042496335942>"
USERNAME = "tahnuyo_0"

# Đổi thành instance RSSHub bạn tự host (khuyến nghị mạnh).
# Public rsshub.app hay bị TikTok chặn -> feed rỗng, im lặng không lỗi.
RSSHUB_BASE = "https://rsshub.app"

FIRESTORE_COLLECTION = "tiktok_bot"
FIRESTORE_DOC = "last_video"

_sent_live = False
_last_video = None
_video_state_loaded = False  # đánh dấu đã load state từ Firestore chưa


def _get_last_video_from_firestore():
    try:
        db = firestore.client()
        doc = db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOC).get()
        if doc.exists:
            return doc.to_dict().get("link")
    except Exception as ex:
        print(f"[tiktok] lỗi đọc Firestore: {ex!r}")
    return None


def _save_last_video_to_firestore(link):
    try:
        db = firestore.client()
        db.collection(FIRESTORE_COLLECTION).document(FIRESTORE_DOC).set(
            {"link": link, "updated_at": int(time.time())}
        )
    except Exception as ex:
        print(f"[tiktok] lỗi ghi Firestore: {ex!r}")


async def _video_loop(bot):
    global _last_video, _video_state_loaded

    url = f"{RSSHUB_BASE}/tiktok/user/{USERNAME}"

    while True:
        try:
            if not _video_state_loaded:
                # Lấy state đã lưu lần chạy trước từ Firestore (nếu có)
                _last_video = await asyncio.to_thread(_get_last_video_from_firestore)
                _video_state_loaded = True
                print(f"[tiktok] đã load state từ Firestore: {_last_video}")

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
                    await asyncio.to_thread(_save_last_video_to_firestore, post.link)

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
