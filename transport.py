"""Plugin-owned parent CDP transport with frame logging disabled."""
import logging

from websockets.sync.client import connect

if __package__:
    from .consent import connect_with_consent
    from .worker import Wire as _Wire
else:
    from consent import connect_with_consent
    from worker import Wire as _Wire


class Wire(_Wire):
    def __init__(self, endpoint, data_root):
        # A separate, non-propagating logger keeps page data out of frame logs.
        logger = logging.Logger('original-chrome-transport', level=logging.CRITICAL + 1)
        logger.addHandler(logging.NullHandler())
        logger.propagate = False
        self.ws = connect_with_consent(endpoint, data_root,
            lambda *a, **kw: connect(*a, **kw, logger=logger))
        self.counter = 0
