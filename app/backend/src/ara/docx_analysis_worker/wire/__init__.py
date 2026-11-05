"""Pure private-pipe protocol. EOF/result bytes alone never prove a model success."""

from ._codec import WireBinding, WireError, WireMessage, encode_message
from ._stream import StreamDecoder

__all__ = ["WireBinding", "WireError", "WireMessage", "encode_message", "StreamDecoder"]
