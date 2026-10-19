from src.logger import get_logger

logger = get_logger(__name__)


class Agent:
    def __init__(self, name: str):
        self.name = name
        self.logger = logger
