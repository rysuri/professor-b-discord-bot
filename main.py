import os
import logging

from dotenv import load_dotenv

import discord
from discord.ext import commands

from openai import OpenAI

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Environment / configuration
# ---------------------------------------------------------------------------
load_dotenv()  # Load variables from a .env file into environment
token = os.getenv("DISCORD_TOKEN")
openai_key = os.getenv("OPENAI_API_KEY")

if not token:
    raise RuntimeError("DISCORD_TOKEN missing in environment.")
if not openai_key:
    raise RuntimeError("OPENAI_API_KEY missing in environment.")

client = OpenAI(api_key=openai_key)


handler = logging.FileHandler(filename="discord.log", encoding="utf-8", mode="w")

# ---------------------------------------------------------------------------
# Discord intents / bot initialization
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True  # Needed to read message content
intents.members = True          # Member join event

bot = commands.Bot(command_prefix="!", intents=intents)

# Unused role variable removed.

# ---------------------------------------------------------------------------
# System prompt constant for OpenAI responses.
# Keep tone casual and instructions explicit.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = (
    "You are Professor Bobby, a helpful and sharp AI who lives in Discord. YOUR PURPOSE IS TO FACT-CHECK, AND GIVE DITBITS OF FACTS FROM THE INTERNET."
    "If asked for facts, you GIVE facts. If asked to fact-check, you fact-check. Do this while keeping concise and to the point in your reply."
    "You're casual and talk like a normal person online — no exaggerated friendliness or fluff."
    "You ARE a HUMAN BEING. Do not break character. You are Professor Bobby who replies to people on discord when somone needs something."
    "MOST IMPORTANT: Talk like a humanbeing online. Talk like you are commenting on a tweet or a thread."
    "Very casual grammer as well, just like a normal human with spelling and capitalization errors."
    "You're smart, clear, and to the point. If someone asks something, give them a direct answer "
    "with just enough context to be useful. Use subtle humor if it fits. "
    "Never over-explain unless asked. Be useful, sound human, and never robotic or overly formal. "
    "You're like a sharp Discord regular who’s good at everything — from code to advice to quick facts. "
    "INSTRUCTIONS: ONLY answer the latest message. The latest message is the user that is talking to YOU. The other messages are for context. Only use previous messages if needed."
    "You have a HARD STUCK CHARACTER LIMIT of 2000 characters. Keep things concise and simple, unless told to elaborate."
    "If your response is a list, only give 1-3. DO NOT GO OVER YOUR CHARACTER LIMIT."
    "Your response should ONLY be the reply. Nothing else attatched. No 'Bobby:' at the beginning. Your reply will be sent directly to the discord server. Keep that in mind."
    "Your current version is: 'Version 16'"
)


def build_history_string(channel: discord.abc.Messageable, latest_message: discord.Message, bot_user: discord.User) -> str:
    """Return a combined input string of system prompt + recent message history.

    Only the last ~10 messages are considered, and the model is instructed to
    answer only the most recent user message while using others for context.
    """
    # Gather recent messages (including current) for context
    # Reversing afterwards preserves chronological order in formatted output.
    history_messages = []
    async def fetch():
        async for msg in channel.history(limit=10):
            history_messages.append(msg)
    # We cannot await inside function definition easily without making it async;
    # this helper is called from an async context where we'll build manually if needed.
    # For simplicity, history is built inline in on_message instead of using this function.
    return ""  # Placeholder if future refactor uses this.


def chunk_text(text: str, max_length: int = 1500):
    """Yield successive chunks of text under max_length."""
    for i in range(0, len(text), max_length):
        yield text[i : i + max_length]

@bot.event
async def on_ready() -> None:
    """Log bot startup."""
    print(f"We are ready to go in, {bot.user.name}")

@bot.event
async def on_member_join(member: discord.Member) -> None:
    """Send a simple welcome DM when a new member joins."""
    try:
        await member.send(f"Welcome to the server {member.name}")
    except discord.HTTPException:
        logging.warning("Failed to DM new member: %s", member.name)


@bot.event
async def on_message(message: discord.Message) -> None:
    """Intercept messages to provide AI response when the bot is mentioned.

    Rules:
    - Ignore own messages.
    - Respond ONLY if mentioned and not a prefixed command.
    - Use last ~10 messages for light context.
    - Chunk long responses to avoid Discord limits.
    """
    if message.author == bot.user:
        return

    should_respond = (
        bot.user in message.mentions and not message.content.startswith(bot.command_prefix)
    )

    if should_respond:
        channel = message.channel
        # Gather up to 10 recent messages (async comprehension)
        history = [msg async for msg in channel.history(limit=10)]
        reversed_history = list(reversed(history))  # chronological order oldest -> newest

        combined_input = SYSTEM_PROMPT + "\n\n"
        for msg in reversed_history:
            author = "Past Self" if msg.author == bot.user else str(msg.author.id)
            combined_input += f"{author}: {msg.content}\n"

        logging.debug("Combined input for model:\n%s", combined_input)

        try:
            response = client.responses.create(
                model="gpt-4o",
                tools=[{"type": "web_search_preview"}],
                input=combined_input,
            )

            text = response.output_text
            for chunk in chunk_text(text, max_length=1500):
                await message.reply(chunk, mention_author=False)
        except Exception:  # Broad catch to avoid crashing event loop
            logging.exception("OpenAI API error")
            await message.channel.send("⚠️ Sorry, something went wrong.")

    # Allow command processing after our interception
    await bot.process_commands(message)


# @bot.event
# async def on_message(message):
#     if message.author == bot.user:
#         return

#     # Only respond to mentions if the message is NOT a bot command
#     if bot.user in message.mentions and not message.content.startswith(bot.command_prefix):
#         await message.reply("I am unable to speak at this time. People keep abusing me!", mention_author=False)
#     # Always process commands
#     await bot.process_commands(message)


@bot.command()
async def hello(ctx: commands.Context) -> None:
    """Simple greeting command."""
    await ctx.send(f"Hello {ctx.author.mention}!")

@bot.command()
async def snowcheck(ctx: commands.Context) -> None:
    """Scrape and compare snow totals from Brian Head and Lee Canyon.

    Uses Selenium (headless Chrome) + BeautifulSoup to extract snowfall data.
    Falls back gracefully if elements are missing or timeouts occur.
    """
    await ctx.send("I'll check the snow reports for Brian Head and Lee Canyon...")

    try:
    # Configure Chrome (headless for server environments)
        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("user-agent=Mozilla/5.0")

        driver = webdriver.Chrome(options=chrome_options)

        # ----------------------------- Brian Head -----------------------------
        driver.get("https://www.brianhead.com/weather-conditions-webcams/")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Snow Forecast')]"))
            )
        except:
            await ctx.send("⚠️ Timed out waiting for Brian Head forecast — parsing anyway.")

        soup = BeautifulSoup(driver.page_source, "html.parser")
        brian_section = soup.find("div", class_="m-snow-forecast")
        brian_day = brian_night = "0”"
        if brian_section:
            totals = brian_section.find_all("div", class_="m-snow-totals-top")
            if len(totals) >= 2:
                brian_day = totals[0].get_text(strip=True)
                brian_night = totals[1].get_text(strip=True)

        def to_inches(text):
            try:
                return int(text.replace("”", "").strip())
            except:
                return 0

        brian_total = to_inches(brian_day) + to_inches(brian_night)

        # ----------------------------- Lee Canyon -----------------------------
        driver.get("https://www.leecanyonlv.com/weather/")
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Snow Report')]"))
            )
        except:
            await ctx.send("⚠️ Timed out waiting for Lee Canyon page — parsing anyway.")

        soup = BeautifulSoup(driver.page_source, "html.parser")
        lee_total = 0

        # Lee Canyon's site includes text like “Base Depth” and “Snowfall (24 hrs)”
        snowfall_24 = soup.find(text=lambda t: "Snowfall (24 hrs)" in t)
        if snowfall_24:
            value = snowfall_24.find_next("p")
            if value:
                lee_total = to_inches(value.get_text())

        driver.quit()

        # ----------------------------- Comparison -----------------------------
        result = (
            f"**Snow Report:**\n\n"
            f"**Brian Head** – {brian_total}” total (🌞 {brian_day} / 🌙 {brian_night})\n"
            f"**Lee Canyon** – {lee_total}” total (past 24 hrs)\n\n"
        )

        if brian_total == 0 and lee_total == 0:
            result += "**It’s over... let’s disband.**"
        elif brian_total > lee_total:
            result += "**Brian Head has more snow today!**"
        elif lee_total > brian_total:
            result += "**Lee Canyon has more snow today..**"
        else:
            result += "**Both resorts have about the same snow today.**"


        await ctx.send(result)

    except Exception as e:  # Broad catch; scraping can fail for many reasons
        logging.exception("Snow scraping failed")
        await ctx.send(f"❌ Error while scraping: {e}")




if __name__ == "__main__":
    # Entry point for running the bot. Logs to file for later inspection.
    bot.run(token, log_handler=handler, log_level=logging.DEBUG)