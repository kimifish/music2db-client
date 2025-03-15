"""Music2DB Client - Music metadata collection client."""
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("music2db-client")
except PackageNotFoundError:
    __version__ = "0.3.0"  # Updated fallback version
