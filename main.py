import discord
import os
import web_server
import games
from discord.ext import commands
from discord import app_commands

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
                    await message.channel.send(f"💀 Hết lượt! Từ đúng là: **{games.wordle_word(cid).upper()}**")
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
        await message.channel.send(embed=embed, view=EndGameView(cid, kind))
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


# ============ NÚT "🛑 Kết thúc" DÙNG CHUNG CHO MỌI GAME ============
GAME_CONFIG = {
    "wordle": {
        "active": games.wordle_active,
        "end": games.wordle_end,
        "label": "Wordle",
        "reveal": lambda cid: f"Từ đúng là **{games.wordle_word(cid).upper()}**",
    },
    "flag": {
        "active": games.flag_active,
        "end": games.flag_end,
        "label": "Đoán cờ",
        "reveal": lambda cid: f"Đáp án là **{games.flag_answer(cid).title()}**",
    },
    "fruit": {
        "active": games.fruit_active,
        "end": games.fruit_end,
        "label": "Đoán trái cây",
        "reveal": lambda cid: f"Đáp án là **{games.fruit_answer(cid).title()}**",
    },
    "ttt": {
        "active": games.ttt_active,
        "end": games.ttt_end,
        "label": "Cờ caro",
        "reveal": lambda cid: "Ván đấu đã dừng.",
    },
    "chess": {
        "active": games.chess_active,
        "end": games.chess_end,
        "label": "Cờ vua",
        "reveal": lambda cid: "Ván đấu đã dừng.",
    },
}


def make_end_button(cid, kind, row=None):
    """Tạo nút Kết thúc dùng chung — gắn được vào bất kỳ View nào"""
    cfg = GAME_CONFIG[kind]
    button = discord.ui.Button(label="🛑 Kết thúc", style=discord.ButtonStyle.danger, row=row)

    async def callback(interaction: discord.Interaction):
        if not cfg["active"](cid):
            await interaction.response.send_message(f"❌ Ván {cfg['label']} đã kết thúc rồi.", ephemeral=True)
            return
        text = f"🛑 Đã kết thúc ván {cfg['label']}. {cfg['reveal'](cid)}"
        cfg["end"](cid)
        await interaction.response.edit_message(content=text, embed=None, view=None)

    button.callback = callback
    return button


class EndGameView(discord.ui.View):
    """View chỉ gồm nút Kết thúc — dùng cho wordle/flag/fruit/chess"""
    def __init__(self, cid, kind, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(make_end_button(cid, kind))


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
        await interaction.response.edit_message(content=None, embed=embed, view=EndGameView(self.cid, "flag"))

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
        self.add_item(make_end_button(cid, "ttt", row=3))

    def render_board(self):
        board = games.ttt_board(self.cid)
        for child in self.children:
            if not isinstance(child, TicTacToeButton):
                continue
            mark = board[child.index]
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


# ============ UI CỜ VUA (chọn quân + chọn ô bằng dropdown, không cần gõ ký hiệu) ============
def _chess_current_player_id(cid):
    """Trả về user_id của người cần đi nước tiếp theo, dùng chung cho vs-bot & PvP"""
    if games.chess_is_pvp(cid):
        return games.chess_current_turn_id(cid)
    return games.chess_player_id(cid)


def _chess_display_names(cid):
    """Trả về dict {True: mention_trắng, False: mention_đen}, dùng chung cho vs-bot & PvP"""
    if games.chess_is_pvp(cid):
        game = games._chess_games[cid]
        return {True: f"<@{game['white_id']}>", False: f"<@{game['black_id']}>"}
    game = games._chess_games[cid]
    return {True: f"<@{game['player_id']}>", False: "Bot"}


def _add_chess_action_buttons(view, cid):
    """Thêm 2 nút Đầu hàng + Gợi ý (dùng chung cho ChessFromView và ChessToView)"""
    resign_btn = discord.ui.Button(label="🏳️ Đầu hàng", style=discord.ButtonStyle.danger, row=4)

    async def on_resign(interaction: discord.Interaction):
        if games.chess_is_pvp(cid):
            game = games._chess_games[cid]
            if interaction.user.id not in (game["white_id"], game["black_id"]):
                await interaction.response.send_message("❌ Đây không phải ván của bạn!", ephemeral=True)
                return
        else:
            if interaction.user.id != games.chess_player_id(cid):
                await interaction.response.send_message("❌ Đây không phải ván của bạn!", ephemeral=True)
                return

        names = _chess_display_names(cid)
        text = games.chess_resign_text(cid, interaction.user.id, names)
        games.chess_end(cid)
        embed = discord.Embed(description=text, color=0x2C3E50)
        await interaction.response.edit_message(embed=embed, attachments=[], view=None)

    resign_btn.callback = on_resign
    view.add_item(resign_btn)

    hint_btn = discord.ui.Button(
        label=f"💡 Gợi ý (-{games.HINT_ELO_PENALTY} Elo)", style=discord.ButtonStyle.secondary, row=4
    )

    async def on_hint(interaction: discord.Interaction):
        if interaction.user.id != _chess_current_player_id(cid):
            await interaction.response.send_message("❌ Chỉ người đến lượt mới xin gợi ý được!", ephemeral=True)
            return
        hint_text, new_elo = games.chess_hint(cid, interaction.user.id)
        await interaction.response.send_message(
            f"{hint_text}\n(Elo của bạn giờ còn **{new_elo}**)", ephemeral=True
        )

    hint_btn.callback = on_hint
    view.add_item(hint_btn)


def _chess_board_embed(cid, extra_line=None):
    """Dựng embed chuẩn cho bàn cờ: header Elo 2 người chơi + (tuỳ chọn) 1 dòng phụ (VD: đến lượt ai)"""
    names = _chess_display_names(cid)
    header = games.chess_header_text(cid, names)
    description = f"{header}\n\n{extra_line}" if extra_line else header
    embed = discord.Embed(description=description, color=0x2C3E50)
    embed.set_image(url="attachment://board.png")
    return embed


class ChessFromView(discord.ui.View):
    """Bước 1: chọn quân muốn đi"""
    def __init__(self, cid):
        super().__init__(timeout=180)
        self.cid = cid
        options = games.chess_from_options(cid)[:25]
        select = discord.ui.Select(
            placeholder="♟️ Chọn quân muốn đi...",
            options=[discord.SelectOption(label=label, value=val) for val, label in options],
        )
        select.callback = self.on_select
        self.add_item(select)
        self.add_item(make_end_button(cid, "chess"))
        _add_chess_action_buttons(self, cid)

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != _chess_current_player_id(self.cid):
            await interaction.response.send_message("❌ Chưa đến lượt bạn!", ephemeral=True)
            return
        from_sq = interaction.data["values"][0]
        await interaction.response.edit_message(view=ChessToView(self.cid, interaction.user.id, from_sq))


class ChessToView(discord.ui.View):
    """Bước 2: chọn ô muốn đi tới"""
    def __init__(self, cid, player_id, from_sq):
        super().__init__(timeout=180)
        self.cid = cid
        self.player_id = player_id
        self.from_sq = from_sq
        options = games.chess_to_options(cid, from_sq)[:25]
        select = discord.ui.Select(
            placeholder=f"👉 Đi quân ở {from_sq} đến đâu?",
            options=[discord.SelectOption(label=label, value=val) for val, label in options],
        )
        select.callback = self.on_select
        self.add_item(select)
        back = discord.ui.Button(label="🔙 Chọn lại", style=discord.ButtonStyle.secondary)
        back.callback = self.on_back
        self.add_item(back)
        self.add_item(make_end_button(cid, "chess"))
        _add_chess_action_buttons(self, cid)

    async def on_back(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Đây không phải ván của bạn!", ephemeral=True)
            return
        await interaction.response.edit_message(view=ChessFromView(self.cid))

    async def on_select(self, interaction: discord.Interaction):
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("❌ Đây không phải ván của bạn!", ephemeral=True)
            return

        to_sq = interaction.data["values"][0]
        outcome = games.chess_make_move(self.cid, self.from_sq, to_sq)

        # Vs Bot: sau khi người đi xong, đến lượt bot đánh ngay
        if outcome is None and not games.chess_is_pvp(self.cid):
            outcome = games.chess_bot_move(self.cid)

        image = games.chess_board_image(self.cid)
        file = discord.File(image, filename="board.png")

        if outcome is not None:
            names = _chess_display_names(self.cid)
            text = games.chess_outcome_text(self.cid, outcome, names)
            games.chess_end(self.cid)
            embed = discord.Embed(description=text, color=0x2C3E50)
            embed.set_image(url="attachment://board.png")
            await interaction.response.edit_message(embed=embed, attachments=[file], view=None)
        else:
            extra = f"👉 Đến lượt <@{games.chess_current_turn_id(self.cid)}>!" if games.chess_is_pvp(self.cid) else None
            embed = _chess_board_embed(self.cid, extra)
            new_view = ChessFromView(self.cid)
            await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)




# ============ SLASH COMMANDS ============
@bot.tree.command(name="ping", description="Kiểm tra độ trễ của bot")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")


@bot.tree.command(name="about", description="Thông tin về bot")
async def about_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 About Bot",
        description="Bot mini-game vui nhộn cho server: đoán chữ, đoán cờ, đoán trái cây, cờ caro, cờ vua và bói vui.",
        color=0x5865F2,
    )
    embed.add_field(
        name="🎮 Các lệnh",
        value=(
            "`/wordle` — đoán từ 5 chữ\n"
            "`/flag` — đoán cờ các nước\n"
            "`/fruit` — đoán tên trái cây qua hình\n"
            "`/caro` — cờ caro vs bot\n"
            "`/chess` — cờ vua vs bot\n"
            "`/chess_invite @ai_đó` — mời PvP cờ vua\n"
            "`/chess_reset` — xóa ván cờ bị kẹt (nếu bot báo lỗi)\n"
            "`/whatuinto` — bói vui\n"
            "`/wiki <từ khóa>` — tra bách khoa toàn thư\n"
            "`/ping` — kiểm tra độ trễ"
        ),
        inline=False,
    )
    embed.set_footer(text="Made by TVPixel")
    await interaction.response.send_message(embed=embed)


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
    await interaction.response.send_message(embed=embed, view=EndGameView(cid, "wordle"))


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
    await interaction.response.send_message(embed=embed, view=EndGameView(cid, "fruit"))


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


@bot.tree.command(name="chess", description="Chơi cờ vua với bot (bạn cầm quân Trắng)")
async def chess_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.chess_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván cờ vua chưa xong trong kênh này!", ephemeral=True)
        return

    games.chess_start(cid, interaction.user.id)
    image = games.chess_board_image(cid)
    file = discord.File(image, filename="board.png")
    embed = _chess_board_embed(cid, "Chọn **quân** rồi chọn **ô muốn đi tới** bằng menu bên dưới.")
    await interaction.response.send_message(embed=embed, file=file, view=ChessFromView(cid))


@bot.tree.command(name="chess_reset", description="Xóa cưỡng bức trạng thái ván cờ bị kẹt trong kênh này")
async def chess_reset_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    existed = games.chess_force_reset(cid)
    if existed:
        await interaction.response.send_message("🧹 Đã xóa trạng thái ván cờ cũ. Giờ có thể dùng `/chess` hoặc `/chess_invite` lại bình thường.")
    else:
        await interaction.response.send_message("ℹ️ Không có ván cờ nào được lưu trong kênh này để xóa.")


class ChessInviteView(discord.ui.View):
    def __init__(self, cid, inviter_id, invitee_id):
        super().__init__(timeout=120)
        self.cid = cid
        self.inviter_id = inviter_id
        self.invitee_id = invitee_id

    @discord.ui.button(label="✅ Chấp nhận", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invitee_id:
            await interaction.response.send_message("❌ Lời mời này không dành cho bạn!", ephemeral=True)
            return
        if games.chess_get_invite(self.cid) is None:
            await interaction.response.send_message("❌ Lời mời đã hết hạn hoặc bị hủy.", ephemeral=True)
            return
        if games.chess_active(self.cid):
            await interaction.response.send_message("⚠️ Đang có ván cờ vua khác chưa xong trong kênh này!", ephemeral=True)
            return

        games.chess_clear_invite(self.cid)
        games.chess_start_pvp(self.cid, self.inviter_id, self.invitee_id)
        image = games.chess_board_image(self.cid)
        file = discord.File(image, filename="board.png")
        embed = _chess_board_embed(self.cid, f"👉 Đến lượt <@{self.inviter_id}>!")
        await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=ChessFromView(self.cid))

    @discord.ui.button(label="❌ Từ chối", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.invitee_id:
            await interaction.response.send_message("❌ Lời mời này không dành cho bạn!", ephemeral=True)
            return
        games.chess_clear_invite(self.cid)
        await interaction.response.edit_message(content="❌ Đã từ chối lời mời chơi cờ vua.", embed=None, view=None)


@bot.tree.command(name="chess_invite", description="Mời người khác chơi cờ vua PvP (bạn cầm Trắng)")
@app_commands.describe(doi_thu="Người bạn muốn mời chơi")
async def chess_invite_slash(interaction: discord.Interaction, doi_thu: discord.Member):
    cid = interaction.channel_id

    if games.chess_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván cờ vua chưa xong trong kênh này!", ephemeral=True)
        return
    if doi_thu.bot:
        await interaction.response.send_message("❌ Không thể mời bot chơi PvP!", ephemeral=True)
        return
    if doi_thu.id == interaction.user.id:
        await interaction.response.send_message("❌ Không thể tự mời chính mình!", ephemeral=True)
        return

    games.chess_create_invite(cid, interaction.user.id, doi_thu.id)
    view = ChessInviteView(cid, interaction.user.id, doi_thu.id)
    await interaction.response.send_message(
        content=(
            f"♟️ {doi_thu.mention}, {interaction.user.mention} mời bạn chơi cờ vua "
            f"({interaction.user.mention} cầm ⚪ Trắng)! Chấp nhận không?"
        ),
        view=view,
    )


@bot.tree.command(name="wiki", description="Tra cứu bách khoa toàn thư (Wikipedia tiếng Việt)")
@app_commands.describe(tu_khoa="Từ khóa cần tra cứu")
async def wiki_slash(interaction: discord.Interaction, tu_khoa: str):
    await interaction.response.defer()  # tra cứu mạng có thể mất vài giây

    result = games.wiki_lookup(tu_khoa)
    if result is None:
        await interaction.followup.send(f"❌ Không tìm thấy thông tin cho **\"{tu_khoa}\"**.")
        return

    title, summary, thumbnail, url = result
    embed = discord.Embed(
        title=f"📖 {title}",
        description=summary,
        url=url,
        color=0x36C5F0,
    )
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    embed.set_footer(text="Nguồn: Wikipedia tiếng Việt")
    await interaction.followup.send(embed=embed)


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
