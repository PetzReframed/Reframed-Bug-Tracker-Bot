"""python -m bug_tracker_bot: watch the report folder and post new reports until stopped."""
import logging
import signal
import sys

from .config import load_config
from .tracker import run


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s', stream=sys.stdout)
    try:
        config = load_config()
    except ValueError as error:
        logging.getLogger('bug-tracker-bot').error('%s', error)
        return 2
    # docker stop sends SIGTERM: leave at once, between two passes or in the wait.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        run(config)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
