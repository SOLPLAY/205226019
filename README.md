# Distributed-P2P-Communication-Application

1. Project Overview & Objectives
This document outlines the scope and system design for a web-based communication application utilizing a Distributed Peer-to-Peer (P2P) Edge computing paradigm. The 12-week MVP focuses on deploying cooperative node daemons across two physical laptops, demonstrating decentralized resource management, node synchronization, and local network discovery.

2. Feature Scope


| Category | Phase 1: 12-Week MVP (Base Scope) | Phase 2: Long-term Vision |
|---|---|---|
| **User Management** | Basic registration and authentication | OAuth integration, advanced profile management, status updates |
| **Messaging** | 1-on-1 real-time text messaging, basic chat history | Group chats, read receipts, multimedia sharing, offline message queuing |
| **Resource Limits** | Hard-capped 30-40% resource utilization per node | Dynamic load balancing based on device power states |

3. System Architecture & Technology Stack
·	Computing Paradigm: Distributed P2P / Edge Mesh. The application operates as a decentralized mesh network where two physical laptops act as cooperative primary nodes routing messages and syncing data.
·	Resource Management: Application-level throttling (using Python's psutil and OS process priority controls) to ensure the background node daemon consumes a maximum of 30-40% of system CPU and memory.
·	Frontend (Python-Based): Frameworks like Reflex or PyScript for a unified Python stack, providing a web interface without writing raw JavaScript.
·	Backend & Communication: Python-based gRPC server utilizing Protocol Buffers for fast, bidirectional message streaming between the decentralized nodes.
·	Database: Local SQLite instances on each node, coupled with a synchronization mechanism to replicate message history across the distributed network.
·	Development Environment: Linux (Ubuntu) for native process management, resource control, and seamless execution of the Python node daemons.


