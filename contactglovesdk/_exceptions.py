class ContactGloveSDKError(Exception):
    """Base class for the exceptions raised by the SDK"""


class SDKNotAvailableError(ContactGloveSDKError):
    """Raised when opening a local UDP socket fails (for example because the port is in use)"""


class NotConnectedError(ContactGloveSDKError):
    """Raised when an operation that requires a connection is attempted while that connection does not exist"""


class InvalidIDError(ContactGloveSDKError):
    """Raised when no data for the specified glove ID exists in the current data store"""
