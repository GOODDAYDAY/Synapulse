import logging

logger = logging.getLogger("synapulse.provider.mock")


async def chat(message: str) -> str:
    logger.debug("Mock chat called (length=%d)", len(message))
    return "mock hello"
