from odooupgrader.errors_catalog import actionable_error


def test_actionable_error_formats_message_with_suggested_action():
    message = actionable_error("upgrade_step_failed", target_version="15.0")

    assert "Upgrade step to 15.0 failed." in message
    assert "Suggested action:" in message
