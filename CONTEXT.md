# modern-di-grpc

A [`modern-di`](https://github.com/modern-python/modern-di) integration for gRPC (`grpcio`): a
server interceptor opens one `Scope.REQUEST` child container per RPC, and an `@inject` decorator
resolves the `FromDI`-marked parameters of servicer methods from it. Sync (`grpc.server`) and async
(`grpc.aio.server`) are both first-class.

## Language

A term is listed only when there is a synonym to reject, or a meaning subtle enough that code and
docs must agree on it. General programming vocabulary does not belong here, however heavily this
package uses it.

Two vocabularies are borrowed whole and **not** redefined here. The domain terms are `modern-di`'s —
`Container`, `Provider`, `Group`, `Scope`, `Resolution`, `Override`; that project's `CONTEXT.md` is
the authority for all of them, including its rule that *injection* means passing a resolved value
into a callable, which is exactly what `@inject` does. The transport terms are gRPC's — servicer,
stub, channel, interceptor, RPC; gRPC's own documentation is the authority. The three below are this
package's own.

**Behavior**:
gRPC's name for the callable held in one of an `RpcMethodHandler`'s four slots — what the interceptor
re-wraps, and for a registered service the servicer method itself.
_Avoid_: handler — reserved for the `RpcMethodHandler` that *carries* a behavior. `_rewrap` takes a
handler and returns a handler; the wrapper builders take a behavior and return a behavior, and
collapsing the two names is how a rebuilt handler loses its deserializer.

**Per-RPC child container**:
The `Scope.REQUEST` child the interceptor builds, opens, and closes for one RPC. One RPC is one unit
of work across all four RPC types, so a client-streaming call gets exactly one child, not one per
message. For a response-streaming RPC the child outlives the behavior *call* — it stays open for as
long as gRPC is pulling items and closes when the stream is exhausted, cancelled, or raises.

**Root container**:
The caller's `Container`, handed to `DIInterceptor` / `DIAioInterceptor` at construction. This
package never opens it and never closes it: gRPC has no server start/stop hook, so both halves are
the caller's, end to end.
