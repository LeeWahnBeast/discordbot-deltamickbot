import asyncio
import discord
import feedparser
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent

CHANNEL_ID = 1528570574807236688
ROLE = "<@&1534358042496335942>"
USERNAME = "tahnuyo_0"

_sent_live = False
_last_video = None

async def _video_loop(bot):
    global _last_video
    url = f"https://rsshub.app/tiktok/user/{USERNAME}"
    while True:
        try:
            feed = feedparser.parse(url)
            if feed.entries:
                post = feed.entries[0]
                if _last_video is None:
                    _last_video = post.link
                elif post.link != _last_video:
                    _last_video = post.link
                    ch = bot.get_channel(CHANNEL_ID)
                    e = discord.Embed(
                        title="🤣 delta mommy vừa up cái video xỉn rượu kìa🤣🤣🤣",
                        description=f"Ohhh shiiii🤣🤣🥀🥀 {ROLE}\n\nThằng delta ỉa cái vid nhảm cho m xem r kìa🤣🤣🤣",
                        color=0xFF0050,
                        url=post.link
                    )
                    await ch.send(content=ROLE, embed=e)
        except Exception as ex:
            print(ex)
        await asyncio.sleep(60)

async def setup(bot):
    global _sent_live
    client = TikTokLiveClient(unique_id="@"+USERNAME)

    @client.on(ConnectEvent)
    async def on_connect(event):
        global _sent_live
        if _sent_live:
            return
        _sent_live = True
        ch = bot.get_channel(CHANNEL_ID)
        e = discord.Embed(
            title="🥀🥀🥀 delta mommy asmr trên live kìa",
            description=f"Vào nghe nói lẹ các {ROLE}",
            color=0xFF0050,
            url=f"https://www.tiktok.com/@{USERNAME}/live"
        )
        await ch.send(content=ROLE, embed=e)

    asyncio.create_task(client.start())
    asyncio.create_task(_video_loop(bot))
