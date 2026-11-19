import logging
from unittest.mock import MagicMock
from xml.etree import ElementTree

import pytest

from sniffer.jobs import SearchJob
from sniffer.platforms.instagram import automation
from sniffer.platforms.instagram.automation import search
from sniffer.platforms.instagram.selectors import interact, wait_for


class StaleElementReferenceException(Exception):
    """Offline W3C error stand-in; Selenium is an optional dependency."""


def search_driver():
    driver = MagicMock()
    home, tab, field, results, viewer = (
        MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock(),
    )
    viewer.id = "post-feed-viewer"
    viewer.rect = {"x": 0, "y": 48, "width": 720, "height": 1016}
    for element in (home, tab, field, results, viewer):
        element.is_displayed.return_value = True
    field.get_attribute.return_value = "private-keyword"
    mapping = {
        ("accessibility id", "Home"): home,
        ("accessibility id", "Beranda"): home,
        ("id", "com.instagram.android:id/feed_tab"): home,
        ("accessibility id", "Search and explore"): tab,
        ("id", "com.instagram.android:id/action_bar_search_edit_text"): field,
        ("id", "com.instagram.android:id/recycler_view"): results,
        ("id", "com.instagram.android:id/clips_viewer_view_pager"): viewer,
    }
    driver.find_elements.side_effect = lambda strategy, value: (
        [mapping[(strategy, value)]] if (strategy, value) in mapping else []
    )
    driver._home_tab = home
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
        "search_input.verify",
    ):
        assert f"step={name} status=START" in caplog.text
        assert f"step={name} status=END" in caplog.text
    assert job.keyword not in caplog.text


def test_keyword_flow_opens_first_result_then_caps_at_120_total_contents(settings, monkeypatch):
    driver, _, _ = search_driver()
    results = driver.find_elements.side_effect(
        "id", "com.instagram.android:id/recycler_view"
    )[0]
    first, second = MagicMock(), MagicMock()
    first.is_displayed.return_value = True
    second.is_displayed.return_value = True
    results.find_elements.return_value = [first, second]
    delays = []
    monkeypatch.setattr(
        automation, "_human_delay", lambda _checkpoint, *, deadline, first: (
            delays.append(first) or True
        ),
    )
    driver.execute_script.return_value = None

    result = automation.search_open_first_post_and_scroll(
        driver, settings.platforms["instagram"],
        SearchJob(job_id="content-flow", keyword="private-keyword", scroll_count=119),
        lambda: None,
    )

    first.click.assert_called_once()
    second.click.assert_not_called()
    driver._home_tab.click.assert_called_once()
    assert driver.execute_script.call_count == 119
    assert all(
        call.args == ("mobile: swipeGesture", {
            "left": 0, "top": 48, "width": 720, "height": 1016,
            "direction": "up", "percent": 0.75,
        })
        for call in driver.execute_script.call_args_list
    )
    assert delays == [True] + [False] * 119
    assert result == {
        "action": "search_open_first_post_and_scroll",
        "first_result_tapped": True,
        "content_visit_limit": 120,
        "content_visits_requested": 120,
        "content_visits_verified": False,
        "scrolls": 119,
        "stop_reason": "content_limit",
    }


def test_keyword_flow_respects_trial_budget_and_finishes_partial_visit(settings, monkeypatch):
    driver, _, _ = search_driver()
    results = driver.find_elements.side_effect(
        "id", "com.instagram.android:id/recycler_view"
    )[0]
    first = MagicMock()
    first.is_displayed.return_value = True
    results.find_elements.return_value = [first]
    monkeypatch.setattr(
        automation, "_human_delay", lambda *_args, **_kwargs: False,
    )
    result = automation.search_open_first_post_and_scroll(
        driver, settings.platforms["instagram"],
        SearchJob(job_id="content-budget", keyword="private-keyword", scroll_count=119),
        lambda: None, deadline=0,
    )
    first.click.assert_called_once()
    driver.execute_script.assert_not_called()
    assert result["content_visits_requested"] == 1
    assert result["scrolls"] == 0
    assert result["stop_reason"] == "trial_time_budget"


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


def test_stale_visibility_reacquires_before_return():
    driver, old, fresh = MagicMock(), MagicMock(), MagicMock()
    old.is_displayed.side_effect = StaleElementReferenceException()
    fresh.is_displayed.return_value = True
    driver.find_elements.side_effect = [[old], [fresh]]
    assert wait_for(driver, [("id", "input")], timeout=2) is fresh
    assert driver.find_elements.call_count == 2


def test_stale_click_reacquires_element_and_is_bounded(caplog):
    driver, old, fresh = MagicMock(), MagicMock(), MagicMock()
    old.click.side_effect = StaleElementReferenceException()
    fresh.is_displayed.return_value = True
    driver.find_elements.return_value = [fresh]
    with caplog.at_level(logging.WARNING):
        result = interact(
            driver, [("id", "tab")], lambda e: e.click(), initial=old,
            name="search_tab.click", checkpoint=lambda: None,
        )
    assert result is fresh
    old.click.assert_called_once()
    fresh.click.assert_called_once()
    assert "status=STALE_RETRY next_attempt=2/3" in caplog.text


def test_persistent_stale_does_not_retry_forever():
    driver, element = MagicMock(), MagicMock()
    element.is_displayed.return_value = True
    element.click.side_effect = StaleElementReferenceException()
    driver.find_elements.return_value = [element]
    with pytest.raises(StaleElementReferenceException):
        interact(
            driver, [("id", "tab")], lambda e: e.click(),
            name="search_tab.click", checkpoint=lambda: None,
        )
    assert driver.find_elements.call_count == element.click.call_count == 3


def test_non_stale_driver_error_is_not_replayed():
    driver, element = MagicMock(), MagicMock()
    element.click.side_effect = RuntimeError("driver disconnected")
    with pytest.raises(RuntimeError, match="disconnected"):
        interact(
            driver, [("id", "tab")], lambda e: e.click(), initial=element,
            name="search_tab.click", checkpoint=lambda: None,
        )
    element.click.assert_called_once()
    driver.find_elements.assert_not_called()


def test_partial_stale_typing_clears_fresh_element_before_retyping(settings, caplog):
    driver, _, old = search_driver()
    old.send_keys.side_effect = StaleElementReferenceException()
    fresh = MagicMock()
    fresh.is_displayed.return_value = True
    fresh.get_attribute.return_value = "private-keyword"
    original = driver.find_elements.side_effect
    inputs = iter([old, fresh])
    def lookup(strategy, value):
        if value == "com.instagram.android:id/action_bar_search_edit_text":
            return [next(inputs)]
        return original(strategy, value)
    driver.find_elements.side_effect = lookup
    order = MagicMock()
    order.attach_mock(fresh.clear, "clear")
    order.attach_mock(fresh.send_keys, "type")
    with caplog.at_level(logging.INFO):
        search(
            driver, settings.platforms["instagram"],
            SearchJob(job_id="partial", keyword="private-keyword", scroll_count=0), lambda: None,
        )
    old.clear.assert_called_once()
    fresh.clear.assert_called_once()
    fresh.send_keys.assert_called_once_with("private-keyword")
    assert [call[0] for call in order.mock_calls] == ["clear", "type"]
    assert "step=search_input.enter status=STALE_RETRY" in caplog.text
    assert "private-keyword" not in caplog.text
    driver.press_keycode.assert_called_once_with(66)


def test_keyword_readback_mismatch_never_submits(settings, monkeypatch):
    from itertools import count

    driver, _, field = search_driver()
    field.get_attribute.return_value = "wrong-value"
    ticks = count()
    monkeypatch.setattr("sniffer.platforms.instagram.automation.time.monotonic", lambda: next(ticks))
    monkeypatch.setattr("sniffer.platforms.instagram.automation.time.sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="not confirmed"):
        search(
            driver, settings.platforms["instagram"],
            SearchJob(job_id="mismatch", keyword="private-keyword", scroll_count=0), lambda: None,
        )
    driver.press_keycode.assert_not_called()
