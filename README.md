<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)"  srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/modern-di-grpc/lockup-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/modern-di-grpc/lockup-light.svg">
    <img alt="modern-di-grpc" src="https://raw.githubusercontent.com/modern-python/.github/main/brand/projects/modern-di-grpc/lockup.png" width="420">
  </picture>
</p>

[![PyPI version](https://img.shields.io/pypi/v/modern-di-grpc.svg)](https://pypi.org/project/modern-di-grpc/)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/modern-di-grpc.svg)](https://pypi.org/project/modern-di-grpc/)
[![Downloads](https://static.pepy.tech/badge/modern-di-grpc/month)](https://pepy.tech/projects/modern-di-grpc)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen.svg)](https://github.com/modern-python/modern-di-grpc/actions/workflows/ci.yml)
[![CI](https://github.com/modern-python/modern-di-grpc/actions/workflows/ci.yml/badge.svg)](https://github.com/modern-python/modern-di-grpc/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/modern-python/modern-di-grpc.svg)](https://github.com/modern-python/modern-di-grpc/blob/main/LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/modern-python/modern-di-grpc)](https://github.com/modern-python/modern-di-grpc/stargazers)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

[Modern-DI](https://github.com/modern-python/modern-di) integration for [gRPC](https://grpc.io) (`grpcio`).

Full guide: [gRPC integration docs](https://modern-di.modern-python.org/integrations/grpc/)

## Installation

```bash
uv add modern-di-grpc      # or: pip install modern-di-grpc
```

## Usage

gRPC has no dependency-injection system of its own, so `modern-di-grpc` pairs an `@inject` decorator with inert `FromDI` markers. A `DIInterceptor` (sync) or `DIAioInterceptor` (async) opens one `Scope.REQUEST` child container per RPC and resolves the `FromDI`-marked parameters of `@inject`-decorated servicer methods. Constructing the interceptor registers the `ServicerContext` provider on the container automatically — there is no separate setup call.

```python
import typing
from concurrent import futures

import grpc
from modern_di import Container, Group, Scope, providers
from modern_di_grpc import DIInterceptor, FromDI, inject

from myapp import greeter_pb2, greeter_pb2_grpc   # your generated stubs


class Settings:
    def __init__(self) -> None:
        self.greeting = "hello"


class Greeter:
    def __init__(self, settings: Settings) -> None:   # auto-injected by type
        self._settings = settings

    def greet(self, name: str) -> str:
        return f"{self._settings.greeting}, {name}"


class AppGroup(Group):
    settings = providers.Factory(Settings, scope=Scope.APP, cache=True)
    greeter = providers.Factory(Greeter, scope=Scope.REQUEST)


class GreeterService(greeter_pb2_grpc.GreeterServicer):
    @inject
    def SayHello(
        self,
        request: greeter_pb2.HelloRequest,
        context: grpc.ServicerContext,
        greeter: typing.Annotated[Greeter, FromDI(Greeter)],   # resolve by type
    ) -> greeter_pb2.HelloReply:
        return greeter_pb2.HelloReply(message=greeter.greet(request.name))


container = Container(groups=[AppGroup], validate=True)
container.open()  # or: with container: ... — required under modern-di 3.x's mandatory-open lifecycle
server = grpc.server(
    futures.ThreadPoolExecutor(max_workers=10),
    interceptors=[DIInterceptor(container)],
)
greeter_pb2_grpc.add_GreeterServicer_to_server(GreeterService(), server)
server.add_insecure_port("[::]:50051")
server.start()
server.wait_for_termination()
container.close_sync()
```

For an async server, pass `DIAioInterceptor(container)` to `grpc.aio.server(...)` and write `async def` servicer methods; `@inject` adapts to sync, async, and async-generator (server-streaming) methods across all four RPC types. gRPC has no server startup/shutdown hook, so the root container's lifecycle is yours to own end-to-end: call `.open()` (or use `with`/`async with`) *before* constructing the interceptor and serving traffic — required under modern-di 3.x's mandatory-open lifecycle, since `DIInterceptor`/`DIAioInterceptor` never open the root themselves — and call `close_sync()` (or `await close_async()` on `grpc.aio`) after the server stops.

## API

| Symbol | Description |
|---|---|
| `DIInterceptor(container)` | `grpc.ServerInterceptor` for the sync thread-pool server. Opens a `Scope.REQUEST` child per RPC (`close_sync`); auto-registers `grpc_context_provider` |
| `DIAioInterceptor(container)` | `grpc.aio.ServerInterceptor` for the async server. Same, with `close_async` |
| `FromDI(dependency)` | Inert marker for `Annotated[T, FromDI(...)]` in servicer-method signatures; accepts a provider instance or a type |
| `inject(method)` | Decorates a servicer method to resolve its `FromDI` parameters from the current RPC's child container; adapts to sync / async / async-generator methods |
| `fetch_di_container()` | Returns the current RPC's child container (raises `LookupError` outside an RPC) |
| `grpc_context_provider` | `ContextProvider` exposing `grpc.ServicerContext` at `Scope.REQUEST`; auto-registered by the interceptor |

## 📦 [PyPI](https://pypi.org/project/modern-di-grpc)

## 📝 [License](LICENSE)

## Part of `modern-python`

Built on [`modern-di`](https://github.com/modern-python/modern-di), a dependency-injection framework with IoC container and scopes.

Browse the full list of templates and libraries in
[`modern-python`](https://github.com/modern-python) — see the org profile for the categorized index.
