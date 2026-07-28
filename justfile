# Roboclaws command runner.
#
# Public surface:
# - just run::surface surface=<surface> agent_engine=<engine> [world=<world>]
#   [backend=<backend>] [intent=<intent>] [key=value ...]
# - just agent::<dispatcher> ...
#
# Implementation modules stay private so completion shows the composable facade,
# not every lower-level recipe combination. Maintainers can still invoke private
# modules explicitly when debugging.

set dotenv-load := true
set shell := ["bash", "-uc"]

[private]
mod openclaw  'just/openclaw.just'
[private]
mod chat      'just/chat.just'
[private]
mod dev       'just/dev.just'
[private]
mod mcp       'just/mcp.just'
[private]
mod harness   'just/harness.just'
[private]
mod verify    'just/verify.just'
[private]
mod molmo     'just/molmo.just'
mod agent     'just/agent.just'
mod run       'just/run.just'
mod console   'just/console.just'

# Default: show the public recipe list.
[private]
default:
    @just --list
