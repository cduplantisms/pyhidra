import argparse
import code
import logging

import sys
from pathlib import Path

import pyhidra
import pyhidra.core
import pyhidra.gui


# NOTE: this must be "pyhidra" and not __name__
logger = logging.getLogger("pyhidra")


def _create_shortcut():
    from pyhidra.win_shortcut import create_shortcut
    create_shortcut(Path(sys.argv[-1]))


def _interpreter(interpreter_globals: dict):
    from ghidra.framework import Application
    version = Application.getApplicationVersion()
    name = Application.getApplicationReleaseName()
    banner = f"Python Interpreter for Ghidra {version} {name}\n"
    banner += f"Python {sys.version} on {sys.platform}"
    code.interact(banner=banner, local=interpreter_globals, exitmsg='')


# pylint: disable=too-few-public-methods
class PyhidraArgs(argparse.Namespace):
    """
    Custom namespace for holding the command line arguments
    """

    def __init__(self, parser: argparse.ArgumentParser, **kwargs):
        super().__init__(**kwargs)
        self.parser = parser
        self.valid = True
        self.verbose = False
        self.skip_analysis = False
        self.binary_path: Path = None
        self.script_path: Path = None
        self.project_name = None
        self.project_path: Path = None
        self.install_dir: Path = None
        self._script_args = []
        self.gui = False
        self.debug = False

    def func(self):
        """
        Run script or enter repl
        """
        if not self.valid:
            self.parser.print_usage()
            return

        if self.debug:
            logger.setLevel(logging.DEBUG)

        if self.gui:
            pyhidra.gui.gui(self.install_dir)
            return

        if self.script_path is not None:
            try:
                pyhidra.run_script(
                    self.binary_path,
                    self.script_path,
                    project_location=self.project_path,
                    project_name=self.project_name,
                    script_args=self._script_args,
                    verbose=self.verbose,
                    analyze=not self.skip_analysis,
                    install_dir=self.install_dir
                )
            except KeyboardInterrupt:
                # gracefully finish when cancelled
                pass
        elif self.binary_path is not None:
            args = (
                self.binary_path,
                self.project_path,
                self.project_name,
                self.verbose,
                not self.skip_analysis
            )
            with pyhidra.core._flat_api(*args, install_dir=self.install_dir) as api:
                _interpreter(api)
        else:
            pyhidra.HeadlessPyhidraLauncher(
                verbose=self.verbose, install_dir=self.install_dir).start()
            _interpreter(globals())

    @property
    def script_args(self):
        return self._script_args

    @script_args.setter
    def script_args(self, value):
        if self._script_args is None:
            self._script_args = value
        else:
            # append any remaining args to the ones which were previously consumed
            self._script_args.extend(value)


class PathAction(argparse.Action):
    """
    Custom action for handling script and binary paths as positional arguments
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.nargs = '*'
        self.type = str

    def __call__(self, parser, namespace: PyhidraArgs, values, option_string=None):

        if not values:
            return

        if namespace.script_path is not None:
            # Any arguments after the script path get passed to the script
            namespace.script_args = values
            return

        value = Path(values.pop(0))

        if not value.exists():
            # File must exist
            namespace.valid = False

        if value.suffix == ".py":
            namespace.script_path = value
            namespace.script_args = values
            return

        if namespace.binary_path is None:
            # Peek at the next value, if present, to check if it is a script
            # The optional binary file MUST come before the script
            if len(values) > 0 and not values[0].endswith(".py"):
                namespace.valid = False

            namespace.binary_path = value

        if not values:
            return

        # Recurse until all values are consumed
        # The remaining arguments in the ArgParser was a lie for pretty help text
        # and to pick up trailing optional arguments meant for the script
        self(parser, namespace, values)


def _get_parser():
    is_win32 = sys.platform == "win32"
    extra_flag = "[-s] " if is_win32 else ""
    usage = f"pyhidra [-h] [-v] [-g] [-d] [--install-dir] {extra_flag}[--no-analysis] "\
            "[--project-name name] [--project-path path] [binary_path] [script_path] ..."
    parser = argparse.ArgumentParser(prog="pyhidra", usage=usage)
    parser.add_argument(
        "-v",
        "--verbose",
        dest="verbose",
        action="store_true",
        help="Enable verbose JVM output during Ghidra initialization"
    )
    parser.add_argument(
        "-d",
        "--debug",
        default=False,
        action="store_true",
        help="Sets the log level to DEBUG"
    )
    parser.add_argument(
        "-g",
        "--gui",
        action="store_true",
        dest="gui",
        help="Start Ghidra GUI"
    )
    if is_win32:
        parser.add_argument(
            "-s",
            "--shortcut",
            action="store_const",
            dest="func",
            const=_create_shortcut,
            help="Creates a shortcut that can be pinned to the taskbar (Windows only)"
        )
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=None,
        dest="install_dir",
        metavar="",
        help="Path to Ghidra installation. "
             "(defaults to the GHIDRA_INSTALL_DIR environment variable)"
    )
    parser.add_argument(
        "--skip-analysis",
        dest="skip_analysis",
        action="store_true",
        help="Switch to skip analysis after loading the binary file if provided"
    )
    parser.add_argument(
        "binary_path",
        action=PathAction,
        help="Optional binary path"
    )
    parser.add_argument(
        "script_path",
        action=PathAction,
        help=(
            "Headless script path. The script must have a .py extension. "
            "If a script is not provided, pyhidra will drop into a repl."
        )
    )
    parser.add_argument(
        "script_args",
        help="Arguments to be passed to the headless script",
        nargs=argparse.REMAINDER
    )
    parser.add_argument(
        "--project-name",
        type=str,
        dest="project_name",
        metavar="name",
        help="Project name to use. "
             "(defaults to binary filename with \"_ghidra\" suffix if provided else None)"
    )
    parser.add_argument(
        "--project-path",
        type=Path,
        dest="project_path",
        metavar="path",
        help="Location to store project. "
             "(defaults to same directory as binary file if provided else None)"
    )
    return parser


def main():
    """
    pyhidra module main function
    """
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(filename)s:%(lineno)d %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    parser = _get_parser()
    parser.parse_args(namespace=PyhidraArgs(parser)).func()


if __name__ == "__main__":
    main()
