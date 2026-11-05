"""Fixed isolated model fixture entry. No work on import."""


def main():
    import os
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    try:
        from ara.docx_analysis_worker.windows._adopt import entry

        code = entry("M", sys.argv[1]) if len(sys.argv) == 2 else 75
    except BaseException:
        code = 75
    os._exit(code)


if __name__ == "__main__":
    main()
