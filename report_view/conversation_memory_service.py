from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .conversation_state import (
    ActiveQueryState,
    ConversationState,
    ConversationTurn,
    utc_now,
)
from .operational_memory_store import OperationalMemoryStore
from .report_logging import log_info, log_warning
from .result_models import QueryPlan, QueryResult


class ConversationMemoryService:
    def __init__(self, store: OperationalMemoryStore, max_turns: int = 12):
        self.store = store
        self.max_turns = max(4, int(max_turns))
        self._cache: Dict[str, ConversationState] = {}
        self._ensure_schema()

    def _ensure_schema(self):
        try:
            with self.store.connection() as connection:
                connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_state (
                        session_id TEXT PRIMARY KEY,
                        last_updated TEXT NOT NULL,
                        state_json TEXT NOT NULL DEFAULT '{}'
                    );
                    """
                )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao inicializar conversation_state "
                f"error={exc}"
            )

    def get_state(self, session_id: str) -> ConversationState:
        resolved_session = str(session_id or "").strip()
        if not resolved_session:
            return ConversationState(session_id="")
        cached = self._cache.get(resolved_session)
        if cached is not None:
            return ConversationState.from_payload(cached.to_payload(), session_id=resolved_session)
        try:
            with self.store.connection() as connection:
                row = connection.execute(
                    "SELECT state_json FROM conversation_state WHERE session_id = ?",
                    (resolved_session,),
                ).fetchone()
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao ler estado conversacional "
                f"session_id={resolved_session} error={exc}"
            )
            state = ConversationState(session_id=resolved_session)
            self._cache[resolved_session] = state
            return ConversationState.from_payload(state.to_payload(), session_id=resolved_session)

        if row is None:
            state = ConversationState(session_id=resolved_session)
            self._cache[resolved_session] = state
            return ConversationState.from_payload(state.to_payload(), session_id=resolved_session)

        payload = {}
        try:
            payload = json.loads(row["state_json"] or "{}")
        except Exception:
            payload = {}
        state = ConversationState.from_payload(payload, session_id=resolved_session)
        self._cache[resolved_session] = state
        return ConversationState.from_payload(state.to_payload(), session_id=resolved_session)

    def update_state(
        self,
        session_id: str,
        interpreted_query: Optional[QueryPlan],
        result: Optional[QueryResult],
        raw_query: str = "",
        normalized_query: str = "",
        merged_query: str = "",
        is_followup: bool = False,
        followup_type: str = "",
        delta: Optional[Dict[str, Any]] = None,
        debug: Optional[list] = None,
        success: bool = True,
        error_message: str = "",
        interpretation_status: str = "",
        confidence: float = 0.0,
        source: str = "",
    ) -> ConversationState:
        state = self.get_state(session_id)
        plan = interpreted_query
        turn = ConversationTurn(
            created_utc=utc_now(),
            raw_query=raw_query,
            normalized_query=normalized_query,
            merged_query=merged_query or normalized_query or raw_query,
            is_followup=bool(is_followup),
            followup_type=followup_type or "",
            delta=dict(delta or {}),
            interpretation_status=interpretation_status or ("ok" if success else "failed"),
            confidence=float(confidence or 0.0),
            plan_payload=plan.to_dict() if plan is not None else {},
            result_summary=(result.summary.text if result is not None and result.summary is not None else "") or "",
            success=bool(success),
            source=source or "",
            debug=list(debug or []),
            error_message=error_message or "",
        )
        state.append_turn(turn, max_turns=self.max_turns)
        if success and plan is not None:
            state.active_query = ActiveQueryState.from_plan(plan, confidence=confidence)
        state.last_updated = turn.created_utc
        self._persist_state(state)
        return ConversationState.from_payload(state.to_payload(), session_id=session_id)

    def clear_state(self, session_id: str):
        resolved_session = str(session_id or "").strip()
        if not resolved_session:
            return
        self._cache.pop(resolved_session, None)
        try:
            with self.store.connection() as connection:
                connection.execute(
                    "DELETE FROM conversation_state WHERE session_id = ?",
                    (resolved_session,),
                )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao limpar estado conversacional "
                f"session_id={resolved_session} error={exc}"
            )

    def merge_with_previous(
        self,
        session_id: str,
        new_input: str,
        delta: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        state = self.get_state(session_id)
        return {
            "conversation_state": state,
            "new_input": new_input,
            "delta": dict(delta or {}),
            "has_context": state.active_query is not None,
        }

    def _persist_state(self, state: ConversationState):
        payload = state.to_payload()
        try:
            with self.store.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO conversation_state(session_id, last_updated, state_json)
                    VALUES (?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        last_updated = excluded.last_updated,
                        state_json = excluded.state_json
                    """,
                    (
                        state.session_id,
                        state.last_updated or utc_now(),
                        json.dumps(payload, ensure_ascii=True),
                    ),
                )
            self._cache[state.session_id] = ConversationState.from_payload(payload, session_id=state.session_id)
            log_info(
                "[Relatorios] conversation "
                f"event=state_updated session_id={state.session_id} turns={len(state.turns)}"
            )
        except Exception as exc:
            log_warning(
                "[Relatorios] falha ao persistir estado conversacional "
                f"session_id={state.session_id} error={exc}"
            )
