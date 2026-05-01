"""
examples/demo_scenario.py
==========================
演示场景：JWT → OAuth2 + PKCE 认证系统重构分析。

运行方式：
  python examples/demo_scenario.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import GitDiffEvent
from core.coordinator import ArchitectCoordinator

DEMO_DIFF = "\n".join([
    "diff --git a/auth/jwt_handler.py b/auth/oauth2_handler.py",
    "rename from auth/jwt_handler.py",
    "rename to auth/oauth2_handler.py",
    "--- a/auth/jwt_handler.py",
    "+++ b/auth/oauth2_handler.py",
    "@@ -1,20 +1,40 @@",
    "-# JWT 认证处理器（旧版）",
    "-import jwt",
    "-SECRET_KEY = os.environ.get('JWT_SECRET', 'fallback-secret')",
    "-ALGORITHM = 'HS256'",
    "-def create_access_token(user_id: str, expires_delta: int = 3600) -> str:",
    "-    payload = {'sub': user_id}",
    "-    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)",
    "+# OAuth2 + PKCE 认证处理器（符合 RFC 7636）",
    "+import secrets, hashlib, base64",
    "+from cryptography.fernet import Fernet",
    "+from redis import asyncio as aioredis",
    "+class OAuth2PKCEHandler:",
    "+    def __init__(self, redis_url: str, client_id: str, client_secret: str):",
    "+        self.redis_url = redis_url",
    "+        self._cipher = Fernet(Fernet.generate_key())",
    "+    def generate_pkce_challenge(self) -> dict:",
    "+        code_verifier = secrets.token_urlsafe(64)",
    "+        digest = hashlib.sha256(code_verifier.encode()).digest()",
    "+        code_challenge = base64.urlsafe_b64encode(digest).rstrip(b'=').decode()",
    "+        return {'code_verifier': code_verifier, 'code_challenge': code_challenge}",
    "+    async def exchange_code_for_token(self, code, code_verifier, redirect_uri):",
    "+        async with aioredis.from_url(self.redis_url) as redis:",
    "+            stored = await redis.get(f'pkce:{code}')",
    "+            if not stored or stored.decode() != code_verifier:",
    "+                raise ValueError('PKCE 验证失败：code_verifier 不匹配')",
    "+            await redis.delete(f'pkce:{code}')",
    "+        return {'access_token': secrets.token_urlsafe(48), 'token_type': 'Bearer'}",
    "",
    "diff --git a/models/user.py b/models/user.py",
    "--- a/models/user.py",
    "+++ b/models/user.py",
    "@@ -10,8 +10,12 @@ class User(Base):",
    "     id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)",
    "     email = Column(String(255), unique=True, nullable=False, index=True)",
    "-    username = Column(String(64), unique=True, nullable=False, index=True)",
    "-    password_hash = Column(String(255), nullable=False)",
    "+    # BREAKING CHANGE: 移除 username 和 password_hash，认证完全委托给 OAuth2",
    "+    oauth2_provider = Column(String(50), nullable=False)",
    "+    oauth2_subject = Column(String(255), nullable=False)",
    "+    oauth2_tokens_encrypted = Column(Text, nullable=True)",
    "+    is_active = Column(Boolean, default=True, nullable=False)",
    "",
    "diff --git a/api/v1/auth_router.py b/api/v1/auth_router.py",
    "--- a/api/v1/auth_router.py",
    "+++ b/api/v1/auth_router.py",
    "@@ -1,10 +1,25 @@",
    "-@router.post('/auth/login')",
    "-async def login(username: str, password: str):",
    "-    user = db.query(User).filter(User.username == username).first()",
    "-    return {'access_token': create_access_token(user.id)}",
    "+@router.get('/auth/oauth2/authorize')",
    "+async def oauth2_authorize(client_id, redirect_uri, code_challenge, state):",
    "+    if code_challenge is None:",
    "+        raise HTTPException(400, 'PKCE code_challenge is required')",
    "+    return RedirectResponse(build_authorization_url(client_id, redirect_uri, code_challenge, state))",
    "+@router.post('/auth/oauth2/token')",
    "+async def oauth2_token_exchange(code, code_verifier, redirect_uri):",
    "+    handler = OAuth2PKCEHandler(settings.REDIS_URL, settings.CLIENT_ID, settings.CLIENT_SECRET)",
    "+    token = await handler.exchange_code_for_token(code, code_verifier, redirect_uri)",
    "+    if not token:",
    "+        raise HTTPException(status_code=400, detail='Token 交换失败')",
    "+    return token",
])

DEMO_EVENT = GitDiffEvent(
    repo_name="myapp/backend-api",
    commit_hash="a3f9c2d",
    author="zhang.wei@company.com",
    commit_message="refactor(auth): 将认证系统从 JWT 迁移至 OAuth2 + PKCE，重构用户模型",
    changed_files=[
        "auth/jwt_handler.py -> auth/oauth2_handler.py",
        "models/user.py",
        "api/v1/auth_router.py",
        "migrations/0024_remove_password_add_oauth2.py",
        "tests/test_auth.py",
    ],
    diff_content=DEMO_DIFF,
    tags=["breaking-change", "security", "authentication"],
)


async def run_demo():
    """运行完整的演示流水线。"""
    print("\n" + "🚀 " * 20)
    print("  Claude Architect Agent — 演示场景")
    print("  场景: JWT → OAuth2 + PKCE 认证系统重构")
    print("🚀 " * 20)

    coordinator = ArchitectCoordinator()

    try:
        final_report = await coordinator.process(DEMO_EVENT)

        output_path = "demo_analysis_report.md"
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(final_report)

        print(f"\n✅ 分析报告已保存至: {output_path}")
        print("\n" + "─" * 60)
        print("  报告预览（前 600 字符）：")
        print("─" * 60)
        print(final_report[:600])
        print("...")

    except Exception as exc:
        print(f"\n❌ 演示运行失败: {exc}")
        raise


if __name__ == "__main__":
    asyncio.run(run_demo())
