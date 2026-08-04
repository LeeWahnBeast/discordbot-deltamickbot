import discord
import os
import time
import random
import re
import io
import asyncio
import web_server
import games
import games_ext as gx
import ai
import autoresponse
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
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f'✅ Đã đồng bộ {len(synced)} slash command(s)')
    except Exception as e:
        print(f'⚠️ Lỗi đồng bộ slash command: {e}')
    ai.start_auto_chat_loop(bot)
    for guild in list(bot.guilds):
        if guild.id != ALLOWED_GUILD_ID:
            await _leave_unauthorized_guild(guild)
    print(f'✅ Bot đã đăng nhập với tên {bot.user}')
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    raise error

ALLOWED_GUILD_ID = 1528554640378171562
LEAVE_NOTICE_MESSAGE = (
    'Bot này dành riêng cho server Delta Mick, bạn không thuộc quyền sở hữu nó! '
    'Vui lòng liên hệ server: https://discord.gg/Wgwqpq8N7W\n'
    'Gặp: <@1210771747889090571>'
)

async def _leave_unauthorized_guild(guild: discord.Guild):
    target_channel = guild.system_channel
    if target_channel is None or not target_channel.permissions_for(guild.me).send_messages:
        target_channel = None
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                target_channel = channel
                break
    if target_channel is not None:
        try:
            await target_channel.send(LEAVE_NOTICE_MESSAGE)
        except Exception as e:
            print(f'⚠️ Không gửi được thông báo rời server {guild.id}: {e!r}')
    try:
        await guild.leave()
        print(f'🚪 Đã rời server không được phép: {guild.name} ({guild.id})')
    except Exception as e:
        print(f'⚠️ Lỗi khi rời server {guild.id}: {e!r}')

@bot.event
async def on_guild_join(guild: discord.Guild):
    if guild.id != ALLOWED_GUILD_ID:
        await _leave_unauthorized_guild(guild)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    cid = message.channel.id
    content = message.content.strip()
    if not content.startswith('!') and (not content.startswith('/')):
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
    try:
        completed = gx.quest_check_message(message.author.id, content, bool(message.mentions))
        for slot in completed:
            await message.channel.send(f'🎉 <@{message.author.id}> đã hoàn thành nhiệm vụ **{slot["id"]}**! +{gx.QUEST_REWARD_DEION} {games.DEION_ICON} Deion. Gõ `/quest` xem tiến độ!')
    except Exception as e:
        print(f'⚠️ Lỗi quest on_message: {e!r}')
    try:
        await autoresponse.check(message)
    except Exception as e:
        print(f'⚠️ Lỗi autoresponse: {e!r}')
    await bot.process_commands(message)

@bot.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    try:
        completed = gx.quest_check_command(interaction.user.id)
        for slot in completed:
            try:
                await interaction.followup.send(f'🎉 Bạn vừa hoàn thành nhiệm vụ "sài lệnh ngẫu nhiên"! +{gx.QUEST_REWARD_DEION} {games.DEION_ICON} Deion. Gõ `/quest` xem tiến độ!', ephemeral=True)
            except discord.HTTPException:
                pass
    except Exception as e:
        print(f'⚠️ Lỗi quest on_app_command_completion: {e!r}')

def _quest_embed(user_id):
    st = gx.quest_state(user_id)
    lines = [f'{i + 1}. {gx.quest_desc_line(slot)}  {"✅" if slot["done"] else ""}' for i, slot in enumerate(st['slots'])]
    reset_ts = gx.quest_reset_timestamp()
    desc = (
        'Quest hàng ngày:\n' + '\n'.join(lines) +
        f'\n\nTiến độ:\n{gx.quest_bar(user_id)} ( kết thúc <t:{reset_ts}:R> )\n\n'
        f'🎁 Mỗi nhiệm vụ hoàn thành: **+{gx.QUEST_REWARD_DEION}** {games.DEION_ICON} Deion'
    )
    embed = discord.Embed(title='📜 NHIỆM VỤ HÔM NAY', description=desc, color=3447003)
    if st['swapped']:
        embed.set_footer(text='Đã dùng lượt đổi nhiệm vụ hôm nay')
    return embed

class QuestView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=120)
        self.user_id = user_id

    @discord.ui.button(label='🔄 Đổi nhiệm vụ (1 lần/ngày)', style=discord.ButtonStyle.secondary)
    async def swap_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Đây không phải quest của bạn!'):
            return
        ok = gx.quest_swap(self.user_id)
        if not ok:
            await interaction.response.send_message('❌ Bạn đã dùng lượt đổi nhiệm vụ hôm nay rồi!', ephemeral=True)
            return
        await interaction.response.edit_message(embed=_quest_embed(self.user_id))

@bot.tree.command(name='quest', description='📜 Xem nhiệm vụ hàng ngày & tiến độ — hoàn thành nhận 10 Deion/nv')
async def quest_slash(interaction: discord.Interaction):
    await interaction.response.send_message(embed=_quest_embed(interaction.user.id), view=QuestView(interaction.user.id))

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

MOVE_ANNOTATION_TEXT = {'!!': '✨ **!!** Nước đi thiên tài!', '??': '🤦 **??** Nước đi ngớ ngẩn!'}
GAME_CONFIG = {'chess': {'active': games.chess_active, 'end': games.chess_end, 'label': 'Cờ vua', 'reveal': lambda cid: 'Ván đấu đã dừng.'}}

# --- Thanh đếm ngược dùng chung cho các minigame có giới hạn thời gian ---
_COUNTDOWN_SLOTS = 10

def _countdown_bar(remaining, total=15):
    filled = max(0, min(_COUNTDOWN_SLOTS, round(remaining / total * _COUNTDOWN_SLOTS)))
    if remaining > total * 0.5:
        fill_emoji = '🟩'
    elif remaining > total * 0.2:
        fill_emoji = '🟨'
    else:
        fill_emoji = '🟥'
    return fill_emoji * filled + '⬜' * (_COUNTDOWN_SLOTS - filled)
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

@bot.tree.command(name='random_elliot_sigma', description='🗿 Random 1 câu nói huyền thoại')
async def random_elliot_sigma_slash(interaction: discord.Interaction):
    phrase = gx.random_elliot_sigma()
    embed = discord.Embed(description=f'🗿 **{phrase}**', color=15844367)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='jackpot', description='🎰 Cược Deion vào hũ — cược càng cao thì % thắng càng thấp, liệu hồn!')
@app_commands.describe(cuoc='Số Deion muốn cược (càng cược nhiều thì càng dễ toang)')
async def jackpot_slash(interaction: discord.Interaction, cuoc: float):
    uid = interaction.user.id
    ok, reason, won, win_chance, new_balance, payout = gx.jackpot_play(uid, cuoc)
    if not ok:
        await interaction.response.send_message(reason, ephemeral=True)
        return
    chance_pct = round(win_chance * 100)
    if won:
        _, ve = gx.award_win('jackpot', uid, deion_mult=0)
        embed = discord.Embed(
            title='🎰 JACKPOT NỔ HŨ RỒI ĐÓ THÁNH 🤑🔥',
            description=(
                f'Cược **{cuoc} Deion**, tỉ lệ thắng có **{chance_pct}%** thôi mà mày trúng thiệt 😳\n\n'
                f'{games.DEION_ICON} **+{payout} Deion**, {gx.VE_ICON} +{ve} Vé (số dư: **{new_balance}**)\n\n'
                f'🍀 Số hưởng dữ vậy đi mua vé số đi, đừng chơi bot nữa 💅'
            ),
            color=3066993,
        )
    else:
        embed = discord.Embed(
            title='🎰 CHÁY TÚI RỒI ĐỒ NGHIỆN 💀📉',
            description=(
                f'Cược **{cuoc} Deion**, tỉ lệ thắng chỉ **{chance_pct}%**... và mày thua thiệt rồi 🤡\n\n'
                f'{games.DEION_ICON} **-{payout} Deion** (số dư: **{new_balance}**)\n\n'
                f'😭 Cược cao thì dễ toang thôi, biết điều thì cược nhẹ nhẹ lại đi 🙏'
            ),
            color=15158332,
        )
    embed.set_footer(text='📉 Cược càng cao thì % thắng càng thấp — tham thì thâm nha bạn ơi')
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name='create-code', description='🎫 Tự tạo code tặng Deion cho người khác — Deion trừ thẳng từ ví của mày mỗi khi có người nhập')
@app_commands.describe(
    ten='Tên code (không trùng code có sẵn)',
    deion='Số Deion tặng MỖI lượt nhập (trừ thẳng từ ví của mày)',
    thoihan='Thời hạn code, tính theo GIỜ (VD: 24 = 1 ngày)',
    luot='Số lượt nhập tối đa (bỏ trống = không giới hạn, chỉ dừng khi hết hạn hoặc hết Deion)',
)
async def create_code_slash(interaction: discord.Interaction, ten: str, deion: float, thoihan: float, luot: int = None):
    ok, reason = gx.create_custom_code(interaction.user.id, ten, deion, thoihan, luot)
    if not ok:
        await interaction.response.send_message(reason, ephemeral=True)
        return
    luot_text = f'{luot} lượt' if luot else 'không giới hạn lượt'
    embed = discord.Embed(
        title='🎫 TẠO CODE THÀNH CÔNG — RẢI ĐI THÔI 📢',
        description=(
            f'Tên code: **{ten.strip()}**\n'
            f'{games.DEION_ICON} Mỗi lượt nhập: **{deion} Deion** (trừ thẳng từ ví của mày mỗi khi có người nhập)\n'
            f'⏳ Hạn dùng: **{int(thoihan)} giờ** · 🔁 {luot_text}\n\n'
            f'⚠️ Ví cạn Deion giữa chừng là code tự bay màu, người nhập sau sẽ thấy dòng "Hết Deion của người tạo code" đó nha 😤\n'
            f'🙅 Mày tự tạo thì tự mày không nhập được code này đâu, đừng có lách luật.'
        ),
        color=15844367,
    )
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

@bot.tree.command(name='chess-reset', description='Xóa cưỡng bức trạng thái ván cờ bị kẹt trong kênh này')
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

@bot.tree.command(name='custom-chess', description='Đổi hình ảnh cho 1 quân cờ cụ thể bằng link ảnh HOẶC upload file ảnh')
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

@bot.tree.command(name='custom-chess-xóa', description='Xóa ảnh custom của 1 quân cờ (bỏ trống = xóa toàn bộ)')
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

@bot.tree.command(name='custom-chess-xem', description='Xem bộ quân cờ custom hiện tại của bạn')
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

@bot.tree.command(name='deion', description='Xem số dư Deion')
@app_commands.describe(member='Xem Deion của người khác (bỏ trống để xem của chính bạn)')
async def deion_slash(interaction: discord.Interaction, member: discord.Member=None):
    target = member or interaction.user
    balance = games.get_deion(target.id)
    who = 'Bạn' if target.id == interaction.user.id else target.mention
    await interaction.response.send_message(f'{games.DEION_ICON} {who} đang có **{balance} Deion**.')

def _format_receipt(target_name, r):
    ts = time.strftime('%d/%m/%Y %H:%M', time.localtime(r['time']))
    currency_label = 'Deion' if r['currency'] == 'deion' else 'Elo'
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

GUBBY_ROLE_ID = 1528977786490978454

SHOP_ITEMS_PER_PAGE = 4

def _shop_page_keys(page):
    keys = list(games.shop_list().keys())
    start = page * SHOP_ITEMS_PER_PAGE
    return keys[start:start + SHOP_ITEMS_PER_PAGE]

def _shop_page_count():
    total = len(games.shop_list())
    return max(1, -(-total // SHOP_ITEMS_PER_PAGE))

_RARITY_TAG = {'common': '⚪ Thường', 'rare': '🔵 Hiếm', 'epic': '🟣 Cực hiếm', 'legendary': '🟠 Huyền thoại', 'mythic': '🔴 Thần thoại'}

def _shop_embed(page=0):
    remain = games.shop_seconds_until_restock()
    m, s = divmod(remain, 60)
    total_pages = _shop_page_count()
    embed = discord.Embed(
        title='🛍️ DELTA SHOP',
        description=f'🕒 Restock mỗi 5 phút · Tiếp theo sau **{m}:{s:02d}**\n*"Tiền không mua được hạnh phúc... nhưng mua được Elo."* 🥕',
        color=3066993,
    )
    for key in _shop_page_keys(page):
        item = games.shop_list()[key]
        currency_label = 'Deion' if item['currency'] == 'deion' else 'Elo'
        stock = games.shop_stock_left(key)
        stock_line = f'📦 Còn **{stock}**' if stock > 0 else '📦 **CHÁY HÀNG**'
        rarity = _RARITY_TAG.get(item.get('rarity'), '')
        desc_short = item['desc'].split(chr(10))[0]
        value = f"💰 **{item['price']}** {currency_label}  ·  {stock_line}  ·  {rarity}\n{desc_short}"
        embed.add_field(name=f"{item['emoji']} {item['name']}", value=value, inline=False)
    embed.set_footer(text=f'Trang {page + 1}/{total_pages} · Chọn vật phẩm ở menu dưới để mua')
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
            label = f"{item['name']} — {item['price']} {('Deion' if item['currency'] == 'deion' else 'Elo')}"
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

@bot.tree.command(name='shop', description='🛒 Mở Delta Shop — đổi Deion/Elo lấy vật phẩm & buff')
async def shop_slash(interaction: discord.Interaction):
    embed = _shop_embed(0)
    view = ShopView(interaction.user.id, 0)
    await interaction.response.send_message(embed=embed, view=view)

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

@bot.tree.command(name='admin-congdeion', description='👑 [Chủ bot] Cộng Deion cho bất kỳ ai (số âm để trừ)')
@app_commands.describe(nguoi='Người nhận', so_luong='Số Deion muốn cộng (âm để trừ)')
async def admin_congdeion_slash(interaction: discord.Interaction, nguoi: discord.Member, so_luong: float):
    if interaction.user.id != games.BOT_OWNER_ID:
        await interaction.response.send_message('❌ Lệnh này chỉ dành cho chủ bot.', ephemeral=True)
        return
    new_balance = games.add_deion(nguoi.id, so_luong)
    await interaction.response.send_message(f"👑 Đã cộng **{so_luong}** Deion cho {nguoi.mention}. Số dư hiện tại: **{new_balance}**.", ephemeral=True)

@bot.tree.command(name='bangxephang', description='🏆 Xem bảng xếp hạng Deion hoặc Elo')
@app_commands.describe(loai='Xếp theo Deion hay Elo')
@app_commands.choices(loai=[app_commands.Choice(name='Deion', value='deion'), app_commands.Choice(name='Elo', value='elo')])
async def bangxephang_slash(interaction: discord.Interaction, loai: app_commands.Choice[str] = None):
    key = loai.value if loai else 'deion'
    top = games.top_deion(10) if key == 'deion' else games.top_elo(10)
    title = '🏆 Top 10 Deion' if key == 'deion' else '🏆 Top 10 Elo'
    if not top:
        await interaction.response.send_message('_(Chưa có dữ liệu xếp hạng)_', ephemeral=True)
        return
    medals = ['🥇', '🥈', '🥉']
    lines = []
    for i, (uid, value) in enumerate(top):
        rank = medals[i] if i < 3 else f'#{i + 1}'
        lines.append(f"{rank} <@{uid}> — **{value}**{' Deion' if key == 'deion' else ' Elo'}")
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

# ============================================================
# 🟩 WORDLE
# ============================================================
class WordleGuessModal(discord.ui.Modal, title='Đoán từ Wordle (5 chữ)'):
    guess_input = discord.ui.TextInput(label='Nhập 1 từ có đúng 5 chữ cái', placeholder='VÍ DỤ: MANGO', min_length=5, max_length=5)

    def __init__(self, cid, user_id):
        super().__init__()
        self.cid = cid
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        ok, reason, feedback, done, won = gx.wordle_guess(self.cid, self.user_id, self.guess_input.value)
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        if done:
            answer = gx.wordle_answer(self.cid, self.user_id)
            board = gx.wordle_render(self.cid, self.user_id)
            gx.wordle_end(self.cid, self.user_id)
            if won:
                reward, ve = gx.award_win('wordle', self.user_id)
                new_balance = games.get_deion(self.user_id)
                text = f'🎉 **CHÍNH XÁC!** Bạn đoán đúng từ **{answer}**!\n\n{board}\n\n{games.DEION_ICON} +{reward} Deion, {gx.VE_ICON} +{ve} Vé (số dư: {new_balance})'
            else:
                text = f'💀 Hết lượt rồi! Từ đúng là **{answer}**.\n\n{board}'
            await interaction.response.edit_message(content=text, view=None)
            return
        board = gx.wordle_render(self.cid, self.user_id)
        view = WordleView(self.cid, self.user_id)
        await interaction.response.edit_message(content=f'🟩 **WORDLE** — đoán từ tiếng Anh 5 chữ cái!\n\n{board}', view=view)

class WordleView(discord.ui.View):
    def __init__(self, cid, user_id):
        super().__init__(timeout=300)
        self.cid = cid
        self.user_id = user_id

    @discord.ui.button(label='✏️ Nhập chữ', style=discord.ButtonStyle.primary)
    async def guess_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Đây không phải ván Wordle của bạn!'):
            return
        if not gx.wordle_active(self.cid, self.user_id):
            await interaction.response.send_message('❌ Ván này đã kết thúc rồi.', ephemeral=True)
            return
        await interaction.response.send_modal(WordleGuessModal(self.cid, self.user_id))

    async def on_timeout(self):
        gx.wordle_end(self.cid, self.user_id)

@bot.tree.command(name='wordle', description=f'🟩 Chơi Wordle — đoán từ 5 chữ cái ({gx.GAME_VE_COST["wordle"]} Vé nếu hết lượt free)')
async def wordle_slash(interaction: discord.Interaction):
    cid, uid = interaction.channel.id, interaction.user.id
    if gx.wordle_active(cid, uid):
        await interaction.response.send_message('⚠️ Bạn đang có ván Wordle chưa xong ở kênh này rồi!', ephemeral=True)
        return
    can_play, note = gx.can_play_or_reason('wordle', uid)
    if not can_play:
        await interaction.response.send_message(note, ephemeral=True)
        return
    gx.wordle_start(cid, uid)
    board = gx.wordle_render(cid, uid)
    ve_note = '\n_(Đã dùng 1 🎟️ Vé vì hết lượt free hôm nay)_' if note == 've' else ''
    view = WordleView(cid, uid)
    await interaction.response.send_message(f'🟩 **WORDLE** — đoán từ tiếng Anh 5 chữ cái!\n\n{board}{ve_note}', view=view)


# ============================================================
# 💣 MINESWEEPER (v2 — seed, size NxN tuỳ chỉnh, chord, lệnh song ngữ)
# ============================================================
def _mine_status_line(cid, uid):
    rows, cols, bombs = gx.minesweeper_bounds(cid, uid)
    return f'Bàn {rows}x{cols} · 💣{bombs} · cột A-{chr(64 + cols)}, hàng 1-{rows}'

class MinesweeperMoveModal(discord.ui.Modal, title='Nhập nước đi Minesweeper'):
    cmd_input = discord.ui.TextInput(
        label='Lệnh (VN hoặc EN)',
        placeholder='VD: B3 | mở B3 / open b3 | cờ C4 / flag c4 | dò B3 / chord b3',
        max_length=20,
    )

    def __init__(self, cid, user_id):
        super().__init__()
        self.cid = cid
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        action, coord_text = gx.mine_parse_command(self.cmd_input.value)
        rc = gx.mine_coord_to_rc(coord_text) if coord_text else None
        if action is None or rc is None:
            await interaction.response.send_message(
                f'❌ Lệnh gì kỳ vậy 🤨 Gõ kiểu **B3**, **mở B3**/**open b3**, **cờ C4**/**flag c4**, **dò B3**/**chord b3** đi bạn êi.\n({_mine_status_line(self.cid, self.user_id)})',
                ephemeral=True,
            )
            return
        row, col = rc
        cid, uid = self.cid, self.user_id

        if action == 'flag':
            ok, msg = gx.minesweeper_toggle_flag(cid, uid, row, col)
            if not ok:
                await interaction.response.send_message(msg, ephemeral=True)
                return
            image = gx.minesweeper_board_image(cid, uid)
            file = discord.File(image, filename='mine.png')
            embed = discord.Embed(description=f'💣 **DÒ MÌN**\n{msg} 🚩', color=8421504)
            embed.set_image(url='attachment://mine.png')
            view = MinesweeperView(cid, uid)
            await interaction.response.edit_message(embed=embed, attachments=[file], view=view)
            return

        if action == 'chord':
            ok, reason, exploded, won = gx.minesweeper_chord(cid, uid, row, col)
            if not ok:
                await interaction.response.send_message(reason, ephemeral=True)
                return
            if reason:  # cảnh báo (chưa đủ cờ) nhưng vẫn ok=True
                await interaction.response.send_message(reason, ephemeral=True)
                return
        else:  # open
            ok, reason, exploded, won = gx.minesweeper_reveal(cid, uid, row, col)
            if not ok:
                await interaction.response.send_message(reason, ephemeral=True)
                return

        image = gx.minesweeper_board_image(cid, uid)
        file = discord.File(image, filename='mine.png')
        if exploded:
            gx.minesweeper_end(cid, uid)
            embed = discord.Embed(description='💥 **BÙM CHÁY NỔ!** Đạp trúng mìn rồi, tạch ván này luôn 💀🤡', color=15158332)
            embed.set_image(url='attachment://mine.png')
            await interaction.response.edit_message(embed=embed, attachments=[file], view=None)
        elif won:
            gx.minesweeper_end(cid, uid)
            reward, ve = gx.award_win('minesweeper', uid)
            new_balance = games.get_deion(uid)
            embed = discord.Embed(description=f'🎉 **QUÁ ĐỈNH, GỠ SẠCH MÌN LUÔN!** 🧠✨\n\n{games.DEION_ICON} +{reward} Deion, {gx.VE_ICON} +{ve} Vé (số dư: {new_balance})', color=3066993)
            embed.set_image(url='attachment://mine.png')
            await interaction.response.edit_message(embed=embed, attachments=[file], view=None)
        else:
            embed = discord.Embed(description=f'💣 **DÒ MÌN** — bấm 🎮 Đi nước để mở/cắm cờ/dò tiếp nha 😤\n_{_mine_status_line(cid, uid)}_', color=8421504)
            embed.set_image(url='attachment://mine.png')
            view = MinesweeperView(cid, uid)
            await interaction.response.edit_message(embed=embed, attachments=[file], view=view)

class MinesweeperView(discord.ui.View):
    def __init__(self, cid, user_id):
        super().__init__(timeout=300)
        self.cid = cid
        self.user_id = user_id

    @discord.ui.button(label='🎮 Đi nước', style=discord.ButtonStyle.primary)
    async def move_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Ván này không phải của mày, bú 🙅'):
            return
        if not gx.minesweeper_active(self.cid, self.user_id):
            await interaction.response.send_message('❌ Ván này đã kết thúc rồi.', ephemeral=True)
            return
        await interaction.response.send_modal(MinesweeperMoveModal(self.cid, self.user_id))

    async def on_timeout(self):
        gx.minesweeper_end(self.cid, self.user_id)

@bot.tree.command(name='minesweeper', description=f'💣 Chơi Dò Mìn — tuỳ chỉnh size, số bom, seed ({gx.GAME_VE_COST["minesweeper"]} Vé nếu hết lượt free)')
@app_commands.describe(
    hang=f'Số hàng bàn cờ ({gx.MINE_MIN_SIZE}-{gx.MINE_MAX_SIZE}, mặc định {gx.MINE_DEFAULT_SIZE})',
    cot=f'Số cột bàn cờ ({gx.MINE_MIN_SIZE}-{gx.MINE_MAX_SIZE}, mặc định {gx.MINE_DEFAULT_SIZE})',
    bom='Số lượng bom (bỏ trống để tự tính theo kích thước bàn)',
    seed='Seed để tạo lại y hệt 1 bàn cờ (bỏ trống = ngẫu nhiên)',
)
async def minesweeper_slash(
    interaction: discord.Interaction,
    hang: app_commands.Range[int, gx.MINE_MIN_SIZE, gx.MINE_MAX_SIZE] = None,
    cot: app_commands.Range[int, gx.MINE_MIN_SIZE, gx.MINE_MAX_SIZE] = None,
    bom: int = None,
    seed: int = None,
):
    cid, uid = interaction.channel.id, interaction.user.id
    if gx.minesweeper_active(cid, uid):
        await interaction.response.send_message('⚠️ Ê còn ván Dò Mìn chưa xong ở kênh này kìa, giải quyết nốt đi đã 😤', ephemeral=True)
        return
    can_play, note = gx.can_play_or_reason('minesweeper', uid)
    if not can_play:
        await interaction.response.send_message(note, ephemeral=True)
        return
    gx.minesweeper_start(cid, uid, rows=hang, cols=cot, bombs=bom, seed=seed)
    image = gx.minesweeper_board_image(cid, uid)
    file = discord.File(image, filename='mine.png')
    ve_note = f'\n_(Đã dùng {gx.GAME_VE_COST["minesweeper"]} 🎟️ Vé vì hết lượt free hôm nay)_' if note == 've' else ''
    seed_note = f'\n🌱 Seed: `{seed}`' if seed is not None else ''
    embed = discord.Embed(
        description=(
            '💣 **DÒ MÌN** — bấm 🎮 **Đi nước** rồi gõ lệnh (VN/EN) 🧠:\n'
            '`B3` mở ô · `cờ C4`/`flag c4` cắm cờ · `dò B3`/`chord b3` dò xung quanh\n\n'
            f'_{_mine_status_line(cid, uid)}_{seed_note}{ve_note}'
        ),
        color=8421504,
    )
    embed.set_image(url='attachment://mine.png')
    view = MinesweeperView(cid, uid)
    await interaction.response.send_message(embed=embed, file=file, view=view)


# ============================================================
# 🌍 GUESS-COUNTRY (v2 — đếm ngược 15s/gợi ý, embed đẹp hơn)
# ============================================================
def _country_embed(hints, remaining=None, ve_note='', result_line=None, color=3447003):
    if result_line:
        desc = result_line
    else:
        hint_lines = '\n'.join(f'💡 **Gợi ý {i + 1}:** {h}' for i, h in enumerate(hints))
        bar = _countdown_bar(remaining, gx.COUNTRY_TIME_LIMIT)
        desc = f'{hint_lines}\n\n⏱️ {bar}  `{max(0, remaining)}s` — hết giờ là lộ thêm gợi ý á nha, đừng lù đù!{ve_note}'
    embed = discord.Embed(title='🌍 ĐOÁN QUỐC GIA (đoán lẹ kẻo quê 😎)', description=desc, color=color)
    if not result_line:
        embed.set_footer(text='Bấm ✏️ Đoán quốc gia để trả lời bất cứ lúc nào — hết gợi ý mà vẫn ngu ngơ là thua đó!')
    return embed

class CountryGuessModal(discord.ui.Modal, title='Đoán tên quốc gia'):
    guess_input = discord.ui.TextInput(label='Tên quốc gia', placeholder='VÍ DỤ: Việt Nam', max_length=50)

    def __init__(self, cid, user_id):
        super().__init__()
        self.cid = cid
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        ok, reason, correct, done, won, answer = gx.guess_country_guess(self.cid, self.user_id, self.guess_input.value)
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        if won:
            gx.guess_country_end(self.cid, self.user_id)
            reward, ve = gx.award_win('guess_country', self.user_id)
            new_balance = games.get_deion(self.user_id)
            flag = gx.guess_country_flag(answer)
            result_line = f'🎉 **CHUẨN LUÔN ĐÓ THÁNH!** Đáp án là {flag} **{answer}**! 🔥\n\n{games.DEION_ICON} +{reward} Deion, {gx.VE_ICON} +{ve} Vé (số dư: {new_balance})'
            embed = _country_embed([], result_line=result_line, color=3066993)
            await interaction.response.edit_message(embed=embed, content=None, view=None)
            return
        # Sai -> chỉ báo riêng tư, KHÔNG đụng vào embed chính (đồng hồ đếm ngược vẫn đang chạy nền)
        await interaction.response.send_message(f'❌ **{self.guess_input.value.strip()}** sai bét rồi 🤡, thử lại lẹ đi (đồng hồ vẫn đang chạy ⏱️)', ephemeral=True)

class CountryView(discord.ui.View):
    def __init__(self, cid, user_id):
        super().__init__(timeout=None)
        self.cid = cid
        self.user_id = user_id
        self.message = None

    @discord.ui.button(label='✏️ Đoán quốc gia', style=discord.ButtonStyle.primary)
    async def guess_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Ván này không phải của mày, đừng có chen 🙅'):
            return
        if not gx.guess_country_active(self.cid, self.user_id):
            await interaction.response.send_message('❌ Ván này toang rồi, làm ván khác đi bạn êi.', ephemeral=True)
            return
        await interaction.response.send_modal(CountryGuessModal(self.cid, self.user_id))

    async def _safe_edit(self, embed, disable=False):
        if not self.message:
            return
        try:
            if disable:
                await self.message.edit(embed=embed, content=None, view=None)
            else:
                await self.message.edit(embed=embed, content=None)
        except discord.HTTPException:
            pass

    async def run_countdown(self, ve_note=''):
        cid, uid = self.cid, self.user_id
        max_ticks = 20  # an toàn, phòng lỗi khiến vòng lặp chạy mãi
        ticks = 0
        try:
            while gx.guess_country_active(cid, uid) and ticks < max_ticks:
                for remaining in range(gx.COUNTRY_TIME_LIMIT - 3, -1, -3):
                    await asyncio.sleep(3)
                    if not gx.guess_country_active(cid, uid):
                        return
                    hints = gx.guess_country_current_hints(cid, uid)
                    await self._safe_edit(_country_embed(hints, remaining=remaining, ve_note=ve_note))
                if not gx.guess_country_active(cid, uid):
                    return
                done, revealed_new, answer = gx.guess_country_tick(cid, uid)
                ticks += 1
                if done:
                    flag = gx.guess_country_flag(answer) if answer else '🌍'
                    result_line = f'⏰ **HẾT GIỜ, GÀ QUÁ!** Đáp án đúng là {flag} **{answer}** đó, chịu khó nhớ nha 🤦'
                    await self._safe_edit(_country_embed([], result_line=result_line, color=15158332), disable=True)
                    return
                hints = gx.guess_country_current_hints(cid, uid)
                await self._safe_edit(_country_embed(hints, remaining=gx.COUNTRY_TIME_LIMIT, ve_note=ve_note))
        except Exception as e:
            print(f'[guess_country] Lỗi countdown: {e!r}')

@bot.tree.command(name='guess-country', description=f'🌍 Đoán quốc gia qua gợi ý, mỗi 15s lộ thêm 1 gợi ý ({gx.GAME_VE_COST["guess_country"]} Vé nếu hết lượt free)')
async def guess_country_slash(interaction: discord.Interaction):
    cid, uid = interaction.channel.id, interaction.user.id
    if gx.guess_country_active(cid, uid):
        await interaction.response.send_message('⚠️ Ê còn ván Đoán Quốc Gia chưa xong ở kênh này kìa, giải quyết nốt đi 😤', ephemeral=True)
        return
    can_play, note = gx.can_play_or_reason('guess_country', uid)
    if not can_play:
        await interaction.response.send_message(note, ephemeral=True)
        return
    gx.guess_country_start(cid, uid)
    hints = gx.guess_country_current_hints(cid, uid)
    ve_note = f'\n_(Đã dùng {gx.GAME_VE_COST["guess_country"]} 🎟️ Vé vì hết lượt free hôm nay)_' if note == 've' else ''
    view = CountryView(cid, uid)
    embed = _country_embed(hints, remaining=gx.COUNTRY_TIME_LIMIT, ve_note=ve_note)
    await interaction.response.send_message(embed=embed, view=view)
    view.message = await interaction.original_response()
    asyncio.create_task(view.run_countdown(ve_note=ve_note))


# ============================================================
# 🖼️ GUESS-MEME (v2 — đếm ngược 15s/lần lộ chữ, embed đẹp hơn)
# ============================================================
def _meme_embed(masked, remaining=None, ve_note='', result_line=None, color=3447003, image_url=None):
    if result_line:
        desc = f'Tên: `{masked}`\n\n{result_line}' if masked else result_line
    else:
        bar = _countdown_bar(remaining, gx.MEME_TIME_LIMIT)
        desc = f'Tên: `{masked}`\n\n⏱️ {bar}  `{max(0, remaining)}s` — hết giờ là lộ thêm chữ á, lẹ lẹ lên!{ve_note}'
    embed = discord.Embed(title='🖼️ ĐOÁN MEME (não cá vàng thì thua chắc 🐟)', description=desc, color=color)
    if image_url:
        embed.set_image(url=image_url)
    if not result_line:
        embed.set_footer(text='Bấm ✏️ Đoán tên meme để trả lời bất cứ lúc nào — lộ hết chữ mà còn ngu ngơ là thua!')
    return embed

class MemeGuessModal(discord.ui.Modal, title='Đoán tên meme'):
    guess_input = discord.ui.TextInput(label='Tên meme (tiếng Anh)', placeholder='VÍ DỤ: Distracted Boyfriend', max_length=80)

    def __init__(self, cid, user_id):
        super().__init__()
        self.cid = cid
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        ok, reason, correct, done, won, answer = gx.guess_meme_guess(self.cid, self.user_id, self.guess_input.value)
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        if won:
            url = gx.guess_meme_url(self.cid, self.user_id)
            gx.guess_meme_end(self.cid, self.user_id)
            reward, ve = gx.award_win('guess_meme', self.user_id)
            new_balance = games.get_deion(self.user_id)
            result_line = f'🎉 **XỊN QUÁ TRỜI, ĐÚNG PHÓC!** Đây là meme **{answer}** đó 🔥\n\n{games.DEION_ICON} +{reward} Deion, {gx.VE_ICON} +{ve} Vé (số dư: {new_balance})'
            embed = _meme_embed('', result_line=result_line, color=3066993, image_url=url)
            await interaction.response.edit_message(embed=embed, view=None)
            return
        # Sai -> chỉ báo riêng tư, KHÔNG đụng vào embed chính (đồng hồ đếm ngược vẫn đang chạy nền)
        await interaction.response.send_message(f'❌ **{self.guess_input.value.strip()}** sai bét rồi 🤡, thử lại lẹ đi (đồng hồ vẫn đang chạy ⏱️)', ephemeral=True)

class MemeView(discord.ui.View):
    def __init__(self, cid, user_id):
        super().__init__(timeout=None)
        self.cid = cid
        self.user_id = user_id
        self.message = None

    @discord.ui.button(label='✏️ Đoán tên meme', style=discord.ButtonStyle.primary)
    async def guess_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Ván này không phải của mày, đừng chen 🙅'):
            return
        if not gx.guess_meme_active(self.cid, self.user_id):
            await interaction.response.send_message('❌ Ván này toang rồi, làm ván mới đi bạn êi.', ephemeral=True)
            return
        await interaction.response.send_modal(MemeGuessModal(self.cid, self.user_id))

    async def _safe_edit(self, embed, disable=False):
        if not self.message:
            return
        try:
            if disable:
                await self.message.edit(embed=embed, view=None)
            else:
                await self.message.edit(embed=embed)
        except discord.HTTPException:
            pass

    async def run_countdown(self, ve_note=''):
        cid, uid = self.cid, self.user_id
        max_ticks = 20
        ticks = 0
        try:
            while gx.guess_meme_active(cid, uid) and ticks < max_ticks:
                for remaining in range(gx.MEME_TIME_LIMIT - 3, -1, -3):
                    await asyncio.sleep(3)
                    if not gx.guess_meme_active(cid, uid):
                        return
                    masked = gx.guess_meme_masked(cid, uid)
                    url = gx.guess_meme_url(cid, uid)
                    await self._safe_edit(_meme_embed(masked, remaining=remaining, ve_note=ve_note, image_url=url))
                if not gx.guess_meme_active(cid, uid):
                    return
                done, revealed_new, answer = gx.guess_meme_tick(cid, uid)
                ticks += 1
                if done:
                    url = gx.guess_meme_url(cid, uid)
                    result_line = f'⏰ **HẾT GIỜ, GÀ THẬT SỰ!** Lộ hết chữ luôn mà vẫn không đoán ra 🐔 Đáp án là **{answer}** đó.'
                    await self._safe_edit(_meme_embed('', result_line=result_line, color=15158332, image_url=url), disable=True)
                    return
                masked = gx.guess_meme_masked(cid, uid)
                url = gx.guess_meme_url(cid, uid)
                await self._safe_edit(_meme_embed(masked, remaining=gx.MEME_TIME_LIMIT, ve_note=ve_note, image_url=url))
        except Exception as e:
            print(f'[guess_meme] Lỗi countdown: {e!r}')

@bot.tree.command(name='guess-meme', description=f'🖼️ Đoán tên meme qua hình, mỗi 15s lộ thêm chữ ({gx.GAME_VE_COST["guess_meme"]} Vé nếu hết lượt free)')
async def guess_meme_slash(interaction: discord.Interaction):
    cid, uid = interaction.channel.id, interaction.user.id
    if gx.guess_meme_active(cid, uid):
        await interaction.response.send_message('⚠️ Ê còn ván Đoán Meme chưa xong ở kênh này kìa, xử nốt đi đã 😤', ephemeral=True)
        return
    can_play, note = gx.can_play_or_reason('guess_meme', uid)
    if not can_play:
        await interaction.response.send_message(note, ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    entry = gx.guess_meme_start(cid, uid)
    if entry is None:
        await interaction.followup.send('⚠️ Không lấy được danh sách meme từ imgflip lúc này, thử lại sau nhé.')
        return
    masked = gx.guess_meme_masked(cid, uid)
    ve_note = f'\n_(Đã dùng {gx.GAME_VE_COST["guess_meme"]} 🎟️ Vé vì hết lượt free hôm nay)_' if note == 've' else ''
    embed = _meme_embed(masked, remaining=gx.MEME_TIME_LIMIT, ve_note=ve_note, image_url=entry['url'])
    view = MemeView(cid, uid)
    await interaction.followup.send(embed=embed, view=view)
    view.message = await interaction.original_response()
    asyncio.create_task(view.run_countdown(ve_note=ve_note))


# ============================================================
# 🈴 GUESS-LANGUAGE — đoán loại chữ viết/ngôn ngữ trong 15 giây
# ============================================================
def _lang_embed(cid, uid, remaining, ve_note='', result_line=None, color=3447003, final_sample=None):
    if result_line:
        desc = f'> **{final_sample}**\n\n{result_line}'
    else:
        bar = _countdown_bar(remaining, gx.LANGUAGE_TIME_LIMIT)
        hint_lines = '\n'.join(gx.guess_language_hints(cid, uid))
        desc = (
            f'Quốc gia này nói **ngôn ngữ chính thức** nào?\n\n'
            f'{hint_lines}\n\n'
            f'⏱️ {bar}  `{max(0, remaining)}s`{ve_note}'
        )
    embed = discord.Embed(title='🈴 GUESS-LANGUAGE: NƯỚC NÀY NÓI TIẾNG GÌ? 🌐', description=desc, color=color)
    embed.set_footer(text='Chọn 1 trong 4 đáp án bên dưới trước khi hết giờ, chậm là toang!')
    return embed

class LanguageView(discord.ui.View):
    def __init__(self, cid, user_id, choices):
        super().__init__(timeout=gx.LANGUAGE_TIME_LIMIT)
        self.cid = cid
        self.user_id = user_id
        self.message = None
        self.answered = False
        letters = ['🇦', '🇧', '🇨', '🇩']
        for i, choice in enumerate(choices):
            btn = discord.ui.Button(label=f'{chr(65 + i)}. {choice}', style=discord.ButtonStyle.primary, emoji=letters[i], row=i // 2)
            btn.callback = self._make_callback(i)
            self.add_item(btn)

    def _make_callback(self, index):
        async def callback(interaction: discord.Interaction):
            if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Đây không phải ván của bạn!'):
                return
            if not gx.guess_language_active(self.cid, self.user_id):
                await interaction.response.send_message('❌ Ván này đã kết thúc rồi.', ephemeral=True)
                return
            self.answered = True
            self.stop()
            final_sample = gx.guess_language_final_label(self.cid, self.user_id)
            ok, correct, answer, note = gx.guess_language_answer(self.cid, self.user_id, index)
            gx.guess_language_end(self.cid, self.user_id)
            if correct:
                reward, ve = gx.award_win('guess_language', interaction.user.id)
                new_balance = games.get_deion(interaction.user.id)
                result_line = f'🎉 **BÁ ĐẠO, ĐOÁN ĐÚNG PHÓC!** Đây là **{answer}**! 🧠🔥\n\n{note}\n\n{games.DEION_ICON} +{reward} Deion, {gx.VE_ICON} +{ve} Vé (số dư: {new_balance})'
                embed = _lang_embed(self.cid, self.user_id, 0, result_line=result_line, color=3066993, final_sample=final_sample)
            else:
                result_line = f'❌ **SAI TOÉT RỒI 🤡** Đáp án đúng là **{answer}** đó.\n\n{note}'
                embed = _lang_embed(self.cid, self.user_id, 0, result_line=result_line, color=15158332, final_sample=final_sample)
            await interaction.response.edit_message(embed=embed, view=None)
        return callback

    async def on_timeout(self):
        if self.answered or not gx.guess_language_active(self.cid, self.user_id):
            return
        final_sample = gx.guess_language_final_label(self.cid, self.user_id)
        ok, correct, answer, note = gx.guess_language_answer(self.cid, self.user_id, -1)
        gx.guess_language_end(self.cid, self.user_id)
        if not self.message:
            return
        result_line = f'⏰ **HẾT GIỜ LUÔN RỒI, CHẬM QUÁ TRỜI!** Đáp án đúng là **{answer}**.\n\n{note}'
        embed = _lang_embed(self.cid, self.user_id, 0, result_line=result_line, color=15158332, final_sample=final_sample)
        try:
            await self.message.edit(embed=embed, view=None)
        except discord.HTTPException:
            pass

async def _language_countdown(message, view, cid, uid, ve_note):
    try:
        for remaining in range(gx.LANGUAGE_TIME_LIMIT - 3, -1, -3):
            await asyncio.sleep(3)
            if view.answered or not gx.guess_language_active(cid, uid):
                return
            gx.guess_language_tick(cid, uid)
            embed = _lang_embed(cid, uid, remaining, ve_note=ve_note)
            try:
                await message.edit(embed=embed)
            except discord.HTTPException:
                return
    except Exception as e:
        print(f'[guess_language] Lỗi đếm giờ: {e!r}')

@bot.tree.command(name='doan-ngon-ngu', description=f'🈴 Đoán loại chữ viết/ngôn ngữ trong 15 giây ({gx.GAME_VE_COST["guess_language"]} Vé nếu hết lượt free)')
async def guess_language_slash(interaction: discord.Interaction):
    cid, uid = interaction.channel.id, interaction.user.id
    if gx.guess_language_active(cid, uid):
        await interaction.response.send_message('⚠️ Ê còn ván Đoán Chữ chưa xong ở kênh này kìa, trả lời nốt đi 😤', ephemeral=True)
        return
    can_play, note = gx.can_play_or_reason('guess_language', uid)
    if not can_play:
        await interaction.response.send_message(note, ephemeral=True)
        return
    entry, choices = gx.guess_language_start(cid, uid)
    ve_note = f'\n_(Đã dùng {gx.GAME_VE_COST["guess_language"]} 🎟️ Vé vì hết lượt free hôm nay)_' if note == 've' else ''
    view = LanguageView(cid, uid, choices)
    embed = _lang_embed(cid, uid, gx.LANGUAGE_TIME_LIMIT, ve_note=ve_note)
    await interaction.response.send_message(embed=embed, view=view)
    msg = await interaction.original_response()
    view.message = msg
    asyncio.create_task(_language_countdown(msg, view, cid, uid, ve_note))


# ============================================================
# 🏪 /tạp-hoá — gộp nhapcode + hoadon + shop
# ============================================================
class NhapCodeModal(discord.ui.Modal, title='Nhập Code Nhận Thưởng'):
    code_input = discord.ui.TextInput(label='Mã code (phân biệt hoa thường)', placeholder='VÍ DỤ: ChaoNgayMoiVuiVe')

    async def on_submit(self, interaction: discord.Interaction):
        code = self.code_input.value
        found, ok, reason, amount = gx.redeem_custom_code(interaction.user.id, code)
        if found:
            if not ok:
                await interaction.response.send_message(reason, ephemeral=True)
                return
            await interaction.response.send_message(f'🎁 Nhập code thành công! Nhận được: {games.DEION_ICON} +{amount} Deion (quà từ 1 người dùng khác tạo đó nha) 🎉', ephemeral=True)
            return
        # không phải custom code -> thử code hệ thống (REDEEM_CODES admin tạo)
        result = games.redeem_code(interaction.user.id, code)
        if not result['ok']:
            await interaction.response.send_message(result['reason'], ephemeral=True)
            return
        await interaction.response.send_message(f"🎁 Nhập code thành công! Nhận được: {' , '.join(result['reward_lines'])}", ephemeral=True)

class CreateCodeModal(discord.ui.Modal, title='Tạo Code Tặng Deion'):
    ten_input = discord.ui.TextInput(label='Tên code', placeholder='VÍ DỤ: ChuaHoiThamGiDo', max_length=32)
    deion_input = discord.ui.TextInput(label='Deion tặng mỗi lượt nhập', placeholder='VÍ DỤ: 1', max_length=10)
    thoihan_input = discord.ui.TextInput(label='Thời hạn (giờ)', placeholder='VÍ DỤ: 24 (= 1 ngày)', max_length=6)
    luot_input = discord.ui.TextInput(label='Số lượt nhập tối đa (bỏ trống = vô hạn)', placeholder='VÍ DỤ: 10 (không bắt buộc)', required=False, max_length=6)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            deion_amount = float(self.deion_input.value.strip().replace(',', '.'))
        except ValueError:
            await interaction.response.send_message('❌ Số Deion nhập sai định dạng rồi, ghi số thôi (VD: 1 hoặc 0.5).', ephemeral=True)
            return
        try:
            hours = float(self.thoihan_input.value.strip().replace(',', '.'))
        except ValueError:
            await interaction.response.send_message('❌ Thời hạn nhập sai định dạng, ghi số giờ thôi (VD: 24).', ephemeral=True)
            return
        max_uses = None
        raw_luot = self.luot_input.value.strip()
        if raw_luot:
            try:
                max_uses = int(raw_luot)
            except ValueError:
                await interaction.response.send_message('❌ Số lượt nhập sai định dạng, ghi số nguyên thôi (VD: 10).', ephemeral=True)
                return
        ok, reason = gx.create_custom_code(interaction.user.id, self.ten_input.value, deion_amount, hours, max_uses)
        if not ok:
            await interaction.response.send_message(reason, ephemeral=True)
            return
        luot_text = f'{max_uses} lượt' if max_uses else 'không giới hạn lượt'
        await interaction.response.send_message(
            f'🎫 Tạo code **{self.ten_input.value.strip()}** thành công!\n'
            f'{games.DEION_ICON} Mỗi lượt nhập: **{deion_amount} Deion** (trừ thẳng từ ví của mày mỗi khi có người nhập)\n'
            f'⏳ Hạn dùng: **{int(hours)} giờ** · 🔁 {luot_text}\n\n'
            f'📢 Đi rải code này cho thiên hạ nhập ở nút 🎁 Nhập Code trong `/tạp-hoá` nha, ví cạn thì code tự bay màu luôn đó 😤',
            ephemeral=True,
        )

class TapHoaView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id

    @discord.ui.button(label='🎁 Nhập Code', style=discord.ButtonStyle.success)
    async def nhapcode_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Tạp hoá của người ta, bén mảng vào làm gì 🙅 tự `/tạp-hoá` cái riêng đi!'):
            return
        await interaction.response.send_modal(NhapCodeModal())

    @discord.ui.button(label='🎫 Tạo Code', style=discord.ButtonStyle.success)
    async def taocode_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Tạp hoá của người ta, bén mảng vào làm gì 🙅 tự `/tạp-hoá` cái riêng đi!'):
            return
        await interaction.response.send_modal(CreateCodeModal())

    @discord.ui.button(label='🧾 Hóa Đơn', style=discord.ButtonStyle.secondary)
    async def hoadon_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Tạp hoá của người ta, bén mảng vào làm gì 🙅 tự `/tạp-hoá` cái riêng đi!'):
            return
        receipts = games.get_receipts(interaction.user.id)
        if not receipts:
            await interaction.response.send_message('🧾 Chưa mua gì ở Delta Shop cả, nghèo mà trong sạch 😇', ephemeral=True)
            return
        lines = ['```', '===== LỊCH SỬ MUA HÀNG DELTA SHOP =====', f'Khách hàng: {interaction.user.display_name}', '-----------------------------------------']
        for i, r in enumerate(receipts[:15], start=1):
            ts = time.strftime('%d/%m/%Y %H:%M', time.localtime(r['time']))
            currency_label = 'Deion' if r['currency'] == 'deion' else 'Elo'
            lines.append(f"#{i:02d} [{ts}] {r['emoji']} {r['item_name']}  -{r['cost']} {currency_label}")
        lines.append('-----------------------------------------')
        if len(receipts) > 15:
            lines.append(f'(...còn {len(receipts) - 15} hóa đơn cũ hơn không hiện)')
        lines.append('=========================================')
        lines.append('```')
        await interaction.response.send_message('🧾 Hóa đơn tiêu xài của bạn nè, coi có xót ví không:\n' + '\n'.join(lines), ephemeral=True)

    @discord.ui.button(label='🛒 Shop', style=discord.ButtonStyle.primary)
    async def shop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Tạp hoá của người ta, bén mảng vào làm gì 🙅 tự `/tạp-hoá` cái riêng đi!'):
            return
        embed = _shop_embed(0)
        view = ShopView(interaction.user.id, 0)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @discord.ui.button(label='🎒 Kho', style=discord.ButtonStyle.secondary)
    async def kho_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Tạp hoá của người ta, bén mảng vào làm gì 🙅 tự `/tạp-hoá` cái riêng đi!'):
            return
        text = games.shop_inventory_text(interaction.user.id)
        await interaction.response.send_message(f'🎒 Kho đồ của bạn nè, xem có gì hay ho không:\n{text}', ephemeral=True)

    @discord.ui.button(label='🎟️ Vé', style=discord.ButtonStyle.secondary)
    async def ve_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if await _deny_unless(interaction, interaction.user.id == self.user_id, '❌ Tạp hoá của người ta, bén mảng vào làm gì 🙅 tự `/tạp-hoá` cái riêng đi!'):
            return
        count = gx.get_ve(interaction.user.id)
        await interaction.response.send_message(f'🎟️ Đang có **{count} Vé** trong túi.\nHết vé thì qua 🛒 Shop múc thêm nha, đừng có than nghèo!', ephemeral=True)

@bot.tree.command(name='tạp-hoá', description='🏪 Nhập code / Hóa đơn / Kho / Vé / Shop — tất cả trong 1 lệnh')
async def taphoa_slash(interaction: discord.Interaction):
    embed = discord.Embed(
        title='🏪 Tạp Hoá Delta — ghé qua lụm đồ nè 🛍️',
        description=(
            'Chọn 1 trong các chức năng bên dưới, đừng đứng đó lù đù:\n\n'
            '🎁 **Nhập Code** — có mã thì đổi Deion lẹ đi\n'
            '🎫 **Tạo Code** — tự chế code tặng Deion cho người khác\n'
            '🧾 **Hóa Đơn** — coi lại đã nướng bao nhiêu tiền\n'
            '🛒 **Shop** — vô đây mà quẹt thẻ (à nhầm, quẹt Deion)\n'
            '🎒 **Kho** — đồ/buff đang giữ trong người\n'
            '🎟️ **Vé** — còn bao nhiêu vé để cày minigame'
        ),
        color=3447003,
    )
    view = TapHoaView(interaction.user.id)
    await interaction.response.send_message(embed=embed, view=view)

web_server.keep_alive()
bot.run(os.environ['DISCORD_KEY'])