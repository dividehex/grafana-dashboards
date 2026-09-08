# grafana-dashboards

Custom Grafana dashboards for the home AI stack. Each dashboard lives in its
own directory with the generated `dashboard.json` and, where one exists, the
`build-dashboard.py` script that produces it. Edit the script, regenerate the
JSON, and import it into Grafana with "overwrite" to replace the dashboard in
place.

## Dashboards

### ai-server

Host, GPU and llama.cpp inference metrics for the llama-swap server. Scrapes
the `ai-llama-metrics` exporter on port 9101, which merges:

- `llamaswap_*` host and GPU gauges from llama-swap;
- `gputemps_*` core, junction and VRAM temperatures from
  [gputemps](https://github.com/ThomasBaruzier/gddr6-core-junction-vram-temps),
  which reads the GDDR6X sensors that NVML does not expose on GeForce cards;
- `llamacpp:*` per-model series from every loaded llama-server;
- `llama_metrics_model_state` and `llama_metrics_scrape_errors`.

```sh
cd ai-server
python3 build-dashboard.py > dashboard.json
```

The Prometheus datasource is a dashboard variable, so the JSON imports on any
Grafana instance unchanged. The dashboard uid is set at the top of the script.

## Loading the dashboards with Git Sync

Grafana 13 (OSS) can provision every dashboard in this repository directly:
Administration > General > Provisioning > Connect to repository, repository
URL `https://github.com/dividehex/grafana-dashboards`, branch `main`, path
left empty. Each top-level directory becomes a Grafana folder.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
