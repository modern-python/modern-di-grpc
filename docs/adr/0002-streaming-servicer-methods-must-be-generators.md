# Response-streaming servicer methods must be generators

The response-streaming contract is the idiomatic (async) generator servicer form only: a method that
returns nothing and streams by calling `context.write(...)` is not supported, and `inject` keeps its
three wrapper shapes rather than growing a fourth to detect one. gRPC accepts both forms, and
dishka's grpcio integration handles the `context.write` coroutine as well, but the two need opposite
lifetimes. A generator behavior is consumed lazily, so `_wrap_stream_sync` and `_wrap_stream_aio` are
themselves generators that keep the per-RPC child and its `ContextVar` alive for as long as the
stream runs, while a `context.write` behavior is a plain coroutine that wants the response-unary
wrapper. `inspect` cannot tell the two apart, and guessing unary for a generator closes the child
before gRPC pulls a single item, tearing down every resolved dependency mid-stream. Supporting the
other form takes an explicit opt-in, never a runtime guess.
