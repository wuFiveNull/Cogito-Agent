from __future__ import annotations

from pydantic import BaseModel


class TurnBudget(BaseModel):
    max_model_calls: int = 1
    max_tool_calls: int = 2
    max_wall_time_seconds: int = 60
    max_input_tokens: int = 8192
    max_output_tokens: int = 4096

    def can_call_model(self, calls_made: int) -> bool:
        return calls_made < self.max_model_calls

    def can_call_tool(self, calls_made: int) -> bool:
        return calls_made < self.max_tool_calls
