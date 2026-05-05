"""``sd`` — quickImage CLI entry point."""
from __future__ import annotations

import sys

import click

from sdcli import __version__
from sdcli.commands.config import config_cmd
from sdcli.commands.gen import gen_cmd
from sdcli.commands.info import info_cmd
from sdcli.commands.models import models_cmd
from sdcli.commands.server import server


CONTEXT_SETTINGS = {"help_option_names": ["-h", "--help"], "max_content_width": 100}


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, prog_name="sd")
def main() -> None:
    """quickImage — generate images locally with one command.

    Common usage:

    \b
        sd info                                 system / model overview
        sd server start                         bring up the ComfyUI backend
        sd models recommend                     curated downloads
        sd models pull --recommend realvis-xl   grab a model
        sd gen "a serene mountain at sunrise"   generate
        sd gen "..." --ref portrait.png         img2img with reference

    Use ``sd <command> --help`` to see the options for any subcommand.
    """


main.add_command(gen_cmd)
main.add_command(models_cmd)
main.add_command(server)
main.add_command(info_cmd)
main.add_command(config_cmd)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
