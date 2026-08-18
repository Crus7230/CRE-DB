from __future__ import annotations

import io
import zipfile


def _decode_code_file(raw: bytes) -> str:
    for encoding in ("cp949", "euc-kr", "utf-8-sig", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("unsupported MOIS legal district file encoding")


def parse_mois_legal_district_zip(
    zip_bytes: bytes,
    *,
    sido_codes: set[str],
) -> dict[str, dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as archive:
        files = [name for name in archive.namelist() if not name.endswith("/")]
        if len(files) != 1:
            raise ValueError(f"expected one legal district text file, got {len(files)}")
        text = _decode_code_file(archive.read(files[0]))

    candidates: list[tuple[str, str, str]] = []
    for line in text.splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) < 3:
            continue
        legal_code, legal_name, status = (field.strip() for field in fields[:3])
        if status != "존재" or len(legal_code) != 10 or not legal_code.isdigit():
            continue
        sido_code = legal_code[:2]
        if sido_code not in sido_codes:
            continue
        if legal_code[2:] == "00000000" or not legal_code.endswith("00000"):
            continue
        candidates.append((sido_code, legal_code[:5], legal_name))

    result: dict[str, dict[str, str]] = {sido: {} for sido in sorted(sido_codes)}
    for sido_code, sgg_code, legal_name in candidates:
        has_child_sgg = any(
            other_sido == sido_code and other_name.startswith(legal_name + " ")
            for other_sido, _other_code, other_name in candidates
        )
        if not has_child_sgg:
            result[sido_code][sgg_code] = legal_name
    return {sido: dict(sorted(districts.items())) for sido, districts in result.items()}
