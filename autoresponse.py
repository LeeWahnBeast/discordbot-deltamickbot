import discord
import re
import unicodedata
from unidecode import unidecode
from responses import responses


def normalize(text):
    text = unicodedata.normalize("NFKC", text)
    text = unidecode(text).lower()
    text = re.sub(r"[^a-z0-9]", "", text)
    return text


async def check(message):
    if message.author.bot:
        return

    msg = normalize(message.content)

    for trigger, data in responses.items():
        if normalize(trigger) in msg:

            # Có ảnh
            if data["image"]:
                file = discord.File(data["image"])

                # Có cả text và ảnh
                if data["text"]:
                    await message.channel.send(
                        content=data["text"],
                        file=file
                    )

                # Chỉ có ảnh
                else:
                    await message.channel.send(
                        file=file
                    )

            # Chỉ có text
            elif data["text"]:
                await message.channel.send(data["text"])

            break