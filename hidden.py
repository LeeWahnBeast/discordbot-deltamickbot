import discord
from discord.ext import commands

# ID của bot đối thủ cần tự động xoá tin nhắn
TARGET_BOT_ID = 123456789012345678  # <-- thay bằng user ID thật của bot đó


class Hidden(commands.Cog):
    """
    Tự động xoá mọi tin nhắn của TARGET_BOT_ID ngay khi nó gửi, không cần lệnh.
    Chỉ hook vào on_message (event có sẵn) -> không loop, không polling,
    phù hợp môi trường giới hạn 0.1 CPU.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.id != TARGET_BOT_ID:
            return
        if message.guild is None:
            return

        perms = message.channel.permissions_for(message.guild.me)
        if not perms.manage_messages:
            return

        try:
            await message.delete()
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Hidden(bot))
