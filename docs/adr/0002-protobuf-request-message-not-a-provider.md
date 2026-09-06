# The protobuf request message is not exposed as a provider

**Decision:** `grpc_context_provider` binds `grpc.ServicerContext` at `Scope.REQUEST` and nothing
else. The protobuf request `Message` is deliberately **not** a second connection provider, even
though every unary-request RPC has one in hand at the moment the child container is built.

Binding it would put `protobuf` in the runtime dependency set of a package that otherwise needs only
`grpcio` and `modern-di` — the provider's `bound_type` has to be a protobuf message class, so the
adapter would have to import protobuf to declare it. That is a real cost paid by every user for a
value they already have: gRPC hands the request to the servicer method as its first positional
argument, so injecting it buys nothing a parameter does not already give.

It is also not uniform. Client-streaming RPCs (`stream_unary`, `stream_stream`) have no single
request message — the behavior receives an iterator — so the provider would resolve for two of the
four RPC types and raise for the other two. `ServicerContext` is present for all four, which is what
makes it the right and only connection object here.

`ServicerContext` alone is also why this integration calls `integrations.bind()` directly and never
`classify_connection`: with one connection provider there is nothing to dispatch across.

**Revisit trigger:** `protobuf` becomes a runtime dependency of this package for some other reason,
or a use case appears that needs the request message resolved *transitively* — inside a provider
several edges deep, where threading it through as a parameter is no longer possible.
