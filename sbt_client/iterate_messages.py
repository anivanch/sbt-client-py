import typing as t
from colorama import Fore, Style
from sbt_client.sbt_client import SbtMessageLevel, SbtResult


_colored_level: t.Dict[SbtMessageLevel, str] = {
    SbtMessageLevel.ERROR: Fore.RED + "[ERROR]" + Style.RESET_ALL,
    SbtMessageLevel.WARNING: Fore.YELLOW + "[WARNING]" + Style.RESET_ALL,
    SbtMessageLevel.INFO: Fore.GREEN + "[INFO]" + Style.RESET_ALL,
    SbtMessageLevel.DEBUG: Style.DIM + "[DEBUG]" + Style.RESET_ALL,
}


def iterate_messages(result: SbtResult, debug: bool = False) -> t.Iterator[str]:
    for message in result.messages:
        if message.level is not SbtMessageLevel.DEBUG or debug:
            yield f"{_colored_level[message.level]} {message.content}"
