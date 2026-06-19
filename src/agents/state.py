"""Shared LangGraph state definition for The Gatekeeper graph."""
from typing import Optional, TypedDict

from src.providers.base import EmailMessage


class GatekeeperState(TypedDict):
    """State threaded through every node in the Gatekeeper LangGraph.

    Fields
    ------
    current_email : The email being processed in this graph thread.
    extracted_metadata : Triage output: category + reasoning.
    project_context : Formatted thread history fetched by researcher node.
    generated_draft : Draft reply text produced by the drafter node.
    is_approved : True once the human approves the draft in the UI.
    user_modifications : Optional edited reply text supplied by the human.
    rejection_reason : Free-text reason if the human rejects the draft.
    """

    current_email: Optional[EmailMessage]
    extracted_metadata: dict
    project_context: Optional[str]
    generated_draft: Optional[str]
    is_approved: bool
    user_modifications: Optional[str]
    rejection_reason: Optional[str]
