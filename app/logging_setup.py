import logging
import sys


class FuseGetxattrFilter(logging.Filter):
    """Filter out expected ENODATA errors from getxattr operations.
    
    These are normal - programs query for extended attributes that don't exist.
    FUSE logs them as exceptions but they're not errors, just expected behavior.
    """
    def filter(self, record):
        # Suppress getxattr ENODATA (errno 61) exception tracebacks
        if (record.name == 'fuse' and 
            'getxattr raised a' in record.getMessage() and
            'errno 61' in record.getMessage()):
            return False
        return True


def setup_logging(log_level=logging.INFO, log_file: str = "/tmp/transfs.log"):
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove all handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Create filter for getxattr noise
    getxattr_filter = FuseGetxattrFilter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    console_handler.addFilter(getxattr_filter)
    root_logger.addHandler(console_handler)

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s"
    ))
    file_handler.addFilter(getxattr_filter)
    root_logger.addHandler(file_handler)