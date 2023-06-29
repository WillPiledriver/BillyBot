import os
import discord
import tools
import re
import json
from datetime import timedelta
from dotenv import load_dotenv
from discord import app_commands
from discord.ext import commands
from urllib.parse import quote_plus
import aiohttp
import openai
import asyncio
from enum import Enum
from Bard import Chatbot
import yt_dlp as youtube_dl
import random
from youtube_search import YoutubeSearch
from pytube import Playlist
import nest_asyncio
nest_asyncio.apply()

default_volume = 0.05
regex_youtube = "^((?:https?:)?\/\/)?((?:www|m)\.)?((?:youtube\.com|youtu.be))(\/(?:[\w\-]+\?v=|embed\/|v\/)?)([\w\-]+)(\S+)?$"

# Suppress noise about console usage from errors
# youtube_dl.utils.bug_reports_message = lambda: ''
ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': 'MusicBot/temp/%(title)s-%(id)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': False,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'cookiefile': "C:/Users/Will/cookies.txt",
    'quiet': False,
    'no_check_formats': True,
    'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
    'no_warnings': False,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}
ffmpeg_options = {
    'options': '-vn'
}
#     'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
ytdl = youtube_dl.YoutubeDL(ytdl_format_options)


class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=default_volume):
        super().__init__(source, volume)

        self.data = data

        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))

        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)


class AlreadyConnectedToChannel(commands.CommandError):
    pass


class NoVoiceChannel(commands.CommandError):
    pass


class QueueIsEmpty(commands.CommandError):
    pass


class NoTracksFound(commands.CommandError):
    pass


class PlayerIsAlreadyPaused(commands.CommandError):
    pass


class NoMoreTracks(commands.CommandError):
    pass


class NoPreviousTracks(commands.CommandError):
    pass


class InvalidRepeatMode(commands.CommandError):
    pass

class RepeatMode(Enum):
    NONE = 0
    ONE = 1
    ALL = 2


class Queue:
    def __init__(self):
        self._queue = []
        self.position = 0
        self.repeat_mode = RepeatMode.ALL

    @property
    def is_empty(self):
        return not self._queue

    @property
    def current_track(self):
        if not self._queue:
            raise QueueIsEmpty

        if self.position <= len(self._queue) - 1:
            return self._queue[self.position]

    @property
    def upcoming(self):
        if not self._queue:
            raise QueueIsEmpty

        return self._queue[self.position + 1:]

    @property
    def history(self):
        if not self._queue:
            raise QueueIsEmpty

        return self._queue[:self.position]

    @property
    def length(self):
        return len(self._queue)

    def add(self, *args):
        self._queue.extend(args)

    def save_queue(self, name):
        current = tools.rw_dict("saved_qs.json", "r")
        current[name] = self._queue
        tools.rw_dict("saved_qs.json", "w", data=current)

    def load_queue(self, name):
        try:
            new = tools.rw_dict("saved_qs.json", "r")[name]
        except Exception as e:
            print(f"No saved q named {name}.")
            return False
        # self.empty()
        self._queue.extend(new)
        return True

    def get_next_track(self):
        if not self._queue:
            raise QueueIsEmpty

        self.position += 1

        if self.position < 0:
            return None
        elif self.position > len(self._queue) - 1:
            if self.repeat_mode == RepeatMode.ALL:
                self.position = 0
            else:
                return None

        return self._queue[self.position]

    def shuffle(self):
        if not self._queue:
            raise QueueIsEmpty

        upcoming = self.upcoming
        random.shuffle(upcoming)
        self._queue = self._queue[:self.position + 1]
        self._queue.extend(upcoming)

    def set_repeat_mode(self, mode):
        if mode == "none":
            self.repeat_mode = RepeatMode.NONE
        elif mode == "1":
            self.repeat_mode = RepeatMode.ONE
        elif mode == "all":
            self.repeat_mode = RepeatMode.ALL

    def empty(self):
        self._queue.clear()
        self.position = 0

    @property
    def queue(self):
        return self._queue

class Bot(discord.Client):
    def __init__(self, *, guild, intents: discord.Intents):
        super().__init__(intents=intents)
        self.MY_GUILD = guild
        self.tree = app_commands.CommandTree(self)
        self.funny_words = {
            "cum": "(cum)",
            "bruh": "(bruh)",
            "69": "69"*69,
            "lmao": "xD"
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
intents.voice_states = True
client = Bot(guild=GUILD, intents=intents)
bard_chatbot = Chatbot(os.getenv("BARD_KEY"))
queue = Queue()
loop = None
voice = None


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
    await interaction.response.defer()
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
            e = discord.Embed(
                colour=15229474, timestamp=interaction.created_at)
            e.title = "Urban Dictionary"
            e.set_author(name=interaction.user.name,
                         icon_url=interaction.user.display_avatar.url)
            e.add_field(name=f"{query}:", value=data['definition'].replace('[', '').replace(']', '')[:1023],
                        inline=False)
            e.add_field(name="Example:", value=data['example'].replace(
                '[', '').replace(']', ''), inline=False)
            await interaction.followup.send(embed=e)

        except Exception as er:
            await interaction.followup.send(content="Something went wrong. Probably no results found",
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
    await interaction.response.defer()
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
            em = discord.Embed(
                colour=1452538, timestamp=interaction.created_at)
            em.title = "GE price lookup"
            em.set_author(name=data["name"], icon_url=data["icon_large"])
            em.add_field(name="Price", value=str(current_price), inline=True)
            em.add_field(name="Price change today",
                         value=data["today"]["price"], inline=True)
            em.add_field(name="Description", value=desc, inline=False)
            await interaction.followup.send(embed=em)

    except Exception as er:
        await interaction.followup.send(content="Something went wrong. Probably no results found",
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
        em.add_field(name="Ingredients", value='\n'.join(
            self.recipes[self.values[0]]['ingredients']), inline=False)
        em.add_field(
            name="Recipe", value=self.recipes[self.values[0]]["url"], inline=True)
        em.add_field(
            name="Calories", value=f"{int(self.recipes[self.values[0]]['calories']):,}", inline=True)

        if int(self.recipes[self.values[0]]["time"]) != 0:
            em.add_field(name="Time to cook",
                         value=str(timedelta(minutes=int(self.recipes[self.values[0]]["time"])))[:-3], inline=True)
        await interaction.response.edit_message(embed=em)


@client.tree.command()
@app_commands.describe(
    query="Which ingredients to search."
)
async def recipe(interaction: discord.Interaction, query: str):
    """Search for a recipe."""
    await interaction.response.defer()
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
            em = discord.Embed(
                colour=6999040, timestamp=interaction.created_at)
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
            await interaction.followup.send(embed=em, view=v)

    except Exception as er:
        await interaction.followup.send(content="Something went wrong. Probably no results found",
                                                ephemeral=True)
        print(type(er), er)
        raise
    await session.close()


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
        em.set_author(name="Google Bard Query",
                      icon_url="https://i.imgur.com/mVjfxsD.png")
        em.add_field(name="Query:", value=q, inline=False)
        if len(response) > 1023:
            while n * 1023 < len(response):
                em.add_field(
                    name=s, value=response[n * 1023:(n + 1) * 1023], inline=False)
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
    q = response["textQuery"][0] if len(response["textQuery"]) > 0 else query
    choices = response["choices"]
    em = discord.Embed(colour=1864940, timestamp=interaction.created_at)
    em.set_author(name="Google Bard Query", icon_url="https://i.imgur.com/mVjfxsD.png")
    em.add_field(name="Query:", value=q, inline=False)
    n = 0
    s = "Response:"
    if len(response["content"]) > 1023:
        while n * 1023 < len(response["content"]):
            em.add_field(
                name=s, value=response["content"][n * 1023:(n + 1) * 1023], inline=False)
            n += 1
            s = "Continued:"
    else:
        em.add_field(name=s, value=response["content"], inline=False)
    print(response)
    v = discord.ui.View()
    choices = {
        "query": q,
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
    em.set_author(name="ChatGPT Query",
                  icon_url="https://i.imgur.com/n7OLqng.png")
    em.add_field(name="Query:", value=query, inline=False)
    n = 0
    s = "Response:"
    if len(response.choices[0]["message"]["content"]) > 1023:
        while n * 1023 < len(response.choices[0]["message"]["content"]):
            em.add_field(
                name=s, value=response.choices[0]["message"]["content"][n*1023:(n+1)*1023], inline=False)
            n += 1
            s = "Continued:"
    else:
        em.add_field(
            name=s, value=response.choices[0]["message"]["content"], inline=False)
    print(response.choices[0]["message"]["content"])
    await interaction.followup.send(embed=em)


@client.tree.command()
@app_commands.describe(
    volume="Volume you want to set it to."
)
async def vol(interaction: discord.Interaction, volume: int):
    """Sets playback volume."""
    global voice
    global default_volume
    if volume > 100:
        volume = 100
    elif volume < 1:
        volume = 1
    if voice is None:
        await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
    voice.source.volume = volume / 100
    default_volume = volume / 100
    await interaction.response.send_message(f"Changed volume to {volume}")
    

@client.tree.command()
async def shuffle(interaction: discord.Interaction):
    """Shuffles the queue."""
    global queue
    queue.shuffle()
    await interaction.response.send_message("Queue shuffled.")

@client.tree.command()
async def stop(interaction: discord.Interaction):
    """Stops playback."""
    global queue
    global voice
    global loop
    loop = None
    queue.empty()
    try:
        await voice.disconnect()
        voice = None
    except AttributeError:
        await interaction.response.send_message("Not connected to a voice channel.", ephemeral=True)
    await interaction.response.send_message("Playback stopped.")

@client.tree.command()
async def skip(interaction: discord.Interaction):
    """Skips to the next track in the queue."""
    global voice
    voice.stop()
    await interaction.response.send_message("Skipped song.")

async def ensure_q(interaction: discord.Interaction):
    # voice.is_connected() ?
    global voice
    if voice is None:
        voices = interaction.client.voice_clients
        for i in voices:
            if i.channel == interaction.user.voice.channel:
                voice = i
                break
        else:
            if interaction.user.voice is not None:
                vc = interaction.user.voice.channel
                voice = await vc.connect()
                return True
            else:
                await interaction.response.defer(ephemeral=True)
                await interaction.followup.send("You are not in a voice channel.")
                return False
    else:
        return True

@client.tree.command(name="saveq")
@app_commands.describe(
    name="Name of the queue."
)
async def save_q(interaction: discord.Interaction, name: str):
    global queue
    queue.save_queue(name)
    await interaction.response.send_message(f"{queue.length} items saved to the queue named **{name}**.")

@client.tree.command(name="loadq")
@app_commands.describe(
    name="Name of the queue."
)
async def load_q(interaction: discord.Interaction, name: str):
    global queue
    global voice
    global loop
    c = int(queue.length)
    if queue.load_queue(name):
        if voice is not None:
            await ensure_q(interaction)
        else:
            if not await ensure_q(interaction):
                return
            loop = interaction.client.loop.create_task(yt_queue_thread(interaction))
        await interaction.response.send_message(f"Loaded {queue.length - c} items into the queue.")
    else:
        await interaction.response.send_message(f"{name} is not a recognized queue name.")

async def yt(interaction: discord.Interaction, url):
        """Plays from a url (almost anything youtube_dl supports)"""
        global voice
        global default_volume
        player = await YTDLSource.from_url(url, loop=interaction.client.loop)
        player.volume = default_volume
        voice.play(player, after=lambda e: print('Player error: %s' % e) if e else None)
        await interaction.channel.send('Now playing: {}'.format(player.title))

async def yt_queue_thread(interaction: discord.Interaction):
        global queue
        global voice
        global loop
        queue.repeat_mode = 0
        first_play = False
        if queue.position == 0:
            first_play = True
        while not queue.is_empty:
            if not voice.is_playing():
                if first_play:
                    await yt(interaction, url=queue.current_track)
                    first_play = False
                else:
                    track = queue.get_next_track()
                    if track is None:
                        loop = None
                        break
                    try:
                        await yt(interaction, url=track)
                    except Exception as e:
                        print(e)
                        continue
            await asyncio.sleep(0.5)
        queue.empty()
        if voice is not None:
            voice.stop()

class YTDropdown(discord.ui.Select):
    def __init__(self, data):
        super().__init__(placeholder="Choose a video", min_values=1, max_values=1)
        opt = list()
        self.choices = data
        n = 0
        for k in data:
            opt.append(discord.SelectOption(label=str(k["title"]), value=n))
            n += 1

        for o in opt:
            self.append_option(o)

    async def callback(self, interaction: discord.Interaction):
        global queue
        global loop
        url = f"https://youtu.be/{self.choices[int(self.values[0])]['id']}"
        em = discord.Embed(color=16711680)
        em.add_field(name="Chosen song:", value=url)
        queue.add(url)
        await interaction.response.edit_message(content=f"Chosen song: {url}", embed=None, view=None)
        if loop is None:
            loop = interaction.client.loop.create_task(yt_queue_thread(interaction))

@client.tree.command()
@app_commands.describe(
    query="The URL or search query"
)
async def q(interaction: discord.Interaction, query: str):
    """Queue up a song or playlist. Supports any website that yt-dlp supports."""
    global queue
    global loop
    if not await ensure_q(interaction):
        return

    await interaction.response.defer()

    if re.search(regex_youtube, query) and query.find("list=") != -1:
        playlist = Playlist(query)
        if playlist != []:
            playlist_ids = playlist.video_urls
            for p in playlist_ids:
                queue.add(p)
            await interaction.followup.send(f"{len(playlist_ids)} items added to the queue.")
            if loop is None:
                loop = interaction.client.loop.create_task(yt_queue_thread(interaction))
            return
    elif re.search("(https:\/\/www\.|http:\/\/www\.|https:\/\/|http:\/\/)?[a-zA-Z]{2,}(\.[a-zA-Z]{2,})(\.[a-zA-Z]{2,})?\/[a-zA-Z0-9]{2,}|((https:\/\/www\.|http:\/\/www\.|https:\/\/|http:\/\/)?[a-zA-Z]{2,}(\.[a-zA-Z]{2,})(\.[a-zA-Z]{2,})?)|(https:\/\/www\.|http:\/\/www\.|https:\/\/|http:\/\/)?[a-zA-Z0-9]{2,}\.[a-zA-Z0-9]{2,}\.[a-zA-Z0-9]{2,}(\.[a-zA-Z0-9]{2,})?", query):
        temp_ydl = youtube_dl.YoutubeDL({'outtmpl': 'MusicBot/temp/%(title)s-%(id)s.%(ext)s', "quiet": True,})
        result = temp_ydl.extract_info(query, download=False, process=False)

        c = 0
        if "entries" in result:
            for r in result["entries"]:
                # TODO: check for edge cases here
                if "url" in r:
                    c += 1
                    # TODO: Counting is unnecessary here because queue.add extends not appends
                    queue.add(r["url"])
                else:
                    queue.add(query)
                    if loop is None:
                        loop = interaction.client.loop.create_task(yt_queue_thread(interaction))
                    return
            await interaction.followup.send(f"{c} items added to the queue.")
            if loop is None:
                loop = interaction.client.loop.create_task(yt_queue_thread(interaction))
            return
        else:
            queue.add(query)
        if loop is None:
            loop = interaction.client.loop.create_task(yt_queue_thread(interaction))
        await interaction.followup.send(f"Chosen song: {query}")
        return
    search = YoutubeSearch(query, max_results=20).to_dict()
    v = discord.ui.View()
    v.add_item(YTDropdown(search))
    await interaction.followup.send(view=v)


client.run(TOKEN)
