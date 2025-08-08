import discord
import yt_dlp
import asyncio
import logging
import random
from datetime import timedelta
from redbot.core import commands, Config
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
            queue=[], autoplay=True, repeat=False, repeat_one=False,
            shuffle=False, volume=0.5, playlists={}
        )
        self.players = {}
        # Start idle disconnect loop
        self._idle_task = self.bot.loop.create_task(self._idle_loop())

    def cog_unload(self):
        try:
            self._idle_task.cancel()
        except Exception:
            pass

    def get_player(self, guild):
        player = self.players.get(guild.id)
        if not player:
            player = {
                'vc': None,
                'queue': [],
                'current': None,
                'paused': False,
                'last_active': self.bot.loop.time()
            }
            self.players[guild.id] = player
        return player

    async def _idle_loop(self):
        """Background task: disconnect when alone for >2 minutes."""
        await self.bot.wait_until_red_ready()
        while True:
            for guild in self.bot.guilds:
                vc = guild.voice_client
                if vc and vc.is_connected() and len(vc.channel.members) <= 1:
                    player = self.get_player(guild)
                    idle = self.bot.loop.time() - player['last_active']
                    if idle > 120:
                        await vc.disconnect()
                        log.info(f"Disconnected from {guild.name} due to inactivity.")
            await asyncio.sleep(30)

    async def _get_info(self, url):
        ydl_opts = {'format': 'bestaudio/best', 'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                return ydl.extract_info(url, download=False)
            except Exception as e:
                log.error(f"yt-dlp error fetching info: {e}")
                return None

    async def _search(self, query, limit=6):
        opts = {'quiet': True, 'extract_flat': True, 'skip_download': True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
                return info.get('entries', [])
            except Exception as e:
                log.error(f"yt-dlp error searching: {e}")
                return []

    @commands.command()
    async def play(self, ctx, *, query):
        """Play a URL or search YouTube for keywords and select."""
        # Ensure user is in a voice channel
        if not ctx.author.voice or not ctx.author.voice.channel:
            return await ctx.send("You need to be in a voice channel to use this command.")
        channel = ctx.author.voice.channel
        vc = ctx.guild.voice_client
        # Connect if not already
        if not vc:
            try:
                vc = await channel.connect()
                await ctx.send(f"Connected to voice channel: {channel.name}")
            except Exception as e:
                log.error(f"Failed to connect to voice channel: {e}")
                return await ctx.send(f"Could not connect: {e}")
        player = self.get_player(ctx.guild)
        # Direct URL playback
        if query.startswith('http'):
            info = await self._get_info(query)
            if not info:
                return await ctx.send("Could not load video.")
            track = Track(query, info.get('title'), info.get('duration', 0), ctx.author.id)
            if vc.is_playing():
                player['queue'].append(track)
                await ctx.send(f"Queued: [{track.title}]({track.url})")
            else:
                await self._play(ctx.guild, track)
                await ctx.send(f"Now playing: [{track.title}]({track.url})")
            return
        # Keyword search flow
        results = await self._search(query)
        if not results:
            return await ctx.send("No results found.")
        # Build and display search results
        desc = "\n".join(
            f"{i+1}. [{e['title']}]({e.get('url') or f'https://youtu.be/{e['id']}'} )"
            for i, e in enumerate(results)
        )
        embed = discord.Embed(
            title="Search Results",
            description=desc,
            color=discord.Color.blurple()
        )
        msg = await ctx.send(embed=embed)
        emojis = ['1️⃣','2️⃣','3️⃣','4️⃣','5️⃣','6️⃣']
        for emj in emojis:
            await msg.add_reaction(emj)
        def check(r, u):
            return u == ctx.author and r.message.id == msg.id and str(r.emoji) in emojis
        try:
            reaction, _ = await self.bot.wait_for('reaction_add', check=check, timeout=30)
            idx = emojis.index(str(reaction.emoji))
            sel = results[idx]
            url = sel.get('url') or f"https://youtu.be/{sel['id']}"
            info = await self._get_info(url)
            track = Track(url, info.get('title'), info.get('duration', 0), ctx.author.id)
            if vc.is_playing():
                player['queue'].append(track)
                await ctx.send(f"Queued: [{track.title}]({track.url})")
            else:
                await self._play(ctx.guild, track)
                await ctx.send(f"Now playing: [{track.title}]({track.url})")
        except asyncio.TimeoutError:
            await ctx.send("Selection timed out.")

    async def _play(self, guild, track):
        vc = guild.voice_client
        if not vc:
            return
        source = discord.FFmpegPCMAudio(track.url)
        vol = await self.config.guild(guild).volume()
        vc.source = discord.PCMVolumeTransformer(source, volume=vol)
        vc.play(vc.source, after=lambda e: asyncio.create_task(self._after(guild)))
        player = self.get_player(guild)
        player['current'] = track
        player['last_active'] = self.bot.loop.time()

    async def _after(self, guild):
        player = self.get_player(guild)
        queue = player['queue']
        rep = await self.config.guild(guild).repeat()
        one = await self.config.guild(guild).repeat_one()
        if one and player['current']:
            await self._play(guild, player['current'])
            return
        if rep and player['current']:
            queue.append(player['current'])
        if queue:
            nxt = queue.pop(0)
            await self._play(guild, nxt)
        else:
            player['current'] = None

async def setup(bot):
    await bot.add_cog(SmartAudio(bot))
