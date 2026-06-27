def test_cli_commands_are_registered_once():
    import ytdb.cli as cli_module

    commands = list(cli_module.cli.commands)
    assert len(commands) == len(set(commands))
    assert set(commands) == {"init-db", "list-channels", "sync", "serve"}


def test_cli_without_command_shows_short_message():
    import click.testing

    import ytdb.cli as cli_module

    runner = click.testing.CliRunner()
    result = runner.invoke(cli_module.cli, [])

    assert result.exit_code == 2
    assert "no command specified" in result.output.lower()
    assert "Commands:" not in result.output
    assert "Usage:" not in result.output


def test_cli_help_lists_each_command_once():
    import click.testing

    import ytdb.cli as cli_module

    runner = click.testing.CliRunner()
    result = runner.invoke(cli_module.cli, ["--help"])

    assert result.exit_code == 0
    assert result.output.count("  init-db") == 1
    assert result.output.count("  list-channels") == 1
    assert result.output.count("  serve") == 1
    assert result.output.count("  sync") == 1
