from apps.bot.config.settings import config
from apps.bot.config.logging import setup_logging

setup_logging(config.LOG_LEVEL)


def main():
    from apps.bot.core.handler import start

    start()


if __name__ == "__main__":
    main()
