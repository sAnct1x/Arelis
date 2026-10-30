# Dependencies in a dev checkout

When you run Arelis from a source checkout, it checks `pyproject.toml` each time the window starts.
If the file changed since the last successful sync, Arelis runs `pip install -e .` in its own
virtualenv before the window opens, so new or updated dependencies are installed for you.

- The first launch after a change takes longer while pip runs.
- If the install fails (for example, with no network), Arelis still starts and tries again on the next launch.
  The reason is written to the log.
- Installed copies of Arelis never do this. They update through the installer.
