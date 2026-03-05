"""
langchain_shim.py
Patches sys.modules to redirect old langchain import paths that PaddleX
tries to use internally. Must be imported BEFORE any paddleocr / paddlex import.
"""
import sys
import types


def _safe_import(module_name: str):
    try:
        return __import__(module_name, fromlist=[""])
    except ImportError:
        return types.ModuleType(module_name)


# --------------------------------------------------------------------------
# langchain.docstore  →  langchain_community.docstore
# --------------------------------------------------------------------------
if "langchain.docstore" not in sys.modules:
    _lc_ds = _safe_import("langchain_community.docstore")
    sys.modules.setdefault("langchain.docstore", _lc_ds)

if "langchain.docstore.document" not in sys.modules:
    _lc_ds_doc = _safe_import("langchain_community.docstore.document")
    sys.modules.setdefault("langchain.docstore.document", _lc_ds_doc)

# --------------------------------------------------------------------------
# langchain.text_splitter  →  langchain_text_splitters
# --------------------------------------------------------------------------
if "langchain.text_splitter" not in sys.modules:
    _lc_ts = _safe_import("langchain_text_splitters")
    sys.modules.setdefault("langchain.text_splitter", _lc_ts)

# --------------------------------------------------------------------------
# langchain.schema  (sometimes also needed)
# --------------------------------------------------------------------------
if "langchain.schema" not in sys.modules:
    _lc_schema = _safe_import("langchain_core.documents")
    sys.modules.setdefault("langchain.schema", _lc_schema)
