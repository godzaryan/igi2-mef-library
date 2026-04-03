"""
igi2mef
~~~~~~~
Python library for reading IGI 2 binary MEF model files.

Public API
----------
Functions:  ``quick_validate``, ``parse_mef``
Data:       ``MefModel``, ``MefPart``, ``MefBone``, ``MagicVertex``,
            ``Portal``, ``CollisionMesh``, ``GlowSprite``, ``ChunkInfo``
Exceptions: ``MefError``, ``MefParseError``, ``MefValidationError``
"""

from .exceptions import MefError, MefParseError, MefValidationError
from .models import (
    ChunkInfo, MefModel, MefPart, MefBone,
    MagicVertex, Portal, CollisionMesh, GlowSprite,
)
from .parser import parse_mef, quick_validate

__all__ = [
    # Functions
    "parse_mef",
    "quick_validate",
    # Data classes
    "MefModel",
    "MefPart",
    "MefBone",
    "MagicVertex",
    "Portal",
    "CollisionMesh",
    "GlowSprite",
    "ChunkInfo",
    # Exceptions
    "MefError",
    "MefParseError",
    "MefValidationError",
]

__version__ = "1.1.0"
__author__  = "Antigravity Toolchain"
__license__ = "MIT"
