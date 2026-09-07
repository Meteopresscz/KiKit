"""
Compatibility shims for KiCad's SWIG-generated pcbnew bindings.

KiCad hand-writes ``__iter__`` for DRAWINGS, TRACKS and VECTOR_SHAPEPTR in its
SWIG interface files and calls ``it.next()`` there. SWIG >= 4.4 no longer
generates that Python 2 era alias on ``SwigPyIterator`` (only ``__next__``),
so with such a build ``for d in board.GetDrawings()`` raises
``AttributeError: 'SwigPyIterator' object has no attribute 'next'``.
First seen with Debian kicad 10.0.6+dfsg-1 built against SWIG 4.5.0.

Restore the alias when it is missing. Importing this module is enough.
"""
from pcbnewTransition import pcbnew

if not hasattr(pcbnew.SwigPyIterator, "next"):
    pcbnew.SwigPyIterator.next = pcbnew.SwigPyIterator.__next__
