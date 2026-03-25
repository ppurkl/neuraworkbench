import os
import asyncio
from pathlib import Path
from browser_use import Agent, Browser
from browser_use import ChatOpenAI, ChatGoogle

#####################################################
#                      API Keys                     #
#####################################################
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent.parent  # Expects the keys to be on the same level as neuraworkbench

os.environ["OPENAI_API_KEY"] = (PROJECT_ROOT / "openai_key.txt").read_text().strip()
os.environ["GOOGLE_API_KEY"] = (PROJECT_ROOT / "google_key.txt").read_text().strip()
os.environ["ANTHROPIC_API_KEY"] = (PROJECT_ROOT / "anthropic_key.txt").read_text().strip()


async def run_browser_task(task: str):
    browser = Browser(
        # use_cloud=True,  # Use a stealth browser on Browser Use Cloud
    )

    agent = Agent(
        task=task,
        # llm=ChatOpenAI(model="gpt-5.2"),
        llm=ChatGoogle(model="gemini-3-flash-preview"),
        browser=browser,
    )
    await agent.run()


def run_browser_task_sync(task: str):
    return asyncio.run(run_browser_task(task))
