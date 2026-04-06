import copy
from dataclasses import dataclass
from typing import Dict, List, Optional

from .result_models import QueryPlan, QueryResult


@dataclass
class ReportContextTurn:
    question: str
    plan: QueryPlan
    summary: str = ""
    chart_type: str = "auto"
    understanding: str = ""


class ReportContextMemory:
    def __init__(self, max_turns: int = 4):
        self.max_turns = max(1, int(max_turns))
        self._turns: List[ReportContextTurn] = []

    def clear(self):
        self._turns = []

    def remember_result(self, question: str, plan: QueryPlan, result: QueryResult):
        turn = ReportContextTurn(
            question=question,
            plan=copy.deepcopy(plan),
            summary=(result.summary.text or "").strip(),
            chart_type=(plan.chart.type or "auto"),
            understanding=(plan.understanding_text or "").strip(),
        )
        self._turns.append(turn)
        if len(self._turns) > self.max_turns:
            self._turns = self._turns[-self.max_turns :]

    def last_plan(self) -> Optional[QueryPlan]:
        turn = self.last_turn()
        return copy.deepcopy(turn.plan) if turn is not None else None

    def last_turn(self) -> Optional[ReportContextTurn]:
        return self._turns[-1] if self._turns else None

    def build_prompt_context(self) -> Dict:
        last_turn = self.last_turn()
        if last_turn is None:
            return {}
        return {
            "last_question": last_turn.question,
            "last_summary": last_turn.summary,
            "last_chart_type": last_turn.chart_type,
            "last_understanding": last_turn.understanding,
            "last_target_layer": last_turn.plan.target_layer_name,
            "last_metric": last_turn.plan.metric.to_dict(),
            "last_group_field": last_turn.plan.group_field,
            "last_filters": [item.to_dict() for item in last_turn.plan.filters],
            "last_plan": last_turn.plan.to_dict(),
        }
