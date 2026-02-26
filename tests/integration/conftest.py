"""Integration test fixtures — moto-backed DynamoDB tables."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import aioboto3
import bcrypt as _bcrypt_lib
import boto3
import httpx
import pytest
from botocore.awsrequest import AWSResponse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from moto import mock_aws

# ── aiobotocore + moto compatibility patch ────────────────────────────────────
# aiobotocore awaits `http_response.content`, but moto's AWSResponse.content is
# a synchronous property returning bytes.  We replace it with an AwaitableBytes
# wrapper that behaves like bytes for sync callers AND is awaitable for async
# callers (aiobotocore does `await http_response.content`).
_original_content_fget = AWSResponse.content.fget  # type: ignore[union-attr]


class _AwaitableBytes(bytes):
    """bytes subclass that is also awaitable — returns itself when awaited."""

    def __await__(self):  # type: ignore[override]
        yield  # makes it a generator-based coroutine
        return self


def _awaitable_content(self: AWSResponse) -> _AwaitableBytes:
    raw: bytes = _original_content_fget(self)  # type: ignore[misc]
    return _AwaitableBytes(raw)


AWSResponse.content = property(_awaitable_content)  # type: ignore[assignment]
# ─────────────────────────────────────────────────────────────────────────────

from src.infrastructure.persistence.dynamodb_token_blacklist import (  # noqa: E402
    DynamoDBTokenBlacklistRepository,
)
from src.infrastructure.persistence.dynamodb_user_repository import (  # noqa: E402
    DynamoDBUserRepository,
)

_USERS_TABLE = "ugsys-identity-manager-users-test"
_BLACKLIST_TABLE = "ugsys-identity-test-token-blacklist"
_EVENT_BUS = "ugsys-platform-events-test"
_JWT_ALGORITHM = "RS256"

# ── Test RSA key pair (generated once at module load, reused across all tests) ─
_TEST_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_JWT_PRIVATE_KEY_PEM = _TEST_RSA_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_JWT_PUBLIC_KEY_PEM = (
    _TEST_RSA_KEY.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)
# JWTTokenService uses `secret_key` for both sign (private) and verify (public).
# For RS256, jose uses the private key to sign and the public key to verify.
# We pass the private key as `secret_key` so the service can both sign and verify.
_JWT_SECRET = _JWT_PRIVATE_KEY_PEM


def _create_tables(region: str = "us-east-1") -> None:
    """Create both DynamoDB tables in the active moto context using sync boto3."""
    dynamodb = boto3.resource("dynamodb", region_name=region)

    dynamodb.create_table(
        TableName=_USERS_TABLE,
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
            {"AttributeName": "email", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "email-index",
                "KeySchema": [{"AttributeName": "email", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )

    dynamodb.create_table(
        TableName=_BLACKLIST_TABLE,
        KeySchema=[{"AttributeName": "jti", "KeyType": "HASH"}],
        AttributeDefinitions=[{"AttributeName": "jti", "AttributeType": "S"}],
        BillingMode="PAY_PER_REQUEST",
    )
    boto3.client("dynamodb", region_name=region).update_time_to_live(
        TableName=_BLACKLIST_TABLE,
        TimeToLiveSpecification={"Enabled": True, "AttributeName": "ttl"},
    )
    # Create the EventBridge custom bus so put_events calls succeed in moto
    boto3.client("events", region_name=region).create_event_bus(Name=_EVENT_BUS)


def _make_aioboto3_session() -> aioboto3.Session:
    """Return an aioboto3 Session — moto intercepts its calls when mock_aws is active."""
    return aioboto3.Session()


def _reset_rate_limit_counters() -> None:
    """Walk the middleware stack (if built) and clear all RateLimitMiddleware counters."""
    from collections import defaultdict

    import src.presentation.middleware.rate_limiting as rl_module
    from src.main import app
    from src.presentation.middleware.rate_limiting import RateLimitMiddleware

    # Clear legacy stub
    rl_module._request_log.clear()

    def _walk(node: object) -> None:
        if isinstance(node, RateLimitMiddleware):
            node._counters = defaultdict(list)
        inner = getattr(node, "app", None)
        if inner is not None and inner is not node:
            _walk(inner)

    # Walk both the raw app and the built middleware stack (built lazily on first request)
    _walk(app)
    stack = getattr(app, "middleware_stack", None)
    if stack is not None:
        _walk(stack)


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Reset rate limiter counters before AND after each test to prevent state leakage."""
    _reset_rate_limit_counters()
    yield  # type: ignore[misc]
    _reset_rate_limit_counters()


@pytest.fixture()
def aws_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject fake AWS credentials so moto intercepts all boto3 calls."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")


@pytest.fixture()
def users_table_name() -> str:
    return _USERS_TABLE


@pytest.fixture()
def blacklist_table_name() -> str:
    return _BLACKLIST_TABLE


@pytest.fixture()
def dynamodb_tables(
    aws_credentials: None,
    users_table_name: str,
    blacklist_table_name: str,
) -> object:
    """Create both DynamoDB tables inside a moto mock context and yield."""
    with mock_aws():
        _create_tables()
        yield  # keeps the mock context alive


@pytest.fixture()
def user_repo(dynamodb_tables: object, users_table_name: str) -> DynamoDBUserRepository:
    return DynamoDBUserRepository(
        table_name=users_table_name,
        region="us-east-1",
        session=_make_aioboto3_session(),
    )


@pytest.fixture()
def blacklist_repo(
    dynamodb_tables: object,
    blacklist_table_name: str,
) -> DynamoDBTokenBlacklistRepository:
    return DynamoDBTokenBlacklistRepository(
        table_name=blacklist_table_name,
        region="us-east-1",
        session=_make_aioboto3_session(),
    )


@pytest.fixture()
async def app_client(monkeypatch: pytest.MonkeyPatch) -> AsyncGenerator[httpx.AsyncClient]:
    """
    Full-stack HTTP test client: moto DynamoDB + FastAPI app wired via dependency_overrides.

    Bypasses the ASGI lifespan entirely — builds all services directly from test config
    and injects them via app.dependency_overrides.  The mock_aws context keeps all
    boto3 calls intercepted for the duration of the test.
    """
    # Fake AWS credentials so boto3 doesn't hit real AWS
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")

    with mock_aws():
        _create_tables()

        # Import dependency keys and the module-level app
        from src.application.services.auth_service import AuthService
        from src.application.services.user_service import UserService
        from src.domain.value_objects.password_validator import PasswordValidator
        from src.infrastructure.adapters.jwt_token_service import JWTTokenService
        from src.infrastructure.messaging.event_publisher import EventBridgePublisher
        from src.main import app
        from src.presentation.api.v1.auth import get_auth_service
        from src.presentation.api.v1.roles import get_token_service as get_roles_token_service
        from src.presentation.api.v1.users import get_token_service, get_user_service

        # Build infrastructure adapters pointed at the moto tables
        session = _make_aioboto3_session()
        user_repo = DynamoDBUserRepository(
            table_name=_USERS_TABLE, region="us-east-1", session=session
        )
        blacklist_repo = DynamoDBTokenBlacklistRepository(
            table_name=_BLACKLIST_TABLE, region="us-east-1", session=session
        )
        token_service = JWTTokenService(
            secret_key=_JWT_SECRET,
            algorithm=_JWT_ALGORITHM,
            token_blacklist=blacklist_repo,
        )
        event_publisher = EventBridgePublisher(
            bus_name="ugsys-platform-events-test",
            region="us-east-1",
        )

        class _BcryptHasher:
            def hash(self, password: str) -> str:
                return _bcrypt_lib.hashpw(password.encode("utf-8"), _bcrypt_lib.gensalt()).decode(
                    "utf-8"
                )

            def verify(self, plain: str, hashed: str) -> bool:
                return bool(_bcrypt_lib.checkpw(plain.encode("utf-8"), hashed.encode("utf-8")))

        auth_service = AuthService(
            user_repo=user_repo,
            token_service=token_service,
            password_hasher=_BcryptHasher(),
            token_blacklist=blacklist_repo,
            password_validator=PasswordValidator(),
            event_publisher=event_publisher,
        )
        user_service = UserService(user_repo=user_repo, event_publisher=event_publisher)

        # Wire overrides directly — no lifespan needed
        app.dependency_overrides[get_auth_service] = lambda: auth_service
        app.dependency_overrides[get_user_service] = lambda: user_service
        app.dependency_overrides[get_token_service] = lambda: token_service
        app.dependency_overrides[get_roles_token_service] = lambda: token_service

        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                yield client
        finally:
            # Restore overrides so other tests aren't affected
            app.dependency_overrides.pop(get_auth_service, None)
            app.dependency_overrides.pop(get_user_service, None)
            app.dependency_overrides.pop(get_token_service, None)
            app.dependency_overrides.pop(get_roles_token_service, None)
