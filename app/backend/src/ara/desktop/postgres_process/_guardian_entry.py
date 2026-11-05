"""Fixed isolated entry, importing only from this installed package location."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).absolute().parents[3]))
    from ara.desktop.postgres_process._guardian import main

    try:
        result = main(sys.argv[1:])
    except BaseException:
        result = 75
    sys.exit(result)
