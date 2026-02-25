# ugsys-identity-manager

Identity & access management service for the ugsys platform.

## Running locally

```bash
just install-hooks
uv sync
uv run uvicorn src.main:app --reload
```

## Unit tests

```bash
uv run pytest tests/unit/ -v
```

## Smoke tests (against deployed API)

Requires AWS credentials with read access to DynamoDB (`ugsys-identity-manager-users-prod`).

```bash
IDENTITY_API_URL=https://nrhybmgg3j.execute-api.us-east-1.amazonaws.com \
AWS_PROFILE=awscbba \
uv run python scripts/smoke_test.py
```

The script covers the full register → verify-email → login → logout flow. It reads the
email verification token directly from DynamoDB since email delivery (omnichannel service)
is not yet built.

Each run creates a unique test user (`smoke+<run-id>@test.cbba.cloud.org.bo`) so it is
safe to run repeatedly without cleanup.
