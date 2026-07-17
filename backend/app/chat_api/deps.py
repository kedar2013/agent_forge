from fastapi import Depends, HTTPException, status

from app.principal import Principal, get_current_principal

# Viewer is deliberately excluded here — chat sends real messages through a
# real LLM (cost + audit implications), so it's not a "read-only" action.
# developer gets chat access too, both to dogfood agents they're building and
# because it's an explicit part of the developer role's scope.
_CHAT_ROLES = ("admin", "chat_user", "developer")


async def require_chat_access(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.role not in _CHAT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account not approved for chat")
    return principal
