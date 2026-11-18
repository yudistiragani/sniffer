def scroll_up(driver) -> None:
    size = driver.get_window_size()
    driver.execute_script("mobile: swipeGesture", {
        "left": int(size["width"] * 0.15),
        "top": int(size["height"] * 0.25),
        "width": int(size["width"] * 0.70),
        "height": int(size["height"] * 0.50),
        "direction": "up",
        "percent": 0.75,
    })
