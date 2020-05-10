import typing as t
import os
import re
import io
import json
import time
import pydantic
import logging
import subprocess
import asyncio
from asyncio import (
    StreamReader,
    StreamWriter,
)
from enum import Enum
from collections import defaultdict
from sbt_client.models import (
    RpcRequest,
    RpcResponse,
    RpcError,
    RpcResult,
    ResultStatus,
    LogMessageRequest,
    Diagnostic,
)


SbtServerUri = t.NewType("SbtServerUri", str)


def _create_sbt_process() -> subprocess.Popen:
    return subprocess.Popen("sbt")


class SbtConnection(t.NamedTuple):
    reader: StreamReader
    writer: StreamWriter


async def _connect_to_server(uri: SbtServerUri) -> SbtConnection:
    reader, writer = await asyncio.open_unix_connection(path=uri)
    return SbtConnection(reader, writer)


_default_rpc_id: int = 1


def _request_sbt_exec(sbt_command: str) -> RpcRequest:
    return RpcRequest(
        jsonrpc="2.0",
        id=_default_rpc_id,
        method="sbt/exec",
        params={"commandLine": sbt_command},
    )


def _parse_response(response: str) -> RpcResponse:
    return pydantic.parse_obj_as(RpcResponse, json.loads(response))  # type: ignore


def _request_to_str(request: RpcRequest) -> str:
    request_str = str(dict(request._asdict())).replace("'", '"')
    with_headers = f"Content-Length: {len(request_str) + 2}\r\n\r\n{request_str}\r\n"
    return with_headers


async def _read_headers(reader: StreamReader) -> str:
    headers = await reader.readuntil(b"\r\n\r\n")
    return headers.decode("utf-8")


_content_length_regexp = re.compile(r"Content-Length: (\d*)")


def _get_content_length(headers: str) -> int:
    match = _content_length_regexp.match(headers)
    if match is None:
        raise ValueError(f"No content length header in {headers}")
    return int(match.group(1))


def _check_sbt_project(working_directory: str) -> bool:
    return os.path.isdir(working_directory + "/project") and os.path.isfile(
        working_directory + "/build.sbt"
    )


class SbtMessageLevel(Enum):
    ERROR = 1
    WARNING = 2
    INFO = 3
    DEBUG = 4


SbtMessage = t.NewType("SbtMessage", str)
ExecutionResult = t.Dict[SbtMessageLevel, t.List[SbtMessage]]


def _execution_result() -> ExecutionResult:
    return defaultdict(list)


def _handle_response(response: RpcResponse, result: ExecutionResult) -> bool:
    """
    :param response: Response from sbt server
    :param result: Current execution result, which gets updated in the process
    :return: True if sbt finished processing request, False otherwise
    """
    if isinstance(response, RpcError) or (
        isinstance(response, RpcResult) and response.result.status is ResultStatus.DONE
    ):
        return True
    if isinstance(response, LogMessageRequest):
        level = SbtMessageLevel(response.params.type)
        result[level].append(SbtMessage(response.params.message))
    else:
        for diagnostic in response.params.diagnostics:
            level = SbtMessageLevel(diagnostic.severity)
            result[level].append(
                SbtMessage(_print_diagnostic(response.params.uri, diagnostic))
            )
    return False


def _print_diagnostic(uri: str, diagnostic: Diagnostic) -> str:
    buffer = io.StringIO()
    filename = uri.replace("file://", "")
    with open(filename) as error_file:
        for _ in range(diagnostic.range.start.line):
            error_file.readlines()
        error_line = error_file.readline()
        message = "{}:{}:{}: {}".format(
            filename,
            diagnostic.range.start.line + 1,
            diagnostic.range.start.character + 1,
            diagnostic.message,
        )
        buffer.write(message)
        buffer.write(error_line)
        buffer.write(" " * diagnostic.range.start.character + "^")
    return buffer.getvalue()


class SbtClient:
    _uri_file: str
    _connection: t.Optional[SbtConnection]
    _logger: logging.Logger
    _uri_file_relative: str = "/project/target/active.json"
    _sleep_duration_s: float = 1

    def __init__(self, working_directory: str) -> None:
        if not _check_sbt_project(working_directory):
            raise ValueError(
                f"Current working directory {working_directory} is not an sbt project"
            )
        self._uri_file = working_directory + self._uri_file_relative
        self._connection = None
        self._logger = logging.getLogger(self.__class__.__name__)

    async def connect(self, timeout_s: float = 60) -> None:
        uri = await asyncio.wait_for(
            self._find_or_create_sbt_server(), timeout=timeout_s,
        )
        self._logger.debug(f"Connecting to sbt server at {uri}")
        self._connection = await _connect_to_server(uri)

    async def execute_many(
        self, sbt_commands: t.List[str], timeout_s: float = 60
    ) -> ExecutionResult:
        results = [await self.execute(command, timeout_s) for command in sbt_commands]
        final_result = _execution_result()
        for level in SbtMessageLevel:
            for result in results:
                final_result[level] += result[level]
        return final_result

    async def execute(self, sbt_command: str, timeout_s: float = 60) -> ExecutionResult:
        """
        :param sbt_command: Command for sbt to execute
            If several commands are present in this argument,
            only the first one gets executed
        :param timeout_s: Timeout for request to sbt server
        :return: Nothing
        :raises:
            RuntimeError: If client is not connected to a server
            pydantic.ValidationError: In case response parsing went wrong
        """
        if self._connection is None:
            raise RuntimeError(
                f"Executing sbt command {sbt_command} with no connection to server. "
                "Please connect to server using `connect` method first"
            )
        reader, writer = self._connection
        first_command = sbt_command.split(";", maxsplit=1)[0]
        return await asyncio.wait_for(
            self._execute(reader, writer, first_command), timeout=timeout_s,
        )

    async def _execute(
        self, reader: StreamReader, writer: StreamWriter, sbt_command: str,
    ) -> ExecutionResult:
        request = _request_to_str(_request_sbt_exec(sbt_command))
        self._logger.debug(f"Sending rpc request: {request}")
        writer.write(request.encode("utf-8"))
        await writer.drain()
        result = _execution_result()
        while True:
            headers = await _read_headers(reader)
            content_length = _get_content_length(headers)
            response = await reader.read(content_length)
            parsed = _parse_response(response.decode("utf-8"))
            self._logger.debug(f"Received rpc response: {parsed}")
            done = _handle_response(parsed, result)
            if done:
                self._logger.info(
                    f"Sbt command line successfully executed: {sbt_command}"
                )
                return result

    async def _find_or_create_sbt_server(self) -> SbtServerUri:
        if not self._server_is_running():
            self._logger.info(
                "No sbt server running for this project was found, starting new sbt process"
            )
            process = _create_sbt_process()
            await self._wait_for_sbt_server()
            self._logger.info(f"Sbt process with pid={process.pid} created")
        with open(self._uri_file) as uri_file:
            uri: str = json.loads(uri_file.read())["uri"]
            return SbtServerUri(uri.replace("local://", ""))

    async def _wait_for_sbt_server(self) -> None:
        start = time.time()
        while not self._server_is_running():
            await asyncio.sleep(self._sleep_duration_s)
            now = time.time()
            self._logger.info(f"Waiting for sbt server for {(now - start):.0f}s")

    def _server_is_running(self) -> bool:
        return os.path.isfile(self._uri_file)
