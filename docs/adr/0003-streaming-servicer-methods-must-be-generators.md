# Response-streaming servicer methods must be generators

**Decision:** the response-streaming contract is the idiomatic **(async) generator** servicer form
only. A servicer method that returns nothing and streams by calling `context.write(...)` is not
supported, and `inject` does not grow a fourth wrapper shape to detect one.

gRPC accepts both forms for a server-streaming or bidi RPC. Dishka's grpcio integration handles the
`context.write` coroutine form as well; modern-di keeps the narrower contract. The reason is that
the two forms need opposite lifetimes from the wrapper. A generator behavior is consumed lazily —
gRPC pulls items only when the wrapper itself is iterated — so `_wrap_stream_sync` /
`_wrap_stream_aio` must themselves be generators, keeping the per-RPC child and the `ContextVar`
alive for exactly as long as the stream runs. A `context.write` behavior is a plain coroutine that
returns once, and would need the response-*unary* wrapper instead. Supporting both means deciding at
wrap time which one a behavior is, and `inspect` cannot tell a `context.write` streamer from any
other coroutine — the only signal is a `unary_stream` / `stream_stream` handler slot holding a
non-generator function, which is also what a genuinely broken servicer looks like.

The cost of guessing wrong is silent and severe in one direction: pick the unary wrapper for a
generator behavior and the child is closed before gRPC has pulled a single item, so every resolved
dependency is torn down mid-stream. The generator-only contract is the conservative choice, and it
is the form the original spike proved end-to-end across all four RPC types.

**Revisit trigger:** a user reports a real `context.write` servicer, or gRPC's own guidance shifts to
recommend that form — at which point the dispatch needs an explicit opt-in (a decorator argument or
a distinct decorator), never a runtime guess.
