import discord
import os
import time
import random
import re
import io
import asyncio
import web_server
import games
import ai
from discord.ext import commands
from discord import app_commands
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    import traceback
    traceback.print_exc()
    try:
        if not interaction.response.is_done():
            await interaction.response.send_message('⚠️ Có lỗi xảy ra khi xử lý lệnh này, thử lại sau.', ephemeral=True)
        else:
            await interaction.followup.send('⚠️ Có lỗi xảy ra khi xử lý lệnh này, thử lại sau.', ephemeral=True)
    except Exception:
        traceback.print_exc()

async def _auto_rate_art_thread(thread):
    if games.art_thread_already_rated(thread.id):
        return
    try:
        starter = thread.starter_message or await thread.fetch_message(thread.id)
    except (discord.HTTPException, discord.NotFound, AttributeError):
        starter = None
    image_url = None
    if starter:
        for att in starter.attachments:
            if att.content_type and att.content_type.startswith('image/'):
                image_url = att.url
                break
    if image_url is None:
        return
    games.art_thread_mark_rated(thread.id)
    embed = _danhgia_embed(image_url, 'Bot (tự động)')
    await thread.send(embed=embed)

@bot.event
async def on_thread_create(thread):
    if thread.parent_id == games.ART_FORUM_CHANNEL_ID:
        await asyncio.sleep(1)
        await _auto_rate_art_thread(thread)

@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f'✅ Đã đồng bộ {len(synced)} slash command(s)')
    except Exception as e:
        print(f'⚠️ Lỗi đồng bộ slash command: {e}')
    art_channel = bot.get_channel(games.ART_FORUM_CHANNEL_ID)
    if art_channel is not None:
        try:
            for thread in art_channel.threads:
                await _auto_rate_art_thread(thread)
        except Exception as e:
            print(f'⚠️ Lỗi quét thread art chưa chấm: {e!r}')
    ai.start_auto_chat_loop(bot)
    print(f'✅ Bot đã đăng nhập với tên {bot.user}')

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    cid = message.channel.id
    content = message.content.strip()
    if not content.startswith('!') and (not content.startswith('/')):
        try:
            if games.wordle_active(cid):
                word = content.lower()
                if len(word) == 5 and word.isalpha():
                    result, correct, done = games.wordle_check(cid, word)
                    await message.channel.send(f'`{word.upper()}`\n{result}')
                    if correct:
                        new_aura = games.add_aura(message.author.id, 10)
                        new_aura_plus = games.award_game_completion_aura_plus(message.author.id)
                        await message.channel.send(f'🎉 Chính xác! {message.author.mention} đã đoán đúng!\n{games.AURA_ICON} +10 Aura (số dư: {new_aura}) và +{games.AURA_PLUS_PER_GAME} Aura+ (số dư: {new_aura_plus}).')
                        games.wordle_end(cid)
                    elif done:
                        new_aura_plus = games.award_game_completion_aura_plus(message.author.id)
                        await message.channel.send(f'💀 Hết lượt! Từ đúng là: **{games.wordle_word(cid).upper()}**\n{games.AURA_PLUS_ICON} +{games.AURA_PLUS_PER_GAME} Aura+ (số dư: {new_aura_plus}) vì đã chơi hết ván.')
                        games.wordle_end(cid)
                return
            if games.flag_active(cid):
                await _handle_flag_round(message, content)
                return
        except Exception as e:
            print(f'⚠️ Lỗi xử lý round game (channel {cid}): {e!r}')
            await message.channel.send(f'⚠️ Lỗi khi xử lý câu trả lời: `{e}`\nVán đã bị hủy, dùng lệnh game để bắt đầu lại.')
            games.wordle_end(cid)
            games.flag_end(cid)
            return
        if ai.is_ai_channel(cid):
            try:
                handled = await ai.handle_reply_to_bot(bot, message)
                if handled:
                    return
            except Exception as e:
                print(f'⚠️ Lỗi xử lý AI chat (channel {cid}): {e!r}')
        try:
            handled = await ai.handle_mention_to_bot(bot, message)
            if handled:
                return
        except Exception as e:
            print(f'⚠️ Lỗi xử lý AI chat mention (channel {cid}): {e!r}')
    await bot.process_commands(message)

async def _get_display_name_no_ping(user_id):
    user = bot.get_user(user_id)
    if user is None:
        try:
            user = await bot.fetch_user(user_id)
        except discord.HTTPException:
            return 'Ẩn danh'
    return user.display_name

async def _deny_unless(interaction: discord.Interaction, allowed: bool, msg='❌ Đây không phải ván của bạn!'):
    if not allowed:
        await interaction.response.send_message(msg, ephemeral=True)
        return True
    return False

async def _handle_flag_round(message, guess_text):
    cid = message.channel.id
    result, has_next = games.flag_check(cid, message.author.id, guess_text)
    if result == 'not_owner':
        return
    correct = result
    answer = games.flag_answer(cid)
    round_num, total, score = games.flag_progress(cid)
    if correct:
        reward = games.flag_aura_reward(cid)
        new_aura = games.add_aura(message.author.id, reward)
        await message.channel.send(f'✅ Chính xác! Đó là **{answer.title()}**! (Điểm: {score}/{round_num})\n{games.AURA_ICON} +{reward} Aura (số dư: {new_aura}).')
    else:
        await message.channel.send(f'❌ Sai rồi! Đáp án là **{answer.title()}**! (Điểm: {score}/{round_num})')
    if has_next:
        url = games.flag_next(cid)
        embed = discord.Embed(title=f'🏳️ Vòng tiếp theo ({round_num + 1}/{total})', description='Chat thẳng tên quốc gia (tiếng Anh) để đoán! (chỉ người mở ván mới được tính điểm)', color=4160800)
        embed.set_image(url=url)
        await message.channel.send(embed=embed, view=EndGameView(cid, 'flag'))
    else:
        tier, flavor, rank_color = games.folk_valley_rank(score, total)
        games.flag_end(cid)
        new_aura_plus = games.award_game_completion_aura_plus(message.author.id)
        embed = discord.Embed(title='🌾 TỔNG KẾT — FOLK VALLEY 🌾', description=f'**Điểm số: {score}/{total}**\n\n{flavor}\n\n{games.AURA_PLUS_ICON} +{games.AURA_PLUS_PER_GAME} Aura+ vì đã hoàn thành ván (số dư: {new_aura_plus}).', color=rank_color)
        embed.add_field(name='Xếp loại', value=f'## {tier}')
        embed.set_footer(text='Folk Valley thì thầm: hẹn gặp lại ở vòng đoán sau...')
        await message.channel.send(embed=embed)
MOVE_ANNOTATION_TEXT = {'!!': '✨ **!!** Nước đi thiên tài!', '??': '🤦 **??** Nước đi ngớ ngẩn!'}
GAME_CONFIG = {'wordle': {'active': games.wordle_active, 'end': games.wordle_end, 'label': 'Wordle', 'reveal': lambda cid: f'Từ đúng là **{games.wordle_word(cid).upper()}**'}, 'flag': {'active': games.flag_active, 'end': games.flag_end, 'label': 'Đoán cờ', 'reveal': lambda cid: f'Đáp án là **{games.flag_answer(cid).title()}**'}, 'chess': {'active': games.chess_active, 'end': games.chess_end, 'label': 'Cờ vua', 'reveal': lambda cid: 'Ván đấu đã dừng.'}}

def make_end_button(cid, kind, row=None):
    cfg = GAME_CONFIG[kind]
    button = discord.ui.Button(label='🛑 Kết thúc', style=discord.ButtonStyle.danger, row=row)

    async def callback(interaction: discord.Interaction):
        try:
            if not cfg['active'](cid):
                await interaction.response.send_message(f'❌ Ván {cfg['label']} đã kết thúc rồi.', ephemeral=True)
                return
            if kind == 'chess' and games.chess_is_pvp(cid):
                await _handle_chess_end_request(interaction, cid)
                return
            text = f'🛑 Đã kết thúc ván {cfg['label']}. {cfg['reveal'](cid)}'
            cfg['end'](cid)
            await interaction.response.edit_message(content=text, embed=None, view=None)
        except Exception as e:
            print(f'[chess] Lỗi nút Kết thúc ({kind}): {e!r}')
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi khi kết thúc ván, thử lại nhé.', ephemeral=True)
    button.callback = callback
    return button

async def _handle_chess_end_request(interaction: discord.Interaction, cid):
    game = games._chess_games[cid]
    white_id, black_id = (game['white_id'], game['black_id'])
    if interaction.user.id not in (white_id, black_id):
        await interaction.response.send_message('❌ Bạn không phải người chơi trong ván này!', ephemeral=True)
        return
    existing_offer = games.chess_get_draw_offer(cid)
    if existing_offer is None:
        games.chess_offer_draw(cid, interaction.user.id)
        opponent_id = black_id if interaction.user.id == white_id else white_id
        await interaction.response.send_message(f'🛑 <@{interaction.user.id}> đề nghị **kết thúc ván cờ** (hòa, không tính Elo).\n👉 <@{opponent_id}> bấm **🛑 Kết thúc** lần nữa để đồng ý, hoặc cứ tiếp tục đi cờ để từ chối.')
        return
    if existing_offer == interaction.user.id:
        await interaction.response.send_message('⏳ Bạn đã đề nghị rồi, đang chờ đối thủ đồng ý.', ephemeral=True)
        return
    names = _chess_display_names(cid)
    text = games.chess_accept_draw_text(cid, names)
    games.chess_clear_draw_offer(cid)
    games.chess_end(cid)
    embed = discord.Embed(description=text, color=2899536)
    await interaction.response.edit_message(content=None, embed=embed, attachments=[], view=None)

class EndGameView(discord.ui.View):

    def __init__(self, cid, kind, timeout=180):
        super().__init__(timeout=timeout)
        self.add_item(make_end_button(cid, kind))

class DifficultyView(discord.ui.View):

    def __init__(self, cid, owner_id):
        super().__init__(timeout=30)
        self.cid = cid
        self.owner_id = owner_id
        if games.flag_mythic_unlocked(owner_id):
            self.add_item(self._make_mythic_button())

    def _make_mythic_button(self):
        button = discord.ui.Button(label='🌌 Mythic', style=discord.ButtonStyle.secondary, row=1)

        async def callback(interaction):
            await self.start_with(interaction, 'mythic', '🌌 Mythic')
        button.callback = callback
        return button

    async def start_with(self, interaction, difficulty, label):
        if await _deny_unless(interaction, interaction.user.id == self.owner_id, '❌ Đây không phải lệnh /flag của bạn!'):
            return
        if games.flag_active(self.cid):
            await interaction.response.send_message('⚠️ Đang có ván đoán cờ chưa xong!', ephemeral=True)
            return
        url, ok = games.flag_start(self.cid, self.owner_id, difficulty)
        if not ok:
            if difficulty == 'mythic':
                await interaction.response.send_message(f'❌ Chưa mở khóa Mythic! Cần tích lũy **{games.FLAG_UNLOCK_SCORE_MYTHIC}** điểm đoán đúng (hiện có: {games.flag_lifetime_score(self.owner_id)}).', ephemeral=True)
            else:
                await interaction.response.send_message('❌ Bạn đã hết lượt chơi `/flag` hôm nay! Mua thêm 🎟️ Slot Vé Game ở `/shop` hoặc chờ mai nhé.', ephemeral=True)
            return
        left = games.flag_games_left_today(self.owner_id)
        reward = games.FLAG_AURA_PER_DIFFICULTY[difficulty]
        embed = discord.Embed(title=f'🏳️ Đoán cờ — {label} (1/{games.ROUNDS_PER_GAME})', description=f'Chat thẳng tên quốc gia (tiếng Anh) để đoán! Mỗi câu đúng: **+{reward} Aura**.\n🎟️ Lượt chơi còn lại hôm nay: **{left}**', color=4160800)
        embed.set_image(url=url)
        await interaction.response.edit_message(content=None, embed=embed, view=EndGameView(self.cid, 'flag'))

    @discord.ui.button(label='🌱 Dễ', style=discord.ButtonStyle.success)
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, 'easy', '🌱 Dễ')

    @discord.ui.button(label='🌾 Trung bình', style=discord.ButtonStyle.primary)
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, 'medium', '🌾 Trung bình')

    @discord.ui.button(label='🔥 Khó', style=discord.ButtonStyle.danger)
    async def hard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, 'hard', '🔥 Khó')

    @discord.ui.button(label='💀 Insane', style=discord.ButtonStyle.secondary)
    async def insane(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.start_with(interaction, 'insane', '💀 Insane')

def _chess_current_player_id(cid):
    if games.chess_is_pvp(cid):
        return games.chess_current_turn_id(cid)
    return games.chess_player_id(cid)

def _chess_display_names(cid):
    if games.chess_is_pvp(cid):
        game = games._chess_games[cid]
        return {True: f'<@{game['white_id']}>', False: f'<@{game['black_id']}>'}
    game = games._chess_games[cid]
    return {True: f'<@{game['player_id']}>', False: 'Bot'}

async def _check_and_handle_chess_timeout(interaction: discord.Interaction, cid) -> bool:
    timed_out_color = games.chess_check_timeout(cid)
    if timed_out_color is None:
        return False
    names = _chess_display_names(cid)
    text = games.chess_timeout_text(cid, timed_out_color, names)
    games.chess_end(cid)
    embed = discord.Embed(description=text, color=2899536)
    try:
        image = games.chess_board_image(cid)
    except Exception:
        image = None
    if image:
        file = discord.File(image, filename='board.png')
        embed.set_image(url='attachment://board.png')
        await interaction.response.edit_message(embed=embed, attachments=[file], view=None)
    else:
        await interaction.response.edit_message(embed=embed, view=None)
    return True

def _add_chess_action_buttons(view, cid):
    resign_btn = discord.ui.Button(label='🏳️ Đầu hàng', style=discord.ButtonStyle.danger, row=4)

    async def on_resign(interaction: discord.Interaction):
        try:
            if not games.chess_active(cid):
                await interaction.response.send_message('❌ Ván cờ đã kết thúc rồi.', ephemeral=True)
                return
            games.chess_touch(cid)
            if games.chess_is_pvp(cid):
                game = games._chess_games[cid]
                is_participant = interaction.user.id in (game['white_id'], game['black_id'])
            else:
                is_participant = interaction.user.id == games.chess_player_id(cid)
            if await _deny_unless(interaction, is_participant):
                return
            names = _chess_display_names(cid)
            text = games.chess_resign_text(cid, interaction.user.id, names)
            games.chess_end(cid)
            embed = discord.Embed(description=text, color=2899536)
            await interaction.response.edit_message(embed=embed, attachments=[], view=None)
        except Exception as e:
            print(f'[chess] Lỗi nút Đầu hàng: {e!r}')
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi khi đầu hàng, thử /chess_reset nếu ván bị kẹt.', ephemeral=True)
    resign_btn.callback = on_resign
    view.add_item(resign_btn)
    hint_btn = discord.ui.Button(label=f'💡 Gợi ý (-{games.HINT_ELO_PENALTY} Elo)', style=discord.ButtonStyle.secondary, row=4)

    async def on_hint(interaction: discord.Interaction):
        try:
            if not games.chess_active(cid):
                await interaction.response.send_message('❌ Ván cờ đã kết thúc rồi.', ephemeral=True)
                return
            games.chess_touch(cid)
            allowed = interaction.user.id == _chess_current_player_id(cid)
            if await _deny_unless(interaction, allowed, '❌ Chỉ người đến lượt mới xin gợi ý được!'):
                return
            hint_text, new_elo = games.chess_hint(cid, interaction.user.id)
            await interaction.response.send_message(f'{hint_text}\n(Elo của bạn giờ còn **{new_elo}**)', ephemeral=True)
        except Exception as e:
            print(f'[chess] Lỗi nút Gợi ý: {e!r}')
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi khi lấy gợi ý, thử lại nhé.', ephemeral=True)
    hint_btn.callback = on_hint
    view.add_item(hint_btn)
    guide_btn = discord.ui.Button(label='📖 Hướng dẫn', style=discord.ButtonStyle.secondary, row=4)

    async def on_guide(interaction: discord.Interaction):
        is_pvp = games.chess_active(cid) and games.chess_is_pvp(cid)
        if games.chess_active(cid):
            games.chess_touch(cid)
        end_line = '**🛑 Kết thúc** — đề nghị kết thúc ván hòa. Cần **cả 2 người** cùng bấm mới thực sự kết thúc (bấm lần 1 là đề nghị, đối thủ bấm lần 2 là đồng ý). Elo không đổi.\n' if is_pvp else '**🛑 Kết thúc** — dừng ván ngay lập tức.\n'
        text = f'**📖 CÁCH CHƠI CỜ VUA**\n\n1️⃣ Chọn **quân** muốn đi ở menu thả xuống đầu tiên.\n2️⃣ Chọn **ô đích** muốn đi tới ở menu tiếp theo (phong cấp luôn tự thành Hậu).\n3️⃣ **🔙 Chọn lại** — quay lại bước chọn quân nếu bấm nhầm.\n\n**Các nút hành động:**\n🏳️ **Đầu hàng** — tự nhận thua ngay, không cần đối thủ đồng ý (khác với nút Kết thúc).\n💡 **Gợi ý** — bot mách nước đi tốt nhất, nhưng bị trừ **{games.HINT_ELO_PENALTY} Elo** mỗi lần dùng.\n{end_line}\n**Ký hiệu đánh giá nước đi:**\n✨ **!!** — Nước đi thiên tài (rõ ràng tốt hơn hẳn các lựa chọn khác).\n🤦 **??** — Nước đi hớ nặng (bỏ lỡ nước tốt hơn nhiều, hoặc để hở quân lớn cho đối phương ăn free).\n\nTrong bàn cờ còn hiện dòng **quân đã ăn được** của mỗi bên, để dễ theo dõi ai đang lợi thế.\n\n**🎨 Đổi hình quân cờ:** `/custom_chess` — chọn 1 quân ở menu thả xuống rồi dán link ảnh riêng cho quân đó, làm dần từng quân một cũng được. Xem lại bằng `/custom_chess_xem`, xóa bằng `/custom_chess_xoa`.'
        await interaction.response.send_message(text, ephemeral=True)
    guide_btn.callback = on_guide
    view.add_item(guide_btn)

def _chess_board_embed(cid, extra_line=None):
    names = _chess_display_names(cid)
    header = games.chess_header_text(cid, names)
    parts = [header]
    captured = games.chess_captured_text(cid)
    if captured:
        parts.append(captured)
    if extra_line:
        parts.append(extra_line)
    embed = discord.Embed(description='\n\n'.join(parts), color=2899536)
    embed.set_image(url='attachment://board.png')
    return embed

class ChessTimeoutView(discord.ui.View):
    BOT_TIMEOUT = 180
    SAFETY_MARGIN = 120

    def __init__(self, cid, timeout=None):
        if timeout is None:
            if games.chess_is_pvp(cid):
                remaining = games.chess_remaining_seconds(cid, games._chess_games[cid]['board'].turn)
                timeout = (remaining or self.BOT_TIMEOUT) + self.SAFETY_MARGIN
            else:
                timeout = self.BOT_TIMEOUT
        super().__init__(timeout=timeout)
        self.cid = cid

    async def on_timeout(self):
        if not games.chess_active(self.cid):
            return
        timed_out_color = games.chess_check_timeout(self.cid)
        if timed_out_color is not None:
            from_pvp = games.chess_is_pvp(self.cid)
            names = None
            if from_pvp:
                game = games._chess_games[self.cid]
                names = {True: f'<@{game['white_id']}>', False: f'<@{game['black_id']}>'}
            text = games.chess_timeout_text(self.cid, timed_out_color, names)
            games.chess_end(self.cid)
            if self.message:
                try:
                    await self.message.edit(content=text, embed=None, view=None)
                except discord.HTTPException:
                    pass
            return
        games.chess_end(self.cid)
        if self.message:
            try:
                await self.message.edit(content='⌛ Ván cờ đã tự hủy do quá lâu không có nước đi.', view=None)
            except discord.HTTPException:
                pass

class ChessFromView(ChessTimeoutView):

    def __init__(self, cid):
        super().__init__(cid)
        options = games.chess_from_options(cid)[:25]
        select = discord.ui.Select(placeholder='♟️ Chọn quân muốn đi...', options=[discord.SelectOption(label=label, value=val) for val, label in options])
        select.callback = self.on_select
        self.add_item(select)
        self.add_item(make_end_button(cid, 'chess'))
        _add_chess_action_buttons(self, cid)

    async def on_select(self, interaction: discord.Interaction):
        try:
            if not games.chess_active(self.cid):
                await interaction.response.send_message('❌ Ván cờ đã kết thúc rồi.', ephemeral=True)
                return
            if await _check_and_handle_chess_timeout(interaction, self.cid):
                return
            games.chess_touch(self.cid)
            if await _deny_unless(interaction, interaction.user.id == _chess_current_player_id(self.cid), '❌ Chưa đến lượt bạn!'):
                return
            from_sq = interaction.data['values'][0]
            new_view = ChessToView(self.cid, interaction.user.id, from_sq)
            await interaction.response.edit_message(view=new_view)
            new_view.message = await interaction.original_response()
        except Exception as e:
            print(f'[chess] Lỗi chọn quân: {e!r}')
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi khi chọn quân, thử lại nhé.', ephemeral=True)

class ChessToView(ChessTimeoutView):

    def __init__(self, cid, player_id, from_sq):
        super().__init__(cid)
        self.player_id = player_id
        self.from_sq = from_sq
        options = games.chess_to_options(cid, from_sq)[:25]
        select = discord.ui.Select(placeholder=f'👉 Đi quân ở {from_sq} đến đâu?', options=[discord.SelectOption(label=label, value=val) for val, label in options])
        select.callback = self.on_select
        self.add_item(select)
        back = discord.ui.Button(label='🔙 Chọn lại', style=discord.ButtonStyle.secondary)
        back.callback = self.on_back
        self.add_item(back)
        self.add_item(make_end_button(cid, 'chess'))
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
            print(f'[chess] Lỗi Chọn lại: {e!r}')
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi, thử lại nhé.', ephemeral=True)

    async def on_select(self, interaction: discord.Interaction):
        try:
            if not games.chess_active(self.cid):
                await interaction.response.send_message('❌ Ván cờ đã kết thúc rồi.', ephemeral=True)
                return
            if await _check_and_handle_chess_timeout(interaction, self.cid):
                return
            if await _deny_unless(interaction, interaction.user.id == self.player_id):
                return
            to_sq = interaction.data['values'][0]
            ok, outcome, annotation = games.chess_make_move(self.cid, self.from_sq, to_sq)
            if not ok:
                await interaction.response.send_message('⚠️ Nước đi này không còn hợp lệ, hãy chọn lại!', ephemeral=True)
                return
            games.chess_clear_draw_offer(self.cid)
            player_annotation = annotation
            bot_annotation = None
            if outcome is None and (not games.chess_is_pvp(self.cid)):
                outcome, bot_annotation = games.chess_bot_move(self.cid)
            image = games.chess_board_image(self.cid)
            file = discord.File(image, filename='board.png')
            player_line = MOVE_ANNOTATION_TEXT.get(player_annotation)
            bot_line = MOVE_ANNOTATION_TEXT.get(bot_annotation)
            if bot_line:
                bot_line = f'🤖 {bot_line}'
            annotation_line = '\n'.join((l for l in (player_line, bot_line) if l)) or None
            if outcome is not None:
                names = _chess_display_names(self.cid)
                text = games.chess_outcome_text(self.cid, outcome, names)
                if annotation_line:
                    text += f'\n\n{annotation_line}'
                games.chess_end(self.cid)
                embed = discord.Embed(description=text, color=2899536)
                embed.set_image(url='attachment://board.png')
                await interaction.response.edit_message(embed=embed, attachments=[file], view=None)
            else:
                extra = f'👉 Đến lượt <@{games.chess_current_turn_id(self.cid)}>!' if games.chess_is_pvp(self.cid) else None
                if annotation_line:
                    extra = f'{extra}\n{annotation_line}' if extra else annotation_line
                embed = _chess_board_embed(self.cid, extra)
                new_view = ChessFromView(self.cid)
                await interaction.response.edit_message(embed=embed, attachments=[file], view=new_view)
                new_view.message = await interaction.original_response()
        except Exception as e:
            print(f'[chess] Lỗi khi đi nước: {e!r}')
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi khi đi nước, thử /chess_reset nếu ván bị kẹt.', ephemeral=True)

@bot.tree.command(name='ping', description='Kiểm tra độ trễ của bot')
async def ping_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f'🏓 Pong! ({round(bot.latency * 1000)}ms)')

@bot.tree.command(name='minesweeper', description='💣 Dò Mìn — trò chơi cổ đại thử thách trí tuệ, thắng nhận Aura + Aura+ (10 vé/ngày)')
@app_commands.describe(size=f'Kích thước bàn dạng NxN, VD "8x8" (mặc định {games.MINESWEEPER_DEFAULT_SIZE}x{games.MINESWEEPER_DEFAULT_SIZE}, từ {games.MINESWEEPER_MIN_SIZE}x{games.MINESWEEPER_MIN_SIZE} đến {games.MINESWEEPER_MAX_SIZE}x{games.MINESWEEPER_MAX_SIZE})', seed='Nhập seed cũ để chơi lại đúng bàn đó (để trống để random)')
async def minesweeper_slash(interaction: discord.Interaction, size: str=None, seed: str=None):
    cid = interaction.channel_id
    if games.minesweeper_active(cid):
        await interaction.response.send_message('⚠️ Đang có ván Dò Mìn chưa xong trong kênh này! Dùng `/minesweeper_reset` nếu ván bị kẹt.', ephemeral=True)
        return
    if games.minesweeper_games_left_today(interaction.user.id) <= 0:
        await interaction.response.send_message('❌ Bạn đã hết vé chơi Dò Mìn hôm nay (10 vé/ngày)! Chờ mai nhé.', ephemeral=True)
        return
    board_size, size_ok = games.minesweeper_parse_size(size)
    if not size_ok:
        await interaction.response.send_message(f'❌ Kích thước không hợp lệ. Dùng dạng `NxN` (VD `8x8`), từ {games.MINESWEEPER_MIN_SIZE}x{games.MINESWEEPER_MIN_SIZE} đến {games.MINESWEEPER_MAX_SIZE}x{games.MINESWEEPER_MAX_SIZE}.', ephemeral=True)
        return
    seed_val, seed_ok = games.minesweeper_parse_seed(seed)
    if not seed_ok:
        await interaction.response.send_message('❌ Seed không hợp lệ, chỉ được nhập số nguyên dương.', ephemeral=True)
        return
    try:
        game_id, ok, used_seed = games.minesweeper_start(cid, interaction.user.id, size=board_size, seed=seed_val)
        if not ok:
            await interaction.response.send_message('❌ Bạn đã hết vé chơi Dò Mìn hôm nay (10 vé/ngày)! Chờ mai nhé.', ephemeral=True)
            return
        left = games.minesweeper_games_left_today(interaction.user.id)
        game = games.minesweeper_game(cid)
        img_buf = games.minesweeper_render_image(cid)
        file = discord.File(img_buf, filename='minesweeper.png')
        est_aura, est_aura_plus, _, _ = games.minesweeper_reward(game)
        embed = discord.Embed(title='💣 Dò Mìn — Trò Chơi Cổ Đại', description=f"Một trò chơi trí tuệ cổ xưa được lưu truyền qua nhiều thế hệ, thử thách sự tính toán và may rủi của người chơi.\n\nBàn {board_size}x{board_size}, có {game['mine_count']} quả mìn ẩn (mìn chỉ xuất hiện sau ô mở đầu tiên, đảm bảo không bao giờ 'toang' ngay phát đầu).\nBấm ⌨️ để nhập tọa độ (VD: `B3`), hoặc bấm 🚩 để bật/tắt chế độ cắm cờ. Nhập lại tọa độ một ô số đã mở (đủ cờ xung quanh) để tự mở nhanh các ô lân cận.\n🏆 Thắng: **~{est_aura} Aura** và **~{est_aura_plus} Aura+** (thưởng tăng theo độ khó, cộng bonus nếu thắng nhanh).\n\n🌱 Seed: `{used_seed}` (dùng lại seed này ở lệnh `/minesweeper` để chơi đúng bàn này)\n🎟️ Vé chơi còn lại hôm nay: **{left}**", color=3447003)
        embed.set_image(url='attachment://minesweeper.png')
        view = MinesweeperView(cid, interaction.user.id, game_id)
        await interaction.response.send_message(embed=embed, file=file, view=view)
    except Exception:
        import traceback
        traceback.print_exc()
        games.minesweeper_force_reset(cid)
        if not interaction.response.is_done():
            await interaction.response.send_message('⚠️ Có lỗi khi tạo ván Dò Mìn, thử lại sau.', ephemeral=True)


@bot.tree.command(name='minesweeper_reset', description='🧹 Xóa ván Dò Mìn bị kẹt trong kênh này')
async def minesweeper_reset_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    existed = games.minesweeper_force_reset(cid)
    if not existed:
        await interaction.response.send_message('ℹ️ Kênh này không có ván Dò Mìn nào đang chạy.', ephemeral=True)
        return
    await interaction.response.send_message('🧹 Đã xóa ván Dò Mìn bị kẹt. Chơi ván mới với `/minesweeper`!', ephemeral=True)


@bot.tree.command(name='minesweeper_top', description='🏆 Bảng xếp hạng Dò Mìn — theo số ván thắng')
async def minesweeper_top_slash(interaction: discord.Interaction):
    top = games.top_minesweeper(10)
    if not top:
        await interaction.response.send_message('_(Chưa có ai thắng ván Dò Mìn nào cả)_', ephemeral=True)
        return
    medals = ['🥇', '🥈', '🥉']
    lines = []
    for i, (uid, wins, total_aura) in enumerate(top):
        rank = medals[i] if i < 3 else f'#{i + 1}'
        lines.append(f'{rank} <@{uid}> — **{wins}** ván thắng ({total_aura} Aura kiếm được)')
    embed = discord.Embed(title='🏆 Top 10 Dò Mìn', description='\n'.join(lines), color=15844367)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name='wordle', description='Bắt đầu ván Wordle — chat thẳng 5 chữ để đoán')
async def wordle_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.wordle_active(cid):
        await interaction.response.send_message('⚠️ Đang có ván Wordle chưa xong!', ephemeral=True)
        return
    word, ok = games.wordle_start(cid, interaction.user.id)
    if not ok:
        await interaction.response.send_message('❌ Bạn đã hết lượt chơi `/wordle` hôm nay! Mua thêm 🎟️ Slot Vé Game ở `/shop` hoặc chờ mai nhé.', ephemeral=True)
        return
    left = games.daily_games_left_today('wordle', interaction.user.id)
    embed = discord.Embed(title='🎮 Wordle bắt đầu!', description=f'Chat thẳng một từ **5 chữ cái** để đoán (không cần lệnh).\nTối đa **{games.WORDLE_MAX_GUESSES} lượt**.\n🎟️ Lượt chơi còn lại hôm nay: **{left}**\n\n🟩 đúng vị trí ・ 🟨 đúng chữ sai vị trí ・ ⬜ sai', color=3066993)
    await interaction.response.send_message(embed=embed, view=EndGameView(cid, 'wordle'))

@bot.tree.command(name='flag', description='Đoán cờ các nước — chọn độ khó trước khi bắt đầu')
async def flag_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.flag_active(cid):
        await interaction.response.send_message('⚠️ Đang có ván đoán cờ chưa xong!', ephemeral=True)
        return
    left = games.flag_games_left_today(interaction.user.id)
    if left <= 0:
        await interaction.response.send_message('❌ Bạn đã hết lượt chơi `/flag` hôm nay! Mua thêm 🎟️ Slot Vé Game ở `/shop` hoặc chờ mai nhé.', ephemeral=True)
        return
    view = DifficultyView(cid, interaction.user.id)
    desc = f'🌱 **Dễ** (+{games.FLAG_AURA_PER_DIFFICULTY["easy"]} Aura/câu) — các nước nổi tiếng\n🌾 **Trung bình** (+{games.FLAG_AURA_PER_DIFFICULTY["medium"]} Aura/câu) — các nước quen thuộc vừa phải\n🔥 **Khó** (+{games.FLAG_AURA_PER_DIFFICULTY["hard"]} Aura/câu) — các nước ít gặp hơn\n💀 **Insane** (+{games.FLAG_AURA_PER_DIFFICULTY["insane"]} Aura/câu) — các nước siêu hiếm!'
    if games.flag_mythic_unlocked(interaction.user.id):
        desc += f'\n🌌 **Mythic** (+{games.FLAG_AURA_PER_DIFFICULTY["mythic"]} Aura/câu) — đã mở khóa, chỉ dành cho huyền thoại!'
    else:
        desc += f'\n🔒 Mythic mở khóa ở **{games.FLAG_UNLOCK_SCORE_MYTHIC}** điểm tích lũy (hiện có: {games.flag_lifetime_score(interaction.user.id)})'
    desc += f'\n\n🎟️ Lượt chơi còn lại hôm nay: **{left}**'
    embed = discord.Embed(title='🏳️ Chọn độ khó', description=desc, color=4160800)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name='whatuinto', description="Bói vui xem bạn 'thích' thể loại gì 👀")
async def whatuinto_slash(interaction: discord.Interaction):
    label, caption, percent = games.whatuinto_roll()
    embed = discord.Embed(title=f'🔮 Kết quả bói cho {interaction.user.display_name}', description=f'## {percent}% **{label}**\n\n{caption}', color=14702333)
    embed.set_footer(text='Kết quả 100% chính xác khoa học (không có căn cứ gì cả) 😌')
    await interaction.response.send_message(embed=embed)

class ChessDifficultyView(discord.ui.View):

    def __init__(self, cid, player_id):
        super().__init__(timeout=30)
        self.cid = cid
        self.player_id = player_id

    async def _start(self, interaction, bot_elo):
        if await _deny_unless(interaction, interaction.user.id == self.player_id):
            return
        if games.chess_active(self.cid):
            await interaction.response.send_message('⚠️ Đang có ván cờ vua chưa xong trong kênh này!', ephemeral=True)
            return
        _, ok = games.chess_start(self.cid, self.player_id, bot_elo)
        if not ok:
            await interaction.response.send_message('❌ Bạn đã hết lượt chơi cờ vs Bot hôm nay! Mua thêm 🎟️ Slot ở `/shop` hoặc chờ mai nhé.', ephemeral=True)
            return
        image = games.chess_board_image(self.cid)
        file = discord.File(image, filename='board.png')
        embed = _chess_board_embed(self.cid, 'Chọn **quân** rồi chọn **ô muốn đi tới** bằng menu bên dưới.')
        new_view = ChessFromView(self.cid)
        await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=new_view)
        new_view.message = await interaction.original_response()

    @discord.ui.button(label='🟢 Dễ (800 Elo)', style=discord.ButtonStyle.success)
    async def easy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, 800)

    @discord.ui.button(label='🟡 Vừa (1200 Elo)', style=discord.ButtonStyle.primary)
    async def medium(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, 1200)

    @discord.ui.button(label='🔴 Khó (1600 Elo)', style=discord.ButtonStyle.danger)
    async def hard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._start(interaction, 1600)

class ChessOpponentSelectView(discord.ui.View):

    def __init__(self, cid, inviter_id):
        super().__init__(timeout=60)
        self.cid = cid
        self.inviter_id = inviter_id
        self.time_mode = games.CHESS_DEFAULT_TIME_MODE
        user_select = discord.ui.UserSelect(placeholder='Chọn đối thủ để mời PvP...')
        user_select.callback = self._on_user_select
        self.add_item(user_select)
        mode_select = discord.ui.Select(placeholder=f"Chế độ thời gian (mặc định: {games.CHESS_TIME_MODES[self.time_mode]['label']})", options=[discord.SelectOption(label=cfg['label'], value=key) for key, cfg in games.CHESS_TIME_MODES.items()])
        mode_select.callback = self._on_mode_select
        self.add_item(mode_select)

    async def interaction_check(self, interaction: discord.Interaction):
        return not await _deny_unless(interaction, interaction.user.id == self.inviter_id, '❌ Đây không phải lựa chọn của bạn!')

    async def _on_mode_select(self, interaction: discord.Interaction):
        self.time_mode = interaction.data['values'][0]
        await interaction.response.send_message(f"✅ Đã chọn chế độ **{games.CHESS_TIME_MODES[self.time_mode]['label']}**, giờ chọn đối thủ ở menu trên.", ephemeral=True)

    async def _on_user_select(self, interaction: discord.Interaction):
        doi_thu = interaction.data['resolved']['users']
        doi_thu_id = int(list(doi_thu.keys())[0])
        doi_thu_data = doi_thu[str(doi_thu_id)]
        if doi_thu_data.get('bot'):
            await interaction.response.send_message('❌ Không thể mời bot chơi PvP!', ephemeral=True)
            return
        if doi_thu_id == self.inviter_id:
            await interaction.response.send_message('❌ Không thể tự mời chính mình!', ephemeral=True)
            return
        if games.chess_active(self.cid):
            await interaction.response.send_message('⚠️ Đang có ván cờ vua chưa xong trong kênh này!', ephemeral=True)
            return
        games.chess_create_invite(self.cid, self.inviter_id, doi_thu_id)
        view = ChessInviteView(self.cid, self.inviter_id, doi_thu_id, self.time_mode)
        mode_label = games.CHESS_TIME_MODES[self.time_mode]['label']
        await interaction.response.edit_message(content=f"♟️ <@{doi_thu_id}>, <@{self.inviter_id}> mời bạn chơi cờ vua (<@{self.inviter_id}> cầm ⚪ Trắng) — chế độ **{mode_label}**! Chấp nhận không?", embed=None, view=view)

class ChessModeView(discord.ui.View):

    def __init__(self, cid, player_id):
        super().__init__(timeout=60)
        self.cid = cid
        self.player_id = player_id

    async def interaction_check(self, interaction: discord.Interaction):
        return not await _deny_unless(interaction, interaction.user.id == self.player_id, '❌ Đây không phải lựa chọn của bạn!')

    @discord.ui.button(label='🤖 Đấu với Bot', style=discord.ButtonStyle.primary)
    async def vs_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        if games.chess_active(self.cid):
            await interaction.response.send_message('⚠️ Đang có ván cờ vua chưa xong trong kênh này!', ephemeral=True)
            return
        view = ChessDifficultyView(self.cid, self.player_id)
        await interaction.response.edit_message(content='♟️ Chọn độ khó cho bot:', view=view)

    @discord.ui.button(label='👥 Mời PvP', style=discord.ButtonStyle.success)
    async def vs_player(self, interaction: discord.Interaction, button: discord.ui.Button):
        if games.chess_active(self.cid):
            await interaction.response.send_message('⚠️ Đang có ván cờ vua chưa xong trong kênh này!', ephemeral=True)
            return
        view = ChessOpponentSelectView(self.cid, self.player_id)
        await interaction.response.edit_message(content='♟️ Chọn đối thủ và chế độ thời gian (chọn đối thủ sau cùng để gửi lời mời):', view=view)

@bot.tree.command(name='chess', description='♟️ Chơi cờ vua — đấu với Bot hoặc mời PvP')
async def chess_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    if games.chess_active(cid):
        await interaction.response.send_message('⚠️ Đang có ván cờ vua chưa xong trong kênh này!', ephemeral=True)
        return
    view = ChessModeView(cid, interaction.user.id)
    await interaction.response.send_message('♟️ Bạn muốn chơi cờ vua kiểu nào?', view=view)

@bot.tree.command(name='chess_reset', description='Xóa cưỡng bức trạng thái ván cờ bị kẹt trong kênh này')
async def chess_reset_slash(interaction: discord.Interaction):
    cid = interaction.channel_id
    existed = games.chess_force_reset(cid)
    if existed:
        await interaction.response.send_message('🧹 Đã xóa trạng thái ván cờ cũ. Giờ có thể dùng `/chess` lại bình thường.')
    else:
        await interaction.response.send_message('ℹ️ Không có ván cờ nào được lưu trong kênh này để xóa.')

class ChessInviteView(discord.ui.View):

    def __init__(self, cid, inviter_id, invitee_id, time_mode):
        super().__init__(timeout=120)
        self.cid = cid
        self.inviter_id = inviter_id
        self.invitee_id = invitee_id
        self.time_mode = time_mode

    @discord.ui.button(label='✅ Chấp nhận', style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.invitee_id, '❌ Lời mời này không dành cho bạn!'):
            return
        if games.chess_get_invite(self.cid) is None:
            await interaction.response.send_message('❌ Lời mời đã hết hạn hoặc bị hủy.', ephemeral=True)
            return
        if games.chess_active(self.cid):
            await interaction.response.send_message('⚠️ Đang có ván cờ vua khác chưa xong trong kênh này!', ephemeral=True)
            return
        games.chess_clear_invite(self.cid)
        games.chess_start_pvp(self.cid, self.inviter_id, self.invitee_id, self.time_mode)
        image = games.chess_board_image(self.cid)
        file = discord.File(image, filename='board.png')
        embed = _chess_board_embed(self.cid, f'👉 Đến lượt <@{self.inviter_id}>!')
        new_view = ChessFromView(self.cid)
        await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=new_view)
        new_view.message = await interaction.original_response()

    @discord.ui.button(label='❌ Từ chối', style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.invitee_id, '❌ Lời mời này không dành cho bạn!'):
            return
        games.chess_clear_invite(self.cid)
        await interaction.response.edit_message(content='❌ Đã từ chối lời mời chơi cờ vua.', embed=None, view=None)

_PIECE_CHOICES = [app_commands.Choice(name=label, value=key) for key, label in games.PIECE_KEY_LABELS.items()]

@bot.tree.command(name='custom_chess', description='Đổi hình ảnh cho 1 quân cờ cụ thể bằng link ảnh HOẶC upload file ảnh')
@app_commands.describe(quan='Chọn quân cờ muốn đổi ảnh', link='Link ảnh (PNG/JPG) trỏ thẳng tới file, chỉ cho quân này', file='Hoặc upload trực tiếp file ảnh (PNG/JPG) thay vì dán link')
@app_commands.choices(quan=_PIECE_CHOICES)
async def custom_chess_slash(interaction: discord.Interaction, quan: app_commands.Choice[str], link: str=None, file: discord.Attachment=None):
    if not link and (not file):
        await interaction.response.send_message('❌ Cần cung cấp **link** ảnh hoặc **file** ảnh (chọn 1 trong 2).', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if file:
        if not file.content_type or not file.content_type.startswith('image/'):
            await interaction.followup.send('❌ File phải là ảnh (png/jpg/webp...).')
            return
        raw = await file.read()
        ok = games.set_piece_theme_bytes(interaction.user.id, quan.value, raw)
    else:
        ok = games.set_piece_theme(interaction.user.id, quan.value, link)
    if not ok:
        await interaction.followup.send('❌ Không tải/đọc được ảnh này. Kiểm tra lại: nếu dùng link, phải trỏ thẳng tới file ảnh (PNG/JPG) và còn truy cập được (lưu ý: link CDN Discord có thể hết hạn sau vài giờ, hãy dùng link ảnh cố định như Imgur).')
        return
    preview = games.piece_theme_preview_image(interaction.user.id)
    file_out = discord.File(preview, filename='piece_theme.png')
    await interaction.followup.send(content=f'✅ Đã đổi ảnh cho **{quan.name}**! Đây là toàn bộ bộ quân cờ hiện tại của bạn:', file=file_out)

@bot.tree.command(name='custom_chess_xoa', description='Xóa ảnh custom của 1 quân cờ (bỏ trống = xóa toàn bộ)')
@app_commands.describe(quan='Quân muốn xóa ảnh custom — bỏ trống để xóa hết cả bộ')
@app_commands.choices(quan=_PIECE_CHOICES)
async def custom_chess_xoa_slash(interaction: discord.Interaction, quan: app_commands.Choice[str]=None):
    key = quan.value if quan else None
    existed = games.clear_piece_theme(interaction.user.id, key)
    if not existed:
        await interaction.response.send_message('ℹ️ Không có ảnh custom nào để xóa.', ephemeral=True)
        return
    label = quan.name if quan else 'toàn bộ bộ quân'
    await interaction.response.send_message(f'🧹 Đã xóa ảnh custom cho **{label}**, quay về mặc định.', ephemeral=True)

@bot.tree.command(name='custom_chess_xem', description='Xem bộ quân cờ custom hiện tại của bạn')
async def custom_chess_xem_slash(interaction: discord.Interaction):
    preview = games.piece_theme_preview_image(interaction.user.id)
    file = discord.File(preview, filename='piece_theme.png')
    await interaction.response.send_message(content='🎨 Bộ quân cờ hiện tại của bạn:', file=file)

@bot.tree.command(name='wiki', description='Tra cứu bách khoa toàn thư (Wikipedia tiếng Việt)')
@app_commands.describe(tu_khoa='Từ khóa cần tra cứu')
async def wiki_slash(interaction: discord.Interaction, tu_khoa: str):
    await interaction.response.defer()
    result = games.wiki_lookup(tu_khoa)
    if result is None:
        await interaction.followup.send(f'❌ Không tìm thấy thông tin cho **"{tu_khoa}"**.')
        return
    title, summary, thumbnail, url = result
    embed = discord.Embed(title=f'📖 {title}', description=summary, url=url, color=3589616)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    embed.set_footer(text='Nguồn: Wikipedia tiếng Việt')
    await interaction.followup.send(embed=embed)

@bot.tree.command(name='aura', description='Xem số dư Aura')
@app_commands.describe(member='Xem Aura của người khác (bỏ trống để xem của chính bạn)')
async def aura_slash(interaction: discord.Interaction, member: discord.Member=None):
    target = member or interaction.user
    balance = games.get_aura(target.id)
    balance_plus = games.get_aura_plus(target.id)
    who = 'Bạn' if target.id == interaction.user.id else target.mention
    await interaction.response.send_message(f'{games.AURA_ICON} {who} đang có **{balance} Aura** và **{balance_plus} Aura+**.')

@bot.tree.command(name='chon_tiente', description='💱 Đổi qua lại giữa Aura và Aura+ (phí đổi 80%)')
@app_commands.describe(loai='Chọn chiều đổi', so_luong='Số lượng muốn đổi')
@app_commands.choices(loai=[app_commands.Choice(name='Aura+ ➜ Aura', value='plus_to_aura'), app_commands.Choice(name='Aura ➜ Aura+', value='aura_to_plus')])
async def chon_tiente_slash(interaction: discord.Interaction, loai: app_commands.Choice[str], so_luong: float):
    user_id = interaction.user.id
    if so_luong <= 0:
        await interaction.response.send_message('❌ Số lượng phải lớn hơn 0.', ephemeral=True)
        return
    if loai.value == 'plus_to_aura':
        result = games.exchange_aura_plus_to_aura(user_id, so_luong)
        if result is None:
            await interaction.response.send_message(f'❌ Không đủ Aura+! Bạn hiện có **{games.get_aura_plus(user_id)} Aura+**.', ephemeral=True)
            return
        await interaction.response.send_message(f"💱 Đã đổi **{result['spent']} Aura+** ➜ **{result['received']:.1f} Aura** (phí đổi 80%).\n{games.AURA_ICON} Số dư: **{result['aura_after']} Aura**, **{result['aura_plus_after']} Aura+**.")
    else:
        result = games.exchange_aura_to_aura_plus(user_id, so_luong)
        if result is None:
            await interaction.response.send_message(f'❌ Không đủ Aura! Bạn hiện có **{games.get_aura(user_id)} Aura**.', ephemeral=True)
            return
        await interaction.response.send_message(f"💱 Đã đổi **{result['spent']} Aura** ➜ **{result['received']} Aura+** (phí đổi 80%).\n{games.AURA_ICON} Số dư: **{result['aura_after']} Aura**, **{result['aura_plus_after']} Aura+**.")

def _format_receipt(target_name, r):
    ts = time.strftime('%d/%m/%Y %H:%M', time.localtime(r['time']))
    currency_label = 'Aura' if r['currency'] == 'aura' else 'Elo'
    lines = [
        '```',
        '======= HÓA ĐƠN DELTA SHOP 🧾 =======',
        f'Khách hàng : {target_name}',
        f'Thời gian  : {ts}',
        '--------------------------------------',
        f"{r['emoji']} {r['item_name']}",
        f"  -{r['cost']} {currency_label}",
        '--------------------------------------',
        f'Số dư sau  : {r["balance_after"]} {currency_label}',
        '======= Cảm ơn đã ủng hộ Delta =======',
        '```',
    ]
    return '\n'.join(lines)

@bot.tree.command(name='hoadon', description='🧾 Xem hóa đơn các lần mua ở Delta Shop')
@app_commands.describe(member='Xem hóa đơn của người khác (bỏ trống để xem của chính bạn)')
async def hoadon_slash(interaction: discord.Interaction, member: discord.Member=None):
    target = member or interaction.user
    receipts = games.get_receipts(target.id)
    who = 'Bạn' if target.id == interaction.user.id else target.mention
    if not receipts:
        await interaction.response.send_message(f'🧾 {who} chưa mua gì ở Delta Shop cả. Sạch sẽ, minh bạch 😇', ephemeral=member is None)
        return
    lines = ['```', '===== LỊCH SỬ MUA HÀNG DELTA SHOP =====', f'Khách hàng: {target.display_name}', '-----------------------------------------']
    for i, r in enumerate(receipts[:15], start=1):
        ts = time.strftime('%d/%m/%Y %H:%M', time.localtime(r['time']))
        currency_label = 'Aura' if r['currency'] == 'aura' else 'Elo'
        lines.append(f"#{i:02d} [{ts}] {r['emoji']} {r['item_name']}  -{r['cost']} {currency_label}")
    lines.append('-----------------------------------------')
    if len(receipts) > 15:
        lines.append(f'(...còn {len(receipts) - 15} hóa đơn cũ hơn không hiện)')
    lines.append('=========================================')
    lines.append('```')
    await interaction.response.send_message(f'🧾 Hóa đơn Delta Shop của {who}:\n' + '\n'.join(lines))
GUBBY_ROLE_ID = 1528977786490978454

SHOP_ITEMS_PER_PAGE = 4

def _shop_page_keys(page):
    keys = list(games.shop_list().keys())
    start = page * SHOP_ITEMS_PER_PAGE
    return keys[start:start + SHOP_ITEMS_PER_PAGE]

def _shop_page_count():
    total = len(games.shop_list())
    return max(1, -(-total // SHOP_ITEMS_PER_PAGE))

def _shop_embed(page=0):
    remain = games.shop_seconds_until_restock()
    m, s = divmod(remain, 60)
    total_pages = _shop_page_count()
    lines = ['> 🕒 Restock mỗi 5 phút, học hỏi tinh hoa từ Grow a Garden — nhanh tay kẻo hết, chậm tay ăn cám.', '', '╭────────────────────────────╮', '🛍️ Gian Hàng Bán Danh Dự', '╰────────────────────────────╯', '']
    for key in _shop_page_keys(page):
        item = games.shop_list()[key]
        currency_label = 'Aura' if item['currency'] == 'aura' else 'Elo'
        stock = games.shop_stock_left(key)
        stock_line = f'📦 Còn lại: **{stock}**' if stock > 0 else '📦 **CHÁY HÀNG** (dân tình gom sạch rồi)'
        lines.append(f"{item['emoji']} **{item['name']}**")
        lines.append(f"> 💰 Giá: {item['price']} {currency_label}  |  {stock_line}")
        for l in item['desc'].split('\n'):
            lines.append(f'> {l}')
        lines.append('')
    lines.append(f'⏰ Restock tiếp theo sau: **{m}:{s:02d}** — ráng chờ hoặc ráng nghèo.')
    lines.append('')
    lines.append('*"Tiền không mua được hạnh phúc... nhưng mua được Elo, mà Elo còn đáng giá hơn hạnh phúc."* 🥕🥶')
    embed = discord.Embed(title=f'🛒 Delta Shop (trang {page + 1}/{total_pages})', description='\n'.join(lines), color=3066993)
    return embed

class ShopView(discord.ui.View):

    def __init__(self, buyer_id, page=0):
        super().__init__(timeout=120)
        self.buyer_id = buyer_id
        self.page = page
        total_pages = _shop_page_count()
        options = []
        for key in _shop_page_keys(page):
            item = games.shop_list()[key]
            stock = games.shop_stock_left(key)
            label = f"{item['name']} — {item['price']} {('Aura' if item['currency'] == 'aura' else 'Elo')}"
            if stock <= 0:
                label += ' (Hết hàng)'
            options.append(discord.SelectOption(label=label, value=key, emoji=item['emoji']))
        select = discord.ui.Select(placeholder='🛒 Chọn vật phẩm muốn mua...', options=options, row=0)
        select.callback = self.on_select
        self.add_item(select)
        prev_button = discord.ui.Button(label='◀', style=discord.ButtonStyle.secondary, disabled=page <= 0, row=1)
        prev_button.callback = self.on_prev
        self.add_item(prev_button)
        page_label = discord.ui.Button(label=f'{page + 1}/{total_pages}', style=discord.ButtonStyle.secondary, disabled=True, row=1)
        self.add_item(page_label)
        next_button = discord.ui.Button(label='▶', style=discord.ButtonStyle.secondary, disabled=page >= total_pages - 1, row=1)
        next_button.callback = self.on_next
        self.add_item(next_button)

    async def _goto(self, interaction, new_page):
        if await _deny_unless(interaction, interaction.user.id == self.buyer_id, '❌ Đây không phải shop của bạn, dùng `/shop` để mở cái riêng!'):
            return
        embed = _shop_embed(new_page)
        view = ShopView(self.buyer_id, new_page)
        await interaction.response.edit_message(embed=embed, view=view)

    async def on_prev(self, interaction: discord.Interaction):
        await self._goto(interaction, self.page - 1)

    async def on_next(self, interaction: discord.Interaction):
        await self._goto(interaction, self.page + 1)

    async def on_select(self, interaction: discord.Interaction):
        if await _deny_unless(interaction, interaction.user.id == self.buyer_id, '❌ Đây không phải shop của bạn, dùng `/shop` để mở cái riêng!'):
            return
        item_key = interaction.data['values'][0]
        result = games.shop_buy(interaction.user.id, item_key)
        if not result['ok']:
            await interaction.response.send_message(result['reason'], ephemeral=True)
            return
        item = result['item']
        msg = f"{item['emoji']} Đã mua **{item['name']}**! Số dư mới: **{result['balance_after']}**."
        if item_key == 'role_gubby':
            role = interaction.guild.get_role(GUBBY_ROLE_ID) if interaction.guild else None
            if role and isinstance(interaction.user, discord.Member):
                try:
                    await interaction.user.add_roles(role, reason='Mua Role Gubby ở Delta Shop')
                    msg += f'\n🐹 Đã trao role {role.mention} cho bạn!'
                except discord.Forbidden:
                    msg += '\n⚠️ Bot không đủ quyền để trao role, nhờ admin cấp `Manage Roles` cho bot nhé.'
            else:
                msg += '\n⚠️ Không tìm thấy role Gubby trong server này.'
        receipt_text = _format_receipt(interaction.user.display_name, result['receipt'])
        await interaction.response.send_message(f'{msg}\n{receipt_text}', ephemeral=True)

@bot.tree.command(name='shop', description='🛒 Mở Delta Shop — đổi Aura/Elo lấy vật phẩm & buff')
async def shop_slash(interaction: discord.Interaction):
    embed = _shop_embed(0)
    view = ShopView(interaction.user.id, 0)
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name='kho', description='🎒 Xem vật phẩm/buff bạn đang sở hữu từ Delta Shop')
@app_commands.describe(member='Xem kho của người khác (bỏ trống để xem của chính bạn)')
async def kho_slash(interaction: discord.Interaction, member: discord.Member=None):
    target = member or interaction.user
    who = 'Bạn' if target.id == interaction.user.id else target.mention
    text = games.shop_inventory_text(target.id)
    await interaction.response.send_message(f'🎒 Kho đồ của {who}:\n{text}')

def _danhgia_embed(image_url, rater_name):
    result = games.danhgia_generate(image_url)
    stars = '⭐' * result['score'] + '☆' * (10 - result['score'])
    embed = discord.Embed(title=f"📸 Đánh Giá Ảnh — {result['tier_label']}", description=f"**Điểm: {result['score']}/10**\n{stars}\n\n{result['comment']}", color=result['color'])
    embed.set_image(url=result['image_url'])
    embed.set_footer(text=f'Chấm bởi {rater_name}')
    return embed

@bot.tree.command(name='danhgia', description='📸 Nhờ bot chấm điểm thẩm mỹ 1 tấm ảnh (bố cục, ánh sáng, màu sắc...)')
@app_commands.describe(anh='Ảnh muốn chấm điểm (upload trực tiếp)')
async def danhgia_slash(interaction: discord.Interaction, anh: discord.Attachment):
    if not anh.content_type or not anh.content_type.startswith('image/'):
        await interaction.response.send_message('❌ File phải là ảnh (png/jpg/webp...).', ephemeral=True)
        return
    embed = _danhgia_embed(anh.url, interaction.user.display_name)
    await interaction.response.send_message(embed=embed)

NITRO_LOAD_STEPS = [12, 27, 41, 58, 73, 86, 94, 100]

def _nitro_bar(percent):
    filled = round(percent / 100 * 8)
    bar = '▰' * filled + '▱' * (8 - filled)
    return f'{bar} `{percent}%`'

def _nitro_fake_code():
    chars = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    return ''.join(random.choice(chars) for _ in range(16))

@bot.tree.command(name='nitro_generate', description='🎁 Generate Discord Nitro')
async def nitro_generate_slash(interaction: discord.Interaction):
    await interaction.response.send_message(f'🎁 Đang generate Nitro...\n{_nitro_bar(0)}')
    for percent in NITRO_LOAD_STEPS:
        await asyncio.sleep(random.uniform(0.4, 0.9))
        await interaction.edit_original_response(content=f'🎁 Đang generate Nitro...\n{_nitro_bar(percent)}')
    fake_code = _nitro_fake_code()
    await asyncio.sleep(0.3)
    await interaction.edit_original_response(content=f'https://discord.gift/{fake_code}')

def _lottery_prize_line(ticket):
    if ticket['prize_amount'] > 0:
        return f"🎉 **{ticket['prize_label']}**! Vé **#{ticket['id']}** (`{ticket['number']}` - {ticket['province']})\n{games.AURA_ICON} +{ticket['prize_amount']} Aura"
    return f"😢 Vé **#{ticket['id']}** (`{ticket['number']}` - {ticket['province']}) — chúc bạn may mắn lần sau!"

def _lottery_shop_embed():
    if games.lottery_sale_open():
        remain = games.lottery_seconds_until_sale_change()
        status = f'🟢 Đang mở bán — đóng cửa sau **{remain // 3600}h{(remain % 3600) // 60}p** (đúng {games.LOTTERY_SALE_CLOSE_HOUR}h chiều nay).'
    else:
        remain = games.lottery_seconds_until_sale_change()
        status = f'🔴 Đã đóng cửa hôm nay — mở lại sau **{remain // 3600}h{(remain % 3600) // 60}p** (0h đêm nay).'
    stock = games.lottery_stock_remaining()
    embed = discord.Embed(title='🏪 Đại Lý Vé Số Phonk Delta', description=f"{status}\n\n📦 Kho còn: **{stock}/{games.LOTTERY_STOCK_TOTAL}** tờ hôm nay.\n💰 Giá: **{games.LOTTERY_TICKET_PRICE} Aura/tờ**\n🎲 Đài và dãy số được random hoàn toàn, không tự chọn được (né lạm phát 😎).\n\nBấm nút bên dưới để mua 1 tờ!", color=15277667)
    return embed

class LotteryShopView(discord.ui.View):

    def __init__(self):
        super().__init__(timeout=180)

    @discord.ui.button(label='🎫 Mua vé số', style=discord.ButtonStyle.success)
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        result = games.lottery_buy(interaction.user.id)
        if not result['ok']:
            await interaction.response.send_message(result['reason'], ephemeral=True)
            return
        ticket = result['ticket']
        embed = discord.Embed(title='🎫 Vé Số Phonk Delta', description=f'Chúc bạn may mắn, **{interaction.user.display_name}**! 🍀', color=3066993)
        embed.add_field(name='🏙️ Tỉnh', value=ticket['province'], inline=True)
        embed.add_field(name='🔢 Dãy số', value=f"`{ticket['number']}`", inline=True)
        embed.add_field(name='🆔 Mã vé', value=f"#{ticket['id']}", inline=True)
        embed.add_field(name='📦 Kho còn lại', value=f"{result['remaining']}/{games.LOTTERY_STOCK_TOTAL} tờ", inline=False)
        embed.set_footer(text=f"Xem bảng KQXS bằng /xemveso · Kiểm tra riêng vé này bằng /kiemtra_veso {ticket['id']} sau {games.LOTTERY_SALE_CLOSE_HOUR}h chiều")
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name='shop_dailyveso', description='🏪 Mở Đại Lý Vé Số Phonk Delta — bán tới 16h chiều, 10 Aura/tờ')
async def shop_dailyveso_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_lottery_shop_embed(), view=LotteryShopView())

@bot.tree.command(name='xemveso', description='🔍 Xem bảng KQXS 3 tỉnh hôm nay + danh sách vé số của bạn')
async def xemveso_slash(interaction: discord.Interaction):
    weekday, date_str = games.lottery_today_label()
    today_provinces = games.lottery_today_provinces()
    day_key = games._vn_today_key()
    embed = discord.Embed(title=f'📋 KẾT QUẢ XỔ SỐ — {weekday.upper()} - {date_str}', color=15277667)
    if games.lottery_result_announced({'day_key': day_key}):
        for province in today_provinces:
            embed.add_field(name=province, value=games.lottery_board_table(province, day_key), inline=True)
    else:
        remain = games.lottery_seconds_until_sale_change()
        embed.description = f'⏳ KQXS hôm nay chưa công bố — ra lúc {games.LOTTERY_SALE_CLOSE_HOUR}h chiều (còn **{remain // 3600}h{(remain % 3600) // 60}p**).\n\n**Tỉnh mở hôm nay:** {", ".join(today_provinces)}'
    my_tickets = games.lottery_user_tickets(interaction.user.id)
    pending = [t for t in my_tickets if not t['checked']]
    if pending:
        ticket_lines = [f"🎫 Vé **#{t['id']}** — `{t['number']}` ({t['province']})" for t in pending[-15:]]
        embed.add_field(name=f'🎫 Vé chưa dò ({min(len(pending), 15)}/{len(pending)})', value='\n'.join(ticket_lines)[:1024], inline=False)
        embed.set_footer(text=f'Tự dò số của bạn với bảng KQXS trên nhé — dò xong dùng /kiemtra_veso [mã vé] để nhận Aura nếu trúng ({games.LOTTERY_CHECK_PRICE} Aura/lần)')
    elif my_tickets:
        embed.set_footer(text='Bạn đã dò hết vé rồi — mua thêm vé mới bằng /shop_dailyveso')
    else:
        embed.set_footer(text='Bạn chưa có vé nào — mua vé bằng /shop_dailyveso')
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='kiemtra_veso', description=f'🔎 Kiểm tra 1 vé số theo mã — {games.LOTTERY_CHECK_PRICE} Aura/lần')
@app_commands.describe(ma_ve='Mã vé số cần kiểm tra (vd: 12)')
async def kiemtra_veso_slash(interaction: discord.Interaction, ma_ve: int):
    result = games.lottery_check_by_id(interaction.user.id, ma_ve)
    if not result['ok']:
        await interaction.response.send_message(result['reason'], ephemeral=True)
        return
    ticket = result['ticket']
    if ticket['prize_amount'] > 0:
        embed = discord.Embed(title='🎉 CHÚC MỪNG TRÚNG THƯỞNG!', description=f"Vé **#{ticket['id']}** (`{ticket['number']}` - {ticket['province']})\n\n**{ticket['prize_label']}**\n{games.AURA_ICON} +{ticket['prize_amount']} Aura", color=15844367)
    else:
        embed = discord.Embed(title='😢 Chúc bạn may mắn lần sau', description=f"Vé **#{ticket['id']}** (`{ticket['number']}` - {ticket['province']}) không trúng gì.", color=8359053)
    await interaction.response.send_message(embed=embed)

def _minesweeper_status_embed(game, footer_extra=''):
    if game['over'] and (not game['won']):
        title, color, desc = ('💥 DÒ MÌN — Nổ mìn rồi!', 15158332, 'Bạn đã đạp trúng mìn. Chơi lại với `/minesweeper`!')
    elif game['won']:
        title, color, desc = ('🎉 DÒ MÌN — Chiến thắng!', 3066993, 'Bạn đã mở hết toàn bộ ô an toàn!')
    else:
        remaining = game['mine_count'] - len(game['flags'])
        title, color, desc = ('💣 Dò Mìn — Trò Chơi Cổ Đại', 3447003, f"Còn **{remaining}** mìn chưa đánh dấu. Bấm ⌨️ để nhập tọa độ (VD: `B3`), hoặc bấm 🚩 để bật/tắt chế độ cắm cờ.{footer_extra}")
    return discord.Embed(title=title, description=desc, color=color)

class MinesweeperCoordModal(discord.ui.Modal):

    def __init__(self, view):
        super().__init__(title='Nhập tọa độ ô (VD: B3)')
        self.ms_view = view
        self.coord_input = discord.ui.TextInput(label='Tọa độ ô', placeholder='Ví dụ: A1, C5, H8...', max_length=6)
        self.add_item(self.coord_input)

    async def on_submit(self, interaction: discord.Interaction):
        await self.ms_view.handle_coord(interaction, self.coord_input.value)

def _minesweeper_parse_coord(text, size):
    text = text.strip().upper().replace(' ', '')
    m = re.match('^([A-Z]+)(\\d+)$', text)
    if not m:
        return None
    col_letters, row_digits = m.groups()
    col = 0
    for ch in col_letters:
        col = col * 26 + (ord(ch) - 64)
    col -= 1
    row = int(row_digits) - 1
    if not (0 <= row < size and 0 <= col < size):
        return None
    return (row, col)

class MinesweeperView(discord.ui.View):

    def __init__(self, cid, owner_id, game_id):
        super().__init__(timeout=300)
        self.cid = cid
        self.owner_id = owner_id
        self.game_id = game_id
        self.flag_mode = False
        self._sync_flag_button()

    def _sync_flag_button(self):
        self.flag_toggle_btn.style = discord.ButtonStyle.success if self.flag_mode else discord.ButtonStyle.secondary
        self.flag_toggle_btn.label = '🚩 Chế độ cắm cờ: BẬT' if self.flag_mode else '🚩 Chế độ cắm cờ: TẮT'

    async def interaction_check(self, interaction: discord.Interaction):
        return not await _deny_unless(interaction, interaction.user.id == self.owner_id, '❌ Đây không phải ván /minesweeper của bạn!')

    def _game_or_none(self):
        current = games.minesweeper_game(self.cid)
        if current is None or current.get('game_id') != self.game_id:
            return None
        return current

    async def _refresh(self, interaction, extra_note=''):
        game = self._game_or_none()
        if game is None:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content='⌛ Ván này đã kết thúc hoặc hết hạn. Chơi lại với `/minesweeper`!', embed=None, attachments=[], view=self)
            return
        self.timeout = 300
        img_buf = games.minesweeper_render_image(self.cid)
        file = discord.File(img_buf, filename='minesweeper.png')
        embed = _minesweeper_status_embed(game, extra_note)
        embed.set_image(url='attachment://minesweeper.png')
        if game['over']:
            for item in self.children:
                item.disabled = True
            games.minesweeper_end(self.cid, self.game_id)
            if game['won']:
                new_aura, new_aura_plus, aura_gain, aura_plus_gain, elapsed, mult = games.award_minesweeper_win(self.owner_id, game)
                bonus_txt = ''
                if mult >= games.MINESWEEPER_FAST_MULT:
                    bonus_txt = ' ⚡ (bonus thắng siêu tốc!)'
                elif mult >= games.MINESWEEPER_QUICK_MULT:
                    bonus_txt = ' ⚡ (bonus thắng nhanh!)'
                time_txt = f'\n⏱️ Thời gian: **{elapsed}s**{bonus_txt}' if elapsed is not None else ''
                embed.description += f"\n\n{games.AURA_ICON} +{aura_gain} Aura (số dư: {new_aura})\n{games.AURA_PLUS_ICON} +{aura_plus_gain} Aura+ (số dư: {new_aura_plus}){time_txt}"
        await interaction.response.edit_message(content=None, embed=embed, attachments=[file], view=self)

    async def handle_coord(self, interaction, raw_text):
        try:
            game = self._game_or_none()
            if game is None:
                await interaction.response.send_message('⌛ Ván này đã kết thúc hoặc hết hạn. Chơi lại với `/minesweeper`!', ephemeral=True)
                return
            pos = _minesweeper_parse_coord(raw_text, game['size'])
            if pos is None:
                await interaction.response.send_message(f"❌ Tọa độ không hợp lệ. Dùng dạng chữ+số trong phạm vi bàn (VD: `A1` tới `{games.minesweeper_col_label(game['size']-1)}{game['size']}`).", ephemeral=True)
                return
            r, c = pos
            if self.flag_mode:
                games.minesweeper_toggle_flag(self.cid, self.game_id, r, c)
                await self._refresh(interaction)
                return
            result = games.minesweeper_reveal(self.cid, self.game_id, r, c)
            if result in ('gone', 'invalid'):
                await interaction.response.send_message('⌛ Ván đã kết thúc hoặc tọa độ không hợp lệ.', ephemeral=True)
                return
            if result == 'noop':
                await interaction.response.send_message('ℹ️ Ô này đang cắm cờ, hoặc đã mở nhưng số cờ xung quanh chưa khớp số ghi trên ô (cắm đủ cờ rồi nhập lại tọa độ này để tự mở nhanh các ô còn lại).', ephemeral=True)
                return
            await self._refresh(interaction)
        except Exception:
            import traceback
            traceback.print_exc()
            if not interaction.response.is_done():
                await interaction.response.send_message('⚠️ Có lỗi xảy ra, thử chơi ván mới với `/minesweeper`.', ephemeral=True)

    @discord.ui.button(label='⌨️ Nhập tọa độ', style=discord.ButtonStyle.primary, row=0)
    async def enter_coord(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self._game_or_none() is None:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content='⌛ Ván này đã kết thúc hoặc hết hạn. Chơi lại với `/minesweeper`!', view=self)
            return
        await interaction.response.send_modal(MinesweeperCoordModal(self))

    @discord.ui.button(label='🚩 Chế độ cắm cờ: TẮT', style=discord.ButtonStyle.secondary, row=0)
    async def flag_toggle_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.flag_mode = not self.flag_mode
        self._sync_flag_button()
        game = self._game_or_none()
        if game is None:
            for item in self.children:
                item.disabled = True
            await interaction.response.edit_message(content='⌛ Ván này đã kết thúc hoặc hết hạn. Chơi lại với `/minesweeper`!', view=self)
            return
        note = '\n\n🚩 **Chế độ cắm cờ đang BẬT** — nhập tọa độ để cắm/gỡ cờ thay vì mở ô.' if self.flag_mode else ''
        await self._refresh(interaction, note)

    async def on_timeout(self):
        games.minesweeper_end(self.cid, self.game_id)


@bot.tree.command(name='aichat', description='💬 Chat trực tiếp với AI (dựa vào lịch sử đoạn chat trong kênh)')
@app_commands.describe(tin_nhan='Nội dung bạn muốn nói với AI')
async def aichat_slash(interaction: discord.Interaction, tin_nhan: str):
    await interaction.response.defer(thinking=True)
    text, wait_left = await ai.reply_to_slash_command(interaction.channel, interaction.user.id, interaction.user.display_name, tin_nhan)
    if text is None:
        sent = await interaction.followup.send(f'⏳ Hừ, chờ khoảng {wait_left}s nữa rồi hỏi tiếp đi, tốn quota lắm đấy!', wait=True)
        try:
            await sent.delete(delay=5.0)
        except discord.HTTPException:
            pass
        return
    if text == ai.FALLBACK_ERROR_MSG:
        sent = await interaction.followup.send(text, wait=True)
        try:
            await sent.delete(delay=5.0)
        except discord.HTTPException:
            pass
        return
    await interaction.followup.send(f'💬 **{interaction.user.display_name}:** {tin_nhan}\n\n🤖 {text}')

@bot.tree.command(name='nhapcode', description='🎁 Nhập code để nhận thưởng Aura/Aura+')
@app_commands.describe(code='Mã code (phân biệt hoa thường)')
async def nhapcode_slash(interaction: discord.Interaction, code: str):
    result = games.redeem_code(interaction.user.id, code)
    if not result['ok']:
        await interaction.response.send_message(result['reason'], ephemeral=True)
        return
    await interaction.response.send_message(f"🎁 Nhập code thành công! Nhận được: {' , '.join(result['reward_lines'])}", ephemeral=True)

@bot.tree.command(name='admin_congaura', description='👑 [Chủ bot] Cộng Aura cho bất kỳ ai (số âm để trừ)')
@app_commands.describe(nguoi='Người nhận', so_luong='Số Aura muốn cộng (âm để trừ)')
async def admin_congaura_slash(interaction: discord.Interaction, nguoi: discord.Member, so_luong: int):
    if interaction.user.id != games.BOT_OWNER_ID:
        await interaction.response.send_message('❌ Lệnh này chỉ dành cho chủ bot.', ephemeral=True)
        return
    new_balance = games.add_aura(nguoi.id, so_luong)
    await interaction.response.send_message(f"👑 Đã cộng **{so_luong}** Aura cho {nguoi.mention}. Số dư hiện tại: **{new_balance}**.", ephemeral=True)

@bot.tree.command(name='bangxephang', description='🏆 Xem bảng xếp hạng Aura hoặc Elo')
@app_commands.describe(loai='Xếp theo Aura hay Elo')
@app_commands.choices(loai=[app_commands.Choice(name='Aura', value='aura'), app_commands.Choice(name='Elo', value='elo')])
async def bangxephang_slash(interaction: discord.Interaction, loai: app_commands.Choice[str] = None):
    key = loai.value if loai else 'aura'
    top = games.top_aura(10) if key == 'aura' else games.top_elo(10)
    title = '🏆 Top 10 Aura' if key == 'aura' else '🏆 Top 10 Elo'
    if not top:
        await interaction.response.send_message('_(Chưa có dữ liệu xếp hạng)_', ephemeral=True)
        return
    medals = ['🥇', '🥈', '🥉']
    lines = []
    for i, (uid, value) in enumerate(top):
        rank = medals[i] if i < 3 else f'#{i + 1}'
        lines.append(f"{rank} <@{uid}> — **{value}**{' Aura' if key == 'aura' else ' Elo'}")
    embed = discord.Embed(title=title, description='\n'.join(lines), color=15844367)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='help', description='📖 Xem danh sách tất cả lệnh của bot')
async def help_slash(interaction: discord.Interaction):
    embed = discord.Embed(title='📖 Danh Sách Lệnh', description='Bot mini-game vui nhộn cho server: đoán chữ, đoán cờ, cờ vua, Delta Shop, dò mìn và bói vui.\n\nToàn bộ slash command hiện có:', color=3447003)
    lines = [f"`/{cmd.name}` — {cmd.description}" for cmd in sorted(bot.tree.get_commands(), key=lambda c: c.name)]
    chunk, chunk_len, part = [], 0, 1
    for line in lines:
        if chunk_len + len(line) + 1 > 1000:
            embed.add_field(name=f'Lệnh (phần {part})', value='\n'.join(chunk), inline=False)
            chunk, chunk_len, part = [], 0, part + 1
        chunk.append(line)
        chunk_len += len(line) + 1
    if chunk:
        embed.add_field(name=f'Lệnh (phần {part})', value='\n'.join(chunk), inline=False)
    embed.set_footer(text='Made by TVPixel')
    await interaction.response.send_message(embed=embed, ephemeral=True)

web_server.keep_alive()
bot.run(os.environ['DISCORD_KEY'])