# Kalshi Taxonomy Methodology

Phase 12 adds a reproducible, config-driven taxonomy layer for Kalshi
contract-horizon rows. The taxonomy is meant to support audited grouping and
diagnostics; it is not a claim that all domain slices are final confirmatory
research results.

## Rule Sources

Rules live in `configs/taxonomy.yaml`. They are explicit and versioned with the
repository:

- `exact_event_id_rules`: highest-confidence manual mappings for known events.
- `event_family_regex_rules`: regex grouping rules that create related market
  families, especially sports game winner/spread/total/prop variants.
- `prefix_rules`: ticker/event-prefix mappings for finance, sports, weather,
  politics, and entertainment categories.
- `title_keyword_rules`: explicit title-keyword mappings used only when stronger
  ticker rules do not match.
- `default_unknown`: fallback for rows that no rule can classify.

No taxonomy rule reads from future outcomes, prices, or labels. The layer does
not filter or drop rows.

## Precedence

Taxonomy assignment uses fixed precedence:

```text
exact_event_id > event_family_regex > prefix_regex > title_keyword > default_unknown
```

Event-family construction uses regex rules first when available, then falls back
to `event_id`, then `contract_id`. Fallback source and confidence are written to
the output so leakage diagnostics can distinguish audited grouping from
fallback grouping.

## Confidence

Confidence labels are intentionally conservative:

- `high`: exact event mappings and most prefix/event-family regex mappings.
- `medium`: broader prefix or title rules where configured.
- `low`: default unknown and fallback event-family assignments.
- `ambiguous`: conflicting title-keyword matches.

Domain/category claims should use confidence and ambiguity filters. High and
medium ticker-prefix mappings are more defensible than title-keyword mappings.
Ambiguous and unknown rows should be reported separately or excluded in
robustness diagnostics, not silently merged into confirmatory domain claims.

## Ambiguity

Title-keyword inference is lower precedence and explicit only. If multiple title
rules match the same row and imply conflicting domain/category assignments, the
row is marked:

```text
taxonomy_ambiguous = true
taxonomy_source = ambiguous_title_keyword_rule
taxonomy_confidence = ambiguous
```

Ambiguous rows are retained. They are visible in the taxonomy audit and examples
artifacts for manual review.

## Output Fields

The enriched panel includes:

```text
domain
category
event_family_id
taxonomy_source
taxonomy_confidence
taxonomy_notes
is_sports
taxonomy_rule_id
taxonomy_ambiguous
event_family_source
event_family_confidence
```

The raw `event_id`, contract title fields, and contract identifiers are
preserved by the pipeline for auditing.

## Audit Artifacts

The taxonomy command writes:

```text
data/processed/contract_horizon_panel_taxonomy.parquet
data/processed/contract_horizon_taxonomy_audit.parquet
data/processed/contract_horizon_taxonomy_examples.parquet
data/processed/contract_horizon_taxonomy_summary.json
```

The summary records input/output row counts, dropped rows, unknown and ambiguous
rates, sports share, rule counts, source counts, confidence counts, and
event-family source counts.

## Current Limitations

The taxonomy is auditable but not complete. Remaining limitations:

- Domain/category coverage still includes unknown and ambiguous rows.
- Title-keyword classifications are lower confidence and require manual review
  before strong domain-level claims.
- Event-family IDs are hardened with regex grouping where possible, but many rows
  still use explicit `event_id` or `contract_id` fallbacks.
- Clustered inference using the hardened family IDs remains Phase 13.
