"""Integration test fixtures — moto-backed DynamoDB tables."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import bcrypt as _bcrypt_lib
import boto3
import httpx
import pytest
from moto import mock_aws

from src.infrastructure.persistence.dynamodb_token_blacklist import (
    DynamoDBTokenBlacklistRepository,
)
from src.infrastructure.persistence.dynamodb_user_repository import DynamoDBUserRepository

_USERS_TABLE = "ugsys-identity-manager-users-test"
_BLACKLIST_TABLE = "ugsys-identity-test-token-blacklist"
_JWT_SECRET = "test-secret-key-for-integration-tests"
_JWT_ALGORITHM = "HS256"


def _create_tables(region: str = "us-east-1") -> None:
    """Create both DynamoDB tables in the active moto context."""
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


@pytest.fixture(autouse=True)
def reset_rate_limiter() -> None:
    """Clear the in-memory rate limiter between tests to prevent state leakage."""
    from src.presentation.middleware.rate_limiting import _request_log

    _request_log.clear()


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
    return DynamoDBUserRepository(table_name=users_table_name, region="us-east-1")


@pytest.fixture()
def blacklist_repo(
    dynamodb_tables: object,
    blacklist_table_name: str,
) -> DynamoDBTokenBlacklistRepository:
    return DynamoDBTokenBlacklistRepository(table_name=blacklist_table_name, region="us-east-1")


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
        user_repo = DynamoDBUserRepository(table_name=_USERS_TABLE, region="us-east-1")
        blacklist_repo = DynamoDBTokenBlacklistRepository(
            table_name=_BLACKLIST_TABLE, region="us-east-1"
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
