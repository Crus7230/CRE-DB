# Approved sale-process manifest contract (v1.0)

The importer accepts **reviewed normalized facts only**. It never extracts numbers from Korean prose.

## Approval and identity

- `manifest_version` must be `1.0`; `manifest_id` and every entity/fact row have stable explicit IDs.
- `status` must be `APPROVED`.
- `review` requires non-empty reviewer/approver identities and ISO date-time references.
- IDs make repeated imports idempotent; the importer inserts missing rows and never rewrites existing provenance.

## Required top-level objects

`review`, `sources`, `asset`, `organizations`, `event`, `process`, `roles`, `rounds`, `participations`, `participation_members`, `submissions`, `funding`, `decisions`, and `milestones`.

`participation_members` separates the named lead bidder from consortium members,
the asset manager, managed fund/REIT, and acquisition vehicle. Funding rows then
separate LP/project equity, co-investment and acquisition debt. A disclosed lender
amount that is only a subset of a syndicated facility must carry
`metadata.component_scope=SUBSET_OF` and `aggregation_rule=DO_NOT_ADD_TO_PARENT`.

Each business record carries `evidence.source_ids`, and each ID must resolve to a top-level source containing an explicit canonical `url`, publisher, document type, publication date reference, access date reference, and rights status. Sources become `source_documents`/`document_versions`; one approved manual `event_mention` is created per source. Child-table provenance is retained in `metadata_json`. Numeric bid claims additionally become accepted manual `claims`, and the child row points to that claim.

## Amount object (no prose inference)

A submission `amount` is either `null` (unknown) or:

```json
{
  "kind": "EXACT | APPROX | RANGE | AT_LEAST | AT_MOST | GREATER_THAN | LESS_THAN | UNKNOWN",
  "raw_value": "source wording retained verbatim",
  "decimal": "normalized base-currency integer/decimal string",
  "lower_decimal": "required for RANGE",
  "upper_decimal": "required for RANGE",
  "currency": "KRW",
  "price_basis": "TOTAL_CONSIDERATION | EQUITY_VALUE | ENTERPRISE_VALUE | PRICE_PER_PYEONG | PRICE_PER_M2 | UNKNOWN",
  "vat_inclusion": "INCLUDED | EXCLUDED | UNKNOWN",
  "debt_assumption": "INCLUDED | EXCLUDED | UNKNOWN"
}
```

`decimal` is required except for `RANGE` (bounds required) and `UNKNOWN` (no normalized amount). Values must already be normalized decimal strings. A sentence containing several amounts is not a normalized value and fails validation if no explicit normalized field is supplied. The importer does not parse `raw_value`.

Mapping: `EXACT -> comparator EXACT / precision EXACT`; `APPROX -> ABOUT / ROUNDED`; range and inequality kinds map directly to canonical comparator codes and conservative precision.

## Safety and transactions

- Input and all cross-references are validated before opening a write transaction.
- Import uses `BEGIN IMMEDIATE`; every exception rolls the transaction back.
- `--dry-run` executes the complete import and integrity/FK checks, then rolls back.
- The repository's canonical `data/market.db` and `db/market.db` paths are blocked by default. Live import requires the explicit `--allow-live` flag and must only follow a SQLite backup-API snapshot plus a successful live `--dry-run`.
- Existing source documents are reused by canonical URL; the importer does not create a second article/disclosure solely to attach approved evidence.
- Reusing a stable ID with changed content is a hard conflict, not silent `INSERT OR IGNORE` success.
