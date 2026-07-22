import discord
import os
import asyncio
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
                    new_aura = games.add_aura(message.author.id, 10)
                    await message.channel.send(
                        f"🎉 Chính xác! {message.author.mention} đã đoán đúng!\n"
                        f"{games.AURA_ICON} +10 Aura (số dư: {new_aura})."
                    )
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
        new_aura = games.add_aura(message.author.id, 10)
        await message.channel.send(
            f"✅ Chính xác! Đó là **{answer.title()}**! (Điểm: {score}/{round_num})\n"
            f"{games.AURA_ICON} +10 Aura (số dư: {new_aura})."
        )
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
    """Tạo nút Kết thúc dùng chung — gắn được vào bất kỳ View nào.
    Riêng cờ vua PvP: 1 người bấm chỉ là ĐỀ NGHỊ, phải người còn lại xác nhận mới
    thực sự kết thúc (tránh 1 bên tự ý huỷ ván khi đang thua)."""
    cfg = GAME_CONFIG[kind]
    button = discord.ui.Button(label="🛑 Kết thúc", style=discord.ButtonStyle.danger, row=row)

    async def callback(interaction: discord.Interaction):
        try:
            if not cfg["active"](cid):
                await interaction.response.send_message(f"❌ Ván {cfg['label']} đã kết thúc rồi.", ephemeral=True)
                return

            if kind == "chess" and games.chess_is_pvp(cid):
                await _handle_chess_end_request(interaction, cid)
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


async def _handle_chess_end_request(interaction: discord.Interaction, cid):
    """Xử lý bấm nút Kết thúc trong ván cờ PvP — cần cả 2 bên đồng ý."""
    game = games._chess_games[cid]
    white_id, black_id = game["white_id"], game["black_id"]
    if interaction.user.id not in (white_id, black_id):
        await interaction.response.send_message("❌ Bạn không phải người chơi trong ván này!", ephemeral=True)
        return

    existing_offer = games.chess_get_draw_offer(cid)

    if existing_offer is None:
        # Chưa ai đề nghị -> đây là lời đề nghị đầu tiên, chờ đối thủ xác nhận
        games.chess_offer_draw(cid, interaction.user.id)
        opponent_id = black_id if interaction.user.id == white_id else white_id
        await interaction.response.send_message(
            f"🛑 <@{interaction.user.id}> đề nghị **kết thúc ván cờ** (hòa, không tính Elo).\n"
            f"👉 <@{opponent_id}> bấm **🛑 Kết thúc** lần nữa để đồng ý, hoặc cứ tiếp tục đi cờ để từ chối.",
        )
        return

    if existing_offer == interaction.user.id:
        await interaction.response.send_message("⏳ Bạn đã đề nghị rồi, đang chờ đối thủ đồng ý.", ephemeral=True)
        return

    # Người còn lại xác nhận -> kết thúc thật sự
    names = _chess_display_names(cid)
    text = games.chess_accept_draw_text(cid, names)
    games.chess_clear_draw_offer(cid)
    games.chess_end(cid)
    embed = discord.Embed(description=text, color=0x2C3E50)
    await interaction.response.edit_message(content=None, embed=embed, attachments=[], view=None)


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
        new_aura = games.add_aura(user.id, 10)
        return f"🎉 {user.mention} thắng! Bot thua tâm phục khẩu phục.\n\n{games.AURA_ICON} +10 Aura (số dư: {new_aura})."
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
            games.chess_touch(cid)
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
            games.chess_touch(cid)
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

    guide_btn = discord.ui.Button(label="📖 Hướng dẫn", style=discord.ButtonStyle.secondary, row=4)

    async def on_guide(interaction: discord.Interaction):
        is_pvp = games.chess_active(cid) and games.chess_is_pvp(cid)
        if games.chess_active(cid):
            games.chess_touch(cid)
        end_line = (
            "**🛑 Kết thúc** — đề nghị kết thúc ván hòa. Cần **cả 2 người** cùng bấm mới thực sự "
            "kết thúc (bấm lần 1 là đề nghị, đối thủ bấm lần 2 là đồng ý). Elo không đổi.\n"
            if is_pvp else
            "**🛑 Kết thúc** — dừng ván ngay lập tức.\n"
        )
        text = (
            "**📖 CÁCH CHƠI CỜ VUA**\n\n"
            "1️⃣ Chọn **quân** muốn đi ở menu thả xuống đầu tiên.\n"
            "2️⃣ Chọn **ô đích** muốn đi tới ở menu tiếp theo (phong cấp luôn tự thành Hậu).\n"
            "3️⃣ **🔙 Chọn lại** — quay lại bước chọn quân nếu bấm nhầm.\n\n"
            "**Các nút hành động:**\n"
            "🏳️ **Đầu hàng** — tự nhận thua ngay, không cần đối thủ đồng ý (khác với nút Kết thúc).\n"
            f"💡 **Gợi ý** — bot mách nước đi tốt nhất, nhưng bị trừ **{games.HINT_ELO_PENALTY} Elo** mỗi lần dùng.\n"
            f"{end_line}\n"
            "**Ký hiệu đánh giá nước đi:**\n"
            "✨ **!!** — Nước đi thiên tài (rõ ràng tốt hơn hẳn các lựa chọn khác).\n"
            "🤦 **??** — Nước đi hớ nặng (bỏ lỡ nước tốt hơn nhiều, hoặc để hở quân lớn cho đối phương ăn free).\n\n"
            "Trong bàn cờ còn hiện dòng **quân đã ăn được** của mỗi bên, để dễ theo dõi ai đang lợi thế.\n\n"
            "**🎨 Đổi hình quân cờ:** `/custom_chess` — chọn 1 quân ở menu thả xuống rồi dán link ảnh "
            "riêng cho quân đó, làm dần từng quân một cũng được. "
            "Xem lại bằng `/custom_chess_xem`, xóa bằng `/custom_chess_xoa`."
        )
        await interaction.response.send_message(text, ephemeral=True)

    guide_btn.callback = on_guide
    view.add_item(guide_btn)


def _chess_board_embed(cid, extra_line=None):
    """Dựng embed chuẩn cho bàn cờ: header Elo 2 người chơi + quân đã ăn của mỗi bên
    + (tuỳ chọn) 1 dòng phụ (VD: đến lượt ai)"""
    names = _chess_display_names(cid)
    header = games.chess_header_text(cid, names)
    parts = [header]
    captured = games.chess_captured_text(cid)
    if captured:
        parts.append(captured)
    if extra_line:
        parts.append(extra_line)
    embed = discord.Embed(description="\n\n".join(parts), color=0x2C3E50)
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
            games.chess_touch(self.cid)
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
            if games.chess_active(self.cid):
                games.chess_touch(self.cid)
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

            # Có nước đi mới -> coi như từ chối ngầm lời đề nghị kết thúc đang treo (nếu có)
            games.chess_clear_draw_offer(self.cid)

            # Vs Bot: sau khi người đi xong, đến lượt bot đánh ngay.
            # Giữ lại nhãn nước của NGƯỜI CHƠI, không để nhãn nước bot đè mất —
            # cả 2 đều đáng xem, nên hiển thị riêng từng dòng.
            player_annotation = annotation
            bot_annotation = None
            await games.chess_preload_sprites(self.cid)
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
            "`/aura` — xem số dư Aura\n"
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
        await games.chess_preload_sprites(self.cid)
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
        await games.chess_preload_sprites(self.cid)
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


_PIECE_CHOICES = [
    app_commands.Choice(name=label, value=key)
    for key, label in games.PIECE_KEY_LABELS.items()
]


@bot.tree.command(name="custom_chess", description="Đổi hình ảnh cho 1 quân cờ cụ thể bằng link ảnh")
@app_commands.describe(quan="Chọn quân cờ muốn đổi ảnh", link="Link ảnh (PNG/JPG) trỏ thẳng tới file, chỉ cho quân này")
@app_commands.choices(quan=_PIECE_CHOICES)
async def custom_chess_slash(interaction: discord.Interaction, quan: app_commands.Choice[str], link: str):
    await interaction.response.defer(ephemeral=True)
    sprite = await asyncio.to_thread(games.preview_piece_sprite, link)
    if sprite is None:
        await interaction.followup.send(
            "❌ Không đọc được ảnh từ link này. Kiểm tra lại: link phải trỏ thẳng tới file ảnh (PNG/JPG).",
        )
        return

    await asyncio.to_thread(games.set_piece_theme, interaction.user.id, quan.value, link)
    preview = await asyncio.to_thread(games.piece_theme_preview_image, interaction.user.id)
    file = discord.File(preview, filename="piece_theme.png")
    await interaction.followup.send(
        content=f"✅ Đã đổi ảnh cho **{quan.name}**! Đây là toàn bộ bộ quân cờ hiện tại của bạn:",
        file=file,
    )


@bot.tree.command(name="custom_chess_xoa", description="Xóa ảnh custom của 1 quân cờ (bỏ trống = xóa toàn bộ)")
@app_commands.describe(quan="Quân muốn xóa ảnh custom — bỏ trống để xóa hết cả bộ")
@app_commands.choices(quan=_PIECE_CHOICES)
async def custom_chess_xoa_slash(interaction: discord.Interaction, quan: app_commands.Choice[str] = None):
    await interaction.response.defer(ephemeral=True)
    key = quan.value if quan else None
    existed = await asyncio.to_thread(games.clear_piece_theme, interaction.user.id, key)
    if not existed:
        await interaction.followup.send("ℹ️ Không có ảnh custom nào để xóa.")
        return
    label = quan.name if quan else "toàn bộ bộ quân"
    await interaction.followup.send(f"🧹 Đã xóa ảnh custom cho **{label}**, quay về mặc định.")


@bot.tree.command(name="custom_chess_xem", description="Xem bộ quân cờ custom hiện tại của bạn")
async def custom_chess_xem_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    preview = await asyncio.to_thread(games.piece_theme_preview_image, interaction.user.id)
    file = discord.File(preview, filename="piece_theme.png")
    await interaction.followup.send(content="🎨 Bộ quân cờ hiện tại của bạn:", file=file)


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


@bot.tree.command(name="aura", description="Xem số dư Aura")
@app_commands.describe(member="Xem Aura của người khác (bỏ trống để xem của chính bạn)")
async def aura_slash(interaction: discord.Interaction, member: discord.Member = None):
    target = member or interaction.user
    balance = games.get_aura(target.id)
    who = "Bạn" if target.id == interaction.user.id else target.mention
    await interaction.response.send_message(f"{games.AURA_ICON} {who} đang có **{balance} Aura**.")


# Khởi chạy web server để tránh bị Render tắt
web_server.keep_alive()

# Chạy bot bằng token từ biến môi trường
bot.run(os.environ['DISCORD_KEY'])
