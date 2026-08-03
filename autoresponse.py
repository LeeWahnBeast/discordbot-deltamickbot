import discord
from discord.ext import commands
from autoresponse import responses

class AutoResponse(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        msg = message.content.lower()

        for trigger, data in responses.items():
            if trigger in msg:
                if data["image"]:
                    await message.channel.send(
                        data["text"],
                        file=discord.File(data["image"])
                    )
                else:
                    await message.channel.send(data["text"])
                break

async def setup(bot):
    await bot.add_cog(AutoResponse(bot))