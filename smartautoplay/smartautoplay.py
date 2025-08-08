import discord
import yt_dlp
import asyncio
import logging
import random
from datetime import timedelta
from redbot.core import commands, Config
from redbot.core.utils import tasks
from redbot.core.utils.chat_formatting import humanize_timedelta, box

log = logging.getLogger("red.smartaudio")

class Track:
    def __init__(self, url, title, duration, added_by=None):
        self.url = url
        self.title = title
        self.duration = duration
        self.added_by = added_by

class SmartAudio(commands.Cog):
    """Smart Audio – YouTube autoplay, search, playlists, and reaction controls."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=123456789)
        self.config.register_guild(
            queue=[],
            autoplay=True,
            repeat=False,
            repeat_one=False,
            shuffle=False,
            volume=0.5,
            playlists={}
        )
        self.players = {}
        self.idle_check.start()

    def cog_unload(self):
        self.idle_check.cancel()

    def get_player(self, guild):
        player = self.players.get(guild.id)
        if not player:
            player = {
                "vc": None,
                "queue": [],
                "current": None,
                "paused": False,
                "last_active": self.bot.loop.time()
            }
            self.players[guild.id] = player
        return player

    @tasks.loop(seconds=30)
    async def idle_check(self):
        for guild in self.bot.guilds:
            vc = guild.voice_client
            if vc and vc.is_connected() and len(vc.channel.members) <= 1:
                player = self.get_player(guild)
                idle = self.bot.loop.time() - player.get("last_active",0)
                if idle > 120:
                    await vc.disconnect()
                    log.info(f"Disconnected from {guild.name} due to inactivity.")

    async def _get_info(self, url):
        ydl_opts = {"format":"bestaudio/best","quiet":True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                log.warning(f"yt-dlp error: {e}")
                return None

    async def _search(self, query, limit=6):
        opts={"quiet":True,"extract_flat":True,"skip_download":True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info=ydl.extract_info(f"ytsearch{limit}:{query}",download=False)
                return info.get("entries",[])
            except Exception as e:
                log.warning(f"search error: {e}")
                return []

    async def _play(self, guild, track):
        player=self.get_player(guild)
        vc=guild.voice_client
        if not vc:
            return
        source=discord.FFmpegPCMAudio(track.url)
        vol=await self.config.guild(guild).volume()
        vc.source=discord.PCMVolumeTransformer(source,volume=vol)
        vc.play(vc.source,after=lambda e:self.bot.loop.create_task(self._after(guild)))
        player["current"]=track
        player["last_active"]=self.bot.loop.time()

    async def _after(self,guild):
        player=self.get_player(guild)
        queue=player["queue"]
        rep=await self.config.guild(guild).repeat()
        one=await self.config.guild(guild).repeat_one()
        if one and player.get("current"):
            await self._play(guild,player["current"]);return
        if rep and player.get("current"):
            queue.append(player["current"]);
        if queue:
            nextt=queue.pop(0)
            await self._play(guild,nextt)
        else:
            player["current"]=None

    @commands.command()
    async def play(self, ctx, *, query):
        """Play URL or search keywords."""
        vc=ctx.guild.voice_client or (await ctx.author.voice.channel.connect() if ctx.author.voice else None)
        if not vc: return await ctx.send("Join a voice channel first.")
        if query.startswith("http"):
            info=await self._get_info(query)
            if not info: return await ctx.send("Could not load video.")
            t=Track(query,info.get("title"),info.get("duration",0),ctx.author.id)
            player=self.get_player(ctx.guild)
            if vc.is_playing(): player["queue"].append(t);await ctx.send(f"Queued: [{t.title}]({t.url})");
            else: await self._play(ctx.guild,t);await ctx.send(f"Now playing: [{t.title}]({t.url})")
        else:
            entries=await self._search(query)
            if not entries: return await ctx.send("No results.")
            desc = "
".join(
    f"{i+1}. [{entry['title']}]({entry.get('url') or f'https://youtu.be/{entry['id']}'} )"
    for i, entry in enumerate(entries)
)
