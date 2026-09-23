#!/usr/bin/env python3
"""Generate the Grafana dashboard for the ai-gpu-metrics exporter.

Metrics come from ai-gpu-metrics on :9101 of every GPU node (Prometheus job
"ai-gpu"): ai_gpu_* series from NVML, GDDR6/6X junction and VRAM temperatures
from gpu-temps, and GPU memory per pod. Every per-GPU series carries gpu
(NVML index), uuid, name and pci_bus_id. The GPU variable selects by uuid
because the index can change when cards are added.

Usage: python3 build-dashboard.py > dashboard.json

Supersedes ai-server ("AI Server - RTX 3090 / llama-swap"). Inference and
host panels are not carried over: they return with the observability stack.
"""

import json

DS = {"type": "prometheus", "uid": "${datasource}"}
HOST = 'job="$job",instance=~"$instance"'
SEL = f'{HOST},uuid=~"$gpu"'
GPU_LEGEND = "{{name}} ({{gpu}})"
GIB = 1024**3

# Reasons that are configuration, not a throttle; left out of "throttling now".
BENIGN_REASONS = "gpu_idle|applications_clocks_setting|display_clock_setting"

_next_id = 0


def next_id():
    global _next_id
    _next_id += 1
    return _next_id


def thresholds(*steps):
    """steps: (color, value) pairs; the first value may be None for the base colour."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def target(expr, legend="", ref="A", instant=False):
    return {"datasource": DS, "editorMode": "code", "expr": expr, "instant": instant,
            "legendFormat": legend, "range": not instant, "refId": ref}


def targets(*pairs):
    return [target(expr, legend, chr(ord("A") + i)) for i, (expr, legend) in enumerate(pairs)]


def row(title, y):
    return {"collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
            "id": next_id(), "panels": [], "title": title, "type": "row"}


def value_mappings(mapping):
    """{value: (text, color)} -> a Grafana value mapping."""
    return [{"type": "value", "options": {
        str(v): {"text": text, "color": color, "index": i}
        for i, (v, (text, color)) in enumerate(mapping.items())}}]


def stat(title, expr, unit, pos, thr, description="", decimals=0, minimum=0, maximum=None,
         legend=GPU_LEGEND, mappings=None, no_value=None, graph=True):
    defaults = {"color": {"mode": "thresholds"}, "decimals": decimals,
                "mappings": mappings or [], "min": minimum, "thresholds": thr, "unit": unit}
    if maximum is not None:
        defaults["max"] = maximum
    if no_value is not None:
        defaults["noValue"] = no_value
    return {
        "datasource": DS, "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(),
        "options": {"colorMode": "value", "graphMode": "area" if graph else "none",
                    "justifyMode": "auto", "orientation": "auto",
                    "percentChangeColorMode": "standard",
                    "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "showPercentChange": False, "textMode": "auto", "wideLayout": True},
        "pluginVersion": "12.3.1", "targets": [target(expr, legend)],
        "title": title, "type": "stat",
    }


def timeseries(title, tgts, unit, pos, description="", decimals=0, minimum=0, maximum=None,
               stacking="none", overrides=None, interpolation="linear"):
    defaults = {
        "color": {"mode": "palette-classic"},
        "custom": {
            "axisBorderShow": False, "axisCenteredZero": False, "axisColorMode": "text",
            "axisLabel": "", "axisPlacement": "auto", "barAlignment": 0, "barWidthFactor": 0.6,
            "drawStyle": "line", "fillOpacity": 10, "gradientMode": "none",
            "hideFrom": {"legend": False, "tooltip": False, "viz": False},
            "insertNulls": False, "lineInterpolation": interpolation, "lineWidth": 2,
            "pointSize": 5, "scaleDistribution": {"type": "linear"}, "showPoints": "never",
            "showValues": False, "spanNulls": False,
            "stacking": {"group": "A", "mode": stacking}, "thresholdsStyle": {"mode": "off"},
        },
        "decimals": decimals, "mappings": [], "min": minimum,
        "thresholds": thresholds(("green", None), ("red", 80)), "unit": unit,
    }
    if maximum is not None:
        defaults["max"] = maximum
    return {
        "datasource": DS, "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(),
        "options": {"legend": {"calcs": ["lastNotNull", "max", "mean"], "displayMode": "table",
                               "placement": "bottom", "showLegend": True},
                    "tooltip": {"hideZeros": False, "mode": "multi", "sort": "desc"}},
        "pluginVersion": "12.3.1", "targets": tgts, "title": title, "type": "timeseries",
    }


def dashed(name_regex, color=None):
    """Override: series whose name matches are drawn as an unfilled, unstacked dashed line."""
    props = [{"id": "custom.stacking", "value": {"group": "A", "mode": "none"}},
             {"id": "custom.fillOpacity", "value": 0},
             {"id": "custom.lineStyle", "value": {"dash": [10, 10], "fill": "dash"}}]
    if color:
        props.append({"id": "color", "value": {"fixedColor": color, "mode": "fixed"}})
    return {"matcher": {"id": "byRegexp", "options": name_regex}, "properties": props}


def vram_by_workload(pos):
    procs = f"ai_gpu_process_memory_bytes{{{SEL}}}"
    used = f"ai_gpu_memory_used_bytes{{{SEL}}}"
    return timeseries("VRAM by workload", targets(
        (f'sum by (namespace, pod) (ai_gpu_process_memory_bytes{{{SEL},pod!=""}})',
         "{{namespace}}/{{pod}}"),
        (f'sum by (command) (ai_gpu_process_memory_bytes{{{SEL},pod=""}})', "host: {{command}}"),
        # Whatever the card holds beyond the per-process figures is driver and
        # CUDA-context overhead; "or vector(0)" keeps the band when nothing runs.
        (f"sum({used}) - (sum({procs}) or vector(0))", "Other (driver, CUDA context)"),
        (f"sum(ai_gpu_memory_total_bytes{{{SEL}}})", "Total"),
    ), "bytes", pos,
        "GPU memory per pod (namespace/pod), per host process outside Kubernetes, and the "
        "remainder, stacked against the total of the selected GPUs.",
        decimals=1, stacking="normal", overrides=[dashed("^Total$", "text")])


def throttle_timeline(pos):
    expr = f'ai_gpu_clock_event_active{{{SEL},reason!~"applications_clocks_setting|display_clock_setting"}}'
    return {
        "datasource": DS,
        "description": "Why clocks were held down, per GPU and reason. gpu_idle is normal "
                       "at rest; sw_power_cap is the power limit; the thermal and "
                       "hw_slowdown lanes mean the card is protecting itself.",
        "fieldConfig": {"defaults": {
            "color": {"mode": "thresholds"},
            "custom": {"fillOpacity": 80, "hideFrom": {"legend": False, "tooltip": False, "viz": False},
                       "lineWidth": 0},
            "mappings": value_mappings({0: ("", "transparent"), 1: ("active", "red")}),
            "thresholds": thresholds(("green", None))},
            "overrides": [{"matcher": {"id": "byRegexp", "options": ".*gpu_idle$"},
                           "properties": [{"id": "mappings", "value": value_mappings(
                               {0: ("", "transparent"), 1: ("idle", "blue")})}]}]},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(),
        "options": {"alignValue": "left",
                    "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
                    "mergeValues": True, "rowHeight": 0.8, "showValue": "never",
                    "tooltip": {"hideZeros": False, "mode": "single", "sort": "none"}},
        "pluginVersion": "12.3.1", "targets": [target(expr, f"{GPU_LEGEND} {{{{reason}}}}")],
        "title": "Clock event reasons (throttling)", "type": "state-timeline",
    }


def variables():
    datasource = {"current": {"text": "", "value": ""}, "label": "Data source", "name": "datasource",
                  "options": [], "query": "prometheus", "refresh": 1, "regex": "", "type": "datasource"}

    def query_var(name, label, query, multi, regex=""):
        var = {"datasource": DS, "definition": query, "label": label, "name": name, "options": [],
               "query": {"query": query, "refId": "PrometheusVariableQueryEditor-VariableQuery"},
               "refresh": 2, "regex": regex, "sort": 1, "type": "query"}
        if multi:
            var.update({"allValue": ".*", "current": {"text": "All", "value": "$__all"},
                        "includeAll": True, "multi": True})
        else:
            var["current"] = {"text": "", "value": ""}
        return var

    return [
        datasource,
        query_var("job", "Scrape job", "label_values(ai_gpu_info, job)", multi=False),
        query_var("instance", "Host", 'label_values(ai_gpu_info{job="$job"}, instance)', multi=True),
        # Value is the uuid (stable); the dropdown shows the NVML index.
        query_var("gpu", "GPU", f"query_result(ai_gpu_info{{{HOST}}})", multi=True,
                  regex='/gpu="(?<text>[^"]+)".*uuid="(?<value>[^"]+)"/'),
    ]


def build():
    p = []
    flat = thresholds(("green", None))
    pct = thresholds(("green", None), ("yellow", 80), ("red", 95))

    p.append(row("Overview", 0))
    p.append(stat("Utilization", f"ai_gpu_utilization_percent{{{SEL}}}", "percent",
                  (0, 1, 3, 4), pct, "Share of time a kernel was running.", maximum=100))
    p.append(stat("VRAM used", f"100 * ai_gpu_memory_used_bytes{{{SEL}}} / ai_gpu_memory_total_bytes{{{SEL}}}",
                  "percent", (3, 1, 3, 4), thresholds(("green", None), ("yellow", 85), ("red", 96)),
                  "Share of GPU memory allocated.", decimals=1, maximum=100))
    p.append(stat("Core", f'ai_gpu_temperature_celsius{{{SEL},sensor="core"}}', "celsius",
                  (6, 1, 3, 4), thresholds(("green", None), ("yellow", 75), ("orange", 83), ("red", 90)),
                  "GPU core temperature (NVML).", maximum=100))
    p.append(stat("Junction", f'ai_gpu_temperature_celsius{{{SEL},sensor="junction"}}', "celsius",
                  (9, 1, 3, 4), thresholds(("green", None), ("yellow", 85), ("orange", 95), ("red", 100)),
                  "GPU hotspot, read from BAR0 by gpu-temps. Empty on cards without a verified layout.",
                  maximum=110, no_value="n/a"))
    p.append(stat("VRAM temp", f'ai_gpu_temperature_celsius{{{SEL},sensor="vram"}}', "celsius",
                  (12, 1, 3, 4), thresholds(("green", None), ("yellow", 90), ("orange", 100), ("red", 105)),
                  "Hottest GDDR6X module, read from BAR0 by gpu-temps (NVML has no VRAM temperature "
                  "on GeForce). GDDR6X throttles at about 110 C. The RTX 3090 reports in 2 C steps.",
                  maximum=110, no_value="n/a"))
    p.append(stat("Power", f"ai_gpu_power_draw_watts{{{SEL}}}", "watt", (15, 1, 3, 4),
                  thresholds(("green", None), ("yellow", 200), ("red", 240)),
                  "Board power draw. See the power panel for the enforced limit.", maximum=None))
    p.append(stat("Throttling now",
                  f'sum by (gpu, name, uuid) (ai_gpu_clock_event_active{{{SEL},reason!~"{BENIGN_REASONS}"}})',
                  "none", (18, 1, 3, 4), thresholds(("green", None), ("red", 1)),
                  "How many throttle reasons are active, not counting idle and clock settings. "
                  "The timeline below names them.",
                  mappings=value_mappings({0: ("none", "green")}), graph=False))
    p.append(stat("Exporter",
                  f"min(up{{{HOST}}}) * (1 - clamp_max(max(ai_gpu_scrape_errors{{{HOST}}}), 1))",
                  "none", (21, 1, 3, 4), thresholds(("red", None), ("green", 1)),
                  "OK when Prometheus scraped every host and no source (NVML, gpu-temps, pod lookup) "
                  "failed. The Exporter row breaks errors down by source.",
                  legend="", maximum=1, graph=False,
                  mappings=value_mappings({1: ("OK", "green"), 0: ("errors", "red")})))

    p.append(row("Memory", 5))
    p.append(timeseries("VRAM used / total", targets(
        (f"ai_gpu_memory_used_bytes{{{SEL}}}", f"{GPU_LEGEND} used"),
        (f"ai_gpu_memory_total_bytes{{{SEL}}}", f"{GPU_LEGEND} total"),
    ), "bytes", (0, 6, 10, 8), decimals=1, overrides=[dashed("total$")]))
    p.append(vram_by_workload((10, 6, 14, 8)))

    p.append(row("Thermals", 14))
    p.append(timeseries("Temperatures", targets(
        (f"ai_gpu_temperature_celsius{{{SEL}}}", f"{GPU_LEGEND} {{{{sensor}}}}"),
        (f'ai_gpu_temperature_threshold_celsius{{{SEL},threshold="slowdown"}}',
         f"{GPU_LEGEND} core slowdown"),
    ), "celsius", (0, 15, 16, 8),
        "Core (NVML), junction and VRAM (gpu-temps), with the core slowdown threshold dashed.",
        maximum=110, overrides=[dashed("slowdown$", "red")]))
    p.append(timeseries("Fan speed", targets(
        (f"ai_gpu_fan_speed_percent{{{SEL}}}", f"{GPU_LEGEND} fan {{{{fan}}}}"),
    ), "percent", (16, 15, 8, 8), maximum=100))

    p.append(row("Power and clocks", 23))
    p.append(timeseries("Power draw vs limit", targets(
        (f"ai_gpu_power_draw_watts{{{SEL}}}", f"{GPU_LEGEND} draw"),
        (f"ai_gpu_power_limit_watts{{{SEL}}}", f"{GPU_LEGEND} limit"),
    ), "watt", (0, 24, 9, 8), overrides=[dashed("limit$", "red")]))
    p.append(stat("Energy in range",
                  f"sum(increase(ai_gpu_energy_joules_total{{{SEL}}}[$__range])) / 3.6e6",
                  "kwatth", (9, 24, 3, 8), flat, "Energy used by the selected GPUs over the time range.",
                  decimals=2, legend="", graph=False))
    p.append(timeseries("Clocks", targets(
        (f"ai_gpu_clock_hertz{{{SEL}}}", f"{GPU_LEGEND} {{{{clock}}}}"),
        (f'ai_gpu_clock_max_hertz{{{SEL},clock=~"graphics|memory"}}', f"{GPU_LEGEND} {{{{clock}}}} max"),
    ), "hertz", (12, 24, 9, 8), decimals=1, overrides=[dashed("max$")]))
    p.append(stat("P-state", f"ai_gpu_pstate{{{SEL}}}", "none", (21, 24, 3, 8),
                  thresholds(("green", None)),
                  "Performance state: P0 is full performance, P8 is idle.", graph=False,
                  mappings=[{"type": "range", "options": {"from": 0, "to": 15,
                                                          "result": {"text": "P${__value.raw}"}}}]))

    p.append(row("Throttling", 32))
    p.append(throttle_timeline((0, 33, 24, 8)))

    p.append(row("Host totals", 41))
    p.append(stat("GPUs", f"count(ai_gpu_info{{{HOST}}})", "none", (0, 42, 4, 4), flat,
                  "GPUs reporting on the selected hosts.", legend="", graph=False))
    p.append(stat("Total power", f"sum(ai_gpu_power_draw_watts{{{HOST}}})", "watt", (4, 42, 5, 4), flat,
                  "All GPUs on the selected hosts.", legend=""))
    p.append(stat("Total VRAM used",
                  f"sum(ai_gpu_memory_used_bytes{{{HOST}}}) / sum(ai_gpu_memory_total_bytes{{{HOST}}}) * 100",
                  "percent", (9, 42, 5, 4), thresholds(("green", None), ("yellow", 85), ("red", 96)),
                  "All GPUs on the selected hosts.", decimals=1, legend="", maximum=100))
    p.append(stat("PCIe generation", f"ai_gpu_pcie_link_generation{{{SEL}}}", "none", (14, 42, 5, 4), flat,
                  "Current link generation; it drops at idle to save power.", graph=False))
    p.append(stat("PCIe width", f"ai_gpu_pcie_link_width{{{SEL}}}", "none", (19, 42, 5, 4),
                  thresholds(("red", None), ("green", 16)), "Lanes in use; below 16 on an x16 slot "
                  "means a seating or riser problem.", graph=False))

    p.append(row("Exporter", 46))
    p.append(timeseries("Scrape errors by source", targets(
        (f"ai_gpu_scrape_errors{{{HOST}}}", "{{instance}} {{source}}"),
    ), "none", (0, 47, 10, 6),
        "nvml: driver queries; gpu_temps: BAR0 reads; pods: GPU processes whose pod could not be named."))
    p.append(timeseries("Scrape duration", targets(
        (f"ai_gpu_scrape_duration_seconds{{{HOST}}}", "{{instance}}"),
    ), "s", (10, 47, 8, 6), decimals=3))
    p.append(stat("Junction/VRAM sensors", f"ai_gpu_sensor_supported{{{SEL}}}", "none", (18, 47, 6, 6),
                  flat, "Whether gpu-temps has a verified register layout for the card.", graph=False,
                  mappings=value_mappings({1: ("supported", "green"), 0: ("not supported", "orange")})))

    return {
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                                  "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                                  "name": "Annotations & Alerts", "type": "dashboard"}]},
        "description": "NVIDIA GPUs from ai-gpu-metrics: utilisation, memory per pod, "
                       "GDDR6X temperatures, power, clocks, throttling.",
        "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [],
        "panels": p, "preload": False, "refresh": "auto", "schemaVersion": 42,
        "tags": ["ai", "gpu", "nvidia"],
        "templating": {"list": variables()},
        "time": {"from": "now-1h", "to": "now"}, "timepicker": {}, "timezone": "browser",
        "title": "AI GPU", "uid": "ai-gpu", "version": 1,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
