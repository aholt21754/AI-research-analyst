# AI Research Analyst Agent — Architecture & Roadmap

This project is built in progressive phases, each introducing a new layer of agentic capability. The goal is to move from a simple reactive pipeline to a fully autonomous, multi-agent system with human-in-the-loop control.

```mermaid
flowchart TD
    subgraph P1["⚡ Phase 1 — Reactive Agent (MVP)"]
        direction TB
        SRC["📡 Sources\narXiv · HackerNews · GitHub Trending · RSS"]
        SCR["Scraper Agent"]
        FLT["Content Filter\ndedup + relevance scoring"]
        SUM["Summarizer\nClaude Haiku"]
        SES["📧 Email Digest\nAWS SES"]
        SRC --> SCR --> FLT --> SUM --> SES
    end

    subgraph P2["🧠 Phase 2 — Memory & Personalization"]
        direction TB
        EMB["Embedding Pipeline\nHuggingFace sentence-transformers"]
        VEC["Vector Store\nChromaDB"]
        PRF["Interest Profile\nimplicit feedback loop"]
        RNK["Semantic Ranker\ncosine similarity"]
        EMB --> VEC <--> PRF
        RNK --> VEC
    end

    subgraph P3["🔍 Phase 3 — Proactive Planning"]
        direction TB
        SPK["Spike Detector\nLLM-based trend scoring"]
        ALT["📲 Proactive Alerts\nAWS SNS · ad-hoc triggers"]
        SPK --> ALT
    end

    subgraph P4["🤝 Phase 4 — Multi-Agent Orchestration"]
        direction TB
        ORC["Orchestrator\nLangGraph state machine"]
        CRT["Critic Agent\ncredibility + quality scoring"]
        SYN["Synthesis Agent\ncross-article insight extraction"]
        ORC --> CRT
        ORC --> SYN
        CRT --> ORC
        SYN --> ORC
    end

    subgraph P5["👤 Phase 5 — Human in the Loop"]
        direction TB
        INB["Inbound Email\nAWS SES + SQS"]
        INT["Intent Classifier\nLLM-based command parsing"]
        RTR["Task Router\ndispatch to sub-agents"]
        RSP["💬 On-Demand Response\nresearch · drafts · deep dives"]
        INB --> INT --> RTR --> RSP
    end

    P1 -->|"adds semantic memory"| P2
    P2 -->|"adds trend awareness"| P3
    P3 -->|"adds agent specialization"| P4
    P4 -->|"adds user control"| P5

    subgraph INF["☁️ Infrastructure — AWS Free Tier"]
        direction LR
        LAM["Lambda\ncompute"]
        EVB["EventBridge\nscheduler"]
        S3["S3\nstate + history"]
        LAM --- EVB --- S3
    end

    P1 -. runs on .-> INF
    P2 -. persists to .-> S3
    P3 -. triggers via .-> EVB
    P5 -. queues on .-> LAM
```

---

## Phase breakdown

| Phase | Capability added | Key agentic concept | New tech |
|-------|-----------------|---------------------|----------|
| 1 | Scheduled scrape → summarize → email | Tool use, prompt engineering | Lambda, EventBridge, SES, Claude Haiku |
| 2 | Personalized ranking via interest profile | RAG, vector memory | ChromaDB, sentence-transformers |
| 3 | Real-time spike detection & proactive alerts | Agent planning, event-driven action | LLM trend scoring, SNS |
| 4 | Specialized sub-agents with orchestrator | Multi-agent systems | LangGraph |
| 5 | Reply-to-email command interface | Human-in-the-loop, intent classification | SES inbound, SQS, async Lambda |

## Design principles

- **Progressively capable** — each phase is independently shippable and useful
- **Deliberately low cost** — full stack targets <$5/month using AWS Free Tier + Claude Haiku
- **Architecturally transparent** — every design decision is documented with its tradeoffs
- **Production-minded** — real infrastructure, not a notebook demo
```
