"""
ai.py — AI chat tự động cho bot Discord.

Dùng CHUỖI FALLBACK nhiều provider: mặc định thử Gemini trước (nhiều model),
nếu tất cả model Gemini đều lỗi/hết quota thì tự động rớt qua Groq (nhiều model),
tất cả trong CÙNG một lượt gọi — người dùng không nhận ra có chuyển đổi.

Tính năng:
  1. Tại (các) kênh được chỉ định (AI_CHANNEL_IDS), bot sẽ tự động buôn chuyện
     mỗi ~15 phút — dựa vào lịch sử đoạn chat gần đây để bắt chuyện/bình luận.
  2. Nếu có ai đó REPLY vào một tin nhắn của chính bot trong kênh đó, bot sẽ đọc
     lịch sử đoạn chat + câu reply đó rồi trả lời lại ngay.

Cấu hình qua biến môi trường:
  AI_PROVIDER_ORDER      -> thứ tự thử provider, phân tách bằng dấu phẩy.
                            Mặc định "gemini,groq" (Gemini trước, hết thì qua Groq).
                            Có thể đổi thành "groq,gemini" hoặc chỉ "groq" / "gemini".

  GEMINI_API_KEY         -> API key Gemini (https://aistudio.google.com/apikey)
  GEMINI_MODEL           -> model Gemini chính, mặc định "gemini-2.5-flash"
  GEMINI_MODEL_FALLBACKS -> model Gemini dự phòng, phân tách bằng dấu phẩy

  GROQ_API_KEY           -> API key Groq (https://console.groq.com/keys)
  GROQ_MODEL             -> model Groq chính, mặc định "llama-3.3-70b-versatile"
  GROQ_MODEL_FALLBACKS   -> model Groq dự phòng, phân tách bằng dấu phẩy

  AI_CHANNEL_IDS         -> danh sách channel ID, phân tách bằng dấu phẩy
                            (có thể dùng AI_CHANNEL_ID nếu chỉ 1 kênh)
  AI_CHAT_INTERVAL_MINUTES  -> số phút giữa mỗi lần tự nhắn, mặc định 15
  AI_REPLY_COOLDOWN_SECONDS -> giây cooldown/người khi trigger bằng reply, mặc định 20

Cần cài thêm package:
  pip install google-generativeai requests
"""
import os
import time
import asyncio
import discord
import requests

try:
    import google.generativeai as genai
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    _GENAI_AVAILABLE = False

# ---------------------------------------------------------------------------
# Cấu hình Gemini
# ---------------------------------------------------------------------------
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
GEMINI_MODEL = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash').strip()
_GEMINI_DEFAULT_FALLBACKS = ['gemini-2.5-flash', 'gemini-2.0-flash-lite', 'gemini-2.0-flash', 'gemini-1.5-flash']

if _GENAI_AVAILABLE and GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)


def _parse_fallback_chain(primary, env_var, defaults):
    raw = os.environ.get(env_var, '').strip()
    chain = [primary] if primary else []
    candidates = [p.strip() for p in raw.split(',') if p.strip()] if raw else defaults
    for m in candidates:
        if m and m not in chain:
            chain.append(m)
    return chain


GEMINI_MODEL_CHAIN = _parse_fallback_chain(GEMINI_MODEL, 'GEMINI_MODEL_FALLBACKS', _GEMINI_DEFAULT_FALLBACKS)

# ---------------------------------------------------------------------------
# Cấu hình Groq
# ---------------------------------------------------------------------------
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '').strip()
GROQ_MODEL = os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile').strip()
GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
_GROQ_DEFAULT_FALLBACKS = ['llama-3.3-70b-versatile', 'llama-3.1-8b-instant', 'gemma2-9b-it']

GROQ_MODEL_CHAIN = _parse_fallback_chain(GROQ_MODEL, 'GROQ_MODEL_FALLBACKS', _GROQ_DEFAULT_FALLBACKS)

# ---------------------------------------------------------------------------
# Thứ tự provider (mặc định: Gemini trước, hết thì qua Groq)
# ---------------------------------------------------------------------------
_PROVIDER_ORDER_RAW = os.environ.get('AI_PROVIDER_ORDER', 'gemini,groq').strip()
PROVIDER_ORDER = [p.strip().lower() for p in _PROVIDER_ORDER_RAW.split(',') if p.strip()]


def _build_call_chain():
    """Trả về danh sách (provider, model_name) theo đúng thứ tự cần thử."""
    chain = []
    for provider in PROVIDER_ORDER:
        if provider == 'gemini' and _GENAI_AVAILABLE and GEMINI_API_KEY:
            chain.extend(('gemini', m) for m in GEMINI_MODEL_CHAIN)
        elif provider == 'groq' and GROQ_API_KEY:
            chain.extend(('groq', m) for m in GROQ_MODEL_CHAIN)
    return chain


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

# Cooldown chống 1 người spam reply liên tục làm tốn quota
REPLY_COOLDOWN_SECONDS = int(os.environ.get('AI_REPLY_COOLDOWN_SECONDS', '20'))
_user_last_reply_time = {}

FALLBACK_ERROR_MSG = '🤖 Mình đang gặp chút trục trặc khi trả lời (có thể do rate limit), chờ xíu rồi hỏi lại nha!'


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


# ---------------------------------------------------------------------------
# Gọi từng provider (đều chạy sync trong thread riêng, trả về (text, error_msg))
# ---------------------------------------------------------------------------
def _call_gemini_sync(model_name, prompt):
    try:
        model = genai.GenerativeModel(model_name, system_instruction=SYSTEM_PROMPT)
        response = model.generate_content(prompt)
        text = (getattr(response, 'text', '') or '').strip()
        if not text:
            return None, 'Response rỗng'
        return text, None
    except Exception as e:
        return None, repr(e)


def _call_groq_sync(model_name, prompt):
    headers = {
        'Authorization': f'Bearer {GROQ_API_KEY}',
        'Content-Type': 'application/json',
    }
    payload = {
        'model': model_name,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.8,
        'max_tokens': 300,
    }
    try:
        resp = requests.post(GROQ_API_URL, headers=headers, json=payload, timeout=30)
    except requests.RequestException as e:
        return None, repr(e)
    if resp.status_code != 200:
        return None, f'HTTP {resp.status_code}: {resp.text[:300]}'
    try:
        text = resp.json()['choices'][0]['message']['content'].strip()
    except (KeyError, IndexError, TypeError, ValueError):
        return None, 'Không parse được response'
    if not text:
        return None, 'Response rỗng'
    return text, None


async def generate_reply(channel, trigger_message=None):
    """
    Tạo câu trả lời, dựa trên lịch sử đoạn chat của channel.
    Thử lần lượt từng (provider, model) trong _build_call_chain() theo đúng thứ tự
    AI_PROVIDER_ORDER — hết Gemini thì tự rớt qua Groq (hoặc ngược lại), tới khi
    có 1 câu trả lời thành công hoặc hết sạch lựa chọn.
    """
    call_chain = _build_call_chain()
    if not call_chain:
        print('⚠️ Không có provider AI nào được cấu hình đủ (thiếu API key?), bỏ qua AI chat.', flush=True)
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

    for provider, model_name in call_chain:
        if provider == 'gemini':
            text, error = await asyncio.to_thread(_call_gemini_sync, model_name, prompt)
        else:
            text, error = await asyncio.to_thread(_call_groq_sync, model_name, prompt)

        if error is None and text:
            return text

        print(f'⚠️ [{provider}:{model_name}] thất bại ({error}), thử tiếp trong chuỗi fallback...', flush=True)

    print('⚠️ Đã thử hết toàn bộ chuỗi provider/model, không có câu trả lời.', flush=True)
    return None


async def handle_reply_to_bot(bot, message) -> bool:
    """
    Nếu `message` là reply vào một tin nhắn của bot, tạo câu trả lời và gửi lại ngay.
    Trả về True nếu đã xử lý (đã trả lời hoặc thử trả lời).
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

    now = time.time()
    async with _lock:
        last_time = _user_last_reply_time.get(message.author.id, 0)
        if now - last_time < REPLY_COOLDOWN_SECONDS:
            wait_left = int(REPLY_COOLDOWN_SECONDS - (now - last_time))
            try:
                await message.reply(f'⏳ Chờ khoảng {wait_left}s nữa rồi hỏi tiếp nha, đỡ tốn quota!', mention_author=False)
            except discord.HTTPException:
                pass
            return True
        _user_last_reply_time[message.author.id] = now

    try:
        async with message.channel.typing():
            text = await generate_reply(message.channel, trigger_message=message)
    except discord.HTTPException:
        text = await generate_reply(message.channel, trigger_message=message)

    if text is None:
        text = FALLBACK_ERROR_MSG

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

    call_chain = _build_call_chain()
    if not AI_CHANNEL_IDS:
        print('ℹ️ AI_CHANNEL_IDS/AI_CHANNEL_ID chưa được cấu hình, tính năng AI chat tự động sẽ không chạy.', flush=True)
    elif not call_chain:
        print('ℹ️ Chưa có provider AI nào đủ điều kiện (thiếu GEMINI_API_KEY/GROQ_API_KEY), AI chat sẽ không hoạt động.', flush=True)
    else:
        provider_names = ' -> '.join(dict.fromkeys(p for p, _ in call_chain))
        print(f'✅ AI chat sẵn sàng, thứ tự fallback: {provider_names}', flush=True)
        _auto_chat_task.start()
    return _auto_chat_task
