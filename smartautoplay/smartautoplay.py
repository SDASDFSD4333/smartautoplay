import yt_dlp
from redbot.core import commands, Config
from redbot.core.bot import Red

class SmartAutoplay(commands.Cog):
    """Smart Autoplay – Plays related tracks like YouTube's Mix"""

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=987654321)
        self.audio_cog = None

    async def red_get_data_for_user(self, *, user_id):
        return {}

    @commands.Cog.listener()
    async def on_red_ready(self):
        self.audio_cog = self.bot.get_cog("Audio")
        if not self.audio_cog:
            print("Audio cog not found!")

    @commands.Cog.listener()
    async def on_track_end(self, guild, track, track_error=None):
        """Trigger when a track ends and autoplay is enabled."""
        if not await self.config.guild(guild).autoplay_enabled():
            return

        track_url = getattr(track, "url", None) or track.info.get("url")
        if not track_url:
            print("Could not determine track URL.")
            return

        related_url = await self._get_related_track(track_url)
        if related_url:
            vc = self.audio_cog._get_player(guild)
            await vc.queue_url(related_url, guild=guild)
        else:
            if guild.system_channel:
                await guild.system_channel.send("Couldn't find a related track!")

    @commands.group()
    async def smartplay(self, ctx):
        """Toggle autoplay settings."""
        pass

    @smartplay.command()
    async def on(self, ctx):
        await self.config.guild(ctx.guild).autoplay_enabled.set(True)
        await ctx.send("Smart Autoplay enabled.")

    @smartplay.command()
    async def off(self, ctx):
        await self.config.guild(ctx.guild).autoplay_enabled.set(False)
        await ctx.send("Smart Autoplay disabled.")

    async def _get_related_track(self, url):
        """Use yt-dlp to get a related video URL."""
        ydl_opts = {
            "quiet": True,
            "extract_flat": True,
            "skip_download": True,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                print(f"Fetching related for: {url}")
                info = ydl.extract_info(url, download=False)
                print(f"Fetched info keys: {info.keys()}")
                if "related_videos" in info:
                    print(f"Found {len(info['related_videos'])} related videos")
                    for rel in info["related_videos"]:
                        video_id = rel.get("id")
                        if video_id:
                            return f"https://www.youtube.com/watch?v={video_id}"
                    print("No usable related videos found.")
                else:
                    print("No related_videos key found.")
            except Exception as e:
                print(f"[SmartAutoplay Error] {e}")
        return None
