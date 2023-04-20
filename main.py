import os
import discord
import tools
import re
import json
from datetime import timedelta
from dotenv import load_dotenv
from discord import app_commands
from urllib.parse import quote_plus
import aiohttp
import openai
import asyncio
from Bard import Chatbot


class Bot(discord.Client):
    def __init__(self, *, guild, intents: discord.Intents):
        super().__init__(intents=intents)
        self.MY_GUILD = guild
        self.tree = app_commands.CommandTree(self)
        self.funny_words = {
            "cum": "(cum)",
            "bruh": "(bruh)",
            "yo": "(yo)"
        }

    async def setup_hook(self):
        self.tree.copy_global_to(guild=self.MY_GUILD)
        await self.tree.sync(guild=self.MY_GUILD)

    async def on_ready(self):
        print(f"Logged in as {self.user} (ID: {self.user.id})")

    async def on_message(self, msg):
        if msg.author.id == self.user.id:
            return

        for k, d in self.funny_words.items():
            if msg.content.lower().startswith(k):
                await msg.channel.send(d)
                return


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
GUILD_ID = os.getenv("DISCORD_GUILD")
GUILD = discord.Object(id=GUILD_ID)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
client = Bot(guild=GUILD, intents=intents)
bard_chatbot = Chatbot(os.getenv("BARD_KEY"))


def roll_hack(dice, org):
    dice_set = dice.split(";")
    output = "```"
    try:
        for d in range(len(dice_set)):
            dice = dice_set[d]
            output += "\n[{}]:\n".format(dice)
            dice_mult = dice.split("*")
            multi = 1
            if len(dice_mult) > 1:
                multi = int(dice_mult[1])
            dice = dice_mult[0]
            dice_split = dice.split("+")
            for i in range(multi):
                if len(dice_split) > 1:
                    if re.match(re.compile("^[0-9]+d[0-9]+$"), dice_split[1].lower()):
                        if not org:
                            mod = tools.roll(dice_split[1])[1]
                        else:
                            mod = tools.randomorg_roll(dice_split[1])[1]
                        output += f"BONUS DIE: {mod}\n"
                    else:
                        mod = int(dice_split[1])
                    if not org:
                        result = tools.roll(dice_split[0], mod)
                    else:
                        result = tools.randomorg_roll(dice_split[0], mod)
                else:
                    if not org:
                        result = tools.roll(dice)
                    else:
                        result = tools.randomorg_roll(dice)
                output += "\tRoll {}: {}\n".format(i+1, result)
        return output + "```"
    except Exception as e:
        print("Something went terribly wrong.")
        print(e)


@client.tree.command(name="roll")
@app_commands.describe(
    dice="What to roll."
)
async def roll(interaction: discord.Interaction, dice: str):
    """Rolls dice."""
    await interaction.response.send_message(roll_hack(dice, org=False))


@client.tree.command()
async def hello(interaction: discord.Interaction):
    await interaction.response.send_message(f"Hello, {interaction.user.mention}")


@client.tree.command(name="rr")
@app_commands.describe(
    dice="What to roll."
)
async def rr(interaction: discord.Interaction, dice: str):
    """Roll using random.org"""
    await interaction.response.send_message(roll_hack(dice, org=True))


@client.tree.command(name="ud")
@app_commands.describe(
    query="Search query"
)
async def ud(interaction: discord.Interaction, query: str):
    """Search Urban Dictionary for a phrase."""
    url = "https://mashape-community-urban-dictionary.p.rapidapi.com/define"

    headers = {
        "X-RapidAPI-Key": os.getenv("X-RapidAPI-Key"),
        "X-RapidAPI-Host": "mashape-community-urban-dictionary.p.rapidapi.com"
    }
    session = aiohttp.ClientSession()
    querystring = {"term": quote_plus(query)}

    async with session.get(url, params=querystring, headers=headers) as response:
        # response = requests.request("GET", url, headers=headers, params=querystring)
        try:
            text = await response.text()
            data = json.loads(text)["list"][0]
            e = discord.Embed(colour=15229474, timestamp=interaction.created_at)
            e.title = "Urban Dictionary"
            e.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
            e.add_field(name=f"{query}:", value=data['definition'].replace('[', '').replace(']', '')[:1023],
                        inline=False)
            e.add_field(name="Example:", value=data['example'].replace('[', '').replace(']', ''), inline=False)
            await interaction.response.send_message(embed=e)

        except Exception as er:
            await interaction.response.send_message(content="Something went wrong. Probably no results found",
                                                    ephemeral=True)
            print(type(er), er)
            raise
    await session.close()


@client.tree.command()
@app_commands.describe(
    query="Item to look up."
)
async def ge(interaction: discord.Interaction, query: str):
    """Lookup price on OSRS GE"""
    url = f"https://secure.runescape.com/m=itemdb_oldschool/api/catalogue/items.json"
    querystring = {
        "category": 1,
        "alpha": query,
        "page": 1
    }

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BillyBot",
        "charset": "utf-8"
    }

    session = aiohttp.ClientSession()
    try:
        async with session.get(url=url, params=querystring, headers=headers) as response:
            data = json.loads(await response.text())["items"][0]
            desc = data["description"]
            current_price = data["current"]["price"]
            em = discord.Embed(colour=1452538, timestamp=interaction.created_at)
            em.title = "GE price lookup"
            em.set_author(name=data["name"], icon_url=data["icon_large"])
            em.add_field(name="Price", value=str(current_price), inline=True)
            em.add_field(name="Price change today", value=data["today"]["price"], inline=True)
            em.add_field(name="Description", value=desc, inline=False)
            await interaction.response.send_message(embed=em)

    except Exception as er:
        await interaction.response.send_message(content="Something went wrong. Probably no results found",
                                                ephemeral=True)
        print(type(er), er)
    await session.close()


class RecipeDropdown(discord.ui.Select):
    def __init__(self, data):
        super().__init__(placeholder="Pick a recipe", min_values=1, max_values=1)
        opt = list()
        self.recipes = data
        for k, d in data.items():
            opt.append(discord.SelectOption(label=k))

        for o in opt:
            self.append_option(o)

    async def callback(self, interaction: discord.Interaction):
        em = discord.Embed(colour=6999040, timestamp=interaction.created_at)
        em.set_author(name=self.values[0])
        em.set_image(url=self.recipes[self.values[0]]["image"])
        em.add_field(name="Ingredients", value='\n'.join(self.recipes[self.values[0]]['ingredients']), inline=False)
        em.add_field(name="Recipe", value=self.recipes[self.values[0]]["url"], inline=True)
        em.add_field(name="Calories", value=f"{int(self.recipes[self.values[0]]['calories']):,}", inline=True)

        if int(self.recipes[self.values[0]]["time"]) != 0:
            em.add_field(name="Time to cook",
                         value=str(timedelta(minutes=int(self.recipes[self.values[0]]["time"])))[:-3], inline=True)
        await interaction.response.edit_message(embed=em)


@client.tree.command()
@app_commands.describe(
    query="Which ingredients to search."
)
async def recipe(interaction: discord.Interaction, query: str):
    url = "https://api.edamam.com/api/recipes/v2"
    querystring = {
        "type": "public",
        "q": query,
        "app_id": os.getenv("EDAMAM_APP_ID"),
        "app_key": os.getenv("EDAMAM_API_KEY"),
        "imageSize": "REGULAR"
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "BillyBot",
        "charset": "utf-8"
    }

    session = aiohttp.ClientSession()
    try:
        async with session.get(url=url, params=querystring, headers=headers) as response:
            data = json.loads(await response.text())["hits"]
            em = discord.Embed(colour=6999040, timestamp=interaction.created_at)
            em.title = "Recipe Lookup"
            first = data[0]["recipe"]
            em.add_field(name=first["label"], value=first["url"])
            v = discord.ui.View()
            important_data = dict()

            for r in data:
                important_data[r["recipe"]["label"]] = {
                    "shareAs": r["recipe"]["shareAs"],
                    "ingredients": r["recipe"]["ingredientLines"],
                    "calories": r["recipe"]["calories"],
                    "time": r["recipe"]["totalTime"],
                    "url": r["recipe"]["url"],
                    "image": r["recipe"]["image"]
                }

            v.add_item(RecipeDropdown(important_data))
            await interaction.response.send_message(embed=em, view=v)

    except Exception as er:
        await interaction.response.send_message(content="Something went wrong. Probably no results found",
                                                ephemeral=True)
        print(type(er), er)
        raise
    await session.close()


@client.tree.command()
@app_commands.describe(
    first_value='The first value you want to add something to',
    second_value='The value you want to add to the first value',
)
async def add(interaction: discord.Interaction, first_value: int, second_value: int):
    """Adds two numbers together."""
    await interaction.response.send_message(f'{first_value} + {second_value} = {first_value + second_value}')


class BardDropdown(discord.ui.Select):
    def __init__(self, data):
        super().__init__(placeholder="Choose an output", min_values=1, max_values=1)
        opt = list()
        self.choices = data
        for k in range(len(data["data"])):
            opt.append(discord.SelectOption(label=str(k)))

        for o in opt:
            self.append_option(o)

    async def callback(self, interaction: discord.Interaction):
        n = 0
        s = "Response:"
        q = self.choices["query"]
        response = self.choices["data"][int(self.values[0])]["content"][0]
        em = discord.Embed(colour=1864940, timestamp=interaction.created_at)
        em.title = "Google Bard query"
        em.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
        em.add_field(name="Query:", value=q, inline=False)
        if len(response) > 1023:
            while n * 1023 < len(response):
                em.add_field(name=s, value=response[n * 1023:(n + 1) * 1023], inline=False)
                n += 1
                s = "Continued:"
        else:
            em.add_field(name=s, value=response, inline=False)
        print(response)
        await interaction.response.edit_message(embed=em)


@client.tree.command()
@app_commands.describe(
    query='What to query Bard'
)
async def bard(interaction: discord.Interaction, query: str):
    """Queries Google's Bard"""
    await interaction.response.defer()
    response = bard_chatbot.ask(query)
    choices = response["choices"]
    em = discord.Embed(colour=1864940, timestamp=interaction.created_at)
    em.title = "Google Bard query"
    em.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
    em.add_field(name="Query:", value=query, inline=False)
    n = 0
    s = "Response:"
    if len(response["content"]) > 1023:
        while n * 1023 < len(response["content"]):
            em.add_field(name=s, value=response["content"][n * 1023:(n + 1) * 1023], inline=False)
            n += 1
            s = "Continued:"
    else:
        em.add_field(name=s, value=response["content"], inline=False)
    print(response)
    v = discord.ui.View()
    choices = {
        "query": query,
        "data": choices
    }
    v.add_item(BardDropdown(choices))
    await interaction.followup.send(embed=em, view=v)
    

@client.tree.command()
@app_commands.describe(
    query='What to query ChatGPT'
)
async def gpt(interaction: discord.Interaction, query: str):
    """Queries ChatGPT using the openai API"""
    await interaction.response.defer()
    openai.api_key = os.getenv("OPENAI_KEY")
    response = await asyncio.to_thread(openai.ChatCompletion.create, model="gpt-3.5-turbo", messages=[{"role": "user",
                                       "content": query}])
    em = discord.Embed(colour=5364300, timestamp=interaction.created_at)
    em.title = "ChatGPT query"
    em.set_author(name=interaction.user.name, icon_url=interaction.user.display_avatar.url)
    em.add_field(name="Query:", value=query, inline=False)
    n = 0
    s = "Response:"
    if len(response.choices[0]["message"]["content"]) > 1023:
        while n * 1023 < len(response.choices[0]["message"]["content"]):
            em.add_field(name=s, value=response.choices[0]["message"]["content"][n*1023:(n+1)*1023], inline=False)
            n += 1
            s = "Continued:"
    else:
        em.add_field(name=s, value=response.choices[0]["message"]["content"], inline=False)
    print(response.choices[0]["message"]["content"])
    await interaction.followup.send(embed=em)


client.run(TOKEN)
