import os
import sys
import asyncio
import logging
from sbt_client.sbt_client import SbtClient
from sbt_client.iterate_messages import iterate_messages


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    if 1 < len(sys.argv):
        commands = sys.argv[1]
    else:
        commands = ""
    await run_sbt_commands(commands)


async def run_sbt_commands(sbt_command_line: str) -> None:
    working_directory = os.getcwd()
    client = SbtClient(working_directory)
    commands = sbt_command_line.split(";")
    await client.connect()
    result = await client.execute_many(commands)
    for message in iterate_messages(result):
        print(message)


if __name__ == "__main__":
    asyncio.run(main())
