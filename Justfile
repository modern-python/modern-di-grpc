default: install lint test

install:
    uv lock --upgrade
    uv sync --all-extras --frozen --group lint

lint:
    uv run eof-fixer .
    uv run ruff format
    uv run ruff check --fix
    uv run ty check

lint-ci:
    uv run eof-fixer . --check
    uv run ruff format --check
    uv run ruff check --no-fix
    uv run ty check
    uv run python planning/index.py --check

# Regenerate gRPC test stubs from the .proto (committed under tests/protos/).
# protoc emits a bare `import greeter_pb2`, which only resolves as a top-level
# module; rewrite it to a package-relative import so the stubs import cleanly
# as tests.protos.greeter_pb2_grpc.
proto:
    uv run python -m grpc_tools.protoc -Itests/protos --python_out=tests/protos --grpc_python_out=tests/protos tests/protos/greeter.proto
    sed -i.bak 's/^import greeter_pb2 as greeter__pb2$/from tests.protos import greeter_pb2 as greeter__pb2/' tests/protos/greeter_pb2_grpc.py
    rm -f tests/protos/greeter_pb2_grpc.py.bak

# Print the planning change index (flat, newest-first) to stdout.
index:
    uv run python planning/index.py

# Validate planning changes + decisions; CI runs this.
check-planning:
    uv run python planning/index.py --check

test *args:
    uv run --no-sync pytest {{ args }}

test-ci:
    uv run --no-sync pytest --cov=. --cov-report term-missing --cov-report xml --cov-fail-under=100

test-branch:
    uv run --no-sync pytest --cov=. --cov-branch --cov-fail-under=100

# Auth via PyPI Trusted Publishing (OIDC); uv publish auto-detects the CI id-token.
publish:
    rm -rf dist
    uv version $GITHUB_REF_NAME
    uv build
    uv publish
