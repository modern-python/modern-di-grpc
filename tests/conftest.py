from concurrent import futures

import grpc

from tests.protos import greeter_pb2_grpc


def run_sync_server(
    servicer: greeter_pb2_grpc.GreeterServicer, interceptor: grpc.ServerInterceptor
) -> tuple[grpc.Server, int]:
    """Start an in-process sync gRPC server with a single interceptor; caller must ``server.stop(0)``."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=8), interceptors=[interceptor])
    greeter_pb2_grpc.add_GreeterServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    return server, port
