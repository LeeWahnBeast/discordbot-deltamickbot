"""
ai.py — AI chat tự động cho bot Discord, dùng Gemini.

Tính năng:
  1. Tại (các) kênh được chỉ định (AI_CHANNEL_IDS), bot sẽ tự động buôn chuyện
     mỗi ~15 phút (không cần slash command, không cần ai gọi) — dựa vào lịch sử
     đoạn chat gần đây để bắt chuyện/bình luận cho tự nhiên.
  2. Nếu có ai đó REPLY (trả lời) vào một tin nhắn của chính bot trong kênh đó,
     bot sẽ đọc lịch sử đoạn chat + câu reply đó rồi trả lời lại ngay bằng Gemini.

Cấu hình qua biến môi trường:
  GEMINI_API_KEY   -> API key của Google Gemini (bắt buộc để tính năng hoạt động)
  GEMINI_MODEL     -> tên model, mặc định "gemini-2.0-flash"
  AI_CHANNEL_IDS   -> danh sách channel ID, phân tách bằng dấu phẩy
                      (ví dụ: "123456789012345678,987654321098765432")
                      Có thể dùng AI_CHANNEL_ID (số ít) nếu chỉ có 1 kênh.
  AI_CHAT_INTERVAL_MINUTES -> số phút giữa mỗi lần tự nhắn, mặc định 15

Cần cài thêm package:
  pip install google-generativeai
"""
import os
import time
import asyncio
import discord

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    _GENAI_AVAILABLE = False

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
MODEL_NAME = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash').strip()

if _GENAI_AVAILABLE and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def _parse_channel_ids():
    raw = os.environ.get('AI_CHANNEL_IDS', '') or os.environ.get('AI_CHANNEL_ID', '')
    ids = set()
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids


AI_CHANNEL_IDS = _parse_channel_ids()
AUTO_CHAT_INTERVAL_SECONDS = int(os.environ.get('AI_CHAT_INTERVAL_MINUTES', '15')) * 60
HISTORY_LIMIT = 30

SYSTEM_PROMPT = (
    "Bạn là một thành viên AI thân thiện, hài hước, đang trò chuyện tự nhiên bằng tiếng Việt "
    "trong một kênh Discord của server game/giải trí. Quy tắc:\n"
    "- Trả lời NGẮN GỌN (1-3 câu), giọng văn gần gũi, đời thường, như một người bạn trong nhóm chat.\n"
    "- KHÔNG đóng vai trợ lý trang trọng, không giới thiệu bản thân, không nói 'tôi là AI' trừ khi bị hỏi.\n"
    "- KHÔNG dùng slash command hay hướng dẫn kỹ thuật trừ khi được hỏi trực tiếp.\n"
    "- Dựa vào lịch sử đoạn chat được cung cấp để hiểu ngữ cảnh, tên người đang nói, chủ đề đang bàn, "
    "và trả lời/bắt chuyện sao cho hợp lý, tự nhiên, không lạc đề."
)

# Lưu thời điểm gửi tin nhắn tự động gần nhất theo từng channel_id
_last_auto_message_time = {}
_lock = asyncio.Lock()


def is_ai_channel(channel_id: int) -> bool:
    return channel_id in AI_CHANNEL_IDS


def _format_history(messages):
    lines = []
    for m in messages:
        content = (m.content or '').strip()
        if not content:
            continue
        name = m.author.display_name
        lines.append(f'{name}: {content}')
    return '\n'.join(lines)


async def fetch_recent_history(channel, limit=HISTORY_LIMIT):
    msgs = []
    async for m in channel.history(limit=limit):
        msgs.append(m)
    msgs.reverse()
    return msgs


def _build_model():
    return genai.GenerativeModel(MODEL_NAME, system_instruction=SYSTEM_PROMPT)


async def generate_reply(channel, trigger_message=None):
    """Gọi Gemini để tạo câu trả lời, dựa trên lịch sử đoạn chat của channel."""
    if not _GENAI_AVAILABLE:
        print('⚠️ Chưa cài package google-generativeai, bỏ qua AI chat.', flush=True)
        return None
    if not GEMINI_API_KEY:
        print('⚠️ Thiếu GEMINI_API_KEY, bỏ qua AI chat.', flush=True)
        return None

    history_msgs = await fetch_recent_history(channel, limit=HISTORY_LIMIT)
    history_text = _format_history(history_msgs) or '(chưa có gì đáng chú ý)'

    prompt_parts = [f'Lịch sử đoạn chat gần đây trong kênh:\n{history_text}']
    if trigger_message is not None:
        author_name = trigger_message.author.display_name
        prompt_parts.append(
            f"\n{author_name} vừa reply trực tiếp vào tin nhắn của bạn với nội dung: "
            f"\"{trigger_message.content.strip()}\"\n"
            "Hãy trả lời trực tiếp câu đó, dựa trên ngữ cảnh lịch sử chat ở trên."
        )
    else:
        prompt_parts.append(
            "\nHãy chủ động bắt chuyện hoặc bình luận vui, ngắn gọn về những gì đang diễn ra "
            "trong đoạn chat trên, như một thành viên bình thường trong nhóm. "
            "Nếu đoạn chat không có gì để bình luận, chỉ cần bắt chuyện nhẹ nhàng."
        )
    prompt = '\n'.join(prompt_parts)

    try:
        model = _build_model()
        response = await asyncio.to_thread(model.generate_content, prompt)
        text = (getattr(response, 'text', '') or '').strip()
        return text or None
    except Exception as e:
        print(f'⚠️ Lỗi gọi Gemini API: {e!r}', flush=True)
        return None


async def handle_reply_to_bot(bot, message) -> bool:
    """
    Nếu `message` là reply vào một tin nhắn của bot, tạo câu trả lời bằng Gemini
    và gửi lại ngay. Trả về True nếu đã xử lý (đã trả lời hoặc thử trả lời).
    """
    if message.reference is None:
        return False

    replied = message.reference.resolved
    if replied is None or isinstance(replied, discord.DeletedReferencedMessage):
        try:
            replied = await message.channel.fetch_message(message.reference.message_id)
        except (discord.HTTPException, discord.NotFound):
            return False

    if replied is None or replied.author.id != bot.user.id:
        return False

    try:
        async with message.channel.typing():
            text = await generate_reply(message.channel, trigger_message=message)
    except discord.HTTPException:
        text = await generate_reply(message.channel, trigger_message=message)

    if text:
        try:
            await message.reply(text, mention_author=False)
        except discord.HTTPException as e:
            print(f'⚠️ Lỗi gửi reply AI chat: {e!r}', flush=True)

    async with _lock:
        _last_auto_message_time[message.channel.id] = time.time()
    return True


async def maybe_send_auto_message(channel):
    """Gửi 1 tin nhắn tự động (nếu đã đủ ~15 phút và có hoạt động của người dùng)."""
    now = time.time()
    async with _lock:
        last = _last_auto_message_time.get(channel.id, 0)
        if now - last < AUTO_CHAT_INTERVAL_SECONDS:
            return

    history_msgs = await fetch_recent_history(channel, limit=HISTORY_LIMIT)
    if not history_msgs:
        return
    # Chỉ chủ động nhắn nếu gần đây có người (không phải bot) đã nói chuyện
    if not any(not m.author.bot for m in history_msgs):
        return

    text = await generate_reply(channel)
    if not text:
        return

    async with _lock:
        _last_auto_message_time[channel.id] = time.time()
    try:
        await channel.send(text)
    except discord.HTTPException as e:
        print(f'⚠️ Lỗi gửi tin nhắn tự động AI chat: {e!r}', flush=True)


def start_auto_chat_loop(bot):
    """Khởi động vòng lặp tự động nhắn mỗi AI_CHAT_INTERVAL_MINUTES phút."""
    from discord.ext import tasks

    interval_minutes = max(1, AUTO_CHAT_INTERVAL_SECONDS // 60)

    @tasks.loop(minutes=interval_minutes)
    async def _auto_chat_task():
        if not AI_CHANNEL_IDS:
            return
        for cid in AI_CHANNEL_IDS:
            channel = bot.get_channel(cid)
            if channel is None:
                continue
            try:
                await maybe_send_auto_message(channel)
            except Exception as e:
                print(f'⚠️ Lỗi auto chat AI (channel {cid}): {e!r}', flush=True)

    if not AI_CHANNEL_IDS:
        print('ℹ️ AI_CHANNEL_IDS/AI_CHANNEL_ID chưa được cấu hình, tính năng AI chat tự động sẽ không chạy.', flush=True)
    elif not GEMINI_API_KEY:
        print('ℹ️ GEMINI_API_KEY chưa được cấu hình, tính năng AI chat sẽ không hoạt động.', flush=True)
    else:
        _auto_chat_task.start()
    return _auto_chat_task
