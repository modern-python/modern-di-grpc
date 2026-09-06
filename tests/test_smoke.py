import types

import modern_di_grpc
from tests.protos import greeter_pb2, greeter_pb2_grpc


def test_public_surface_is_exactly_the_six_documented_symbols() -> None:
    """INVARIANT: the package exports exactly the six symbols README's API table lists.

    Broken by promoting a helper to a public name, in ``__all__`` or as an unprefixed binding in
    ``__init__`` -- the latter is public whether or not it was meant to be, and this package's
    ``__init__`` is a re-export list, the one file where an added import silently widens the
    surface. Six symbols are the whole semver contract of an adapter this thin: every name here is
    one a major release has to keep working, and the surface is the only place that cost is visible
    before it is paid.
    """
    public = sorted(
        name
        for name, value in vars(modern_di_grpc).items()
        if not name.startswith("_") and not isinstance(value, types.ModuleType)
    )

    assert public == [
        "DIAioInterceptor",
        "DIInterceptor",
        "FromDI",
        "fetch_di_container",
        "grpc_context_provider",
        "inject",
    ]
    assert sorted(modern_di_grpc.__all__) == public


def test_proto_stubs_importable() -> None:
    assert greeter_pb2.HelloRequest is not None  # ty: ignore[unresolved-attribute]
    assert greeter_pb2_grpc.GreeterServicer is not None
