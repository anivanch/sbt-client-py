import os
import sys
import asyncio
import logging
from sbt_client.sbt_client import SbtClient


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if 1 < len(sys.argv):
        command = sys.argv[1]
    else:
        command = ""
    await run_sbt_command(command)


async def run_sbt_command(sbt_command: str) -> None:
    working_directory = os.getcwd()
    client = SbtClient(working_directory)
    await client.connect()
    await client.execute(sbt_command)


if __name__ == "__main__":
    asyncio.run(main())
