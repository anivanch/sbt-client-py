import typing as t
import os
import re
import json
import time
import pydantic
import logging
import asyncio
from asyncio import (
    StreamReader,
    StreamWriter,
)
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


class SbtError(Exception):
    """Error from sbt server."""


async def _create_sbt_process() -> asyncio.subprocess.Process:
    return await asyncio.create_subprocess_exec("sbt")


async def _connect_to_server(uri: SbtServerUri) -> t.Tuple[StreamReader, StreamWriter]:
    return await asyncio.open_unix_connection(path=uri)


_default_rpc_id: int = 1


def _request_sbt_exec(sbt_command_line: str) -> RpcRequest:
    return RpcRequest(
        jsonrpc="2.0",
        id=_default_rpc_id,
        method="sbt/exec",
        params={"commandLine": sbt_command_line},
    )


def _parse_response(response: str) -> RpcResponse:
    return pydantic.parse_obj_as(RpcResponse, json.loads(response))  # type: ignore


def _request_to_str(request: RpcRequest) -> str:
    request_str = str(request._asdict()).replace("'", '"')
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


class SbtClient:
    _uri_file: str
    _logger: logging.Logger
    _uri_file_relative: str = "/project/target/active.json"
    _sleep_duration_s: float = 1

    def __init__(self, working_directory: str) -> None:
        if not _check_sbt_project(working_directory):
            raise ValueError(
                f"Current working directory {working_directory} is not an sbt project"
            )
        self._uri_file = working_directory + self._uri_file_relative
        self._logger = logging.getLogger(self.__class__.__name__)

    async def execute(
        self,
        sbt_command_line: str,
        request_timeout_s: float = 1,
        server_timeout_s: float = 20,
    ) -> None:
        """
        :param sbt_command_line: Command line for sbt to execute
        :param request_timeout_s: Timeout for request to sbt server
        :param server_timeout_s: Timeout for sbt server to startup
        :raises:
            SbtError: Error returned from sbt server
            pydantic.ValidationError: In case response parsing went wrong
        """
        uri = await asyncio.wait_for(
            self._find_or_create_sbt_server(), timeout=server_timeout_s,
        )
        self._logger.debug(f"Connecting to sbt server at {uri}")
        reader, writer = await _connect_to_server(uri)
        await asyncio.wait_for(
            self._execute(reader, writer, sbt_command_line), timeout=request_timeout_s,
        )

    async def _execute(
        self, reader: StreamReader, writer: StreamWriter, sbt_command_line: str,
    ) -> None:
        request = _request_to_str(_request_sbt_exec(sbt_command_line))
        self._logger.debug(f"Sending rpc request: {request}")
        writer.write(request.encode("utf-8"))
        await writer.drain()
        while True:
            headers = await _read_headers(reader)
            content_length = _get_content_length(headers)
            response = await reader.read(content_length)
            parsed = _parse_response(response.decode("utf-8"))
            self._logger.debug(f"Received rpc response: {parsed}")
            done = self._handle_response(parsed)
            if done:
                self._logger.info(
                    f"Sbt command line successfully executed: {sbt_command_line}"
                )
                return

    async def _find_or_create_sbt_server(self) -> SbtServerUri:
        if not self._server_is_running():
            self._logger.info(
                "No sbt server running for this project was found, starting new sbt process"
            )
            process = await _create_sbt_process()
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

    def _handle_response(self, response: RpcResponse) -> bool:
        """
        :param response: Response from sbt server
        :return: True if sbt finished processing request, False otherwise
        """
        if isinstance(response, RpcError):
            raise SbtError(response.error.json())
        elif isinstance(response, RpcResult):
            if response.result.status is ResultStatus.DONE:
                return True
        else:
            if isinstance(response, LogMessageRequest):
                self._log_action_by_severity(response.params.type)(
                    response.params.message
                )
            else:
                for diagnostic in response.params.diagnostics:
                    self._print_diagnostic(response.params.uri, diagnostic)
        return False

    def _print_diagnostic(self, uri: str, diagnostic: Diagnostic) -> None:
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
            log_action = self._log_action_by_severity(diagnostic.severity)
            log_action(message)
            log_action(error_line)
            log_action(" " * diagnostic.range.start.character + "^")

    def _log_action_by_severity(self, severity: int) -> t.Callable[[str], None]:
        if severity == 1:
            return self._logger.error
        elif severity == 2:
            return self._logger.warning
        elif severity == 3:
            return self._logger.info
        return self._logger.debug
