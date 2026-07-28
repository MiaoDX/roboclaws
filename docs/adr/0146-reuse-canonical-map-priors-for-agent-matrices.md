# ADR-0146: Reuse Canonical Map Priors For Agent Matrices

Status: Accepted

Date: 2026-07-23

## Context

The `map_build_consumer` suite currently combines one MapBuild sample with
open-ended and cleanup no-prior/with-prior samples. A provider matrix runs that
combined suite once per provider, so each provider rebuilds the same scene map
before its downstream trials. This makes downstream model comparisons slower
and confounds Agent quality with MapBuild quality.

The repository already has Runtime Map Prior Snapshot artifacts and a
`runtime_map_prior_catalog_v1` selector. The missing boundary is whether a
provider matrix consumes a newly produced prior or a previously promoted,
immutable prior.

## Decision

Use a promoted canonical Runtime Map Prior as the default input to downstream
Agent matrices.

The canonical identity is scoped to:

- scene and source-map identity;
- backend;
- MapBuild builder model/provider and prompt/skill version;
- evidence lane and camera labeler;
- seed;
- Runtime Map Prior schema version.

The default execution modes are separate:

```text
map_build_quality
  -> candidate maps and map-quality comparison

task_matrix_on_fixed_map
  -> one promoted map
  -> multiple Agent/provider/config consumers

end_to_end
  -> explicit same-provider MapBuild + downstream execution
```

No-prior controls run directly against the Base Metric Map and do not execute
MapBuild as an incidental dependency. Fixed-prior consumers read the canonical
artifact read-only.

Promotion requires an explicit maintainer decision based on an accepted
selector report. A passing candidate must not silently replace an existing
canonical catalog entry. Prior versions remain immutable and available for
regrade or historical comparison.

## Rejected Alternatives

- Rebuild a map independently for every provider: rejected because it makes
  provider comparisons pay repeated setup cost and mixes builder quality into
  consumer quality.
- Use one provider to build a map and a different provider to consume it as the
  default: rejected because it creates an implicit cross-provider product path
  that is not an intended baseline contract.
- Run the full builder-by-consumer Cartesian product by default: rejected
  because it multiplies cost without answering the normal regression question.
- Treat the newest successful MapBuild artifact as canonical automatically:
  rejected because it makes baseline behavior change without explicit review.

## Consequences

- Normal provider matrices become substantially cheaper after the first map
  build for a scene and compare Agent consumers on identical map input.
- Map builder quality remains measurable through a dedicated candidate matrix.
- End-to-end behavior is still testable, but must be requested as an explicit
  profile and reported separately.
- Cache invalidation must be driven by the full canonical identity; stale or
  incompatible priors cannot be silently reused.
- The existing selector/catalog implementation can be reused, while the
  combined `map_build_consumer` execution needs to be split into producer,
  no-prior control, and fixed-prior consumer modes.

## Related Plan

`docs/plans/2026-07-01-recommended-runtime-map-prior-selection.md`
