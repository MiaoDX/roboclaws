# Docker × Tailscale MTU blackhole

> Recorded 2026-04-28 after a multi-hour appliance "auto-disconnect" loop where
> the real cause was three layers below the symptom. Methodology first, then
> the diagnosis, so the next operator finds the root cause faster.

## Symptom

The appliance Gateway looks alive, but the chat/agent loop stalls. Concretely:

- Browser Control UI shows the agent "thinking" forever, then errors.
- The session JSONL file gets renamed to `<uuid>.jsonl.reset.<ts>` and a fresh
  session starts from scratch — looks like an "auto disconnect".
- Small tool calls succeed; the first heavy LLM call hangs.
- `docker exec <container> curl https://<llm-upstream>/...` times out;
  the same `curl` from the host succeeds in ~1s.

If you see all four, the diagnosis below applies. If you only see the first
two, finish the triage anyway — they overlap.

## Triage in order

The whole point of writing this down is the **order** — each step rules out
something cheap before you go deeper.

### 1. Is the appliance actually up?

```bash
docker ps --format '{{.Names}}\t{{.Status}}'
just appliance::smoke   # exits 0 iff Control UI proxy + Gateway WS are healthy
```

If the container is "unhealthy" or smoke fails, this doc isn't your problem.

### 2. Look for explicit timeout/error events in session JSONL

Active sessions live in the container at:
`/home/node/.openclaw/agents/<agent>/sessions/<uuid>.jsonl`

Grep for `error` / `timed out` / `idle timeout` in the *previous* session
(the one renamed to `.reset.<ts>` — that's the post-mortem record):

```bash
docker exec roboclaws-appliance sh -lc \
  'ls -lat /home/node/.openclaw/agents/agent-0/sessions/ | head -10'
docker cp roboclaws-appliance:/home/node/.openclaw/agents/agent-0/sessions/<uuid>.jsonl.reset.<ts> /tmp/reset.jsonl
jq -c 'select(.type=="custom") | .payload' /tmp/reset.jsonl | tail -5
```

Real errors look like:

```json
{"provider":"configured_chat","model":"configured-model","api":"openai-completions",
 "error":"request timed out | request timed out"}
{"...","error":"LLM idle timeout (120s): no response from model"}
```

Three of those in a row inside one session ⇒ upstream layer is the suspect,
not the Gateway.

### 3. Cross-check with Gateway diagnostic stream

Inside the container, the Gateway emits a `[diagnostic] stuck session` log
line every 30s while a session is wedged, with `age=<seconds>` rising
monotonically. The `[agent/embedded]` subsystem then prints
`embedded run timeout: ... timeoutMs=600000` once the 10-minute hard
deadline trips.

```bash
docker logs roboclaws-appliance --since 1h 2>&1 \
  | grep -E 'stuck session|embedded run|surface_error'
```

If you see `decision=surface_error reason=timeout from=<provider>/<model>
... fallbackConfigured=false`, the Gateway is doing exactly what it should:
the upstream is silent, no failover profile is configured, so it gives up.

The `[diagnostic] stuck session ... age=...` cadence is faster signal than
the JSONL — every 30s vs whenever the model would have responded.

### 4. Probe the upstream from the same place the Gateway calls it

Pull the provider's `baseUrl` + `apiKey` out of the live config and curl it
from inside the container with a short timeout:

```bash
docker exec roboclaws-appliance sh -lc \
  'cat /home/node/.openclaw/agents/main/agent/models.json' | \
  python3 -c "import json,sys; m=json.load(sys.stdin); \
              p=m['providers']['<provider>']; \
              print(p['baseUrl'], p.get('apiKey'))"

docker exec roboclaws-appliance sh -lc \
  'curl -sS -o /dev/null -w "code=%{http_code} t=%{time_total}\n" \
     --max-time 15 \
     -H "Authorization: Bearer <key>" \
     -H "Content-Type: application/json" \
     -d "{\"model\":\"<model>\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}],\"max_tokens\":4}" \
     <baseUrl>/chat/completions'
```

Then run the **same curl from the host** (no `docker exec`). If host=fast and
container=timeout, you've localized the problem to the network namespace.
Stop here and read §5 — the rest of the LLM stack is innocent.

### 5. Localize "container can't reach what host can reach"

Test progressively smaller failure modes:

```bash
# inside container — does TCP connect at all?
docker exec roboclaws-appliance sh -lc \
  'timeout 8 curl -sS -o /dev/null -w "code=%{http_code} connect=%{time_connect} t=%{time_total}\n" \
     -4 http://<upstream-IP>/'

# inside container — does TLS handshake complete?
docker exec roboclaws-appliance sh -lc \
  'timeout 12 curl -v -sS -o /dev/null -4 \
     --resolve <hostname>:443:<upstream-IP> https://<hostname>/ 2>&1 | tail -20'
```

The pattern that screams **MTU blackhole**: plain HTTP returns a small
response in <1s, but TLS hangs on `Client hello` or never completes the
handshake. (TLS exchanges multi-KB cert frames; small HTTP fits in one
sub-MTU packet.)

### 6. Confirm the MTU mismatch

```bash
ip link show | awk '/mtu/{print}'                         # host: each iface
docker exec roboclaws-appliance ip link show eth0 2>&1     # container
ip route get <upstream-IP>                                 # which iface routes to it?
```

The diagnostic combo:

- `tailscale0` MTU = **1280** (Tailscale default)
- `docker0` / container `eth0` MTU = **1500** (Docker default)
- `ip route get <upstream-IP>` returns `dev tailscale0`

⇒ Container packets at 1281–1500B get to the host, hit the Tailscale
tunnel, and silently drop. Path-MTU Discovery doesn't recover because the
ICMP Frag-Needed reply is masked by NAT. Classic.

### 7. Sanity check — is Tailscale routing more than you think?

```bash
ip route get 8.8.8.8                       # is even DNS via Tailscale?
tailscale status | head                    # is an exit node active?
```

If `tailscale status` shows `... exit node ...` with `active`, every IPv4
egress is going through it. The Singapore exit node we use for Claude/Codex
access is the same one the appliance container ends up using for its LLM
calls — that's how the categories collide.

## Root cause (short version)

Tailscale tunnel is 1280B. Docker bridge is 1500B. Container TLS handshake
to anything that ends up on `tailscale0` blackholes — host doesn't, because
the host's TCP stack does PMTU discovery natively against `tailscale0`. The
container, sitting behind the bridge + SNAT, doesn't recover.

## Fix options

In ascending order of blast radius:

1. **Per-container `--network host`** *(adopted for the appliance — see
   `just/appliance.just`)*. Container shares the host stack entirely; no
   bridge in the path; no MTU mismatch. Bonus: every internal port (8080,
   18789 gateway, 18788 MCP, 18787 snapshot viewer) is reachable at
   `127.0.0.1:<port>` from the host without `-p` forwarding — you can run
   the program inside Docker and watch `views/` from the host browser.
   Caveat: can't run two appliances on one host (port collision).

2. **Per-network `--opt mtu=1280`**. Create a custom Docker network and
   attach the container to it. Targeted; doesn't affect the default bridge.

3. **Daemon-wide `"mtu": 1280` in `/etc/docker/daemon.json`**. Persistent
   across containers; minor effective-bandwidth cost on non-Tailscale paths;
   needs `systemctl restart docker`.

4. **`docker exec ... ip link set eth0 mtu 1280`** *(temporary)*. Useful to
   confirm the diagnosis before committing to a real fix; reverts on
   container restart.

5. **iptables MSS clamping on docker0** (`-j TCPMSS --clamp-mss-to-pmtu`).
   Works but is fiddly to keep in place across reboots.

We prefer option 1 for the appliance because it also gives the host
direct visibility into every container-bound port — handy for debugging
the snapshot viewer and the Gateway's WS endpoint without juggling port
maps.

## What to add to the toolbox next

Worth keeping in mind for the next investigation:

- Gateway log file inside the container is at `/tmp/openclaw/openclaw-<date>.log`
  and is much chattier than `docker logs` — use it for outbound LLM call
  detail (`grep "embedded_run\|model_change\|provider"`).
- The `<uuid>.trajectory.jsonl` sidecar file is the per-step trajectory; the
  `<uuid>.jsonl` is the chat tape. Reset events touch the chat tape only.
- `--add-host <host>:0.0.0.0` is the pattern used to blackhole external
  fetches (OpenRouter pricing, raw.githubusercontent.com); under
  `--network host` Docker still applies these to the container's hosts file
  via overlay, so the offline-determinism guarantee survives.
