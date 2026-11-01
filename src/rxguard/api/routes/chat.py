"""
Chatbot API routes.
Implements POST /api/v1/chat/message.
"""

from fastapi import APIRouter, Depends, HTTPException, status

from src.rxguard.api.dependencies import (
    get_chat_model,
    get_optional_current_user,
    get_profile_store,
    get_rag_service,
    get_safety_engine,
    per_ip_limit,
)
from src.rxguard.auth.jwt import TokenPayload
from src.rxguard.chatbot.orchestrator import (
    ChatbotOrchestrator,
    ChatMessageRequest,
    ChatMessageResponse,
)
from src.rxguard.rag.generator import GeminiChat
from src.rxguard.rag.service import RagService
from src.rxguard.safety.engine import SafetyEngine
from src.rxguard.users.context_guard import AccessDeniedError, ContextGuard
from src.rxguard.users.profile_store import ProfileStore

router = APIRouter(prefix="/chat", tags=["Clinical Chatbot"])


@router.post(
    "/message",
    response_model=ChatMessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit query to evidence-grounded clinical chatbot with user-context isolation",
    dependencies=[per_ip_limit("chat", "rate_limit_chat_per_minute")],
)
async def chat_message(
    request: ChatMessageRequest,
    current_user: TokenPayload | None = Depends(get_optional_current_user),
    profiles: ProfileStore = Depends(get_profile_store),
    safety_engine: SafetyEngine = Depends(get_safety_engine),
    rag: RagService = Depends(get_rag_service),
    chat: GeminiChat | None = Depends(get_chat_model),
) -> ChatMessageResponse:
    """
    Handles user chat query with context isolation, deterministic Layer C safety evaluation,
    and an answer from cited drug-label passages.
    """
    # If user is authenticated and didn't supply explicit context, load their profile context
    if current_user and not request.user_context:
        profile = await profiles.get(current_user.sub)
        if profile:
            try:
                ContextGuard.validate_access(current_user.sub, profile.user_id, current_user.roles)
            except AccessDeniedError as exc:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            request.user_context = profile

    # The app's shared engine, so findings from chat resolve in the evidence trail too.
    return await ChatbotOrchestrator(safety_engine, rag, chat).generate_response(request)
