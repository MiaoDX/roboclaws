"""Isaac Lab worker runtime owner."""

from __future__ import annotations

from roboclaws.backends.isaaclab.runtime_commands import (
    _STATE_COMMANDS,
    read_state,
)
from roboclaws.backends.isaaclab.runtime_dependencies import (
    _DEFERRED_SIMULATION_APP,
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ISAAC_SEGMENTATION_DATA_TYPES,
    Any,
    Callable,
    argparse,
    isaac_runtime_smoke_usd,
    isaac_worker_cli,
    json,
    os,
    sys,
    traceback,
)
from roboclaws.backends.isaaclab.runtime_initialization import (
    init_state,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return isaac_worker_cli.build_arg_parser(
        default_width=DEFAULT_WIDTH,
        default_height=DEFAULT_HEIGHT,
        generated_scene_kinds=isaac_runtime_smoke_usd.GENERATED_SCENE_KINDS,
        segmentation_data_types=ISAAC_SEGMENTATION_DATA_TYPES,
    ).parse_args(argv)


type _IsaacWorkerCommand = Callable[[argparse.Namespace, dict[str, Any]], dict[str, Any]]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "init":
        try:
            result = init_state(args)
        except Exception:
            traceback.print_exc()
            if _DEFERRED_SIMULATION_APP[0] is not None:
                sys.stdout.flush()
                sys.stderr.flush()
                os._exit(1)
            raise
        return _finish_command(result)
    handler = _STATE_COMMANDS.get(args.command)
    if handler is None:  # pragma: no cover - argparse prevents this.
        raise ValueError(f"unsupported command: {args.command}")
    result = handler(args, read_state(args.state_path))
    return _finish_command(result)


def _finish_command(result: dict[str, Any]) -> int:
    print(json.dumps(result, sort_keys=True), flush=True)
    if _DEFERRED_SIMULATION_APP[0] is not None:
        # Isaac/Omniverse shutdown can hang after the render artifacts and JSON
        # result are already written. The worker is one-shot, so prefer a hard
        # successful exit over turning completed captures into parent timeouts.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    return 0


def _close_deferred_simulation_app() -> None:
    if _DEFERRED_SIMULATION_APP[0] is None:
        return
    simulation_app = _DEFERRED_SIMULATION_APP[0]
    _DEFERRED_SIMULATION_APP[0] = None
    simulation_app.close(wait_for_replicator=False, skip_cleanup=True)


if __name__ == "__main__":
    raise SystemExit(main())
