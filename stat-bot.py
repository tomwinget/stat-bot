import os
import random
import discord
import redis
from time import localtime, strftime
from enum import Enum
from discord import VoiceChannel
from discord import CategoryChannel
from discord import DMChannel
from discord.ext import commands
from discord.ext.commands import has_role
from operator import itemgetter

token = os.getenv('statToken')

bot = commands.Bot(command_prefix='~')

r_local = redis.StrictRedis(decode_responses=True)
r_local.set("startup", strftime("%a, %d %b %Y %H:%M:%S", localtime()))

list_msg_format = "* %s: %d\n"

class StatType(Enum):
    EMOTE = 'emotes'
    MESSAGE = 'messages'

def get_stat(arg):
    if arg in ('msg', 'message', 'msgs', 'messages', 'm'):
        return StatType.MESSAGE
    return StatType.EMOTE

@bot.event
async def on_ready():
    print("Stat-bot ready!")
    print("Script started: %s" % r_local.get("startup"))


@bot.command(name='random-user')
async def random_user(ctx):
    async with ctx.message.channel.typing():
        print("Picking random user from channel: %s" % ctx.message.channel)
        await ctx.send(random.choice(ctx.message.channel.members))

@bot.command(name='random-emote')
async def random_emote(ctx):
    async with ctx.message.channel.typing():
        print("Picking random emote!")
        await ctx.send(random.choice(ctx.guild.emojis))

async def send_emote_usage(emotes, ctx):
    emotes = dict([key, int(val)] for key, val in emotes.items())
    msg = "```"
    for emote, count in sorted(emotes.items(), key=itemgetter(1), reverse=True):
        msg += list_msg_format % (emote, int(count))
    msg += "```"
    print("Result msg: ", msg)
    await ctx.send(msg)

@bot.command(name='get-stats')
async def get_stats(ctx, stat: get_stat=StatType.EMOTE, user=None):
    async with ctx.message.channel.typing():
        if len(ctx.message.mentions) == 0:
            print("Getting global stats")
            result = r_local.hgetall(stat.value)
            await send_emote_usage(result, ctx)
        else:
            for member in ctx.message.mentions:
                print("Getting member stats for: ", member.id)
                result = r_local.hgetall(str(member.id)+":"+stat.value)
                await send_emote_usage(result, ctx)

async def process_message_reactions(message):
    r_local.hincrby(str(message.author.id)+":"+StatType.MESSAGE.value, message.channel.name)
    r_local.hincrby(StatType.MESSAGE.value, message.channel.name)
    for reaction in message.reactions:
        if reaction.custom_emoji:
            users = await reaction.users().flatten()
            count = 0
            for user in users:
                if not user.bot:
                    count += 1
                    r_local.hincrby(str(user.id)+":"+StatType.EMOTE.value, reaction.emoji.name)
            if count != 0:
                r_local.hincrby(StatType.EMOTE.value, reaction.emoji.name, count)

async def process_channel(channel, limit=None):
    most_recent_message = None
    async for message in channel.history(limit=limit):
        if not most_recent_message:
            most_recent_message = message
        elif message.created_at > most_recent_message.created_at:
            most_recent_message = message
        await process_message_reactions(message)
    if most_recent_message:
        print("Most recent message id: %d" % most_recent_message.id)
        r_local.hset("most_recent", channel.id, most_recent_message.id)

@bot.command(name='store-stats')
@has_role("Bot Admin")
async def store_stats(ctx):
    async with ctx.message.channel.typing():
        print("Save db to disk")
        await ctx.send("Saving current db image to disk")
        r_local.save()
        print("Flushing db")
        await ctx.send("Flushing db")
        r_local.flushall()
        for channel in ctx.guild.channels:
            if hasattr(channel, 'history'):
                print("Processing messages in channel: %s" % channel)
                await ctx.send("Processing messages in channel: %s" % channel)
                await process_channel(channel)
    await ctx.send("Processed all messages!")

@bot.command(name='add-stats')
async def add_stats(ctx):
    async with ctx.message.channel.typing():
        for channel in ctx.guild.channels:
            if hasattr(channel, 'history'):
                last_update_id = r_local.hget("most_recent",channel.id)
                print("Got ID: %s"%last_update_id)
                last_message = None
                if last_update_id:
                    last_message = await channel.fetch_message(int(last_update_id))
                await ctx.send("Processing messages in channel: %s for message: %s" % (channel, last_message.id))
                if last_message:
                    most_recent_message = None
                    async for message in channel.history(limit=None,after=last_message):
                        if not most_recent_message:
                            most_recent_message = message
                        elif message.created_at > most_recent_message.created_at:
                            most_recent_message = message
                        await process_message_reactions(message)
                    if most_recent_message:
                        print("Most recent message id: %d" % most_recent_message.id)
                        r_local.hset("most_recent", channel.id, most_recent_message.id)
                else:
                    await process_channel(channel)
    await ctx.send("Processed all messages!")

@bot.command(name='calc-stats')
async def calc_stats(ctx, msg_limit=1000, response_size=50):
    async with ctx.message.channel.typing():
        print("Starting reaction calculation")
        dict_of_reacts = {}
        for channel in ctx.guild.channels:
            if hasattr(channel, 'history'):
                print("Processing messages for channel: %s" % channel)
                async for message in channel.history(limit=msg_limit):
                    for reaction in message.reactions:
                        if reaction.custom_emoji:
                            users = await reaction.users().flatten()
                            count = 0
                            for user in users:
                                if not user.bot:
                                    count += 1
                            if count != 0:
                                dict_of_reacts[reaction.emoji.name] = dict_of_reacts.get(reaction.emoji.name, 0) + count

        list_size = 0
        mssage = "```"
        for emote, count in sorted(dict_of_reacts.items(), key=itemgetter(1), reverse=True):
            mssage += list_msg_format % (emote, count)
            list_size += 1
            if list_size > response_size:
                mssage += "```"
                await ctx.send(mssage)
                list_size = 0
                mssage = "```"

        await ctx.send(mssage+"```")
    print("Completed stats calculation!")
            
@random_user.error
@random_emote.error
@get_stats.error
@add_stats.error
@store_stats.error
@calc_stats.error
async def store_stats_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission for this command!")
    elif isinstance(error, commands.MissingRole):
        await ctx.send("You aren't the proper role for this command!")
    else:
        await ctx.send("Error occurred processing your request : %s"%str(error))

bot.run(token)
