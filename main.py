import discord
import os
import web_server
from discord.ext import commands

# intents cần để bot đọc nội dung tin nhắn (bắt buộc với discord.py bản mới)
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập với tên {bot.user}')


@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
