from src.agents.base import Agent


class FormatterAgent(Agent):
    def __init__(self) -> None:
        super().__init__("Formatter")

    async def execute(self, response: str, mode: str = "orientacao") -> str:
        """
        Passthrough: a formatação é governada pelo prompt do modelo, não por
        pós-processamento. Apenas remove espaços nas pontas.
        """
        self.logger.info(f"[{self.name}] Passthrough for mode: {mode}")

        if not response:
            return ""

        return response.strip()
