# The protobuf request message is not exposed as a provider

`grpc_context_provider` binds `grpc.ServicerContext` at `Scope.REQUEST` and nothing else, even
though every unary-request RPC has its protobuf `Message` in hand when the child container is built.
Binding it would force a `protobuf` import to declare the provider's `bound_type`, adding a runtime
dependency to a package that otherwise needs only `grpcio` and `modern-di`, and buying nothing: gRPC
already hands the request to the servicer method as its first positional argument. It would also be
uneven, because client-streaming RPCs receive an iterator rather than a single message, so the
provider would resolve for two of the four RPC types and raise for the other two. `ServicerContext`
is present for all four, and being the only connection provider is why `_build_child` calls
`integrations.bind` directly rather than `classify_connection`. A request message needed
transitively, several provider edges deep, is the case that would reopen this.
