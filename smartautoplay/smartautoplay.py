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
            desc="\n".join(f"{i+1}. [{e['title']}]({e.get('url',f'https://youtu.be/{e['id']}')})" for i,e in enumerate(entries))
            em=discord.Embed(title="Search Results",description=desc,color=discord.Color.blurple())
            msg=await ctx.send(embed=em)
            emojis=["1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣"]
            for emj in emojis: await msg.add_reaction(emj)
            def chk(r,u):return u==ctx.author and r.message.id==msg.id and str(r.emoji) in emojis
            try:
                r,_=await self.bot.wait_for("reaction_add",check=chk,timeout=30)
                idx=emojis.index(str(r.emoji));sel=entries[idx]
                url=sel.get("url") or f"https://youtu.be/{sel['id']}"
                info=await self._get_info(url);t=Track(url,info.get("title"),info.get("duration",0),ctx.author.id)
                player=self.get_player(ctx.guild)
                if vc.is_playing(): player["queue"].append(t);await ctx.send(f"Queued: [{t.title}]({t.url})")
                else: await self._play(ctx.guild,t);await ctx.send(f"Now playing: [{t.title}]({t.url})")
            except asyncio.TimeoutError: await ctx.send("Selection timed out.")

    @commands.command()
    async def pause(self, ctx):
        vc=ctx.guild.voice_client
        if vc and vc.is_playing(): vc.pause();await ctx.send("Paused.")
    @commands.command()
    async def resume(self, ctx):
        vc=ctx.guild.voice_client
        if vc and vc.is_paused(): vc.resume();await ctx.send("Resumed.")
    @commands.command()
    async def stop(self, ctx):
        vc=ctx.guild.voice_client
        if vc: vc.stop();await ctx.send("Stopped.")

    @commands.command()
    async def volume(self, ctx, level:float):
        level=max(0.0,min(1.0,level));await self.config.guild(ctx.guild).volume.set(level)
        vc=ctx.guild.voice_client
        if vc and vc.source: vc.source.volume=level
        await ctx.send(f"Volume set to {int(level*100)}%.")

    @commands.command()
    async def loop(self, ctx):
        cur=await self.config.guild(ctx.guild).repeat_one();await self.config.guild(ctx.guild).repeat_one.set(not cur)
        await ctx.send(f"Loop current: {'on' if not cur else 'off'}")
    @commands.command()
    async def repeatall(self, ctx):
        cur=await self.config.guild(ctx.guild).repeat();await self.config.guild(ctx.guild).repeat.set(not cur)
        await ctx.send(f"Repeat all: {'on' if not cur else 'off'}")
    @commands.command()
    async def shuffle(self, ctx):
        p=self.get_player(ctx.guild);random.shuffle(p['queue']);await ctx.send("Queue shuffled.")

    @commands.command()
    async def savequeue(self, ctx):
        p=self.get_player(ctx.guild);await self.config.guild(ctx.guild).queue.set([t.__dict__ for t in p['queue']]);await ctx.send("Queue saved.")
    @commands.command()
    async def loadqueue(self, ctx):
        raw=await self.config.guild(ctx.guild).queue();p=self.get_player(ctx.guild);
        p['queue']=[Track(d['url'],d['title'],d['duration'],d.get('added_by')) for d in raw];await ctx.send(f"Loaded {len(p['queue'])} tracks.")

    @commands.group(invoke_without_command=True)
    async def playlist(self, ctx):
        await ctx.send_help('playlist')
    @playlist.command()
    async def create(self, ctx, name):
        pls=await self.config.guild(ctx.guild).playlists();
        if name in pls: return await ctx.send('Exists');pls[name]=[];await self.config.guild(ctx.guild).playlists.set(pls);
        await ctx.send(f"Playlist `{name}` created.")
    @playlist.command()
    async def add(self, ctx, name, url):
        pls=await self.config.guild(ctx.guild).playlists();
        if name not in pls: return await ctx.send('No such');info=await self._get_info(url);
        if not info: return await ctx.send('Fail');pls[name].append({'url':url,'title':info['title'],'duration':info.get('duration',0)});
        await self.config.guild(ctx.guild).playlists.set(pls);await ctx.send(f"Added to `{name}`.")
    @playlist.command()
    async def show(self, ctx, name):
        pls=await self.config.guild(ctx.guild).playlists();
        if name not in pls: return await ctx.send('No such');pl=pls[name];
        if not pl: return await ctx.send('Empty');
        lines=[f"{i+1}. [{t['title']}]({t['url']}) ({humanize_timedelta(timedelta(seconds=t['duration']))})" for i,t in enumerate(pl)];
        await ctx.send(embed=discord.Embed(title=f"Playlist {name}",description="\n".join(lines)))
    @playlist.command()
    async def play(self, ctx, name):
        pls=await self.config.guild(ctx.guild).playlists();
        if name not in pls: return await ctx.send('No such');pl=pls[name];
        if not pl: return await ctx.send('Empty');p=self.get_player(ctx.guild);
        for t in pl: p['queue'].append(Track(t['url'],t['title'],t['duration']));
        await ctx.send(f"Added {len(pl)} tracks.")
    @playlist.command()
    async def remove(self, ctx, name, idx:int):
        pls=await self.config.guild(ctx.guild).playlists();
        if name not in pls: return await ctx.send('No such');
        try: rem=pls[name].pop(idx-1)
        except: return await ctx.send('Invalid');await self.config.guild(ctx.guild).playlists.set(pls);
        await ctx.send(f"Removed {rem['title']}")
    @playlist.command()
    async def clear(self, ctx, name):
        pls=await self.config.guild(ctx.guild).playlists();
        if name not in pls: return await ctx.send('No such');pls[name]=[];await self.config.guild(ctx.guild).playlists.set(pls);
        await ctx.send(f"Cleared {name}")
    @playlist.command()
    async def rename(self, ctx, old, new):
        pls=await self.config.guild(ctx.guild).playlists();
        if old not in pls: return await ctx.send('No such');
        if new in pls: return await ctx.send('Exists');pls[new]=pls.pop(old);await self.config.guild(ctx.guild).playlists.set(pls);
        await ctx.send(f"Renamed {old} -> {new}")

    @commands.command()
    async def audioguide(self, ctx):
        guide=(
            "**SmartAudio Commands**\n"
            "!play <url|keywords> — Play or search YouTube\n"
            "!pause/resume/stop — Playback control\n"
            "!loop — Repeat current track\n"
            "!repeatall — Repeat queue\n"
            "!shuffle — Shuffle queue\n"
            "!savequeue/loadqueue — Persist queue\n"
            "!queue — Interactive queue pages\n"
            "!playlist — Manage playlists\n"
            "Reactions: ⬅️➡️ page, 🗑️ remove, 1️⃣–7️⃣ add to playlist1–7\n"
        )
        await ctx.send(box(guide,'ini'))
