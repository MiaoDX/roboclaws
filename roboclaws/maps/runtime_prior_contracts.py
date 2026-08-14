RUNTIME_MAP_PRIOR_SNAPSHOT_SCHEMA = "runtime_map_prior_snapshot_v1"
RUNTIME_METRIC_MAP_SCHEMA = "runtime_metric_map_v1"
PRIVATE_TRUTH_KEYS = frozenset(
    {
        "acceptable_destination_sets",
        "generated_mess_set",
        "global_movable_object_inventory",
        "is_misplaced",
        "private_manifest",
        "target_count",
        "target_receptacle_id",
        "valid_receptacle_ids",
    }
)
MOVABLE_ANCHOR_TYPES = {"movable_object", "object"}
ACTIONABLE_ANCHOR_STATUSES = {"actionable"}
