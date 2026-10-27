import inspect
import pathlib

import bam
import bam.params
from bam.model import load_model

base = pathlib.Path(bam.__path__[0])
print("bam", base)
print("load_model", inspect.signature(load_model))
print("params dirs", sorted(p.name for p in (base / "params").iterdir() if p.is_dir()))

src = inspect.getsource(load_model)
print("---- source ----")
print(src[:2000])
