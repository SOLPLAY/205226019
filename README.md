# DEN — Distributed Edge Network

*A research prototype for a self-organizing, resource-aware, failure-tolerant distributed edge network.*

**Current implementation milestones:** Three-node peer prototype; Linux/Windows LAN monitoring prototype
**Implementation plans:** `DEN-IMP-002` (peer prototype), `DEN-IMP-003` (current status and next milestones)
**Research methodology:** `DEN-EXP-001`

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Project objectives](#2-project-objectives)
3. [Project documentation](#3-project-documentation)
4. [Current implementation scope](#4-current-implementation-scope)
5. [Initial architecture](#5-initial-architecture)
6. [Repository structure](#6-repository-structure)
7. [Node configuration](#7-node-configuration)
8. [Protocol outline](#8-protocol-outline)
9. [Peer health model](#9-peer-health-model)
10. [Development environment and setup](#10-development-environment-and-setup)
11. [Implementation plan](#11-implementation-plan)
12. [Testing and demonstration](#12-testing-and-demonstration)
13. [Security and development guardrails](#13-security-and-development-guardrails)
14. [Research direction and evaluation](#14-research-direction-and-evaluation)
15. [Known limitations](#15-known-limitations)
16. [Author](#16-author)

---

## 1. Project overview

DEN explores how heterogeneous edge devices can cooperate as a distributed network while retaining control over their own resources and local state.

The long-term project direction is a peer-to-peer edge-computing platform. Nodes should be able to discover peers, exchange information about their availability, select suitable participants for work, and continue operating when individual nodes become unavailable.

The peer-runtime objective is deliberately narrower:

> Build three independent node processes that can identify themselves, communicate with peers, maintain a local view of membership, detect peer unavailability, and recognize a peer when it rejoins.

The repository also contains an early LAN monitoring path: a coordinator on a Linux laptop accepts outbound HTTPS reports from enrolled node agents and exposes their last-seen status to a localhost-only dashboard. This monitoring path is separate from the peer-to-peer node runtime and does not yet execute distributed workloads.

## 2. Project objectives

The broader project is concerned with:

- **Autonomous participation:** Each node runs as an independent process and maintains its own identity and local state.
- **Peer communication:** Nodes exchange versioned, validated messages.
- **Peer membership:** Each node maintains its own view of known peers and their observed health.
- **Resource awareness:** Nodes measure local resource conditions and regulate the work they accept.
- **Adaptive service selection:** Work is directed to eligible nodes based on relevant resource and service signals.
- **Failure tolerance:** The network detects unavailable peers and adapts to their absence.
- **State recovery:** Nodes can later synchronize the durable information they missed while offline.

Not all of these capabilities are part of the first implementation milestone. The current scope is defined in [Section 4](#4-current-implementation-scope).

## 3. Project documentation

The following documents define the research and implementation direction.

| Document | Purpose |
|---|---|
| `DEN-RES-001` | Project research vision, motivation, scope, and system design. |
| `DEN-IMP-001` | End-to-end implementation roadmap. |
| `DEN-EXP-001` | Research questions, hypotheses, baselines, experimental design, metrics, and validity considerations. |
| `DEN-IMP-002` | Atomic task plan for implementing three communicating autonomous nodes. |
| [`DEN-IMP-003`](DEN/docs/DEN-IMP-003_Implementation_Status_and_Next_Milestones.docx) | Implementation status, deviations from `DEN-IMP-002`, verified results, limitations, and next milestones. |


## 4. Current implementation scope

### Original milestone: Three autonomous nodes communicating

`DEN-IMP-002` defined a peer-to-peer prototype: three independent node processes with stable identities, configured peer communication, local membership and health views, and failure/rejoin testing. That peer runtime is implemented and its three-process local integration scenario passes.

### Follow-up milestone: LAN monitoring and multi-machine enrollment

After the peer prototype, a separate hub-and-spoke monitoring path was added to support practical multi-machine trials:

- A Linux laptop runs the HTTPS monitor and a localhost-only dashboard.
- Independently enrolled node agents open outbound HTTPS connections to that monitor.
- A persistent registry reports `ACTIVE`, `SUSPECT`, or `UNAVAILABLE` from heartbeat age.
- Linux and Windows machines have been confirmed reporting to the monitor.
- A Debian package and node setup applications/build sources have been added; the Windows/Android installer workflow is not yet fully verified.

This coordinator is a monitoring and enrollment service; it does not replace the original peer-to-peer membership protocol and does not schedule or run distributed work.

### Still deferred

- Internet-wide discovery and NAT traversal.
- Gossip membership at scale or a complete SWIM implementation.
- Distributed event replication and general-purpose database synchronization.
- Consensus or a globally consistent membership view.
- Resource-aware task scheduling and workload execution.
- The end-user messaging application, registration, and authentication flows.
- Production PKI lifecycle automation, Internet/public-network deployment, and arbitrary third-party code execution.
- A validated Android deployment and reliable cross-platform release pipeline.

These milestones provide a networking and monitoring foundation, not the complete end-user application or a production distributed-computing platform.

## 5. Initial architecture

Each node is an independent process with its own configuration, identity, listening endpoint, and local data directory.

```text
                    DEN network (development)

       +----------------+       +----------------+
       |     Node A     |<----->|     Node B     |
       |----------------|       |----------------|
       | Node identity  |       | Node identity  |
       | Node runtime   |       | Node runtime   |
       | HTTP endpoints |       | HTTP endpoints |
       | Peer registry  |       | Peer registry  |
       | Health monitor |       | Health monitor |
       | Local data     |       | Local data     |
       +----------------+       +----------------+
                ^                       ^
                |                       |
                +-----------+-----------+
                            |
                    +----------------+
                    |     Node C     |
                    |----------------|
                    | Node identity  |
                    | Node runtime   |
                    | HTTP endpoints |
                    | Peer registry  |
                    | Health monitor |
                    | Local data     |
                    +----------------+
```

The diagram represents peer communication, not a centralized coordinator. Each node maintains a **local membership view**; the views need not be identical at every instant.

### Node responsibilities

| Component | Responsibility in the initial milestone |
|---|---|
| Configuration | Loads and validates one node's runtime settings. |
| Identity | Creates and persists a stable NodeID in that node's data directory. |
| Lifecycle | Starts, reports status, and shuts down cleanly. |
| Protocol models | Defines and validates versioned peer messages. |
| Transport | Sends and receives HTTP/JSON requests with bounded timeouts. |
| Bootstrap | Loads configured peer endpoints to begin joining the network. |
| Peer registry | Stores the local records for known peers. |
| Health monitor | Sends heartbeats and updates peer health state. |
| Observability | Emits structured logs and exposes node/peer status. |

### Key design decisions

| Concern | Initial decision |
|---|---|
| Language/runtime | Python with asynchronous tasks for concurrent node activity. |
| Process model | One independent process per node. |
| Configuration | One configuration profile per node. |
| Identity | Persistent random NodeID; never derived from IP address, hostname, or port. |
| Transport | HTTP/JSON behind a transport interface; HTTPS with mutual TLS when a node binds or advertises a non-loopback address. |
| Bootstrap | Static seed peer addresses in configuration. |
| Health tracking | Heartbeat request/response with configurable timeout and missed-heartbeat policy. |
| Membership states | `ALIVE`, `SUSPECT`, `UNAVAILABLE`. |
| Local persistence | Separate SQLite/data directory per node where persistence is required. |
| Development trust | Explicit NodeID allowlist; on TLS, the CA-issued client certificate common name must also equal the claimed NodeID. |

HTTP/JSON is an initial implementation choice to simplify development and inspection. The transport boundary is intended to keep membership logic independent of the transport implementation. gRPC/Protocol Buffers may be evaluated after the protocol contracts stabilize; they are not a dependency of the first milestone.

## 6. Repository structure

The planned repository structure is:

```text
DEN/
├── node/
│   ├── main.py
│   ├── config.py
│   ├── identity.py
│   ├── lifecycle.py
│   ├── networking/
│   │   ├── transport.py
│   │   ├── discovery.py
│   │   ├── membership.py
│   │   └── heartbeat.py
│   └── storage/
│       └── database.py
├── dashboard/
│   ├── config.py
│   └── main.py
├── protocols/
│   └── messages.py
├── config/
│   ├── node-a.yaml
│   ├── node-b.yaml
│   └── node-c.yaml
├── scripts/
│   ├── start_nodes.sh
│   ├── stop_nodes.sh
│   └── start_dashboard.sh
├── tests/
│   ├── unit/
│   ├── component/
│   └── integration/
├── docs/
├── runtime/                 # Local node data; do not commit runtime state
├── requirements.txt         # Or the dependency manifest selected in T003
└── README.md
```

The repository has grown beyond this original peer-runtime layout. In addition to these components, it now contains `monitor/` for the coordinator, `node/agent.py` and `node/setup_gui.py` for outbound node onboarding, `android/` for the native Android client, and `packaging/` for Linux deployment. See `DEN-IMP-003` for which parts have been built and verified.

## 7. Node configuration

Each node must have a unique name, listening port, and data directory. A conceptual local development configuration is:

**`config/node-a.yaml`**

```yaml
node_name: node-a
data_dir: ../runtime/node-a
listen_host: 127.0.0.1
advertised_host: 127.0.0.1
listen_port: 8101

bootstrap_peers:
  - http://127.0.0.1:8102

heartbeat_interval_seconds: 2
heartbeat_timeout_seconds: 1
unavailable_after_misses: 3
```

Node B and Node C use separate data directories and ports (for example, `8102` and `8103`). Their bootstrap peer lists must be configured so that the nodes can form the intended peer view.

The values above are development examples, not final tuned values. Configuration validation must reject invalid ports, invalid peer endpoints, shared data directories, and nonsensical timer settings.

### Remote node network settings

The checked-in profiles are loopback-only and use plain HTTP for the local demo. For machines on a private LAN or VPN, configure each node with settings like:

```yaml
node_name: node-a
data_dir: ../runtime/node-a
listen_host: 0.0.0.0
advertised_host: 10.20.0.11  # this machine's stable private address
listen_port: 8101
bootstrap_peers:
  - https://10.20.0.12:8102
trusted_peer_ids:
  - "<NodeID-of-node-b>"
  - "<NodeID-of-node-c>"
trusted_dashboard_ids:
  - den-dashboard
tls_ca_file: ../certs/den-ca.crt
tls_cert_file: ../certs/node-a.crt
tls_key_file: ../certs/node-a.key
heartbeat_interval_seconds: 2
heartbeat_timeout_seconds: 1
unavailable_after_misses: 3
```

Use the reachable private address in `advertised_host`, and ensure the issued certificate has that address in its IP/DNS Subject Alternative Name (SAN). Each configured peer's URI host must match its certificate SAN. Non-loopback bind or advertised addresses are rejected unless mTLS files and a non-wildcard peer allowlist are configured. TLS private-key files must be mode `0600`.

The `trusted_peer_ids` list is an application allowlist, not a substitute for certificate validation. A valid peer certificate must chain to `tls_ca_file`, have a common name (CN) equal to the claimed NodeID, and match the NodeID returned by the peer. Keep the CA private key offline or in a protected signing service. Never copy it to a node or commit private keys.

#### Development certificate provisioning

These commands illustrate a small private test CA. Run CA commands only on a trusted admin machine; distribute only `den-ca.crt` to nodes. For actual use, protect the CA key, verify each CSR's CN/SAN before signing, and rotate or revoke credentials when a machine is lost.

```bash
# On the trusted admin machine; keep den-ca.key private.
openssl req -x509 -newkey rsa:4096 -nodes \
  -keyout den-ca.key -out den-ca.crt -days 365 \
  -subj "/CN=DEN-Private-Test-CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"
```

On each node machine, first generate its stable identity, then create its private key and CSR locally. Substitute that machine's reachable private IP in the SAN:

```bash
cd DEN
mkdir -p certs
NODE_ID="$(python3 -m node.main --config config/node-a.yaml --init-identity)"
openssl req -new -newkey rsa:3072 -nodes \
  -keyout certs/node-a.key -out certs/node-a.csr \
  -subj "/CN=${NODE_ID}" \
  -addext "subjectAltName=IP:10.20.0.11"
chmod 600 certs/node-a.key
```

`--init-identity` reads only the configured data directory, so it works before the TLS certificate files exist.

Transfer only the CSR to the CA admin. Verify that its CN is the expected NodeID and the SAN is the assigned private address:

```bash
openssl req -in node-a.csr -noout -subject -text
```

After verification, the CA admin creates `node-a.ext` with the correct SAN and client/server usages, then signs:

```text
basicConstraints=CA:FALSE
keyUsage=digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=IP:10.20.0.11
```

```bash
openssl x509 -req -in node-a.csr -CA den-ca.crt -CAkey den-ca.key \
  -CAcreateserial -out node-a.crt -days 90 -sha256 -extfile node-a.ext
```

Repeat with a unique NodeID, address, key, and certificate per node. Create the dashboard client key and CSR on the dashboard machine, using its reserved CN:

```bash
openssl req -new -newkey rsa:3072 -nodes \
  -keyout certs/dashboard.key -out certs/dashboard.csr \
  -subj "/CN=den-dashboard"
chmod 600 certs/dashboard.key
```

Have the same CA sign the dashboard CSR with `basicConstraints=CA:FALSE`, `keyUsage=digitalSignature,keyEncipherment`, and `extendedKeyUsage=clientAuth`. Install the CA public certificate and dashboard client certificate/key only where needed; keep `den-dashboard` in the nodes' `trusted_dashboard_ids`.

## 8. Protocol outline

The initial protocol is intentionally small and versioned. Messages should use typed validation models rather than unvalidated dictionaries passed between modules.

### Peer hello

A hello exchange allows nodes to introduce themselves and exchange basic protocol/capability information.

**Hello request fields**

- `protocol_version`
- `node_id`
- `node_name`
- `advertised_host`
- `advertised_port`
- `advertised_scheme`
- `advertised_scheme`
- `capabilities`

**Hello response fields**

- `protocol_version`
- `node_id`
- `node_name`
- `accepted`
- `capabilities`
- `known_peers` — bounded list; may be omitted in the first two-node slice.

### Heartbeat

A heartbeat exchange provides evidence that a peer endpoint is responding.

**Heartbeat request fields**

- `protocol_version`
- `sender_node_id`
- `sequence`
- `sent_at`

**Heartbeat response fields**

- `protocol_version`
- `responder_node_id`
- `echoed_sequence`
- `received_at`

The receiving node must validate the sender identity against the development trust policy. Heartbeat timeouts must use local monotonic time; wall-clock timestamps are for diagnostics and correlation, not timeout correctness.

## 9. Peer health model

Each node maintains its own view of peer health.

```text
                  valid heartbeat
             +--------------------------+
             |                          |
             v                          |
          ALIVE ---- missed heartbeat -> SUSPECT
             ^                          |
             |                          | failure threshold reached
             |                          v
             +---- valid response -- UNAVAILABLE
                                        |
                                        | peer responds again
                                        +----> ALIVE
```

- **ALIVE:** A valid, identity-checked response has been observed within the configured health window.
- **SUSPECT:** One or more expected responses have been missed; the peer may be delayed or unavailable.
- **UNAVAILABLE:** The configured suspicion/missed-heartbeat policy has been reached.
- **Recovery:** A valid response from the expected identity allows the peer to return to `ALIVE`.

A missed heartbeat is not proof of permanent failure. The implementation must avoid immediately declaring a peer unavailable after one timeout.

## 10. Development environment and setup

The initial target environment is Linux (Ubuntu) with Python.

A setup sequence for the current prototype is:

```bash
# From the repository root
cd DEN

# Create and activate a virtual environment
# Python 3.11 or newer is required.
python3 -m venv .venv
source .venv/bin/activate

# Install the project's pinned dependencies
pip install -r requirements.txt

# Run unit and three-process integration tests
python3 -m unittest discover -s tests -v

# Launch, inspect, and stop the three local nodes
./scripts/start_nodes.sh
./scripts/status.sh
./scripts/stop_nodes.sh
```

The node configuration paths are relative to their YAML files. Runtime identities, logs, and PID files are stored under `DEN/runtime/`, which is ignored by Git.

### LAN monitoring test: Linux coordinator, Windows node, Android phone

The monitor path is a **prototype**. Linux and Windows machines have been confirmed reporting to the Linux-hosted monitor. Android source code exists, but an APK build and physical Android test are not yet confirmed.

The Debian package installs the Linux coordinator/dashboard and the desktop `Join DEN` setup app. A Windows setup-app build and native Android source/build configuration are present. The GitHub Actions installer workflow has failed for Linux package execution permissions and Android SDK setup; although the workflow was adjusted, a successful end-to-end rerun has not been confirmed. Do not treat those installer artifacts as verified releases.

On Debian/Ubuntu, build and install the Linux package from the repository root:

```bash
DEN/packaging/linux/build_deb.sh
sudo apt install ./DEN/dist/den-monitor_0.1.0_amd64.deb
```

The package enables the monitor and localhost dashboard at startup. Open `http://127.0.0.1:8765`; read the first-time enrollment code with `sudo den-pairing-code`. Launch **Join DEN** from the desktop app menu (or run `den-join`), and select `/etc/den/den-ca.crt` as the CA certificate. The Linux coordinator's HTTPS URL is printed by the package setup and is also visible in the dashboard configuration at `/etc/den/dashboard.yaml`. To remove the package, use `sudo apt remove den-monitor`; node identity data under the user's data directory is not removed by package removal.

When the [Build DEN installers workflow](https://github.com/SOLPLAY/205226019/actions/workflows/build-installers.yml) is repaired and passes, it is intended to publish a Windows setup executable and Android APK as workflow artifacts. Their build and installation must be verified before distributing them. See `DEN-IMP-003` for the current status and next steps.

All three devices must be on the same trusted Wi-Fi or VPN. The Linux laptop runs the coordinator and dashboard; each node opens outbound HTTPS to it. Do not configure router port forwarding. Keep the dashboard bound to `127.0.0.1`.

#### 1. Start the coordinator on Linux

On the Linux laptop, reserve/find its private LAN address and, from the repository root:

```bash
cd DEN
./scripts/init_monitor_tls.sh 192.168.1.10
cp config/agent.example.yaml config/agent.yaml
cp config/dashboard-lan.example.yaml config/dashboard-lan.yaml
```

Replace `192.168.1.10` with the Linux laptop's actual stable Wi-Fi/VPN address in both YAML files' `monitor_url` values. Keep `DEN/certs/den-ca.key` private; nodes need only `DEN/certs/den-ca.crt`. The monitor config already points to the generated certificate and key. Start it:

```bash
./scripts/start_monitor.sh
```

On first start it prints an enrollment code and dashboard token. The code can enroll at most three distinct nodes by default; each device enters it once, and thereafter reuses its saved per-node credential. The dashboard reads its token from the private runtime file.

In another Linux terminal, start the dashboard using the LAN example:

```bash
cd DEN
python3 -m dashboard.main --config config/dashboard-lan.yaml
```

Open `http://127.0.0.1:8765` on the Linux laptop. The dashboard endpoint is intentionally not exposed to the LAN.

#### 2. Run the Linux node

Install the requirements if not already installed, edit `config/agent.yaml` to set a unique `node_name` (for example `linux-node`), and run:

```bash
cd DEN
python3 -m pip install -r requirements.txt
python3 -m node.agent --config config/agent.yaml
```

At the hidden prompt, enter the enrollment code printed by the coordinator. Keep the process running in the foreground.

#### 3. Run the Windows node

On Windows, install Python 3.11 or newer, place/clone the project, and copy `DEN/certs/den-ca.crt` from Linux to the matching `DEN/certs/` path. In PowerShell, from the `DEN` directory:

```powershell
py -3 -m pip install -r requirements.txt
Copy-Item config/agent.example.yaml config/agent.yaml
```

Edit `config/agent.yaml` so `node_name` is `windows-node`, `data_dir` is a unique path such as `../runtime/windows-node`, `monitor_url` uses the Linux laptop's LAN address, and `monitor_ca_file` points to the copied CA certificate. Then run:

```powershell
py -3 -m node.agent --config config/agent.yaml
```

Enter the enrollment code at the prompt. The Windows firewall may ask whether to allow Python outbound connections; allow access only on the private network. The node does not need an inbound listener.

#### 4. Optional source-level Android test with Termux

This is a developer fallback, not the native Android app. The native APK source and its current build limitation are documented in `DEN-IMP-003` and `android/README.md`. If you want to test the Python agent in Termux instead, install Termux from its official source, then install Python and Git, clone/copy the repository, and install its requirement:

```sh
pkg update
pkg install python git
git clone <your-repository-url>
cd 205226019/DEN
python -m pip install -r requirements.txt
cp config/agent.example.yaml config/agent.yaml
```

Edit `config/agent.yaml` with `node_name: android-node`, a device-local `data_dir`, the Linux monitor URL, and a path to a copy of `den-ca.crt`. Start it in the foreground:

```sh
python -m node.agent --config config/agent.yaml
```

Enter the enrollment code. Android may pause or terminate Termux when the app is backgrounded or the phone sleeps; keep Termux open during this manual test. This is not a native Android service or APK.

#### 5. Check liveness and recovery

The dashboard should show three enrolled node rows. With the default monitor configuration, a node becomes `SUSPECT` after 12 seconds without a report and `UNAVAILABLE` after 25 seconds. Stop one agent with Ctrl+C, wait for the state change, then restart it: it should reuse its saved credential and return to `ACTIVE`. To test a whole-device loss, disconnect one device from Wi-Fi or shut it down. Check Linux firewall rules permit inbound TCP 8443 only from the trusted private network; the dashboard stays on loopback.

For code-level checks, run the tests from `DEN/`:

```bash
python3 -m unittest discover -s tests -v
```

The automated integration test exercises enrollment, authenticated heartbeats, coordinator-backed dashboard data, and offline detection on one host. It does not replace the physical three-device procedure above.

## 11. Implementation plan

Implementation is divided into small task groups. Complete each task only after its acceptance criteria pass.

| Group | Task IDs | Outcome |
|---|---|---|
| A. Repository foundation | `T001–T006` | Reproducible project and test environment. |
| B. Configuration and identity | `T007–T013` | Isolated configuration and persistent identity for each node. |
| C. Minimal node runtime | `T014–T019` | A node starts, reports status, and shuts down cleanly. |
| D. Protocol and transport | `T020–T027` | Two independent nodes exchange validated messages. |
| E. Peer bootstrap and membership | `T028–T035` | Three nodes build useful local peer views. |
| F. Health and failure handling | `T036–T042` | Heartbeat, suspicion, unavailability, and recovery. |
| G. Three-node integration | `T043–T048` | Repeatable end-to-end demonstration and evidence report. |

### Task execution rules

1. Work on one atomic task at a time.
2. Check the task dependencies before starting.
3. Make a small, focused commit for each completed task or coherent task group.
4. Run the relevant tests and verify the acceptance criteria.
5. Record deviations and design changes.
6. Do not mark a task complete merely because its code has been written.

The detailed task descriptions and acceptance criteria are maintained in `DEN-IMP-002`.

## 12. Testing and demonstration

The milestone requires tests at several levels.

| Test level | Examples |
|---|---|
| Unit | Node/dashboard configuration validation, identity persistence, protocol validation, peer registry operations, and health-state transitions. |
| Component | HTTP endpoint behavior, transport timeouts, rejection of untrusted identities, and dashboard configuration. |
| Integration | Two-node hello/heartbeat, three-node peer exchange, mTLS certificate identity enforcement, dashboard status polling, node shutdown, and rejoin. |
| Manual demonstration | Launch all nodes, inspect membership, stop one node, observe unavailability, restart it, and observe recovery. |

### Local monitoring dashboard

With the three local nodes running, use a second terminal from `DEN/`:

```bash
./scripts/start_dashboard.sh
```

Open `http://127.0.0.1:8765`. The dashboard polls configured nodes every two seconds and shows node state, NodeID, uptime, local peer states, and unreachable nodes. Edit `config/dashboard.yaml` to set node endpoints and (recommended) expected `node_id` values. It is read-only and binds only to a loopback address. For remote viewing, run it on a trusted machine and use an SSH local port forward; do not bind the dashboard to `0.0.0.0`.

For remote HTTPS nodes, configure the dashboard with `tls_ca_file`, `tls_cert_file`, and `tls_key_file` (the dashboard's `CN=den-dashboard` client credential). Set each monitored entry's endpoint to its node's HTTPS address and `node_id` to its expected persistent ID. The dashboard verifies the server certificate chain, endpoint SAN, and certificate CN/NodeID match.

### Staged multi-machine deployment test

1. **Keep the first baseline:** run the existing local tests and local three-node demo. Keep the loopback profiles as-is.
2. **Prepare a private network:** place the machines on a trusted LAN or VPN with stable private addresses. Do not use public port forwarding. Permit TCP node ports only between participating nodes and the dashboard host.
3. **Provision identities and certificates:** initialize each NodeID; create each private key and CSR on that node; have the CA sign only after verifying the NodeID CN and address SAN. Create a separate `den-dashboard` client certificate. Distribute the CA certificate and node-specific cert/key files securely; keep keys mode `0600`.
4. **Configure explicit trust:** set each node's `listen_host`, `advertised_host`, HTTPS bootstrap URLs, CA/certificate/key files, and explicit NodeID allowlist. Add `den-dashboard` to `trusted_dashboard_ids`. Set dashboard HTTPS endpoints, expected NodeIDs, and its own TLS CA/certificate/key.
5. **Validate one link first:** start one node on each of two machines. Check `https://<private-address>:<port>/status` with a CA file and client certificate, then confirm hello and heartbeat state. A hostname/SAN, CA, or identity mismatch should fail closed.
6. **Expand to three machines:** start the remaining node, confirm all intended peers appear as `ALIVE` in local `/peers` views and in the dashboard. The views are local observations, not a globally consistent registry.
7. **Exercise failure and rejoin:** stop one node, record when peers show `SUSPECT` and `UNAVAILABLE`, restart it, and record recovery to `ALIVE`. Repeat after a full node restart to confirm its NodeID persisted.
8. **Record evidence:** capture OS/Python versions, private addresses (not private keys), certificate SAN/CN and issuer, firewall/VPN scope, configs with secrets removed, log timestamps, and observed failure/recovery times.

The dashboard machine must be able to reach each configured node endpoint. For remote viewing of a dashboard running on a separate host, keep its bind address at `127.0.0.1` and create the tunnel from your workstation:

```bash
ssh -L 8765:127.0.0.1:8765 user@dashboard-host
```

Then open `http://127.0.0.1:8765` on the workstation. The current prototype does not automate CA issuance/revocation, certificate rotation, VPN/firewall configuration, or multi-host orchestration; this procedure is for controlled private-network experiments only.

### Manual three-node failure and recovery check

Run these commands from `DEN/` after installing the requirements:

```bash
./scripts/start_nodes.sh
./scripts/status.sh

# Stop only Node C; allow the other nodes a few heartbeat intervals.
./scripts/stop_node.sh node-c
sleep 7
./scripts/status.sh

# Restart C with its existing data directory and NodeID.
./scripts/start_node.sh node-c
sleep 3
./scripts/status.sh

./scripts/stop_nodes.sh
```

In Node A's `/peers` output, verify that Node C moves from `ALIVE` through `SUSPECT` to `UNAVAILABLE`, then returns to `ALIVE` after restart. Each process writes JSON logs to `runtime/node-*.log`; peer state changes and identity are visible there. The automated integration test performs the same sequence and checks that Node A learns Node C through Node B.

The sample profiles use `trusted_peer_ids: ["*"]` only to simplify a loopback-only demonstration. The loader rejects wildcard trust when mTLS is configured and requires mTLS for non-loopback bind or advertised addresses. Plain HTTP is permitted only for loopback development.

### Milestone acceptance criteria

The milestone is complete when:

- Three node processes run simultaneously with distinct NodeIDs, ports, and data directories.
- Each node exposes a local status endpoint.
- Nodes exchange validated hello and heartbeat messages over real inter-process transport.
- Each node maintains a local peer table with last-seen information.
- A joining node can learn at least one peer beyond its initial seed, or the first-slice limitation is explicitly documented.
- A stopped node transitions through `SUSPECT` to `UNAVAILABLE` according to configured policy.
- A restarted node is recognized and returns to `ALIVE` after identity validation.
- Unit and integration tests pass from a clean setup.
- The demonstration can be repeated using documented commands.
- An evidence report records the environment, logs, test results, observed timings, and limitations.

## 13. Security and development guardrails

The initial implementation is for controlled local development.

- Keep development endpoints on loopback; controlled multi-machine experiments require a private LAN/VPN and mTLS.
- Do not expose development endpoints or the dashboard to the public Internet.
- Keep peer discovery separate from peer authorization.
- Validate peer identity before accepting peer health information.
- Use bounded request timeouts and bounded peer-list responses.
- Keep each node's identity and local data isolated.
- Do not execute arbitrary workloads received from peers.
- Do not describe this experimental CA setup as a production PKI.
- Do not claim consensus, strong consistency, or Byzantine fault tolerance unless those guarantees are implemented and evaluated.

## 14. Research direction and evaluation

The engineering prototype supports a research program; implementation success alone does not establish a research contribution.

The initial research hypotheses are documented in `DEN-EXP-001`. The central comparisons are expected to include:

- Resource-adaptive participation versus fixed or unthrottled participation.
- Resource-aware service selection versus Round Robin and Least Latency baselines.
- Failure-aware routing versus a no-failover baseline.
- Replication/rejoin behavior under explicitly defined failure scenarios.
- Membership convergence and control overhead as node count and network impairment vary.

For every experiment, record the software revision, configuration, machine specifications, workload, algorithm parameters, run identifier, and raw measurements. Local processes on one laptop are useful for validating protocol behavior, but do not by themselves demonstrate heterogeneous-device performance or WAN behavior.

## 15. Known limitations

- Static bootstrap configuration is a joining mechanism, not a complete decentralized discovery solution.
- Membership is a local, eventually updated view; nodes are not guaranteed to have identical views at every instant.
- Heartbeat-based failure detection can mistake delay or packet loss for failure.
- Peer membership is currently in memory and is lost when that node process restarts; node identity alone is persisted.
- The HTTP listener uses Python's threaded standard-library server while discovery and heartbeat scheduling use asyncio tasks; this is a replaceable development transport, not a production ASGI service.
- The checked-in profiles use loopback wildcard trust for convenience and must not be exposed beyond the local development machine.
- A three-process single-host test shares physical CPU, memory, and network resources.
- The first milestone does not implement event replication, task scheduling, messaging, or a production security model.
- The LAN coordinator and foreground agent are separate from the peer-to-peer runtime. Reports currently contain no peer observations, so the monitor tracks enrolled-node liveness and basic platform/version details only.
- The Windows installer workflow and Android APK pipeline are not yet verified end-to-end; physical Android connectivity has not been confirmed.
- The development monitor CA setup script creates a local test CA; it is not production certificate lifecycle tooling.

## 16. Author

**Shubham Savani**  
Postgraduate Data Analytics Scholar  
National Institute of Technology, Tiruchirappalli
