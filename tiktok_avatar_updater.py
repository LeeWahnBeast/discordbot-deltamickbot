import asyncio
import aiohttp

USERNAME = "tahnuyo_0"
GUILD_ID = 1528554640378171562

_last_avatar = None

async def update_tiktok_avatar(bot):
    global _last_avatar

    await bot.wait_until_ready()

    while not bot.is_closed():
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"https://www.tikwm.com/api/user/info?unique_id={USERNAME}"
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()

                        avatar = (
                            data.get("data", {})
                                .get("user", {})
                                .get("avatarLarger")
                        )

                        if avatar and avatar != _last_avatar:
                            async with session.get(avatar) as img:
                                if img.status == 200:
                                    icon = await img.read()
                                    guild = bot.get_guild(GUILD_ID)

                                    if guild:
                                        await guild.edit(icon=icon)
                                        _last_avatar = avatar
                                        print("Server icon updated.")

        except Exception as e:
            print(f"Avatar updater: {e}")

        await asyncio.sleep(18000)