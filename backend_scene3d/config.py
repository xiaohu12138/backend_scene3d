from dataclasses import dataclass
from pathlib import Path
import os
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')

@dataclass(frozen=True)
class Settings:
    data: Path
    runs: Path
    secret: str

    @classmethod
    def load(cls):
        secret = os.environ.get('SCENE3D_SERVICE_SECRET', '')
        if len(secret.encode()) < 32:
            raise RuntimeError('SCENE3D_SERVICE_SECRET must have at least 32 bytes')
        return cls(Path(os.environ['SCENE3D_DATA_ROOT']).resolve(),
                   Path(os.environ.get('SCENE3D_RUN_ROOT', str(ROOT / 'runs'))).resolve(), secret)
