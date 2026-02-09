import asyncio

from apps.bot.config.logging import setup_logging
from apps.bot.config.settings import config

setup_logging(config.LOG_LEVEL)


def main():
    from apps.bot.core.handler import start

    asyncio.run(start())


if __name__ == "__main__":
    main()
