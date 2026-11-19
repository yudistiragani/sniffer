from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sniffer.automation.gestures import scroll_up
from sniffer.jobs import KEYWORD_CONTENT_LIMIT, KEYWORD_POST_SCROLLS, SearchJob
from sniffer.platforms.instagram.selectors import interact, is_stale, wait_for
from sniffer.settings import Platform

logger = logging.getLogger(__name__)


def _step(name, action, checkpoint):
    checkpoint()
    started = time.monotonic()
    logger.info("IG step=%s status=START", name)
    try:
        result = action()
        checkpoint()
    except Exception as error:
        # Do not log the keyword, field text, page source, or raw exception message.
        logger.error("IG step=%s status=FAILED error_type=%s", name, type(error).__name__)
        raise
    logger.info("IG step=%s status=END duration=%.2fs", name, time.monotonic() - started)
    return result


def _submit_keyword(driver, config: Platform, job: SearchJob, checkpoint):
    # The operator must log in beforehand. Never automate credential entry.
    def step(name, action):
        return _step(name, action, checkpoint)

    tab = step("search_tab.find", lambda: wait_for(
        driver, config.selectors.get("search_tab", []),
        name="search_tab", checkpoint=checkpoint,
    ))
    step("search_tab.click", lambda: interact(
        driver, config.selectors.get("search_tab", []), lambda element: element.click(),
        initial=tab, name="search_tab.click", checkpoint=checkpoint,
    ))
    field = step("search_input.find", lambda: wait_for(
        driver, config.selectors.get("search_input", []),
        name="search_input", checkpoint=checkpoint,
    ))
    field = step("search_input.click", lambda: interact(
        driver, config.selectors.get("search_input", []), lambda element: element.click(),
        initial=field, name="search_input.click", checkpoint=checkpoint,
    ))

    def enter_keyword(element):
        # Retry this whole transaction, not send_keys alone: a partial stale send must
        # be cleared on the fresh element, otherwise the keyword may be duplicated.
        step("search_input.clear", element.clear)
        step("search_input.type", lambda: element.send_keys(job.keyword))

        def verify():
            deadline = time.monotonic() + 3
            while True:
                checkpoint()
                if element.get_attribute("text") == job.keyword:
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError("Instagram keyword was not confirmed in the search input.")
                time.sleep(0.1)

        step("search_input.verify", verify)

    interact(
        driver, config.selectors.get("search_input", []), enter_keyword,
        initial=field, name="search_input.enter", checkpoint=checkpoint,
    )
    # Android ENTER: submit rather than only loading typeahead.
    step("search_input.submit", lambda: driver.press_keycode(66))
    return step("search_results.find", lambda: wait_for(
        driver, config.selectors.get("results", []),
        name="search_results", checkpoint=checkpoint,
    ))


def _dwell(seconds: float, checkpoint: Callable[[], None]) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        checkpoint()
        time.sleep(min(0.2, max(0, deadline - time.monotonic())))


def search(driver, config: Platform, job: SearchJob, checkpoint: Callable[[], None]) -> dict:
    _submit_keyword(driver, config, job, checkpoint)
    for index in range(job.scroll_count):
        _step(f"search_results.scroll.{index + 1}", lambda: scroll_up(driver), checkpoint)
        _dwell(job.scroll_pause_ms / 1000, checkpoint)
    checkpoint()
    return {
        "action": "search", "scrolls": job.scroll_count,
        "result_category": "default UI results; not semantically verified",
    }


def search_open_first_post_and_scroll(
    driver, config: Platform, job: SearchJob, checkpoint: Callable[[], None],
) -> dict:
    """Open the first clickable search result and swipe at most 119 times."""
    if job.scroll_count != KEYWORD_POST_SCROLLS:
        raise ValueError(f"Keyword worker requires {KEYWORD_POST_SCROLLS} post-feed swipes.")
    results = _submit_keyword(driver, config, job, checkpoint)

    def first_visible_clickable():
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            checkpoint()
            try:
                for element in results.find_elements("xpath", ".//*[@clickable='true']"):
                    checkpoint()
                    if element.is_displayed():
                        return element
            except Exception as error:
                if not is_stale(error):
                    raise
            time.sleep(0.2)
        raise RuntimeError("Instagram first search result was not clickable.")

    def tap_first_result():
        for attempt in range(3):
            element = first_visible_clickable()
            try:
                element.click()
                checkpoint()
                return
            except Exception as error:
                if not is_stale(error) or attempt == 2:
                    raise
                logger.warning(
                    "IG step=search_results.first_post.click status=STALE_RETRY "
                    "next_attempt=%s/3", attempt + 2,
                )
                checkpoint()
                time.sleep(0.2)

    started = time.monotonic()
    logger.info("IG step=search_results.first_post.click status=START")
    try:
        tap_first_result()
        logger.info(
            "IG step=search_results.first_post.click status=END duration=%.2fs",
            time.monotonic() - started,
        )
    except Exception as error:
        logger.error(
            "IG step=search_results.first_post.click status=FAILED error_type=%s",
            type(error).__name__,
        )
        raise

    # Count the opened first result as content 1. At most 119 vertical swipes
    # can expose additional feed items, for a ceiling of 120 requested visits.
    _dwell(job.scroll_pause_ms / 1000, checkpoint)
    for index in range(KEYWORD_POST_SCROLLS):
        checkpoint()
        started = time.monotonic()
        logger.info("IG step=post_feed.scroll.%s status=START", index + 1)
        try:
            scroll_up(driver)
            _dwell(job.scroll_pause_ms / 1000, checkpoint)
        except Exception as error:
            logger.error(
                "IG step=post_feed.scroll.%s status=FAILED error_type=%s",
                index + 1, type(error).__name__,
            )
            raise
        logger.info(
            "IG step=post_feed.scroll.%s status=END duration=%.2fs",
            index + 1, time.monotonic() - started,
        )
    checkpoint()
    return {
        "action": "search_open_first_post_and_scroll",
        "first_result_tapped": True,
        "content_visit_limit": KEYWORD_CONTENT_LIMIT,
        "content_visits_requested": KEYWORD_CONTENT_LIMIT,
        "content_visits_verified": False,
        "scrolls": KEYWORD_POST_SCROLLS,
    }
