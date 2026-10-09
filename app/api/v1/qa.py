"""知识问答API接口"""
from typing import Optional
from fastapi import APIRouter, Depends, Request, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.deps import get_current_user, get_current_tenant
from app.models.user import User
from app.core.security import Permission, has_permission, resolve_data_level
from app.schemas.common import APIResponse
from app.schemas.qa import QARequest, QAResponse
from app.services.qa_service import get_qa_service

router = APIRouter()


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "trace_id", None)


@router.post(
    "/qa/ask",
    response_model=APIResponse[QAResponse],
    summary="知识问答",
    description="基于知识库回答用户问题。需要member.query权限（普通党员及以上）。",
    tags=["知识问答"],
)
async def ask_question(
    request: Request,
    qa_request: QARequest,
    user: User = Depends(get_current_user),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> APIResponse[QAResponse]:
    """知识问答

    Args:
        request: 请求对象
        qa_request: 问答请求
        user: 当前用户
        tenant_id: 租户ID
        db: 数据库会话

    Returns:
        问答响应
    """
    # 权限检查：需要member.query权限
    if not has_permission(user.role, Permission.MEMBER_QUERY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="权限不足：需要member.query权限",
        )

    # 获取用户数据级别
    data_level = resolve_data_level(user.role)

    # 获取问答服务
    qa_service = get_qa_service()

    # 执行问答
    try:
        qa_response = await qa_service.answer(
            db=db,
            question=qa_request.question,
            tenant_id=tenant_id,
            data_level=data_level,
            user_role=user.role,
            session_id=qa_request.session_id,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"问答失败: {str(e)}",
        ) from e

    return APIResponse(
        data=qa_response,
        trace_id=_trace_id(request),
    )
