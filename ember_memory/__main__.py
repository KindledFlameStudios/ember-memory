"""Allow running ember_memory subcommands: python -m ember_memory monitor"""

import sys

if len(sys.argv) > 1 and sys.argv[1] == "monitor":
    sys.argv = sys.argv[1:]  # Shift args so monitor sees its own flags
    from ember_memory.monitor import main
    main()
else:
    print("Ember Memory")
    print()
    print("Commands:")
    print("  python -m ember_memory monitor         Live activity monitor")
    print("  python -m ember_memory monitor --last 20  Show recent retrievals")
    print("  python -m ember_memory monitor --stats    Summary statistics")
