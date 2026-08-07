import asyncio
import aiohttp
import yt_dlp

USERNAME = "tahnuyo_0"
GUILD_ID = 1528554640378171562

async def update_tiktok_avatar(bot):
    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            ydl = yt_dlp.YoutubeDL({
                "quiet": True,
                "extract_flat": False
            })

            info = ydl.extract_info(
                f"https://www.tiktok.com/@{USERNAME}",
                download=False
            )

            avatar = None

            if info.get("thumbnails"):
                avatar = info["thumbnails"][-1]["url"]

            if avatar:
                async with aiohttp.ClientSession() as session:
                    async with session.get(avatar) as resp:
                        if resp.status == 200:
                            icon = await resp.read()
                            guild = bot.get_guild(GUILD_ID)

                            if guild:
                                await guild.edit(icon=icon)
                                print("Server icon updated.")

        except Exception as e:
            print(f"TikTok Avatar Error: {e}")

        await asyncio.sleep(7200)