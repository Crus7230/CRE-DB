from __future__ import annotations

import argparse
import hashlib
import html
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

PIPELINE_VERSION = "content-extractive-v1"
PARSER_NAME = "trafilatura"
PARSER_VERSION = "2"
MAX_SUMMARY_CHARS = 700
MAX_EXCERPT_CHARS = 900
MIN_ARTICLE_CHARS = 450
MAX_DOWNLOAD_BYTES = 2_000_000
MAX_REDIRECTS = 5
ENRICHMENT_LOCK_KEY = "cre-document-enrichment-content-extractive-v1"


@dataclass(frozen=True)
class Candidate:
    document_version_id: str
    document_type: str
    title: str
    canonical_url: str | None
    snippet_text: str | None
    stored_text: str | None


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_text(value: str) -> str:
    value = html.unescape(value).replace("\u00a0", " ")
    value = re.sub(r"[\t\r ]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _clean_chunks(text: str, title: str) -> list[str]:
    normalized_title = re.sub(r"\W+", "", title).lower()
    chunks: list[str] = []
    for paragraph in re.split(r"\n+|(?<=[.!?])\s+", normalize_text(text)):
        candidate = paragraph.strip(" ·-–—|\ufeff")
        candidate = re.sub(r"^\[[^\]]{0,80}(?:기자|특파원)\]\s*", "", candidate)
        candidate = re.sub(r"^[가-힣A-Za-z .]{1,30}(?:기자|특파원)\s*=\s*", "", candidate)
        if len(candidate) < 18:
            continue
        compact = re.sub(r"\W+", "", candidate).lower()
        if compact and (compact == normalized_title or compact in normalized_title or normalized_title in compact):
            continue
        if any(compact == re.sub(r"\W+", "", old).lower() for old in chunks):
            continue
        chunks.append(candidate)
    return chunks


def extractive_summary(text: str, title: str, max_chars: int = MAX_SUMMARY_CHARS) -> str | None:
    chunks = _clean_chunks(text, title)
    selected: list[str] = []
    total = 0
    for chunk in chunks:
        remaining = max_chars - total
        if remaining < 60:
            break
        if len(chunk) > remaining:
            sentence_parts = re.split(r"(?<=[.!?])\s+", chunk)
            chunk = next((part for part in sentence_parts if 45 <= len(part) <= remaining), chunk[:remaining].rstrip())
        selected.append(chunk)
        total += len(chunk) + 1
        if len(selected) >= 3 or total >= max_chars - 80:
            break
    return " ".join(selected).strip() or None


def _field(text: str, pattern: str, next_field: str, max_chars: int = 180) -> str | None:
    match = re.search(pattern + r"\s*(.+?)(?=\s+" + next_field + r"(?:\s|$)|$)", text, re.S)
    if not match:
        return None
    value = re.sub(r"\s+", " ", match.group(1)).strip(" :-")
    return value[:max_chars].rstrip() or None


def _topic_phrase(value: str) -> str:
    last = value.rstrip()[-1]
    if "가" <= last <= "힣":
        return value + ("은" if (ord(last) - ord("가")) % 28 else "는")
    return value + "은"


def _object_phrase(value: str) -> str:
    last = value.rstrip()[-1]
    if "가" <= last <= "힣":
        return value + ("을" if (ord(last) - ord("가")) % 28 else "를")
    if last.isdigit():
        return value + ("을" if last in "13678" else "를")
    return value + "을"


def disclosure_summary(text: str, title: str) -> str | None:
    normalized = normalize_text(text)
    action = "양수" if "유형자산 양수" in normalized else "양도" if "유형자산 양도" in normalized else None
    if not action:
        return extractive_summary(normalized, title)
    company_match = re.search(r"회\s*사\s*명\s*:\s*(.{2,80}?)(?=\s+(?:대\s*표|본\s*점|유형자산))", normalized)
    company = re.sub(r"\s+", " ", company_match.group(1)).strip() if company_match else None
    asset = _field(normalized, r"-\s*자산명", r"2\.", 160)
    amount_match = re.search(rf"{action}금액\(원\)\s*([\d,]+)", normalized)
    amount = amount_match.group(1) if amount_match else None
    purpose = _field(normalized, rf"3\.\s*{action}목적", r"4\.", 170)
    parts: list[str] = []
    subject = company or "공시 회사"
    subject_topic = _topic_phrase(subject)
    core = f"{subject_topic} 공개한 유형자산 {action} 결정이다."
    if asset and amount:
        core = f"{subject_topic} {_object_phrase(asset)} {amount}원에 {action}하기로 공시했다."
    elif asset:
        core = f"{subject_topic} {asset}의 {action}을 결정했다."
    elif amount:
        core = f"{subject_topic} {amount}원 규모의 유형자산 {action}을 공시했다."
    parts.append(core)
    if purpose:
        parts.append(f"공시된 목적은 {purpose}이다.")
    if "기재정정" in title or "정 정 신 고" in normalized[:500]:
        parts.append("기재정정 공시이므로 변경 전후의 일정·금액·거래조건을 원문에서 함께 확인해야 한다.")
    return " ".join(parts)[:MAX_SUMMARY_CHARS]


def safe_excerpt(text: str) -> str:
    compact = re.sub(r"\s+", " ", normalize_text(text)).strip()
    return compact[:MAX_EXCERPT_CHARS].rstrip()


def _public_addresses(hostname: str) -> list[str]:
    try:
        addresses = sorted({item[4][0] for item in socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)})
    except socket.gaierror as exc:
        raise RuntimeError("DNS_RESOLUTION_FAILED") from exc
    if not addresses:
        raise RuntimeError("DNS_RESOLUTION_FAILED")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError as exc:
            raise RuntimeError("NON_PUBLIC_DESTINATION") from exc
        if not parsed.is_global:
            raise RuntimeError("NON_PUBLIC_DESTINATION")
    return addresses


def _validated_destination(url: str) -> tuple[Any, list[str], int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError("INVALID_URL")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise RuntimeError("INVALID_URL") from exc
    if port not in {80, 443}:
        raise RuntimeError("DISALLOWED_PORT")
    return parsed, _public_addresses(parsed.hostname), port


def _request_pinned(url: str, max_bytes: int) -> tuple[int, Any, bytes]:
    parsed, addresses, port = _validated_destination(url)
    host_header = parsed.hostname
    if parsed.port:
        host_header = f"{host_header}:{parsed.port}"
    target = parsed.path or "/"
    if parsed.query:
        target += "?" + parsed.query
    last_error: Exception | None = None
    for address in addresses:
        raw_socket = None
        connection = None
        try:
            raw_socket = socket.create_connection((address, port), timeout=15)
            if parsed.scheme == "https":
                raw_socket = ssl.create_default_context().wrap_socket(raw_socket, server_hostname=parsed.hostname)
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=15)
            connection.sock = raw_socket
            connection.request(
                "GET",
                target,
                headers={
                    "Host": host_header,
                    "User-Agent": "CRE-Market-Intelligence/1.0",
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.8,*/*;q=0.1",
                    "Accept-Encoding": "identity",
                    "Connection": "close",
                },
            )
            response = connection.getresponse()
            if response.headers.get("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise RuntimeError("UNSUPPORTED_CONTENT_ENCODING")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise RuntimeError("CONTENT_TOO_LARGE")
            return response.status, response.headers, body
        except RuntimeError:
            raise
        except Exception as exc:
            last_error = exc
        finally:
            if connection is not None:
                connection.close()
            elif raw_socket is not None:
                raw_socket.close()
    raise RuntimeError("FETCH_FAILED") from last_error


def safe_fetch_text(url: str, max_bytes: int = MAX_DOWNLOAD_BYTES) -> tuple[str, str]:
    current = url
    for _ in range(MAX_REDIRECTS + 1):
        status, headers, body = _request_pinned(current, max_bytes)
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("Location")
            if not location:
                raise RuntimeError("REDIRECT_WITHOUT_LOCATION")
            current = urljoin(current, location)
            _validated_destination(current)
            continue
        if status < 200 or status >= 300:
            raise RuntimeError(f"HTTP_{status}")
        content_type = headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise RuntimeError("UNSUPPORTED_CONTENT_TYPE")
        charset = headers.get_content_charset() or "utf-8"
        try:
            return body.decode(charset, errors="replace"), current
        except LookupError:
            return body.decode("utf-8", errors="replace"), current
    raise RuntimeError("TOO_MANY_REDIRECTS")


def robots_status(url: str) -> tuple[bool, str]:
    try:
        parsed, _, _ = _validated_destination(url)
    except RuntimeError as exc:
        return False, str(exc)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    try:
        parser = RobotFileParser()
        parser.set_url(robots_url)
        robots_text, _ = safe_fetch_text(robots_url, max_bytes=256_000)
        parser.parse(robots_text.splitlines())
        return parser.can_fetch("CRE-Market-Intelligence/1.0", url), "CHECKED"
    except Exception:
        return False, "UNAVAILABLE"


def candidate_sql(types: list[str], limit: int, force: bool = False) -> tuple[str, list[Any]]:
    placeholders = ",".join(["%s"] * len(types))
    pending_filter = "" if force else """
    WHERE NOT EXISTS (
      SELECT 1 FROM market_intelligence.document_enrichments de
      WHERE de.document_version_id=l.document_version_id
        AND de.enrichment_kind='CONTENT_SUMMARY'
        AND de.pipeline_version=%s
    )
    """
    sql = f"""
    WITH latest AS (
      SELECT DISTINCT ON (dv.document_id)
        dv.document_version_id,sd.document_type,dv.title,sd.canonical_url,dv.snippet_text,dv.stored_text,dv.published_at
      FROM market_intelligence.document_versions dv
      JOIN market_intelligence.source_documents sd ON sd.document_id=dv.document_id
      WHERE sd.document_type IN ({placeholders})
      ORDER BY dv.document_id,dv.version_no DESC,dv.document_version_id DESC
    )
    SELECT document_version_id,document_type,coalesce(title,''),canonical_url,snippet_text,stored_text
    FROM latest l
    {pending_filter}
    ORDER BY published_at DESC NULLS LAST
    LIMIT %s
    """
    params: list[Any] = [*types]
    if not force:
        params.append(PIPELINE_VERSION)
    params.append(limit)
    return sql, params


def try_lock_enrichment_run(connection: Any) -> bool:
    row = connection.execute(
        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
        (ENRICHMENT_LOCK_KEY,),
    ).fetchone()
    return bool(row and row[0])


def unlock_enrichment_run(connection: Any) -> None:
    connection.execute(
        "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
        (ENRICHMENT_LOCK_KEY,),
    )


def persist(connection: Any, candidate: Candidate, payload: dict[str, Any]) -> None:
    connection.execute(
        """
        INSERT INTO market_intelligence.document_enrichments(
          document_enrichment_id,document_version_id,enrichment_kind,pipeline_version,
          source_content_sha256,resolved_url,content_mode,summary_method,summary_text,safe_excerpt,
          parser_name,parser_version,fetched_at,generated_at,status_code,review_status,error_code,metadata_json
        ) VALUES (%s,%s,'CONTENT_SUMMARY',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'UNREVIEWED',%s,%s)
        ON CONFLICT(document_version_id,enrichment_kind,pipeline_version) DO UPDATE SET
          source_content_sha256=excluded.source_content_sha256,resolved_url=excluded.resolved_url,
          content_mode=excluded.content_mode,summary_method=excluded.summary_method,
          summary_text=excluded.summary_text,safe_excerpt=excluded.safe_excerpt,
          parser_name=excluded.parser_name,parser_version=excluded.parser_version,
          fetched_at=excluded.fetched_at,generated_at=excluded.generated_at,
          status_code=excluded.status_code,error_code=excluded.error_code,metadata_json=excluded.metadata_json
        """,
        (
            uuid.uuid4().hex, candidate.document_version_id, PIPELINE_VERSION,
            payload.get("source_hash"), payload.get("resolved_url"), payload["content_mode"],
            payload["summary_method"], payload.get("summary"), payload.get("excerpt"),
            payload.get("parser_name"), payload.get("parser_version"), payload.get("fetched_at"),
            datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), payload["status"],
            payload.get("error"), json.dumps(payload.get("metadata", {}), ensure_ascii=False),
        ),
    )


def enrich(candidate: Candidate) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if candidate.document_type == "DISCLOSURE" and candidate.stored_text:
        body = normalize_text(candidate.stored_text)
        summary = disclosure_summary(body, candidate.title)
        return {
            "source_hash": hashlib.sha256(body.encode()).hexdigest(), "resolved_url": candidate.canonical_url,
            "content_mode": "FULL_TEXT", "summary_method": "EXTRACTIVE" if summary else "NONE",
            "summary": summary, "excerpt": safe_excerpt(body), "parser_name": "stored-text",
            "parser_version": "1", "fetched_at": now, "status": "COMPLETED" if summary else "FAILED",
            "error": None if summary else "NO_SUMMARY", "metadata": {"source": "stored_document_text"},
        }

    resolved_url = candidate.canonical_url
    try:
        if resolved_url:
            _validated_destination(resolved_url)
        if resolved_url and urlparse(resolved_url).hostname == "news.google.com":
            from googlenewsdecoder import new_decoderv1
            decoded = new_decoderv1(resolved_url)
            resolved_url = decoded.get("decoded_url") if decoded.get("status") else None
        if not resolved_url:
            raise RuntimeError("URL_DECODE_FAILED")
        _validated_destination(resolved_url)
        allowed, robot_state = robots_status(resolved_url)
        if not allowed:
            raise RuntimeError("ROBOTS_DISALLOWED" if robot_state == "CHECKED" else robot_state)
        import trafilatura
        downloaded, resolved_url = safe_fetch_text(resolved_url)
        body = normalize_text(trafilatura.extract(downloaded or "", include_comments=False, include_tables=False, output_format="txt") or "")
        if len(body) < MIN_ARTICLE_CHARS:
            raise RuntimeError("INSUFFICIENT_PUBLIC_TEXT")
        summary = extractive_summary(body, candidate.title)
        if not summary:
            raise RuntimeError("NO_SUMMARY")
        return {
            "source_hash": hashlib.sha256(body.encode()).hexdigest(), "resolved_url": resolved_url,
            "content_mode": "SAFE_EXCERPT", "summary_method": "EXTRACTIVE", "summary": summary,
            "excerpt": safe_excerpt(body), "parser_name": PARSER_NAME, "parser_version": PARSER_VERSION,
            "fetched_at": now, "status": "COMPLETED", "error": None,
            "metadata": {"robots_status": robot_state, "body_stored": False, "extracted_chars": len(body)},
        }
    except Exception as exc:
        code = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        return {
            "resolved_url": resolved_url, "content_mode": "SNIPPET" if candidate.snippet_text else "METADATA",
            "summary_method": "NONE", "summary": None, "excerpt": None, "parser_name": PARSER_NAME,
            "parser_version": PARSER_VERSION, "fetched_at": now, "status": "FAILED", "error": code[:120],
            "metadata": {"body_stored": False},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Persist bounded, versioned content summaries without storing publisher article bodies.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--types", default="RSS_ITEM,DISCLOSURE")
    parser.add_argument("--force", action="store_true", help="Reprocess and replace the same pipeline version for selected latest documents.")
    args = parser.parse_args()
    load_env(Path(r"C:\10137_WorkSpace\env\.env.supabase.local"))
    database_url = os.environ.get("SUPABASE_DB_URL")
    if not database_url:
        raise SystemExit("SUPABASE_DB_URL is required")
    import psycopg
    types = [item.strip() for item in args.types.split(",") if item.strip()]
    sql, params = candidate_sql(types, args.limit, force=args.force)
    counts = {"selected": 0, "completed": 0, "failed": 0}
    with psycopg.connect(database_url) as connection:
        if not try_lock_enrichment_run(connection):
            connection.commit()
            print(json.dumps({"pipeline": PIPELINE_VERSION, **counts, "skipped_concurrent": True}, ensure_ascii=False))
            return 0
        connection.commit()
        try:
            rows = connection.execute(sql, params).fetchall()
            connection.commit()
            counts["selected"] = len(rows)
            for row in rows:
                candidate = Candidate(*row)
                result = enrich(candidate)
                persist(connection, candidate, result)
                connection.commit()
                counts["completed" if result["status"] == "COMPLETED" else "failed"] += 1
        finally:
            connection.rollback()
            unlock_enrichment_run(connection)
            connection.commit()
    print(json.dumps({"pipeline": PIPELINE_VERSION, **counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
