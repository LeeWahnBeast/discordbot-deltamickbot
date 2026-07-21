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
        view = EndGameView(cid, kind) if kind == "flag" else None
        await message.channel.send(embed=embed, view=view)
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


# ============ NÚT "🛑 Kết thúc" (thay cho /endflag) ============
class EndGameView(discord.ui.View):
    def __init__(self, cid, kind):
        super().__init__(timeout=180)
        self.cid = cid
        self.kind = kind

    @discord.ui.button(label="🛑 Kết thúc", style=discord.ButtonStyle.danger)
    async def end_game(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_active = games.flag_active(self.cid) if self.kind == "flag" else games.fruit_active(self.cid)
        if not is_active:
            await interaction.response.send_message("❌ Ván này đã kết thúc rồi.", ephemeral=True)
            return

        answer_fn = games.flag_answer if self.kind == "flag" else games.fruit_answer
        end_fn = games.flag_end if self.kind == "flag" else games.fruit_end
        answer = answer_fn(self.cid)
        end_fn(self.cid)

        await interaction.response.edit_message(
            content=f"🛑 Đã kết thúc ván. Đáp án vòng này là: **{answer.title()}**",
            embed=None,
            view=None,
        )


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
        view = EndGameView(self.cid, "flag")
        await interaction.response.edit_message(content=None, embed=embed, view=view)

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


# ============ UI CỜ CARO (bàn 3x3 bằng nút) ============
class TicTacToeView(discord.ui.View):
    def __init__(self, cid, player_id):
        super().__init__(timeout=120)
        self.cid = cid
        self.player_id = player_id
        for i in range(9):
            self.add_item(TicTacToeButton(i))

    def render_board(self):
        board = games.ttt_board(self.cid)
        for i, child in enumerate(self.children):
            mark = board[i]
            child.label = mark if mark else "\u200b"
            child.style = (
                discord.ButtonStyle.danger if mark == "X"
                else discord.ButtonStyle.primary if mark == "O"
                else discord.ButtonStyle.secondary
            )
            child.disabled = bool(mark)


class TicTacToeButton(discord.ui.Button):
    def __init__(self, index):
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=index // 3)
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        view: TicTacToeView = self.view

        if interaction.user.id != view.player_id:
            await interaction.response.send_message("❌ Đây không phải ván của bạn!", ephemeral=True)
            return

        if not games.ttt_active(view.cid):
            await interaction.response.send_message("❌ Ván này đã kết thúc.", ephemeral=True)
            return

        valid, result = games.ttt_player_move(view.cid, self.index)
        if not valid:
            await interaction.response.send_message("⚠️ Ô này không hợp lệ!", ephemeral=True)
            return

        if result:
            view.render_board()
            for child in view.children:
                child.disabled = True
            games.ttt_end(view.cid)
            text = _ttt_result_text(result, interaction.user)
            await interaction.response.edit_message(content=text, view=view)
            return

        # Đến lượt bot đánh
        bot_result = games.ttt_bot_move(view.cid)
        view.render_board()

        if bot_result:
            for child in view.children:
                child.disabled = True
            games.ttt_end(view.cid)
            text = _ttt_result_text(bot_result, interaction.user)
            await interaction.response.edit_message(content=text, view=view)
        else:
            await interaction.response.edit_message(content="🎮 Đến lượt bạn (❌)!", view=view)


def _ttt_result_text(result, user):
    if result == "X":
        return f"🎉 {user.mention} thắng! Bot thua tâm phục khẩu phục."
    elif result == "O":
        return "🤖 Bot thắng! Thử lại nhé."
    else:
        return "🤝 Hòa! Cả hai đều chơi khá lắm."


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


class EndAnyGameView(discord.ui.View):
    def __init__(self, cid):
        super().__init__(timeout=60)
        self.cid = cid

        if games.wordle_active(cid):
            self.add_item(self._make_button("Wordle", "wordle"))
        if games.flag_active(cid):
            self.add_item(self._make_button("Đoán cờ", "flag"))
        if games.fruit_active(cid):
            self.add_item(self._make_button("Đoán trái cây", "fruit"))
        if games.ttt_active(cid):
            self.add_item(self._make_button("Cờ caro", "ttt"))

    def _make_button(self, label, kind):
        button = discord.ui.Button(label=f"🛑 {label}", style=discord.ButtonStyle.danger)

        async def callback(interaction: discord.Interaction):
            is_active_fn = {
                "wordle": games.wordle_active,
                "flag": games.flag_active,
                "fruit": games.fruit_active,
                "ttt": games.ttt_active,
            }[kind]
            end_fn = {
                "wordle": games.wordle_end,
                "flag": games.flag_end,
                "fruit": games.fruit_end,
                "ttt": games.ttt_end,
            }[kind]

            if not is_active_fn(self.cid):
                await interaction.response.send_message(f"❌ Ván {label} đã kết thúc rồi.", ephemeral=True)
                return

            end_fn(self.cid)
            await interaction.response.send_message(f"🛑 Đã hủy ván {label}.")

        button.callback = callback
        return button


@bot.tree.command(name="endgame", description="Hủy ván chơi đang diễn ra trong kênh này")
async def endgame_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    view = EndAnyGameView(cid)

    if not view.children:
        await interaction.response.send_message("❌ Không có ván nào đang diễn ra trong kênh này.")
        return

    await interaction.response.send_message("Chọn ván muốn hủy:", view=view)


@bot.tree.command(name="whatuinto", description="Bói vui xem bạn 'thích' thể loại gì 👀")
async def whatuinto_slash(interaction: discord.Interaction):
    label, caption, percent = games.whatuinto_roll()
    embed = discord.Embed(
        title=f"🔮 Kết quả bói cho {interaction.user.display_name}",
        description=f"## {percent}% **{label}**\n\n{caption}",
        color=0xE056FD,
    )
    embed.set_footer(text="Kết quả 100% chính xác khoa học (không có căn cứ gì cả) 😌")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="caro", description="Chơi cờ caro (Tic-Tac-Toe) solo với bot")
async def caro_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.ttt_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván cờ caro chưa xong trong kênh này!", ephemeral=True)
        return

    games.ttt_start(cid, interaction.user.id)
    view = TicTacToeView(cid, interaction.user.id)
    view.render_board()
    await interaction.response.send_message(
        content=f"🎮 {interaction.user.mention} vs 🤖 Bot — Bạn là **❌**, đi trước! Bấm ô để đánh.",
        view=view,
    )


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
