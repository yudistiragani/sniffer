import logging
from unittest.mock import MagicMock
from xml.etree import ElementTree

import pytest

from sniffer.jobs import SearchJob
from sniffer.platforms.instagram.automation import search
from sniffer.platforms.instagram.selectors import wait_for


def search_driver():
    driver = MagicMock()
    tab, field, results = MagicMock(), MagicMock(), MagicMock()
    for element in (tab, field, results):
        element.is_displayed.return_value = True
    mapping = {
        ("accessibility id", "Search and explore"): tab,
        ("id", "com.instagram.android:id/action_bar_search_edit_text"): field,
        ("id", "com.instagram.android:id/recycler_view"): results,
    }
    driver.find_elements.side_effect = lambda strategy, value: (
        [mapping[(strategy, value)]] if (strategy, value) in mapping else []
    )
    return driver, tab, field


def test_search_logs_each_input_operation_without_keyword(settings, caplog):
    driver, tab, field = search_driver()
    job = SearchJob(job_id="diagnostic-1", keyword="private-keyword", scroll_count=0)
    with caplog.at_level(logging.INFO):
        search(driver, settings.platforms["instagram"], job, lambda: None)
    tab.click.assert_called_once()
    field.click.assert_called_once()
    field.clear.assert_called_once()
    field.send_keys.assert_called_once_with(job.keyword)
    driver.press_keycode.assert_called_once_with(66)
    for name in (
        "search_tab.find", "search_tab.click", "search_input.find", "search_input.click",
        "search_input.clear", "search_input.type", "search_input.submit", "search_results.find",
    ):
        assert f"step={name} status=START" in caplog.text
        assert f"step={name} status=END" in caplog.text
    assert job.keyword not in caplog.text


def test_failure_log_identifies_clear_and_does_not_continue(settings, caplog):
    driver, _, field = search_driver()
    field.clear.side_effect = RuntimeError("private exception detail")
    with caplog.at_level(logging.INFO), pytest.raises(RuntimeError):
        search(
            driver, settings.platforms["instagram"],
            SearchJob(job_id="diagnostic-2", keyword="private-keyword", scroll_count=0),
            lambda: None,
        )
    assert "step=search_input.clear status=FAILED error_type=RuntimeError" in caplog.text
    assert "private exception detail" not in caplog.text
    assert "private-keyword" not in caplog.text
    field.send_keys.assert_not_called()
    driver.press_keycode.assert_not_called()


def test_timeout_names_the_missing_stage():
    with pytest.raises(RuntimeError, match="search_input not found"):
        wait_for(MagicMock(), [("id", "missing")], timeout=0, name="search_input")


def test_wait_checks_reservation_before_device_rpc():
    driver = MagicMock()
    def lost():
        raise RuntimeError("reservation lost")
    with pytest.raises(RuntimeError, match="reservation lost"):
        wait_for(driver, [("id", "input")], checkpoint=lost)
    driver.find_elements.assert_not_called()


def test_default_input_selector_matches_sanitized_device_structure(settings):
    # Only the non-personal input-node attributes from the user-provided dump.
    # Never commit the original XML: it includes search history/account data.
    node = ElementTree.fromstring(
        '<node resource-id="com.instagram.android:id/action_bar_search_edit_text" '
        'class="android.widget.EditText" text="" focused="false" enabled="true" '
        'clickable="true" bounds="[112,70][680,140]"/>'
    )
    driver, element = MagicMock(), MagicMock()
    element.is_displayed.return_value = True
    driver.find_elements.side_effect = lambda strategy, value: (
        [element] if strategy == "id" and value == node.get("resource-id") else []
    )
    assert wait_for(
        driver, settings.platforms["instagram"].selectors["search_input"]
    ) is element
    assert node.get("focused") == "false" and node.get("text") == ""
