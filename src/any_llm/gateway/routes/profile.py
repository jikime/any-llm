from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from any_llm.gateway.auth import verify_jwt_or_api_key_or_master
from any_llm.gateway.db import APIKey, Budget, CaretUser, UsageLog, User, get_db

router = APIRouter(prefix="/v1/profile", tags=["profile"])


class BudgetInfo(BaseModel):
    """예산 정보."""

    budget_id: str | None
    max_budget: float | None
    budget_duration_sec: int | None
    spend: float
    budget_started_at: str | None
    next_budget_reset_at: str | None


class ProfileInfo(BaseModel):
    """사용자/소셜 통합 프로필."""

    user_id: str
    provider: str | None
    provider_user_id: str | None
    alias: str | None
    name: str | None
    email: str | None
    avatar_url: str | None
    blocked: bool
    metadata: dict
    caret_metadata: dict
    last_login_at: str | None


class UsageWindow(BaseModel):
    """기간별 사용량 합계."""

    requests: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float


class UsageLogItem(BaseModel):
    """최근 사용 로그 일부."""

    id: str
    timestamp: str
    model: str
    provider: str | None
    endpoint: str
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    cost: float | None
    status: str
    error_message: str | None


class ProfileResponse(BaseModel):
    """프로필 응답."""

    profile: ProfileInfo
    budget: BudgetInfo | None
    usage: dict[str, UsageWindow]
    recent_usage: list[UsageLogItem]


def _now_naive() -> datetime:
    """UTC now without tzinfo (DB 저장 방식과 동일)."""
    return datetime.now(UTC).replace(tzinfo=None)


def _aggregate_usage(db: Session, user_id: str, since: datetime) -> UsageWindow:
    """기간별 사용량 합계."""
    requests_count, prompt_sum, completion_sum, total_sum, cost_sum = (
        db.query(
            func.count(UsageLog.id),
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0),
            func.coalesce(func.sum(UsageLog.total_tokens), 0),
            func.coalesce(func.sum(UsageLog.cost), 0.0),
        )
        .filter(UsageLog.user_id == user_id, UsageLog.timestamp >= since)
        .one()
    )

    return UsageWindow(
        requests=int(requests_count),
        prompt_tokens=int(prompt_sum or 0),
        completion_tokens=int(completion_sum or 0),
        total_tokens=int(total_sum or 0),
        cost=float(cost_sum or 0.0),
    )


def _recent_usage(db: Session, user_id: str, limit: int) -> list[UsageLogItem]:
    """최근 사용 로그."""
    logs = (
        db.query(UsageLog)
        .filter(UsageLog.user_id == user_id)
        .order_by(UsageLog.timestamp.desc())
        .limit(limit)
        .all()
    )
    return [
        UsageLogItem(
            id=log.id,
            timestamp=log.timestamp.isoformat(),
            model=log.model,
            provider=log.provider,
            endpoint=log.endpoint,
            prompt_tokens=log.prompt_tokens,
            completion_tokens=log.completion_tokens,
            total_tokens=log.total_tokens,
            cost=log.cost,
            status=log.status,
            error_message=log.error_message,
        )
        for log in logs
    ]


@router.get("")
async def get_profile(
    auth_result: Annotated[tuple[APIKey | None, bool, str | None], Depends(verify_jwt_or_api_key_or_master)],
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[str | None, Query(default=None, description="마스터 키 사용 시 조회할 user_id")],
    recent_limit: Annotated[int, Query(default=10, ge=0, le=100, description="최근 사용 로그 개수")],
) -> ProfileResponse:
    """프로필 + 예산 + 사용량 집계 반환."""
    api_key, is_master, resolved_user_id = auth_result

    # 마스터 키일 때는 user 파라미터 필수
    target_user_id: str
    if is_master:
        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="When using master key, 'user' query parameter is required",
            )
        target_user_id = user
    else:
        target_user_id = resolved_user_id or (api_key.user_id if api_key else None)  # type: ignore[attr-defined]
        if not target_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not resolved")

    user_obj = db.query(User).filter(User.user_id == target_user_id).first()
    if not user_obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"User '{target_user_id}' not found")

    caret = db.query(CaretUser).filter(CaretUser.user_id == target_user_id).first()
    budget = db.query(Budget).filter(Budget.budget_id == user_obj.budget_id).first() if user_obj.budget_id else None

    now = _now_naive()
    usage_windows = {
        "last_24h": _aggregate_usage(db, target_user_id, now - timedelta(hours=24)),
        "last_7d": _aggregate_usage(db, target_user_id, now - timedelta(days=7)),
        "last_30d": _aggregate_usage(db, target_user_id, now - timedelta(days=30)),
    }

    recent_logs = _recent_usage(db, target_user_id, recent_limit)

    profile = ProfileInfo(
        user_id=user_obj.user_id,
        provider=caret.provider if caret else None,
        provider_user_id=caret.provider_user_id if caret else None,
        alias=user_obj.alias,
        name=caret.name if caret else user_obj.alias,
        email=caret.email if caret else None,
        avatar_url=caret.avatar_url if caret else None,
        blocked=bool(user_obj.blocked),
        metadata=dict(user_obj.metadata_) if user_obj.metadata_ else {},
        caret_metadata=dict(caret.metadata_) if caret and caret.metadata_ else {},
        last_login_at=caret.last_login_at.isoformat() if caret and caret.last_login_at else None,
    )

    budget_info = (
        BudgetInfo(
            budget_id=budget.budget_id,
            max_budget=budget.max_budget,
            budget_duration_sec=budget.budget_duration_sec,
            spend=float(user_obj.spend),
            budget_started_at=user_obj.budget_started_at.isoformat() if user_obj.budget_started_at else None,
            next_budget_reset_at=user_obj.next_budget_reset_at.isoformat() if user_obj.next_budget_reset_at else None,
        )
        if budget
        else None
    )

    return ProfileResponse(
        profile=profile,
        budget=budget_info,
        usage=usage_windows,
        recent_usage=recent_logs,
    )
