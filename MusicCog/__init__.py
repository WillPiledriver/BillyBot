from discord.ext import commands
import discord

class MusicBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        print("Cog Loaded")


    @commands.command()
    async def test(self, ctx):
        await ctx.send("Test worked.")