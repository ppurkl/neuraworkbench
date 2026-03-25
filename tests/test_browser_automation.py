from neuraworkbench.src.browser_automation import run_browser_task_sync


def test_browser_automation():
    jobs_task = """
    Insert a browser task here.
    Example: visit a careers page, open each job posting, and extract the visible text.
    """

    flights_task = """
    Insert a browser task here.
    Example: search for flights for your own route and date range.
    """

    # Replace the placeholder text above before running this example.
    if "Insert a browser task here." in flights_task:
        return

    run_browser_task_sync(flights_task)
    # run_browser_task_sync(jobs_task)


if __name__ == "__main__":
    test_browser_automation()
