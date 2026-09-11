#!/usr/bin/env python3
"""Generate the Grafana dashboard for the llama-swap metrics collector.

Metrics come from ai-llama-metrics on :9101 (see scripts/llama-metrics/collector.py):
llamaswap_* host/GPU gauges, gputemps_* core/junction/VRAM temperatures,
llamacpp:* per-model series labelled model="...", llama_metrics_model_state,
llama_metrics_scrape_errors, and on Octominer rigs octofan_* case fan, ambient
climate and hardware watchdog readings.

Usage: python3 build-dashboard.py > dashboard.json

The uid matches the original DCGM/llama.cpp dashboard so importing this file
(with "overwrite") replaces it in place. The Prometheus datasource is a
dashboard variable, so the JSON works on any Grafana instance without editing.
"""

import json

DS = {"type": "prometheus", "uid": "${datasource}"}
GPU = 'job="$job",id=~"$gpu"'
MODEL = 'job="$job",model=~"$model"'
JOB = 'job="$job"'

_next_id = 0


def next_id():
    global _next_id
    _next_id += 1
    return _next_id


def thresholds(*steps):
    """steps: (color, value) pairs; the first value may be None for the base colour."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def target(expr, legend="", ref="A"):
    return {"datasource": DS, "editorMode": "code", "expr": expr,
            "legendFormat": legend, "range": True, "refId": ref}


def targets(*pairs):
    return [target(expr, legend, chr(ord("A") + i)) for i, (expr, legend) in enumerate(pairs)]


def row(title, y):
    return {"collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
            "id": next_id(), "panels": [], "title": title, "type": "row"}


def stat(title, expr, unit, pos, thr, description="", decimals=0, minimum=0, maximum=None,
         legend="", text_mode="auto"):
    defaults = {"color": {"mode": "thresholds"}, "decimals": decimals, "mappings": [],
                "min": minimum, "thresholds": thr, "unit": unit}
    if maximum is not None:
        defaults["max"] = maximum
    return {
        "datasource": DS, "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(),
        "options": {"colorMode": "value", "graphMode": "area", "justifyMode": "auto",
                    "orientation": "auto", "percentChangeColorMode": "standard",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "showPercentChange": False, "textMode": text_mode, "wideLayout": True},
        "pluginVersion": "12.3.1", "targets": [target(expr, legend)],
        "title": title, "type": "stat",
    }


def timeseries(title, tgts, unit, pos, description="", decimals=0, minimum=0, maximum=None,
               stacking="none"):
    defaults = {
        "color": {"mode": "palette-classic"},
        "custom": {
            "axisBorderShow": False, "axisCenteredZero": False, "axisColorMode": "text",
            "axisLabel": "", "axisPlacement": "auto", "barAlignment": 0, "barWidthFactor": 0.6,
            "drawStyle": "line", "fillOpacity": 10, "gradientMode": "none",
            "hideFrom": {"legend": False, "tooltip": False, "viz": False},
            "insertNulls": False, "lineInterpolation": "linear", "lineWidth": 2, "pointSize": 5,
            "scaleDistribution": {"type": "linear"}, "showPoints": "never", "showValues": False,
            "spanNulls": False, "stacking": {"group": "A", "mode": stacking},
            "thresholdsStyle": {"mode": "off"},
        },
        "decimals": decimals, "mappings": [], "min": minimum,
        "thresholds": thresholds(("green", None), ("red", 80)), "unit": unit,
    }
    if maximum is not None:
        defaults["max"] = maximum
    return {
        "datasource": DS, "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(),
        "options": {"legend": {"calcs": ["lastNotNull", "max", "mean"], "displayMode": "table",
                               "placement": "bottom", "showLegend": True},
                    "tooltip": {"hideZeros": False, "mode": "multi", "sort": "desc"}},
        "pluginVersion": "12.3.1", "targets": tgts, "title": title, "type": "timeseries",
    }


def loaded_models_table(pos):
    return {
        "datasource": DS,
        "description": "Models llama-swap currently has loaded, from llama_metrics_model_state.",
        "fieldConfig": {"defaults": {"color": {"mode": "thresholds"}, "mappings": [],
                                     "thresholds": thresholds(("green", None))},
                        "overrides": []},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(),
        "options": {"cellHeight": "sm", "footer": {"show": False}, "showHeader": True},
        "pluginVersion": "12.3.1",
        "targets": [{**target(f"llama_metrics_model_state{{{JOB}}}", "", "A"),
                     "format": "table", "instant": True, "range": False}],
        "transformations": [
            {"id": "organize", "options": {
                "excludeByName": {"Time": True, "Value": True, "__name__": True,
                                  "instance": True, "job": True},
                "indexByName": {"model": 0, "state": 1},
                "renameByName": {"model": "Model", "state": "State"}}},
        ],
        "title": "Loaded models", "type": "table",
    }


def variables():
    def custom(name, label, options, current):
        return {"current": {"text": current, "value": current}, "label": label, "name": name,
                "options": [{"selected": o == current, "text": o, "value": o} for o in options],
                "query": ",".join(options), "type": "custom"}

    def query_var(name, label, metric, lbl, multi):
        q = f"label_values({metric}, {lbl})"
        var = {"datasource": DS, "definition": q, "label": label, "name": name, "options": [],
               "query": {"query": q, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
               "refresh": 1, "sort": 1, "type": "query"}
        if multi:
            var.update({"allValue": ".*", "current": {"text": "All", "value": "$__all"},
                        "includeAll": True, "multi": True})
        else:
            var["current"] = {"text": "", "value": ""}
        return var

    datasource = {"current": {"text": "", "value": ""}, "label": "Data source", "name": "datasource",
                  "options": [], "query": "prometheus", "refresh": 1, "regex": "", "type": "datasource"}

    return [
        datasource,
        query_var("job", "Scrape job", "llamaswap_gpu_util_percent", "job", multi=False),
        query_var("gpu", "GPU", 'llamaswap_gpu_util_percent{job="$job"}', "id", multi=True),
        query_var("model", "Model", 'llamacpp:n_tokens_max{job="$job"}', "model", multi=True),
        custom("context_size", "Context size", ["16384", "32768", "65536", "131072"], "32768"),
    ]


def build():
    p = []
    vram_thr = thresholds(("green", None), ("yellow", 20 * 1024**3), ("red", 23 * 1024**3))
    temp_thr = thresholds(("green", None), ("yellow", 70), ("orange", 80), ("red", 85))
    pct_thr = thresholds(("green", None), ("yellow", 70), ("red", 95))
    flat = thresholds(("green", None))

    # Current state
    p.append(row("Current state", 0))
    p.append(stat("GPU utilization", f"llamaswap_gpu_util_percent{{{GPU}}}", "percent",
                  (0, 1, 3, 4), pct_thr, "Current GPU utilization.", maximum=100))
    p.append(stat("VRAM used", f"llamaswap_gpu_memory_used_bytes{{{GPU}}}", "bytes",
                  (3, 1, 3, 4), vram_thr, "GPU memory in use.", maximum=24 * 1024**3))
    p.append(stat("GPU temperature", f"gputemps_core_temperature_celsius{{{GPU}}}", "celsius",
                  (6, 1, 3, 4), temp_thr, "GPU core temperature (gputemps).", maximum=100))
    p.append(stat("VRAM temperature", f"gputemps_vram_temperature_celsius{{{GPU}}}", "celsius",
                  (9, 1, 3, 4), thresholds(("green", None), ("yellow", 85), ("orange", 95), ("red", 105)),
                  "GDDR6X memory temperature read by gputemps (NVML reports 0 on GeForce).", maximum=110))
    p.append(stat("GPU power", f"llamaswap_gpu_power_draw_watts{{{GPU}}}", "watt",
                  (12, 1, 3, 4), thresholds(("green", None), ("yellow", 280), ("red", 340)),
                  "GPU board power draw.", maximum=350))
    p.append(stat("Generation speed", f"llamacpp:predicted_tokens_seconds{{{MODEL}}}", "none",
                  (15, 1, 3, 4), flat, "llama.cpp generation throughput in tokens per second (last request).",
                  decimals=1, legend="{{model}}"))
    p.append(stat("Prompt speed", f"llamacpp:prompt_tokens_seconds{{{MODEL}}}", "none",
                  (18, 1, 3, 4), flat, "llama.cpp prompt-evaluation throughput in tokens per second (last request).",
                  decimals=1, legend="{{model}}"))
    p.append(stat("Collector health", f"min(up{{{JOB}}}) * ((1 - clamp_max(max(llama_metrics_scrape_errors{{{JOB}}}), 1)) or vector(1))",
                  "none", (21, 1, 3, 4),
                  thresholds(("red", None), ("green", 1)),
                  "1 when Prometheus scraped the collector and every upstream fetch succeeded. "
                  "0 when the scrape failed or the collector could not reach llama-swap or a model.",
                  maximum=1))

    # GPU utilization and memory
    p.append(row("GPU utilization and memory", 5))
    p.append(timeseries("GPU utilization", targets(
        (f"llamaswap_gpu_util_percent{{{GPU}}}", "GPU {{id}} core"),
        (f"llamaswap_gpu_memory_util_percent{{{GPU}}}", "GPU {{id}} memory controller"),
    ), "percent", (0, 6, 12, 8), maximum=100))
    p.append(timeseries("VRAM used / total", targets(
        (f"llamaswap_gpu_memory_used_bytes{{{GPU}}}", "Used"),
        (f"llamaswap_gpu_memory_total_bytes{{{GPU}}}", "Total"),
    ), "bytes", (12, 6, 12, 8)))
    p.append(stat("VRAM allocated",
                  f"100 * llamaswap_gpu_memory_used_bytes{{{GPU}}} / llamaswap_gpu_memory_total_bytes{{{GPU}}}",
                  "percent", (0, 14, 6, 5),
                  thresholds(("green", None), ("yellow", 80), ("orange", 90), ("red", 96)),
                  "Share of GPU memory in use.", decimals=1, maximum=100))
    p.append(timeseries("Fan speed", targets((f"llamaswap_gpu_fan_speed_percent{{{GPU}}}", "GPU {{id}} fan")),
                        "percent", (6, 14, 18, 5), maximum=100))

    # Thermals and power
    p.append(row("Thermals and power", 19))
    p.append(timeseries("Temperatures", targets(
        (f"gputemps_core_temperature_celsius{{{GPU}}}", "GPU core"),
        (f"gputemps_junction_temperature_celsius{{{GPU}}}", "Junction"),
        (f"gputemps_vram_temperature_celsius{{{GPU}}}", "VRAM"),
    ), "celsius", (0, 20, 12, 8), maximum=110))
    p.append(timeseries("Power draw", targets((f"llamaswap_gpu_power_draw_watts{{{GPU}}}", "Power")),
                        "watt", (12, 20, 12, 8), maximum=350))

    # Case fans and ambient (Octominer fan controller; rigs only, empty on other jobs)
    p.append(row("Case fans and ambient", 28))
    p.append(timeseries("Case fans", targets((f"octofan_fan_rpm{{{JOB}}}", "Fan {{channel}}")),
                        "rotrpm", (0, 29, 10, 8),
                        "Case fan tachometer per controller channel (octofan_fan_rpm). Only channels with a fan attached are reported."))
    p.append(stat("Case fan level", f"100 * avg(octofan_fan_pwm{{{JOB}}}) / 255", "percent",
                  (10, 29, 4, 4), thresholds(("green", None), ("yellow", 70), ("red", 90)),
                  "Average PWM setting of the case fans as a percentage of full speed.", maximum=100))
    p.append(stat("Watchdog resets", f"octofan_watchdog_resets_total{{{JOB}}}", "none",
                  (10, 33, 4, 4), flat,
                  "Board resets triggered by the fan controller's hardware watchdog since it was built. "
                  "An increase means the OS stopped feeding it: the rig hung or the feeder service died."))
    p.append(timeseries("Ambient temperature", targets((f"octofan_ambient_temperature_celsius{{{JOB}}}", "Ambient")),
                        "celsius", (14, 29, 5, 8), "BME280 sensor on the fan controller, near the intake.",
                        decimals=1))
    p.append(timeseries("Ambient humidity", targets((f"octofan_ambient_humidity_percent{{{JOB}}}", "Humidity")),
                        "humidity", (19, 29, 5, 8), "BME280 relative humidity.", decimals=1, maximum=100))

    # Host
    p.append(row("Host", 37))
    p.append(timeseries("CPU utilization", targets(
        (f"avg(llamaswap_cpu_util_percent{{{JOB}}})", "All cores"),
        (f"max(llamaswap_cpu_util_percent{{{JOB}}})", "Busiest core"),
    ), "percent", (0, 38, 8, 7), "Average and busiest core, from llama-swap's per-core gauge.",
        maximum=100))
    p.append(timeseries("System memory", targets(
        (f"llamaswap_memory_used_bytes{{{JOB}}}", "RAM used"),
        (f"llamaswap_memory_total_bytes{{{JOB}}}", "RAM total"),
        (f"llamaswap_swap_used_bytes{{{JOB}}}", "Swap used"),
    ), "bytes", (8, 38, 8, 7), "Models with CPU-offloaded experts (qwen3-30b-a3b) show up here."))
    p.append(timeseries("Load average", targets((f"llamaswap_load_average{{{JOB}}}", "{{interval}}")),
                        "none", (16, 38, 8, 7), decimals=2))

    # LLM inference performance
    p.append(row("LLM inference performance", 45))
    p.append(timeseries("Prompt and generation throughput", targets(
        (f"llamacpp:prompt_tokens_seconds{{{MODEL}}}", "{{model}} prompt tok/s"),
        (f"llamacpp:predicted_tokens_seconds{{{MODEL}}}", "{{model}} generation tok/s"),
    ), "none", (0, 46, 12, 8), "Per-request speed reported by each llama-server.", decimals=1))
    p.append(timeseries("GPU utilization vs inference", targets(
        (f"llamaswap_gpu_util_percent{{{GPU}}}", "GPU utilization %"),
        (f"100 * llamacpp:requests_processing{{{MODEL}}}", "{{model}} busy (100 = processing)"),
    ), "percent", (12, 46, 12, 8),
        "Correlate GPU load with inference activity. The busy trace is 100 while a request is being processed.",
        maximum=100))
    p.append(timeseries("Average throughput over range", targets(
        (f"increase(llamacpp:prompt_tokens_total{{{MODEL}}}[$__range]) / increase(llamacpp:prompt_seconds_total{{{MODEL}}}[$__range])",
         "{{model}} prompt tok/s"),
        (f"increase(llamacpp:tokens_predicted_total{{{MODEL}}}[$__range]) / increase(llamacpp:tokens_predicted_seconds_total{{{MODEL}}}[$__range])",
         "{{model}} generation tok/s"),
    ), "none", (0, 54, 12, 7),
        "Tokens divided by seconds spent, over the selected time range. Smoother than the per-request gauges.",
        decimals=1))
    p.append(timeseries("Prompt cache hit rate", targets(
        (f"100 * increase(llamacpp:prompt_tokens_cached_total{{{MODEL}}}[$__rate_interval]) / "
         f"(increase(llamacpp:prompt_tokens_cached_total{{{MODEL}}}[$__rate_interval]) + increase(llamacpp:prompt_tokens_total{{{MODEL}}}[$__rate_interval]))",
         "{{model}}"),
    ), "percent", (12, 54, 12, 7),
        "Share of prompt tokens served from the KV cache instead of being re-evaluated.",
        decimals=1, maximum=100))

    # Context
    p.append(row("Context", 61))
    p.append(stat("Context high-water", f"llamacpp:n_tokens_max{{{MODEL}}}", "none", (0, 62, 6, 5),
                  thresholds(("green", None), ("yellow", 24576), ("red", 31000)),
                  "Highest observed context token count per loaded model.", legend="{{model}}"))
    p.append(stat("Max context used", f"100 * llamacpp:n_tokens_max{{{MODEL}}} / $context_size",
                  "percent", (6, 62, 6, 5),
                  thresholds(("green", None), ("yellow", 75), ("orange", 90), ("red", 97)),
                  "Highest observed context as a percentage of the selected context size.",
                  decimals=1, maximum=100, legend="{{model}}"))
    p.append(timeseries("Context high-water over time", targets(
        (f"llamacpp:n_tokens_max{{{MODEL}}}", "{{model}}")), "none", (12, 62, 12, 5)))

    # Request load
    p.append(row("Request load", 67))
    p.append(timeseries("Processing and deferred requests", targets(
        (f"llamacpp:requests_processing{{{MODEL}}}", "{{model}} processing"),
        (f"llamacpp:requests_deferred{{{MODEL}}}", "{{model}} deferred"),
    ), "none", (0, 68, 12, 8),
        "With --parallel 1, processing should normally be 0-1; deferred requests indicate queueing."))
    p.append(stat("Deferred requests", f"sum(llamacpp:requests_deferred{{{MODEL}}})", "none",
                  (12, 68, 4, 8), thresholds(("green", None), ("yellow", 1), ("red", 2)),
                  "Requests waiting for an inference slot across loaded models."))
    p.append(stat("Collector fetch errors", f"llama_metrics_scrape_errors{{{JOB}}}", "none",
                  (16, 68, 4, 8), thresholds(("green", None), ("red", 1)),
                  "Upstream fetches (llama-swap or a llama-server) that failed on the last scrape."))
    p.append(loaded_models_table((20, 68, 4, 8)))

    # Token workload
    p.append(row("Token workload", 76))
    p.append(stat("Prompt tokens in range", f"sum(increase(llamacpp:prompt_tokens_total{{{MODEL}}}[$__range]))",
                  "short", (0, 77, 6, 6), flat, "Across selected models."))
    p.append(stat("Generated tokens in range", f"sum(increase(llamacpp:tokens_predicted_total{{{MODEL}}}[$__range]))",
                  "short", (6, 77, 6, 6), flat, "Across selected models."))
    p.append(timeseries("Token rate", targets(
        (f"rate(llamacpp:prompt_tokens_total{{{MODEL}}}[$__rate_interval])", "{{model}} prompt tokens/s"),
        (f"rate(llamacpp:tokens_predicted_total{{{MODEL}}}[$__rate_interval])", "{{model}} generated tokens/s"),
    ), "none", (12, 77, 12, 6), decimals=1))
    p.append(timeseries("Tokens by model", targets(
        (f"increase(llamacpp:tokens_predicted_total{{{MODEL}}}[$__interval])", "{{model}}"),
    ), "short", (0, 83, 24, 6), "Generated tokens per interval, stacked by model.", stacking="normal"))

    return {
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                                  "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                                  "name": "Annotations & Alerts", "type": "dashboard"}]},
        "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [],
        "panels": p, "preload": False, "refresh": "auto", "schemaVersion": 42,
        "tags": ["ai", "llama-swap", "llama.cpp", "rtx3090"],
        "templating": {"list": variables()},
        "time": {"from": "now-15m", "to": "now"}, "timepicker": {}, "timezone": "browser",
        "title": "AI Server — RTX 3090 / llama-swap", "uid": "ai-rtx3090-qwen3", "version": 1,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
