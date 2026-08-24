from pathlib import Path
import json
from .pipeline import run
if __name__=='__main__': print(json.dumps(run(Path.cwd()),indent=2))
