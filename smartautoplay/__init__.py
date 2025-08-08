from .smartautoplay import SmartAudio

async def setup(bot):
    await bot.add_cog(SmartAudio(bot))
