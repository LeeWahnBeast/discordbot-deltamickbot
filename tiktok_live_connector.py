import asyncio
import discord
from TikTokLive import TikTokLiveClient
from TikTokLive.events import ConnectEvent

CHANNEL_ID = 123456789012345678
ROLE = "<@&1534358042496335942>"

async def setup(bot):
    client = TikTokLiveClient(unique_id="@tahnuyo_0")

    @client.on(ConnectEvent)
    async def live(event):
        channel = bot.get_channel(CHANNEL_ID)
        if not channel:
            return

        embed = discord.Embed(
            title="🥀🥀🥀 delta mommy asmr trên live kìa",
            description=f"Vào nghe nói lẹ các {ROLE}",
            color=0xFF0050,
            url="https://www.tiktok.com/@tahnuyo_0/live"
        )

        embed.set_thumbnail(url="https://unavatar.io/tiktok/tahnuyo_0")

        await channel.send(embed=embed)

    asyncio.create_task(client.start())