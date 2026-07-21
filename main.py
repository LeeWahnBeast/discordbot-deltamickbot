import discord
import os
import web_server
import wordle_game
import flag_game
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    print(f'Bot đã đăng nhập với tên {bot.user}')


@bot.event
async def on_message(message):
    # Bỏ qua tin nhắn của chính bot ngay lập tức (tránh loop)
    if message.author.bot:
        return

    channel_id = message.channel.id
    content = message.content.strip()

    # Chỉ xử lý nếu KHÔNG phải lệnh "!" và có game đang chạy trong kênh này
    # -> return sớm nhất có thể để không tốn CPU cho tin nhắn không liên quan
    if not content.startswith("!"):
        # --- Xử lý đoán Wordle ---
        if wordle_game.is_game_active(channel_id):
            word = content.lower()
            if len(word) == 5 and word.isalpha():
                result, correct, out_of_guesses = wordle_game.check_guess(channel_id, word)
                await message.channel.send(f"`{word.upper()}`\n{result}")

                if correct:
                    await message.channel.send(f"🎉 Chính xác! {message.author.mention} đã đoán đúng!")
                    wordle_game.end_game(channel_id)
                elif out_of_guesses:
                    answer = wordle_game.active_games[channel_id]["word"]
                    await message.channel.send(f"💀 Hết lượt! Từ đúng là: **{answer.upper()}**")
                    wordle_game.end_game(channel_id)
                return

        # --- Xử lý đoán cờ ---
        if flag_game.is_flag_game_active(channel_id):
            if flag_game.check_flag_guess(channel_id, content):
                answer = flag_game.get_answer(channel_id)
                await message.channel.send(f"🎉 Chính xác! Đó là lá cờ **{answer.title()}**! {message.author.mention}")
                flag_game.end_flag_game(channel_id)
            return

    # Cho phép lệnh "!" hoạt động bình thường
    await bot.process_commands(message)


@bot.command()
async def ping(ctx):
    await ctx.send(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")


@bot.command()
async def wordle(ctx):
    """Bắt đầu ván Wordle - chat thẳng 5 chữ cái để đoán, không cần lệnh"""
    channel_id = ctx.channel.id

    if wordle_game.is_game_active(channel_id):
        await ctx.send("⚠️ Đang có ván Wordle chưa xong! Chat thẳng từ 5 chữ để đoán, hoặc `!endwordle` để hủy.")
        return

    wordle_game.start_game(channel_id, ctx.author.id)
    await ctx.send(
        f"🎮 **Wordle bắt đầu!** Chat thẳng một từ **5 chữ cái** để đoán (không cần `!`).\n"
        f"Tối đa **{wordle_game.MAX_GUESSES} lượt**. 🟩 đúng vị trí, 🟨 đúng chữ sai vị trí, ⬜ sai."
    )


@bot.command()
async def endwordle(ctx):
    channel_id = ctx.channel.id
    if wordle_game.is_game_active(channel_id):
        wordle_game.end_game(channel_id)
        await ctx.send("🛑 Đã hủy ván Wordle.")
    else:
        await ctx.send("❌ Không có ván Wordle nào đang diễn ra.")


@bot.command()
async def flag(ctx):
    """Bắt đầu ván đoán cờ - chat thẳng tên nước để đoán, không cần lệnh"""
    channel_id = ctx.channel.id

    if flag_game.is_flag_game_active(channel_id):
        await ctx.send("⚠️ Đang có ván đoán cờ chưa xong! Chat thẳng tên nước để đoán, hoặc `!endflag` để hủy.")
        return

    flag_url = flag_game.start_flag_game(channel_id)
    embed = discord.Embed(title="🏳️ Đoán lá cờ này là nước nào?", color=discord.Color.blue())
    embed.set_image(url=flag_url)
    await ctx.send(embed=embed)


@bot.command()
async def endflag(ctx):
    channel_id = ctx.channel.id
    if flag_game.is_flag_game_active(channel_id):
        answer = flag_game.get_answer(channel_id)
        flag_game.end_flag_game(channel_id)
        await ctx.send(f"🛑 Đã hủy. Đáp án là: **{answer.title()}**")
    else:
        await ctx.send("❌ Không có ván đoán cờ nào đang diễn ra.")


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
