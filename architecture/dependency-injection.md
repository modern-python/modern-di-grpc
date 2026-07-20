# Dependency injection

The capability this package exists for: wiring a `modern-di` `Container` into
a gRPC server so servicer-method parameters resolve from it, scoped per RPC
call. Everything lives in `modern_di_grpc/main.py`; the public surface is
`DIInterceptor`, `DIAioInterceptor`, `FromDI`, `inject`, `fetch_di_container`,
and `grpc_context_provider`.

gRPC's idiomatic extension point is a `ServerInterceptor`, so this integration
follows modern-di's **interceptor + decorator** shape (like
`modern-di-starlette`/`-faststream`): the interceptor owns the per-RPC child
container, `@inject` resolves parameters from it. There is no `setup_di`-style
entry point — constructing `DIInterceptor(container)` / `DIAioInterceptor(container)`
and passing it to `grpc.server(..., interceptors=[...])` / `grpc.aio.server(...)`
*is* the setup.

## The interceptor mechanism

`DIInterceptor` (sync, `grpc.ServerInterceptor`) and `DIAioInterceptor` (async,
`grpc.aio.ServerInterceptor`) both take the root container in `__init__` and
implement `intercept_service`:

1. Call `continuation(handler_call_details)` to get the original
   `grpc.RpcMethodHandler`. `DIAioInterceptor` awaits it.
2. If the result is `None` — no servicer registered the method — return `None`
   unchanged; gRPC answers `UNIMPLEMENTED` on its own. Nothing is wrapped.
3. Otherwise re-wrap it via `_rewrap`, which reads whichever of the handler's
   four behavior slots is set (`unary_unary`, `unary_stream`, `stream_unary`,
   `stream_stream` — exactly one, per gRPC's contract) and rebuilds the handler
   with the matching `grpc.*_rpc_method_handler` factory, carrying over the
   original `request_deserializer`/`response_serializer` and substituting a
   wrapped behavior.

`_rewrap` is shared by both interceptors; each passes in its own sync or async
behavior builders. Response-unary handlers (`unary_unary`, `stream_unary`) use
the "unary" builder; response-streaming handlers (`unary_stream`,
`stream_stream`) use the "stream" builder — the split is on the *response*
shape, not the request shape, because a client-streaming RPC still returns one
message.

## Per-RPC scope

**Every RPC call opens one `Scope.REQUEST` child container** — one RPC is one
unit of work, uniform across all four RPC types (unary-unary, unary-stream,
stream-unary, stream-stream). `_build_child(container, context)` derives the
child's scope and context via `modern_di.integrations.bind(grpc_context_provider,
context)` — `bind(provider, connection)` returns
`ConnectionMatch(scope=provider.scope, context={provider.context_type:
connection})`, so this always produces `scope=Scope.REQUEST,
context={ServicerContext: context}`, the same values the code used to
hand-write via a separate post-hoc `child.set_context(...)` call — then
builds the child via `container.build_child_container(scope=match.scope,
context=match.context)` in one step, and opens it immediately with
`child.open()` — required under modern-di 3.x's mandatory-open lifecycle,
since `build_child_container`/`open` happen here while the *close* happens
later in the wrapper's own `finally` (see below), with no enclosing `with`
block spanning both. gRPC has no second connection provider to distinguish,
so there is nothing for `classify_connection` (which dispatches across
several providers) to dispatch across here.

Each of the four wrapper builders (`_wrap_unary_sync`, `_wrap_stream_sync`,
`_wrap_unary_aio`, `_wrap_stream_aio`) follows the same shape:

1. Build the child, `_request_container.set(child)`, keeping the `Token`.
2. Run the original behavior.
3. In `finally`, close the child (`close_sync`/`close_async`) inside a
   **nested** `finally` that resets the ContextVar. The nesting matters: if
   `close_sync`/`close_async` raises (a finalizer error), the ContextVar is
   still reset before the exception propagates, so a failed close never leaves
   a stale child visible to a later RPC reusing the same thread/task.

Response-unary wrappers (`_wrap_unary_sync`, `_wrap_unary_aio`) `return`
(`await`) the behavior's result inside that `try/finally`. Response-streaming
wrappers (`_wrap_stream_sync`, `_wrap_stream_aio`) are themselves a generator
or async generator — `yield from behavior(...)` / `async for item in
behavior(...): yield item` — inside the same `try/finally`. This is required,
not stylistic: gRPC only starts consuming a streaming behavior's items when
the wrapper itself is iterated, so a wrapper that eagerly ran the behavior and
closed the child before returning would tear down the child before any item
was ever produced. Making the wrapper a generator keeps the child (and the
ContextVar) alive for exactly as long as gRPC is pulling items, and `finally`
still runs the close once the stream is exhausted, cancelled, or raises.

## Container handoff (a `ContextVar`)

```python
_request_container: contextvars.ContextVar[Container] = contextvars.ContextVar("modern_di_request_container")
```

The interceptor wraps the *behavior*, but the servicer method it calls is a
separate callable with no shared object to stash the child on —
`ServicerContext` is a C-extension object that cannot carry arbitrary
attributes. A `ContextVar` is the handoff: set before the behavior runs, read
by `@inject` and `fetch_di_container()`, reset after.

`fetch_di_container()` returns `_request_container.get()` — the current RPC's
child container. Called outside an intercepted RPC (the ContextVar was never
set), it raises `LookupError`.

## `ServicerContext` provider (auto-registered)

```python
grpc_context_provider = providers.ContextProvider(ServicerContext, scope=Scope.REQUEST)
```

This is the gRPC equivalent of a web integration's "connection provider."
Both interceptors' `__init__` call `_ensure_context_provider(container)`,
which registers `grpc_context_provider` on the container **idempotently** —
checked via `container.providers_registry.find_provider(ServicerContext) is
None` before calling `container.add_providers(...)` — so `ServicerContext`
injects out of the box without the caller registering anything, and
constructing a second interceptor against the same container (or the same
interceptor class twice, e.g. in tests) does not raise on a duplicate
registration.

The protobuf request `Message` is deliberately **not** exposed as a provider:
binding it would add a `protobuf` runtime dependency to a package that
otherwise needs only `grpcio` + `modern-di`, and the request is already a
servicer-method argument.

## `FromDI` marker + `inject` decorator

`FromDI` is `modern_di.integrations.from_di` — its marker factory. Calling
`FromDI(dependency)` returns an inert `Marker(dependency)` wrapping a
provider or a bare type; it does nothing on its own. Parameters opt into
injection by annotating them `typing.Annotated[SomeType, FromDI(dependency)]`.

`integrations.parse_markers(func)` scans `typing.get_type_hints(func,
include_extras=True)` for `Annotated` parameters carrying a `Marker`. If
none are found, `inject` returns `func` unchanged — no wrapper is built at
all.

Otherwise `inject` builds one of three wrapper shapes, matched to `func` by
`inspect.isasyncgenfunction` / `inspect.iscoroutinefunction`:

- **sync** — a plain function calling `func(*args, **kwargs, **resolved)`.
- **async** — a coroutine `await`ing the same call.
- **async generator** — `async for item in func(*args, **kwargs, **resolved):
  yield item`, for streaming servicer methods on the aio server.

All three resolve DI params the same way: `_resolve(di_params)` reads
`_request_container.get()` and calls `integrations.resolve_markers(container,
di_params)`, which calls each `Marker.resolve(container)` — itself
`container.resolve_dependency(marker.dependency)`, dispatching to
`resolve_provider` for a provider instance or `resolve` (by type) for a bare
type — then the wrapper appends the resolved values as **keyword** arguments
alongside gRPC's own `*args, **kwargs`.

This is simpler than the Celery/arq decorator path: gRPC always calls a
servicer method as `(request, context)` **positionally**, a calling
convention gRPC itself fixes and never varies. Because callers never pass DI
parameter names, there is no risk of a resolved keyword colliding with a
positional/keyword argument gRPC supplies — so `inject` needs neither
bind-by-name signature rewriting nor a guard against `*args`/`**kwargs`
parameters (the class of argument-corruption bug the Celery integration
guards against with a decoration-time `TypeError` cannot occur here). Each
wrapper uses `functools.wraps(func)`, since gRPC registers the servicer method
by name and never introspects or unwraps its signature.

## User-owned root lifecycle

gRPC has no server start/stop hook a container could attach to (unlike
Celery's `worker_process_init`/`worker_process_shutdown` signals or an ASGI
app's lifespan). Under modern-di 3.x's mandatory-open lifecycle, a
freshly-constructed container starts unopened, so the caller must open it
themselves — `.open()` or `with`/`async with` — before passing it to
`DIInterceptor`/`DIAioInterceptor` and serving traffic; passing an unopened
root means the very first RPC's `_build_child` call raises
`ContainerClosedError` when it tries to build the per-request child. The
`DIInterceptor`/`DIAioInterceptor` constructors do not open the root
themselves, the same way they have never closed it: opening, like closing,
is the caller's own responsibility end-to-end. The root container then lives
for the entire process lifetime of the server; closing it after
`server.stop(...)` remains the caller's job too — `close_sync()` for the
sync server, `close_async()` for the aio server. This matches
`modern-di-flask` ("no app-shutdown hook").

## Sync and async, both first-class

Unlike `modern-di-celery` (synchronous only) or `modern-di-arq` (async only,
no `grpc`/`grpc.aio` import), this integration ships both: `DIInterceptor` for
`grpc.server(...)` and `DIAioInterceptor` for `grpc.aio.server(...)`, sharing
`_rewrap`, `FromDI`, `inject`, and `grpc_context_provider`. The module imports
`grpc` and `grpc.aio` directly.
