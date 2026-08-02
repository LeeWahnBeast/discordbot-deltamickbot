import discord
from discord.ext import commands
import asyncio

class DmSpamCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="dmspam")
    async def dmspam(self, ctx, count: int = 100):
        user_id = 1314617091139305584
        user = await self.bot.fetch_user(user_id)
        msg = "Mày đã bị raid spam dm đến khi mày ngừng cái việc đó thì bot tao sẽ ngừng - bot bởi <@1210771747889090571>"
        for _ in range(count):
            await user.send(msg)
            await asyncio.sleep(0.2)
        await ctx.send("done")

async def setup(bot):
    await bot.add_cog(DmSpamCog(bot))