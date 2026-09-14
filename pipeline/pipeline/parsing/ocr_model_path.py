"""Work around Windows FastText's inability to open Unicode model paths."""

import hashlib
import os
import tempfile
from pathlib import Path


def ascii_model_copy(source, folder):
    data = Path(source).read_bytes()
    folder = Path(folder)
    if not str(folder).isascii():
        raise ValueError("OCR model cache must use an ASCII path")
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (hashlib.sha256(data).hexdigest() + ".ftz")
    if not target.exists() or target.read_bytes() != data:
        with tempfile.NamedTemporaryFile(dir=folder, delete=False) as stream:
            staged = Path(stream.name)
            stream.write(data)
        try:
            os.replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)
    return target


def prepare_fasttext_path():
    if os.name != "nt":
        return
    import fast_langdetect.ft_detect.infer as infer

    source = Path(infer.LOCAL_SMALL_MODEL_PATH)
    if str(source).isascii():
        return
    default = Path(tempfile.gettempdir()) / "audit-ai-ocr-models"
    if not str(default).isascii():
        default = Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "audit-ai-ocr-models"
    folder = os.environ.get("PIPELINE_OCR_MODEL_CACHE", str(default))
    # Configure only the library's model location; no package files or weights
    # are modified. The content-addressed copy is reusable across worker calls.
    infer.LOCAL_SMALL_MODEL_PATH = ascii_model_copy(source, folder)
