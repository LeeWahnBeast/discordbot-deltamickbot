import discord
import os
import web_server
import games
from discord.ext import commands

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"✅ Đã đồng bộ {len(synced)} slash command(s)")
    except Exception as e:
        print(f"⚠️ Lỗi đồng bộ slash command: {e}")
    print(f"✅ Bot đã đăng nhập với tên {bot.user}")


# ============ CHAT THẲNG ĐỂ ĐOÁN (không cần lệnh) ============
@bot.event
async def on_message(message):
    if message.author.bot:
        return

    cid = message.channel.id
    content = message.content.strip()

    if not content.startswith("!") and not content.startswith("/"):
        if games.wordle_active(cid):
            word = content.lower()
            if len(word) == 5 and word.isalpha():
                result, correct, done = games.wordle_check(cid, word)
                await message.channel.send(f"`{word.upper()}`\n{result}")
                if correct:
                    await message.channel.send(f"🎉 Chính xác! {message.author.mention} đã đoán đúng!")
                    games.wordle_end(cid)
                elif done:
                    await message.channel.send(f"💀 Hết lượt! Từ đúng là: **{games._wordle_games[cid]['word'].upper()}**")
                    games.wordle_end(cid)
            return

        if games.flag_active(cid):
            await _handle_round(message, content, "flag", 0x3F7D20, "🏳️")
            return

        if games.fruit_active(cid):
            await _handle_round(message, content, "fruit", 0xE8590C, "🍉")
            return

    await bot.process_commands(message)


async def _handle_round(message, guess_text, kind, color, icon):
    """Xử lý chung cho flag & fruit vì logic giống nhau"""
    cid = message.channel.id
    check = games.flag_check if kind == "flag" else games.fruit_check
    answer_fn = games.flag_answer if kind == "flag" else games.fruit_answer
    progress_fn = games.flag_progress if kind == "flag" else games.fruit_progress
    next_fn = games.flag_next if kind == "flag" else games.fruit_next
    end_fn = games.flag_end if kind == "flag" else games.fruit_end
    noun = "quốc gia" if kind == "flag" else "trái cây"

    correct, has_next = check(cid, guess_text)
    answer = answer_fn(cid)
    round_num, total, score = progress_fn(cid)

    if correct:
        await message.channel.send(f"✅ Chính xác! Đó là **{answer.title()}**! (Điểm: {score}/{round_num})")
    else:
        await message.channel.send(f"❌ Sai rồi! Đáp án là **{answer.title()}**! (Điểm: {score}/{round_num})")

    if has_next:
        url = next_fn(cid)
        embed = discord.Embed(
            title=f"{icon} Vòng tiếp theo ({round_num + 1}/{total})",
            description=f"Chat thẳng tên {noun} (tiếng Anh) để đoán!",
            color=color,
        )
        embed.set_image(url=url)
        await message.channel.send(embed=embed)
    else:
        tier, flavor, rank_color = games.folk_valley_rank(score, total)
        end_fn(cid)
        embed = discord.Embed(
            title="🌾 TỔNG KẾT — FOLK VALLEY 🌾",
            description=f"**Điểm số: {score}/{total}**\n\n{flavor}",
            color=rank_color,
        )
        embed.add_field(name="Xếp loại", value=f"## {tier}")
        embed.set_footer(text="Folk Valley thì thầm: hẹn gặp lại ở vòng đoán sau...")
        await message.channel.send(embed=embed)


# ============ NÚT CHỌN ĐỘ KHÓ CHO /flag ============
class DifficultyView(discord.ui.View):
    def __init__(self, cid):
        super().__init__(timeout=30)
        self.cid = cid

    async def start_with(self, interaction, difficulty, label):
        if games.flag_active(self.cid):
            await interaction.response.send_message("⚠️ Đang có ván đoán cờ chưa xong!", ephemeral=True)
            return
        url = games.flag_start(self.cid, difficulty)
        embed = discord.Embed(
            title=f"🏳️ Đoán cờ — {label} (1/{games.ROUNDS_PER_GAME})",
            description="Chat thẳng tên quốc gia (tiếng Anh) để đoán!",
            color=0x3F7D20,
        )
        embed.set_image(url=url)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

    @discord.ui.button(label="🌱 Dễ", style=discord.ButtonStyle.success)
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, "easy", "🌱 Dễ")

    @discord.ui.button(label="🌾 Trung bình", style=discord.ButtonStyle.primary)
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, "medium", "🌾 Trung bình")

    @discord.ui.button(label="🔥 Khó", style=discord.ButtonStyle.danger)
    async def hard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, "hard", "🔥 Khó")

    @discord.ui.button(label="💀 Insane", style=discord.ButtonStyle.secondary)
    async def insane(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, "insane", "💀 Insane")


# ============ SLASH COMMANDS ============
@bot.tree.command(name="ping", description="Kiểm tra độ trễ của bot")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")


@bot.tree.command(name="wordle", description="Bắt đầu ván Wordle — chat thẳng 5 chữ để đoán")
async def wordle_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.wordle_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván Wordle chưa xong!", ephemeral=True)
        return
    games.wordle_start(cid)
    embed = discord.Embed(
        title="🎮 Wordle bắt đầu!",
        description=(
            f"Chat thẳng một từ **5 chữ cái** để đoán (không cần lệnh).\n"
            f"Tối đa **{games.WORDLE_MAX_GUESSES} lượt**.\n\n"
            "🟩 đúng vị trí ・ 🟨 đúng chữ sai vị trí ・ ⬜ sai"
        ),
        color=0x2ECC71,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="flag", description="Đoán cờ các nước — chọn độ khó trước khi bắt đầu")
async def flag_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.flag_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván đoán cờ chưa xong!", ephemeral=True)
        return
    view = DifficultyView(cid)
    embed = discord.Embed(
        title="🏳️ Chọn độ khó",
        description=(
            "🌱 **Dễ** — các nước nổi tiếng\n"
            "🌾 **Trung bình** — các nước quen thuộc vừa phải\n"
            "🔥 **Khó** — các nước ít gặp hơn\n"
            "💀 **Insane** — các nước siêu hiếm!"
        ),
        color=0x3F7D20,
    )
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="fruit", description="Đoán tên trái cây qua hình ảnh")
async def fruit_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.fruit_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván đoán trái cây chưa xong!", ephemeral=True)
        return
    url = games.fruit_start(cid)
    embed = discord.Embed(
        title=f"🍉 Đoán trái cây! (1/{games.ROUNDS_PER_GAME})",
        description="Chat thẳng tên trái cây (tiếng Anh) để đoán!",
        color=0xE8590C,
    )
    embed.set_image(url=url)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="endgame", description="Hủy ván chơi đang diễn ra trong kênh này")
async def endgame_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    ended = []
    if games.wordle_active(cid):
        games.wordle_end(cid)
        ended.append("Wordle")
    if games.flag_active(cid):
        games.flag_end(cid)
        ended.append("Đoán cờ")
    if games.fruit_active(cid):
        games.fruit_end(cid)
        ended.append("Đoán trái cây")

    if ended:
        await interaction.response.send_message(f"🛑 Đã hủy ván: {', '.join(ended)}")
    else:
        await interaction.response.send_message("❌ Không có ván nào đang diễn ra.")


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
