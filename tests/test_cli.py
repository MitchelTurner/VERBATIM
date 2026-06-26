def test_cli_commands_are_registered_once():
    import ytdb.cli as cli_module

    cli_module._register_commands()
    cli_module._register_commands()

    commands = list(cli_module.cli.commands)
    assert len(commands) == len(set(commands))
    assert set(commands) == {"init-db", "list-channels", "sync", "serve"}
