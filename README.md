# grafana-dashboards

Custom Grafana dashboards for the home AI stack. Each dashboard lives in its
own directory with the generated `dashboard.json` and, where one exists, the
`build-dashboard.py` script that produces it. Edit the script, regenerate the
JSON, and import it into Grafana with "overwrite" to replace the dashboard in
place.

## Dashboards

### ai-gpu

The NVIDIA GPUs on every GPU node, from the
`ai-gpu-metrics` exporter
(Prometheus job `ai-gpu`, port 9101 on each node). It covers:

- utilisation;
- VRAM, stacked by pod and by host process;
- core temperature from NVML, and GDDR6X junction and VRAM temperatures from
  `gpu-temps`;
- power against the limit, energy, clocks and P-state;
- a timeline of throttle reasons;
- the exporter's own health.

Multi-GPU: the **Host** and **GPU** variables are multi-select. GPUs are
selected by `uuid`, which stays stable when cards are added, and labelled
`name (index)`.

```sh
cd ai-gpu
python3 build-dashboard.py > dashboard.json
```

### ai-server (superseded)

> Superseded by **ai-gpu** on 2026-09-23. Its GPU panels went empty when
> llama-swap stopped exporting `llamaswap_gpu_*`, because llama-swap became a
> controller with no GPU. Its inference and host panels read series that the
> exporter no longer provides. It stays here until ai-gpu has been checked,
> and is then deleted.

Host, GPU and llama.cpp inference metrics for the llama-swap server. Scrapes
the `ai-llama-metrics` exporter on port 9101, which merges:

- `llamaswap_*` host and GPU gauges from llama-swap;
- `gputemps_*` core, junction and VRAM temperatures from
  [gputemps](https://github.com/ThomasBaruzier/gddr6-core-junction-vram-temps),
  which reads the GDDR6X sensors that NVML does not expose on GeForce cards;
- `llamacpp:*` per-model series from every loaded llama-server;
- `llama_metrics_model_state` and `llama_metrics_model_vram_bytes`, which
  models llama-swap has loaded and how much GPU memory each one's process
  holds (nvidia-smi per-process figures matched to the model by its listen
  port; the collector runs with `pid: host` for that);
- `llama_metrics_scrape_errors`.

The "Current state" row names the loaded models, and "VRAM by model" stacks
each model's memory against the card total, with driver and CUDA-context
overhead shown as "Other". The "Model state" timeline under it shows what was
loaded when.

```sh
cd ai-server
python3 build-dashboard.py > dashboard.json
```

The Prometheus datasource is a dashboard variable, so the JSON imports on any
Grafana instance unchanged. The dashboard uid is set at the top of the script.

### context-guard

Conversation health, anomaly and ingest-pipeline metrics for
[Context Guard](https://github.com/dividehex/context-guard), the out-of-band
health monitor for LiteLLM / Open WebUI chats. Scrapes its `/metrics`
endpoint (the metrics-only listener enabled with
`CONTEXT_GUARD_METRICS_LISTEN=0.0.0.0:7433`), which exposes:

- `context_guard_health_score`, `context_guard_risk_score` and
  `context_guard_context_utilization_ratio` per model, for the latest scored
  turn;
- `context_guard_conversations_by_status` for chats active in the last 24 h;
- `context_guard_known_value_drift_total`, `context_guard_tool_anomalies_total`,
  `context_guard_loop_events_total` and
  `context_guard_suspicious_identifiers_total` anomaly counters;
- `context_guard_events_received_total`, `context_guard_events_dropped_total`,
  `context_guard_processing_errors_total`, `context_guard_queue_depth` and the
  `context_guard_ingest_batch_size` histogram for the ingest pipeline.

```sh
cd context-guard
python3 build-dashboard.py > dashboard.json
```

The status bands and context-pressure tiers drawn on the panels are Context
Guard's defaults (healthy >= 90, good >= 75, watch >= 60, degraded >= 40;
penalties from 70 / 80 / 90 % of the context limit). Adjust the constants at
the top of the script if the instance overrides them.

## Loading the dashboards with Git Sync

Grafana 13 (OSS) can provision every dashboard in this repository directly:
Administration > General > Provisioning > Connect to repository, repository
URL `https://github.com/dividehex/grafana-dashboards`, branch `main`, path
left empty. Each top-level directory becomes a Grafana folder.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
