from typing import Any

from src.agents.base import Agent
from src.services.openai_service import OpenAIService


class ScopeValidatorAgent(Agent):
    def __init__(self, openai_service: OpenAIService):
        super().__init__("ScopeValidator")
        self.openai = openai_service

    async def execute(self, query: str, history_context: str = "") -> dict[str, Any]:
        """Validar se pergunta está dentro do escopo Digisac (considerando o histórico se houver)"""
        self.logger.info(
            "Scope validation started",
            extra={"extras": {"query_chars": len(query)}},
        )

        result = await self.openai.validate_scope(query, history_context)

        self.logger.info(
            "Scope validation completed",
            extra={"extras": {"in_scope": result.get("dentro_do_escopo", True)}},
        )
        return result
