import numpy as np

from mxs.processing import ProcessingPipeline

with ProcessingPipeline[np.ndarray, float](lambda frame: float(np.linalg.norm(frame))) as pipeline:
    pipeline.submit(np.arange(1024, dtype=np.float32))
    print(pipeline.read())
