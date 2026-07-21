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
            await _handle_flag_round(message, content)
            return

    await bot.process_commands(message)


async def _deny_unless(interaction: discord.Interaction, allowed: bool, msg="❌ Đây không phải ván của bạn!"):
    """Dùng chung cho mọi callback cần kiểm tra quyền: gửi thông báo lỗi + trả True nếu bị chặn."""
    if not allowed:
        await interaction.response.send_message(msg, ephemeral=True)
        return True
    return False


async def _handle_flag_round(message, guess_text):
    """Xử lý 1 lượt đoán cờ quốc gia."""
    cid = message.channel.id
    correct, has_next = games.flag_check(cid, guess_text)
    answer = games.flag_answer(cid)
    round_num, total, score = games.flag_progress(cid)

    if correct:
        await message.channel.send(f"✅ Chính xác! Đó là **{answer.title()}**! (Điểm: {score}/{round_num})")
    else:
        await message.channel.send(f"❌ Sai rồi! Đáp án là **{answer.title()}**! (Điểm: {score}/{round_num})")

    if has_next:
        url = games.flag_next(cid)
        embed = discord.Embed(
            title=f"🏳️ Vòng tiếp theo ({round_num + 1}/{total})",
            description="Chat thẳng tên quốc gia (tiếng Anh) để đoán!",
            color=0x3F7D20,
        )
        embed.set_image(url=url)
        await message.channel.send(embed=embed, view=EndGameView(cid, "flag"))
    else:
        tier, flavor, rank_color = games.folk_valley_rank(score, total)
        games.flag_end(cid)
        embed = discord.Embed(
            title="🌾 TỔNG KẾT — FOLK VALLEY 🌾",
            description=f"**Điểm số: {score}/{total}**\n\n{flavor}",
            color=rank_color,
        )
        embed.add_field(name="Xếp loại", value=f"## {tier}")
        embed.set_footer(text="Folk Valley thì thầm: hẹn gặp lại ở vòng đoán sau...")
        await message.channel.send(embed=embed)


# ============ NHÃN CHẤT LƯỢNG NƯỚC ĐI CỜ VUA (!! thiên tài / ?? ngớ ngẩn) ============
MOVE_ANNOTATION_TEXT = {
    "!!": "✨ **!!** Nước đi thiên tài!",
    "??": "🤦 **??** Nước đi ngớ ngẩn!",
}


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
        try:
            if not cfg["active"](cid):
                await interaction.response.send_message(f"❌ Ván {cfg['label']} đã kết thúc rồi.", ephemeral=True)
                return
            text = f"🛑 Đã kết thúc ván {cfg['label']}. {cfg['reveal'](cid)}"
            cfg["end"](cid)
            await interaction.response.edit_message(content=text, embed=None, view=None)
        except Exception as e:
            print(f"[chess] Lỗi nút Kết thúc ({kind}): {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi khi kết thúc ván, thử lại nhé.", ephemeral=True)

    button.callback = callback
    return button


class EndGameView(discord.ui.View):
    """View chỉ gồm nút Kết thúc — dùng cho wordle/flag/chess"""
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
        try:
            if not games.chess_active(cid):
                await interaction.response.send_message("❌ Ván cờ đã kết thúc rồi.", ephemeral=True)
                return
            if games.chess_is_pvp(cid):
                game = games._chess_games[cid]
                is_participant = interaction.user.id in (game["white_id"], game["black_id"])
            else:
                is_participant = interaction.user.id == games.chess_player_id(cid)
            if await _deny_unless(interaction, is_participant):
                return

            names = _chess_display_names(cid)
            text = games.chess_resign_text(cid, interaction.user.id, names)
            games.chess_end(cid)
            embed = discord.Embed(description=text, color=0x2C3E50)
            await interaction.response.edit_message(embed=embed, attachments=[], view=None)
        except Exception as e:
            print(f"[chess] Lỗi nút Đầu hàng: {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi khi đầu hàng, thử /chess_reset nếu ván bị kẹt.", ephemeral=True)

    resign_btn.callback = on_resign
    view.add_item(resign_btn)

    hint_btn = discord.ui.Button(
        label=f"💡 Gợi ý (-{games.HINT_ELO_PENALTY} Elo)", style=discord.ButtonStyle.secondary, row=4
    )

    async def on_hint(interaction: discord.Interaction):
        try:
            if not games.chess_active(cid):
                await interaction.response.send_message("❌ Ván cờ đã kết thúc rồi.", ephemeral=True)
                return
            allowed = interaction.user.id == _chess_current_player_id(cid)
            if await _deny_unless(interaction, allowed, "❌ Chỉ người đến lượt mới xin gợi ý được!"):
                return
            hint_text, new_elo = games.chess_hint(cid, interaction.user.id)
            await interaction.response.send_message(
                f"{hint_text}\n(Elo của bạn giờ còn **{new_elo}**)", ephemeral=True
            )
        except Exception as e:
            print(f"[chess] Lỗi nút Gợi ý: {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi khi lấy gợi ý, thử lại nhé.", ephemeral=True)

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


class ChessTimeoutView(discord.ui.View):
    """View cơ sở cho các bước đi cờ vua — tự dọn ván nếu quá lâu không ai thao tác,
    tránh việc ván bị 'kẹt' và phải dùng /chess_reset thủ công."""
    def __init__(self, cid, timeout=180):
        super().__init__(timeout=timeout)
        self.cid = cid

    async def on_timeout(self):
        if not games.chess_active(self.cid):
            return
        games.chess_end(self.cid)
        if self.message:
            try:
                await self.message.edit(content="⌛ Ván cờ đã tự hủy do quá lâu không có nước đi.", view=None)
            except discord.HTTPException:
                pass


class ChessFromView(ChessTimeoutView):
    """Bước 1: chọn quân muốn đi"""
    def __init__(self, cid):
        super().__init__(cid, timeout=180)
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
        try:
            if not games.chess_active(self.cid):
                await interaction.response.send_message("❌ Ván cờ đã kết thúc rồi.", ephemeral=True)
                return
            if await _deny_unless(interaction, interaction.user.id == _chess_current_player_id(self.cid), "❌ Chưa đến lượt bạn!"):
                return
            from_sq = interaction.data["values"][0]
            new_view = ChessToView(self.cid, interaction.user.id, from_sq)
            await interaction.response.edit_message(view=new_view)
            new_view.message = await interaction.original_response()
        except Exception as e:
            print(f"[chess] Lỗi chọn quân: {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi khi chọn quân, thử lại nhé.", ephemeral=True)


class ChessToView(ChessTimeoutView):
    """Bước 2: chọn ô muốn đi tới"""
    def __init__(self, cid, player_id, from_sq):
        super().__init__(cid, timeout=180)
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
        try:
            if await _deny_unless(interaction, interaction.user.id == self.player_id):
                return
            new_view = ChessFromView(self.cid)
            await interaction.response.edit_message(view=new_view)
            new_view.message = await interaction.original_response()
        except Exception as e:
            print(f"[chess] Lỗi Chọn lại: {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi, thử lại nhé.", ephemeral=True)

    async def on_select(self, interaction: discord.Interaction):
        try:
            if not games.chess_active(self.cid):
                await interaction.response.send_message("❌ Ván cờ đã kết thúc rồi.", ephemeral=True)
                return
            if await _deny_unless(interaction, interaction.user.id == self.player_id):
                return

            to_sq = interaction.data["values"][0]
            ok, outcome, annotation = games.chess_make_move(self.cid, self.from_sq, to_sq)
            if not ok:
                await interaction.response.send_message("⚠️ Nước đi này không còn hợp lệ, hãy chọn lại!", ephemeral=True)
                return

            # Vs Bot: sau khi người đi xong, đến lượt bot đánh ngay.
            # Giữ lại nhãn nước của NGƯỜI CHƠI, không để nhãn nước bot đè mất —
            # cả 2 đều đáng xem, nên hiển thị riêng từng dòng.
            player_annotation = annotation
            bot_annotation = None
            if outcome is None and not games.chess_is_pvp(self.cid):
                outcome, bot_annotation = games.chess_bot_move(self.cid)

            image = games.chess_board_image(self.cid)
            file = discord.File(image, filename="board.png")
            player_line = MOVE_ANNOTATION_TEXT.get(player_annotation)
            bot_line = MOVE_ANNOTATION_TEXT.get(bot_annotation)
            if bot_line:
                bot_line = f"🤖 {bot_line}"
            annotation_line = "\n".join(l for l in (player_line, bot_line) if l) or None

            if outcome is not None:
                names = _chess_display_names(self.cid)
                text = games.chess_outcome_text(self.cid, outcome, names)
                if annotation_line:
                    text += f"\n\n{annotation_line}"
                games.chess_end(self.cid)
                embed = discord.Embed(description=text, color=0x2C3E50)
                embed.set_image(url="attachment://board.png")
                await interaction.response.edit_message(embed=embed, attachments=[file], view=None)
            else:
                extra = f"👉 Đến lượt <@{games.chess_current_turn_id(self.cid)}>!" if games.chess_is_pvp(self.cid) else None
                if annotation_line:
                    extra = f"{extra}\n{annotation_line}" if extra else annotation_line
                embed = _chess_board_embed(self.cid, extra)
                new_view = ChessFromView(self.cid)
                await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)
                new_view.message = await interaction.original_response()
        except Exception as e:
            print(f"[chess] Lỗi khi đi nước: {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi khi đi nước, thử /chess_reset nếu ván bị kẹt.", ephemeral=True)




# ============ SLASH COMMANDS ============
@bot.tree.command(name="ping", description="Kiểm tra độ trễ của bot")
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! ({round(bot.latency * 1000)}ms)")


@bot.tree.command(name="about", description="Thông tin về bot")
async def about_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 About Bot",
        description="Bot mini-game vui nhộn cho server: đoán chữ, đoán cờ, cờ caro, cờ vua và bói vui.",
        color=0x5865F2,
    )
    embed.add_field(
        name="🎮 Các lệnh",
        value=(
            "`/wordle` — đoán từ 5 chữ\n"
            "`/flag` — đoán cờ các nước\n"
            "`/caro` — cờ caro vs bot\n"
            "`/chess` — cờ vua vs bot\n"
            "`/chess_invite @ai_đó` — mời PvP cờ vua\n"
            "`/chess_reset` — xóa ván cờ bị kẹt (nếu bot báo lỗi)\n"
            "`/whatuinto` — bói vui\n"
            "`/wiki <từ khóa>` — tra bách khoa toàn thư\n"
            "`/ping` — kiểm tra độ trễ\n\n"
            "**🔒 Nhà tù (Admin)**\n"
            "`/setuptu` — cấu hình kênh giam + vai trò tù nhân\n"
            "`/phattu @ai_đó {số_lần} {lý_do}` — bỏ tù, cấp số lượt dọn tù\n"
            "`/anxa @ai_đó` — ân xá, thả tự do\n"
            "`/laudon` — (tù nhân dùng trong kênh giam) dọn sạch kênh, cooldown 5 phút/lượt"
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


class ChessDifficultyView(discord.ui.View):
    def __init__(self, cid, player_id):
        super().__init__(timeout=30)
        self.cid = cid
        self.player_id = player_id

    async def _start(self, interaction, bot_elo):
        if await _deny_unless(interaction, interaction.user.id == self.player_id):
            return
        if games.chess_active(self.cid):
            await interaction.response.send_message("⚠️ Đang có ván cờ vua chưa xong trong kênh này!", ephemeral=True)
            return

        games.chess_start(self.cid, self.player_id, bot_elo)
        image = games.chess_board_image(self.cid)
        file = discord.File(image, filename="board.png")
        embed = _chess_board_embed(self.cid, "Chọn **quân** rồi chọn **ô muốn đi tới** bằng menu bên dưới.")
        new_view = ChessFromView(self.cid)
        await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=new_view)
        new_view.message = await interaction.original_response()

    @discord.ui.button(label="🟢 Dễ (800 Elo)", style=discord.ButtonStyle.success)
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, 800)

    @discord.ui.button(label="🟡 Vừa (1200 Elo)", style=discord.ButtonStyle.primary)
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, 1200)

    @discord.ui.button(label="🔴 Khó (1600 Elo)", style=discord.ButtonStyle.danger)
    async def hard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, 1600)


@bot.tree.command(name="chess", description="Chơi cờ vua với bot (bạn cầm quân Trắng)")
async def chess_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.chess_active(cid):
        await interaction.response.send_message("⚠️ Đang có ván cờ vua chưa xong trong kênh này!", ephemeral=True)
        return

    view = ChessDifficultyView(cid, interaction.user.id)
    await interaction.response.send_message("♟️ Chọn độ khó cho bot:", view=view)


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
        if await _deny_unless(interaction, interaction.user.id == self.invitee_id, "❌ Lời mời này không dành cho bạn!"):
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
        new_view = ChessFromView(self.cid)
        await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=new_view)
        new_view.message = await interaction.original_response()

    @discord.ui.button(label="❌ Từ chối", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.invitee_id, "❌ Lời mời này không dành cho bạn!"):
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


# ============ NHÀ TÙ ============
def _is_admin(interaction: discord.Interaction) -> bool:
    return isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator


async def _lock_role_to_jail_channel(guild: discord.Guild, role: discord.Role, jail_channel: discord.abc.GuildChannel):
    """Khóa quyền role tù nhân trên toàn server, chỉ mở kênh giam.
    Bỏ qua từng kênh lỗi (thiếu quyền bot, kênh private đặc biệt...) thay vì dừng cả quá trình."""
    for channel in guild.channels:
        try:
            if channel.id == jail_channel.id:
                await channel.set_permissions(
                    role, view_channel=True, send_messages=True, read_message_history=True
                )
            else:
                await channel.set_permissions(role, view_channel=False)
        except discord.HTTPException as e:
            print(f"[jail] Không chỉnh được quyền kênh {channel.name}: {e!r}")


class JailSetupView(discord.ui.View):
    """Bước setup: chọn kênh giam + role tù nhân, bấm Xác nhận để bot tự khóa quyền toàn server."""
    def __init__(self, guild_id):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.channel_id = None
        self.role_id = None

        self.channel_select = discord.ui.ChannelSelect(
            placeholder="📍 Chọn kênh Nhà Giam...",
            channel_types=[discord.ChannelType.text],
        )
        self.channel_select.callback = self.on_channel_select
        self.add_item(self.channel_select)

        self.role_select = discord.ui.RoleSelect(placeholder="🔒 Chọn vai trò Tù Nhân...")
        self.role_select.callback = self.on_role_select
        self.add_item(self.role_select)

        self.confirm_button = discord.ui.Button(
            label="✅ Xác nhận", style=discord.ButtonStyle.success, row=2
        )
        self.confirm_button.callback = self.on_confirm
        self.add_item(self.confirm_button)

    async def on_channel_select(self, interaction: discord.Interaction):
        self.channel_id = self.channel_select.values[0].id
        await interaction.response.defer()

    async def on_role_select(self, interaction: discord.Interaction):
        self.role_id = self.role_select.values[0].id
        await interaction.response.defer()

    async def on_confirm(self, interaction: discord.Interaction):
        try:
            if self.channel_id is None or self.role_id is None:
                await interaction.response.send_message(
                    "⚠️ Bạn cần chọn cả kênh Nhà Giam và vai trò Tù Nhân trước khi xác nhận.", ephemeral=True
                )
                return

            await interaction.response.defer(ephemeral=True)
            guild = interaction.guild
            jail_channel = guild.get_channel(self.channel_id)
            role = guild.get_role(self.role_id)
            if jail_channel is None or role is None:
                await interaction.followup.send("❌ Không tìm thấy kênh hoặc vai trò đã chọn, thử lại nhé.", ephemeral=True)
                return

            await _lock_role_to_jail_channel(guild, role, jail_channel)
            games.jail_configure(self.guild_id, jail_channel.id, role.id)

            await interaction.followup.send(
                f"✅ Đã cấu hình xong!\n"
                f"📍 Kênh Nhà Giam: {jail_channel.mention}\n"
                f"🔒 Vai trò Tù Nhân: {role.mention}\n\n"
                f"Đối với kênh Private có quyền riêng, hãy kiểm tra lại thủ công để chắc chắn.",
                ephemeral=True,
            )
            for item in self.children:
                item.disabled = True
            await interaction.edit_original_response(view=self)
        except Exception as e:
            print(f"[jail] Lỗi khi xác nhận setup: {e!r}")
            if not interaction.response.is_done():
                await interaction.response.send_message("⚠️ Có lỗi khi cấu hình, thử lại nhé.", ephemeral=True)
            else:
                await interaction.followup.send("⚠️ Có lỗi khi cấu hình, thử lại nhé.", ephemeral=True)


@bot.tree.command(name="setuptu", description="[Admin] Cấu hình kênh Nhà Giam và vai trò Tù Nhân")
async def dsetuptu_slash(interaction: discord.Interaction):
    if not _is_admin(interaction):
        await interaction.response.send_message("❌ Chỉ Admin mới dùng được lệnh này.", ephemeral=True)
        return

    embed = discord.Embed(
        title="⚙️ Thiết lập Nhà Tù",
        description=(
            "Vui lòng chọn kênh dùng để giam giữ thành viên khi họ bị áp dụng hình phạt tù.\n"
            "Chọn vai trò sẽ được cấp cho thành viên khi bị đưa vào trạng thái tù.\n\n"
            "Sau khi chọn xong, hãy nhấn nút **[Xác nhận]** bên dưới. Hệ thống sẽ **tự động cấu hình quyền** "
            "cho toàn bộ máy chủ.\n"
            "Vai trò tù nhân sẽ bị tước quyền truy cập và **chỉ có thể xem/nhắn tin tại kênh Nhà Giam** bạn vừa chọn.\n\n"
            "⚠️ __**Lưu ý**__:\n"
            "- Quá trình Bot tự động đè quyền lên các kênh có thể mất vài giây.\n"
            "- Đối với các kênh có thiết lập quyền riêng biệt (Kênh Private), bạn nên **kiểm tra lại thủ công** "
            "để đảm bảo tù nhân không thể nhìn thấy."
        ),
        color=0x2C3E50,
    )
    await interaction.response.send_message(embed=embed, view=JailSetupView(interaction.guild_id), ephemeral=True)


@bot.tree.command(name="phattu", description="[Admin] Bỏ tù 1 thành viên")
@app_commands.describe(member="Thành viên vi phạm", lan="Số lượt được dùng /laudon", ly_do="Lý do phạt tù")
async def dphattu_slash(interaction: discord.Interaction, member: discord.Member, lan: int, ly_do: str):
    if not _is_admin(interaction):
        await interaction.response.send_message("❌ Chỉ Admin mới dùng được lệnh này.", ephemeral=True)
        return
    if not games.jail_is_configured(interaction.guild_id):
        await interaction.response.send_message("⚠️ Server chưa cấu hình nhà tù. Dùng `/setuptu` trước đã.", ephemeral=True)
        return
    if lan < 1:
        await interaction.response.send_message("⚠️ Số lượt dọn tù phải lớn hơn 0.", ephemeral=True)
        return

    try:
        _, role_id = games.jail_config(interaction.guild_id)
        role = interaction.guild.get_role(role_id)
        if role is None:
            await interaction.response.send_message("❌ Vai trò Tù Nhân đã bị xóa, hãy `/setuptu` lại.", ephemeral=True)
            return

        await member.add_roles(role, reason=f"Phạt tù bởi {interaction.user}: {ly_do}")
        games.jail_imprison(interaction.guild_id, member.id, lan, ly_do)

        text = (
            "<a:b66:1527986691833593899> **TÙ NHÂN MỚI** <a:b66:1527986691833593899>\n"
            f"{member.mention} vừa bị chuyển vào đây!\n"
            f"> 🧹 **Hình phạt:** `{lan}` lần lau dọn.\n"
            f"> 📄 **Lý do:** {ly_do}"
        )
        await interaction.response.send_message(text)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot thiếu quyền gán vai trò cho thành viên này.", ephemeral=True)
    except Exception as e:
        print(f"[jail] Lỗi /phattu: {e!r}")
        if not interaction.response.is_done():
            await interaction.response.send_message("⚠️ Có lỗi khi bỏ tù, thử lại nhé.", ephemeral=True)


@bot.tree.command(name="anxa", description="[Admin] Ân xá, thả tự do cho tù nhân")
@app_commands.describe(member="Thành viên cần ân xá")
async def danxa_slash(interaction: discord.Interaction, member: discord.Member):
    if not _is_admin(interaction):
        await interaction.response.send_message("❌ Chỉ Admin mới dùng được lệnh này.", ephemeral=True)
        return
    if not games.jail_is_configured(interaction.guild_id):
        await interaction.response.send_message("⚠️ Server chưa cấu hình nhà tù.", ephemeral=True)
        return

    try:
        was_prisoner = games.jail_release(interaction.guild_id, member.id)
        _, role_id = games.jail_config(interaction.guild_id)
        role = interaction.guild.get_role(role_id)
        if role and role in member.roles:
            await member.remove_roles(role, reason=f"Ân xá bởi {interaction.user}")

        if was_prisoner:
            await interaction.response.send_message(f"🕊️ {member.mention} đã được ân xá, tự do rồi!")
        else:
            await interaction.response.send_message(f"⚠️ {member.mention} không có trong danh sách tù nhân, nhưng đã gỡ vai trò (nếu có).", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Bot thiếu quyền gỡ vai trò cho thành viên này.", ephemeral=True)
    except Exception as e:
        print(f"[jail] Lỗi /anxa: {e!r}")
        if not interaction.response.is_done():
            await interaction.response.send_message("⚠️ Có lỗi khi ân xá, thử lại nhé.", ephemeral=True)


@bot.tree.command(name="laudon", description="[Tù nhân] Dọn sạch kênh Nhà Giam — cooldown 5 phút/lượt")
async def dlaudon_slash(interaction: discord.Interaction):
    try:
        if not games.jail_is_configured(interaction.guild_id):
            await interaction.response.send_message("⚠️ Server chưa cấu hình nhà tù.", ephemeral=True)
            return

        jail_channel_id, role_id = games.jail_config(interaction.guild_id)
        if interaction.channel_id != jail_channel_id:
            await interaction.response.send_message("❌ Lệnh này chỉ dùng được trong kênh Nhà Giam.", ephemeral=True)
            return

        ok, error_msg, remaining = games.jail_try_clean(interaction.guild_id, interaction.user.id)
        if not ok:
            await interaction.response.send_message(error_msg, ephemeral=True)
            return

        member = interaction.user
        name = member.display_name

        await interaction.response.send_message(
            f"<a:lunari_r_20:1475793473750700043> __**{name}**__ ┊ đang cặm cụi lau dọn... (Còn lại: **`{remaining}`** lần)",
            ephemeral=True,
        )
        deleted_total = 0
        while True:
            deleted = await interaction.channel.purge(limit=100)
            deleted_total += len(deleted)
            if len(deleted) < 100:
                break

        if remaining <= 0:
            games.jail_release(interaction.guild_id, member.id)
            role = interaction.guild.get_role(role_id)
            if role and role in member.roles:
                await member.remove_roles(role, reason="Hoàn thành án phạt lau dọn")
            await interaction.channel.send(
                "<:lunari_yess:1523023578436603984> **CẢI TẠO TỐT!**\n"
                f"__**{name}**__ đã hoàn thành án phạt lau dọn, được khôi phục chức vụ và trả tự do!"
            )
    except discord.Forbidden:
        msg = "❌ Bot thiếu quyền xóa tin nhắn ở kênh này."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception as e:
        print(f"[jail] Lỗi /laudon: {e!r}")
        msg = "⚠️ Có lỗi khi dọn kênh, thử lại nhé."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


@bot.event
async def on_member_join(member: discord.Member):
    """Leave rồi vào lại vẫn còn tù — tự động gán lại role tù nhân nếu còn trong danh sách giam."""
    try:
        if not games.jail_is_prisoner(member.guild.id, member.id):
            return
        _, role_id = games.jail_config(member.guild.id)
        role = member.guild.get_role(role_id) if role_id else None
        if role:
            await member.add_roles(role, reason="Tù nhân rời rồi vào lại server — vẫn còn án tù")
    except discord.HTTPException as e:
        print(f"[jail] Lỗi gán lại role tù khi {member} vào lại: {e!r}")


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
