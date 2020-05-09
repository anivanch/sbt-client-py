import os
import sys
import asyncio
import logging
from sbt_client.sbt_client import SbtClient


async def main() -> None:
    logging.basicConfig(level=logging.DEBUG)
    command_line = " ".join(sys.argv[1:])
    await run_sbt_command_line(command_line)


async def run_sbt_command_line(sbt_command_line: str) -> None:
    working_directory = os.getcwd()
    client = SbtClient(working_directory)
    await client.execute(sbt_command_line)


if __name__ == "__main__":
    asyncio.run(main())
