"""Read verified regional years.jsonl archives from engine versions 4.0 through 6.0B2."""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryFile

from .storage import verify_run


REGIONAL_VERSIONS = {"4.0", "5.0A", "5.0B", "5.0C", "5.0D", "6.0A", "6.0A.1", "6.0B1", "6.0B2"}


def observe_archive(path, observer):
    """Return the seed and emit only the exact annual bytes that passed engine replay."""
    directory = Path(path)
    manifest_path = directory / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    meta = json.loads(manifest_bytes)
    if not isinstance(meta, dict) or not isinstance(meta.get("model_version"), str):
        raise ValueError("모델 버전이 기재된 실행 기록이 필요합니다.")
    if meta["model_version"] not in REGIONAL_VERSIONS:
        raise ValueError(f"모델 {meta['model_version']}은 연대기에서 지원하지 않습니다. 4.0~6.0B2 지역별 실행 기록을 지정하세요.")

    expected = verify_run(directory)
    # Pass one replays the actual rules. A private copy of pass two survives replacement
    # of a source file and prevents publishing even a prefix of an unverified archive.
    with TemporaryFile() as snapshot:
        observed = sha256()
        with (directory / "years.jsonl").open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                observed.update(chunk)
                snapshot.write(chunk)
        if observed.hexdigest() != expected or manifest_bytes != manifest_path.read_bytes():
            raise ValueError("검증 도중 실행 기록이 변경됐습니다.")
        snapshot.seek(0)
        for line in snapshot:
            observer.observe(json.loads(line))
    return meta["seed"]
