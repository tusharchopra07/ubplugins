from app import BOT, bot, Message
import aiohttp
from bs4 import BeautifulSoup

@bot.add_cmd(cmd="app")
async def app_function(bot: BOT, message: Message):
    try:
        await message.reply("Searching...")
        app_name = "+".join(message.text.split()[1:])
        async with aiohttp.ClientSession() as ses:
            async with ses.get(f"https://play.google.com/store/search?q={app_name}&c=apps") as res:
                result = BeautifulSoup(await res.text(), "html.parser")

        found = result.find("div", class_="vWM94c")
        if found:
            app_name = found.text
            app_dev = result.find("div", class_="LbQbAe").text
            app_rating = result.find("div", class_="TT9eCd").text.replace("star", "")
            _app_link = result.find("a", class_="Qfxief")['href']
            app_icon = result.find("img", class_="T75of bzqKMd")['src']
        else:
            app_name = result.find("span", class_="DdYX5").text
            app_dev = result.find("span", class_="wMUdtb").text
            app_rating = result.find("span", class_="w2kbF").text
            _app_link = result.find("a", class_="Si6A0c Gy4nib")['href']
            app_icon = result.find("img", class_="T75of stzEZd")['src']

        app_dev_link = (
            "https://play.google.com/store/apps/developer?id="
            + app_dev.replace(" ", "+")
        )
        app_link = "https://play.google.com" + _app_link

        app_details = f"[📲]({app_icon}) **{app_name}**\n\n"
        app_details += f"`Developer :` [{app_dev}]({app_dev_link})\n"
        app_details += f"`Rating :` {app_rating} ⭐️\n"
        app_details += f"`Features :` [View in Play Store]({app_link})"
        await message.reply(app_details, disable_web_page_preview=False)
    except IndexError:
        await message.reply("No result found in search. Please enter **Valid app name**")
    except Exception as err:
        await message.reply(f"Error: {str(err)}")

@bot.add_cmd(cmd="magisk")
async def magisk_function(bot: BOT, message: Message):
    magisk_branch = {"Stable": "stable", "Beta": "beta", "Canary": "canary"}
    magisk_raw_uri = "https://raw.githubusercontent.com/topjohnwu/magisk-files/master/"
    releases = "**Latest Magisk Releases:**\n"
    async with aiohttp.ClientSession() as session:
        for _type, branch in magisk_branch.items():
            async with session.get(magisk_raw_uri + branch + ".json") as res:
                data = await res.json(content_type="text/plain")
                releases += (
                    f'**× {_type}:** `{data["magisk"]["version"]}-{data["magisk"]["versionCode"]}`|'
                    f'[Notes]({data["magisk"]["note"]})|'
                    f'[Magisk]({data["magisk"]["link"]})|\n'
                )
        await message.reply(releases)
