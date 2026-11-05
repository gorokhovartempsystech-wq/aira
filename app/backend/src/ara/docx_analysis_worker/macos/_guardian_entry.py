"""Fixed isolated entry; imports only from the installed trusted package location."""

if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).absolute().parents[3]))
    from ara.docx_analysis_worker.macos._guardian import main

    sys.exit(main(sys.argv[1:]))
