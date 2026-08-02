import discord
from discord.ext import commands
import asyncio

class DmSpamCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="dmspam")
    async def dmspam(self, ctx, count: int = 100):
        user_id = 1210771747889090571
        user = await self.bot.fetch_user(user_id)
        msg = "con chó vào code hộ tao🤣🤣🤣🤣 gà kid con toàn đi kiếm chuyện kẻ yếu mà đòi mạnh nhất ss🤣🤣🤣🤣🤣🤣🤣"
        for _ in range(count):
            await user.send(msg)
            await asyncio.sleep(0.2)
        await ctx.send("done")

async def setup(bot):
    await bot.add_cog(DmSpamCog(bot))