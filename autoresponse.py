import discord
from responses import responses

async def check(message):
    if message.author.bot:
        return

    msg = message.content.lower()

    for trigger, data in responses.items():
        if trigger in msg:
            if data["image"]:
                await message.channel.send(
                    data["text"],
                    file=discord.File(data["image"])
                )
            else:
                await message.channel.send(data["text"])
            break