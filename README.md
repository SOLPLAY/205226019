# DEN — Distributed Edge Network

*A research prototype for a self-organizing, resource-aware, failure-tolerant distributed edge network.*

**Current implementation milestone:** Three autonomous nodes communicating  
**Implementation plan:** `DEN-IMP-002`  
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

The immediate engineering objective is deliberately narrower:

> Build three independent node processes that can identify themselves, communicate with peers, maintain a local view of membership, detect peer unavailability, and recognize a peer when it rejoins.

This first milestone establishes the communication and membership foundation required by later resource-aware scheduling, replication, and recovery experiments.

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


## 4. Current implementation scope

### Milestone: Three autonomous nodes communicating

The initial prototype will run three separate node processes. Development begins with three processes on one Linux machine; the same design will subsequently be tested across separate physical machines.

The milestone includes:

1. A reproducible Python development environment.
2. Separate configuration and data directories for Node A, Node B, and Node C.
3. A persistent, locally generated identity for each node.
4. A minimal node lifecycle and status endpoint.
5. Versioned message contracts for peer hello and heartbeat exchanges.
6. HTTP/JSON communication behind a transport interface.
7. Static bootstrap peer configuration for initial peer discovery.
8. A local peer registry maintained by each node.
9. A development trust/allowlist check for peer identities.
10. Heartbeat-based health tracking with `ALIVE`, `SUSPECT`, and `UNAVAILABLE` states.
11. Peer recovery when a previously unavailable node returns.
12. Automated tests and a repeatable three-node demonstration.

### Explicitly deferred

The following are not required to complete this milestone:

- Internet-wide discovery and NAT traversal.
- Gossip membership at scale or a complete SWIM implementation.
- Distributed event replication and general-purpose database synchronization.
- Consensus or a globally consistent membership view.
- Resource-aware task scheduling and workload execution.
- The end-user messaging application, registration, and authentication flows.
- Production PKI, public-network security hardening, and arbitrary third-party code execution.
- Cross-platform installers and deployment automation.

The first milestone is a networking foundation, not the complete end-user application.

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
| Transport | HTTP/JSON initially, behind a transport interface. |
| Bootstrap | Static seed peer addresses in configuration. |
| Health tracking | Heartbeat request/response with configurable timeout and missed-heartbeat policy. |
| Membership states | `ALIVE`, `SUSPECT`, `UNAVAILABLE`. |
| Local persistence | Separate SQLite/data directory per node where persistence is required. |
| Development trust | Explicit allowlist for expected peer identities. |

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
├── protocols/
│   └── messages.py
├── config/
│   ├── node-a.yaml
│   ├── node-b.yaml
│   └── node-c.yaml
├── scripts/
│   ├── start_nodes.sh
│   └── stop_nodes.sh
├── tests/
│   ├── unit/
│   ├── component/
│   └── integration/
├── docs/
├── runtime/                 # Local node data; do not commit runtime state
├── requirements.txt         # Or the dependency manifest selected in T003
└── README.md
```

This is the target structure, not a claim that every module or script has already been implemented. The repository may evolve as atomic tasks are completed.

## 7. Node configuration

Each node must have a unique name, listening port, and data directory. A conceptual local development configuration is:

**`config/node-a.yaml`**

```yaml
node_name: node-a
data_dir: ./runtime/node-a
listen_host: 127.0.0.1
listen_port: 8101

bootstrap_peers:
  - http://127.0.0.1:8102

heartbeat_interval_seconds: 2
heartbeat_timeout_seconds: 1
unavailable_after_misses: 3
```

Node B and Node C use separate data directories and ports (for example, `8102` and `8103`). Their bootstrap peer lists must be configured so that the nodes can form the intended peer view.

The values above are development examples, not final tuned values. Configuration validation must reject invalid ports, invalid peer endpoints, shared data directories, and nonsensical timer settings.

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
- `capabilities`

**Hello response fields**

- `protocol_version`
- `node_id`
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

A typical setup sequence, once the project files are in place, will be:

```bash
# Clone the repository
git clone <repository-url>
cd <repository-directory>

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the project's pinned dependencies
pip install -r requirements.txt

# Run the automated test suite
pytest
```

These are setup conventions; the dependency manifest and test configuration are established in tasks `T003`–`T005`. Do not assume the three-node launch scripts are available until tasks `T043` and `T044` are completed.

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
| Unit | Configuration validation, identity persistence, protocol validation, peer registry operations, and health-state transitions. |
| Component | HTTP endpoint behavior, transport timeouts, and rejection of untrusted peer identities. |
| Integration | Two-node hello/heartbeat, three-node peer exchange, node shutdown, and rejoin. |
| Manual demonstration | Launch all nodes, inspect membership, stop one node, observe unavailability, restart it, and observe recovery. |

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

- Bind development endpoints to loopback unless a controlled multi-machine test explicitly requires a LAN interface.
- Do not expose unauthenticated development endpoints to the public Internet.
- Keep peer discovery separate from peer authorization.
- Validate peer identity before accepting peer health information.
- Use bounded request timeouts and bounded peer-list responses.
- Keep each node's identity and local data isolated.
- Do not execute arbitrary workloads received from peers.
- Do not describe the development allowlist as production-grade authentication.
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
- A three-process single-host test shares physical CPU, memory, and network resources.
- The first milestone does not implement event replication, task scheduling, messaging, or a production security model.

## 16. Author

**Shubham Savani**  
Postgraduate Data Analytics Scholar  
National Institute of Technology, Tiruchirappalli
