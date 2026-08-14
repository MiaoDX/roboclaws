# Roboclaws command runner.
#
# Canonical repo tasks. Product and specialist implementation belongs to Python
# package owners, not private Just registries.

set dotenv-load := true
set shell := ["bash", "-uc"]

mod agent     'just/agent.just'
mod run       'just/run.just'
mod console   'just/console.just'

# Default: show the public recipe list.
[private]
default:
    @just --list
