#!/usr/bin/env python3
"""Generate the Grafana dashboard for Context Guard.

Metrics come from Context Guard's /metrics endpoint (src/metrics.rs), scraped
as one job per host: context_guard_health_score / risk_score /
context_utilization_ratio per model, conversations_by_status, the four anomaly
counters (known_value_drift, tool_anomalies, loop_events,
suspicious_identifiers), events_received / events_dropped / processing_errors,
queue_depth and the ingest_batch_size histogram.

Usage: python3 build-dashboard.py > dashboard.json

The Prometheus datasource is a dashboard variable, so the JSON works on any
Grafana instance without editing.
"""

import json

DS = {"type": "prometheus", "uid": "${datasource}"}
JOB = 'job="$job"'
MODEL = 'job="$job",model=~"$model"'
PLUGIN_VERSION = "12.3.1"

# Default status bands from config/context-guard.example.toml: healthy >= 90,
# good >= 75, watch >= 60, degraded >= 40, otherwise reset recommended.
STATUS_COLORS = [("healthy", "green"), ("good", "light-green"), ("watch", "yellow"),
                 ("degraded", "orange"), ("reset_recommended", "red")]
HEALTH_THR = (("red", None), ("orange", 40), ("yellow", 60), ("light-green", 75), ("green", 90))
RISK_THR = (("green", None), ("light-green", 11), ("yellow", 26), ("orange", 41), ("red", 61))
# Context pressure penalty tiers: 70 %, 80 %, 90 % of the model's context limit.
CONTEXT_THR = (("green", None), ("yellow", 70), ("orange", 80), ("red", 90))

ANOMALY_FAMILIES = [
    ("context_guard_known_value_drift_total", "Known-value drift"),
    ("context_guard_tool_anomalies_total", "Tool anomalies"),
    ("context_guard_loop_events_total", "Loop events"),
    ("context_guard_suspicious_identifiers_total", "Suspicious identifiers"),
]
# Matches every anomaly counter at once, so a model missing one family is still counted.
ANOMALY_NAME_RE = "|".join(m for m, _ in ANOMALY_FAMILIES)

_next_id = 0


def next_id():
    global _next_id
    _next_id += 1
    return _next_id


def thresholds(*steps):
    """steps: (color, value) pairs; the first value may be None for the base colour."""
    return {"mode": "absolute", "steps": [{"color": c, "value": v} for c, v in steps]}


def fixed_color(name, color):
    return {"matcher": {"id": "byName", "options": name},
            "properties": [{"id": "color", "value": {"fixedColor": color, "mode": "fixed"}}]}


def target(expr, legend="", ref="A"):
    return {"datasource": DS, "editorMode": "code", "expr": expr,
            "legendFormat": legend, "range": True, "refId": ref}


def targets(*pairs):
    return [target(expr, legend, chr(ord("A") + i)) for i, (expr, legend) in enumerate(pairs)]


def in_range(counter, by=""):
    """Increase of a counter over the dashboard time range, summed across the selection."""
    group = f" by ({by})" if by else ""
    return f"sum{group}(increase({counter}{{{MODEL}}}[$__range]))"


def row(title, y):
    return {"collapsed": False, "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
            "id": next_id(), "panels": [], "title": title, "type": "row"}


def panel(kind, title, tgts, pos, defaults, options, description="", overrides=None):
    return {
        "datasource": DS, "description": description,
        "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
        "gridPos": dict(zip("xywh", pos)), "id": next_id(), "options": options,
        "pluginVersion": PLUGIN_VERSION, "targets": tgts, "title": title, "type": kind,
    }


def stat(title, tgts, unit, pos, thr, description="", decimals=0, minimum=0, maximum=None,
         overrides=None):
    defaults = {"color": {"mode": "thresholds"}, "decimals": decimals, "mappings": [],
                "min": minimum, "thresholds": thresholds(*thr), "unit": unit}
    if maximum is not None:
        defaults["max"] = maximum
    options = {"colorMode": "value", "graphMode": "area", "justifyMode": "auto",
               "orientation": "auto", "percentChangeColorMode": "standard",
               "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
               "showPercentChange": False, "textMode": "auto", "wideLayout": True}
    return panel("stat", title, tgts, pos, defaults, options, description, overrides)


def timeseries(title, tgts, unit, pos, description="", decimals=0, minimum=0, maximum=None,
               stacking="none", draw_style="line", thr=None, overrides=None):
    """thr, when given, is drawn as dashed guide lines on the graph."""
    defaults = {
        "color": {"mode": "palette-classic"},
        "custom": {
            "axisBorderShow": False, "axisCenteredZero": False, "axisColorMode": "text",
            "axisLabel": "", "axisPlacement": "auto", "barAlignment": 0, "barWidthFactor": 0.6,
            "drawStyle": draw_style, "fillOpacity": 10 if draw_style == "line" else 60,
            "gradientMode": "none",
            "hideFrom": {"legend": False, "tooltip": False, "viz": False},
            "insertNulls": False, "lineInterpolation": "linear", "lineWidth": 2, "pointSize": 5,
            "scaleDistribution": {"type": "linear"}, "showPoints": "never", "showValues": False,
            "spanNulls": False, "stacking": {"group": "A", "mode": stacking},
            "thresholdsStyle": {"mode": "dashed" if thr else "off"},
        },
        "decimals": decimals, "mappings": [], "min": minimum,
        "thresholds": thresholds(*(thr or (("green", None),))), "unit": unit,
    }
    if maximum is not None:
        defaults["max"] = maximum
    options = {"legend": {"calcs": ["lastNotNull", "max", "mean"], "displayMode": "table",
                          "placement": "bottom", "showLegend": True},
               "tooltip": {"hideZeros": False, "mode": "multi", "sort": "desc"}}
    return panel("timeseries", title, tgts, pos, defaults, options, description, overrides)


def bargauge(title, tgts, pos, description=""):
    defaults = {"color": {"mode": "palette-classic"}, "decimals": 0, "mappings": [], "min": 0,
                "thresholds": thresholds(("green", None)), "unit": "short"}
    options = {"displayMode": "gradient", "legend": {"calcs": [], "displayMode": "list",
                                                      "placement": "bottom", "showLegend": False},
               "maxVizHeight": 300, "minVizHeight": 16, "minVizWidth": 8, "namePlacement": "auto",
               "orientation": "horizontal",
               "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
               "showUnfilled": True, "sizing": "auto", "valueMode": "color"}
    return panel("bargauge", title, tgts, pos, defaults, options, description)


def status_targets():
    """One target per status, in severity order, so panels list them consistently."""
    return targets(*[(f'context_guard_conversations_by_status{{{JOB},status="{s}"}}', s)
                     for s, _ in STATUS_COLORS])


def status_overrides():
    return [fixed_color(s, c) for s, c in STATUS_COLORS]


def variables():
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
        query_var("job", "Scrape job", "context_guard_queue_depth", "job", multi=False),
        query_var("model", "Model", f'context_guard_health_score{{{JOB}}}', "model", multi=True),
    ]


def current_state(p):
    p.append(row("Current state", 0))
    p.append(stat("Health score", targets((f"context_guard_health_score{{{MODEL}}}", "{{model}}")),
                  "none", (0, 1, 5, 5), HEALTH_THR,
                  "Health of the most recently scored turn per model, 0-100. "
                  "Bands: healthy >= 90, good >= 75, watch >= 60, degraded >= 40, otherwise reset recommended.",
                  maximum=100))
    p.append(stat("Risk score", targets((f"context_guard_risk_score{{{MODEL}}}", "{{model}}")),
                  "none", (5, 1, 4, 5), RISK_THR,
                  "Sum of reason penalties for the most recently scored turn per model (100 - health).",
                  maximum=100))
    p.append(stat("Context utilization",
                  targets((f"100 * context_guard_context_utilization_ratio{{{MODEL}}}", "{{model}}")),
                  "percent", (9, 1, 5, 5), CONTEXT_THR,
                  "Prompt tokens as a share of the model's context limit on the most recent turn. "
                  "Penalties start at 70 %.", decimals=1, maximum=100))
    p.append(stat("Active conversations",
                  targets((f"sum(context_guard_conversations_by_status{{{JOB}}})", "")),
                  "none", (14, 1, 3, 5), (("green", None),),
                  "Conversations scored in the last 24 hours."))
    p.append(stat("Needing attention",
                  targets((f'sum(context_guard_conversations_by_status{{{JOB},status=~"degraded|reset_recommended"}})', "")),
                  "none", (17, 1, 3, 5), (("green", None), ("orange", 1), ("red", 3)),
                  "Conversations active in the last 24 hours whose latest status is degraded or reset recommended."))
    p.append(stat("Ingest queue", targets((f"context_guard_queue_depth{{{JOB}}}", "")),
                  "none", (20, 1, 2, 5), (("green", None), ("yellow", 64), ("red", 512)),
                  "Ingest batches waiting for the worker. The queue holds 1024 batches by default; "
                  "when it is full new batches are dropped and counted."))
    p.append(stat("Exporter", targets((f"up{{{JOB}}}", "")),
                  "none", (22, 1, 2, 5), (("red", None), ("green", 1)),
                  "1 when Prometheus scraped Context Guard on its last attempt.", maximum=1))


def conversation_health(p):
    p.append(row("Conversation health", 6))
    p.append(timeseries("Health score", targets((f"context_guard_health_score{{{MODEL}}}", "{{model}}")),
                        "none", (0, 7, 12, 8),
                        "Latest scored turn per model. Dashed lines mark the status bands.",
                        maximum=100, thr=HEALTH_THR))
    p.append(timeseries("Context utilization",
                        targets((f"100 * context_guard_context_utilization_ratio{{{MODEL}}}", "{{model}}")),
                        "percent", (12, 7, 12, 8),
                        "Prompt tokens as a share of the context limit on the latest turn per model. "
                        "Dashed lines mark the 70 / 80 / 90 % penalty tiers.",
                        decimals=1, maximum=100, thr=CONTEXT_THR))
    p.append(stat("Conversations by status",
                  status_targets(),
                  "none", (0, 15, 8, 6), (("text", None),),
                  "Conversations active in the last 24 hours by their latest status.",
                  overrides=status_overrides()))
    p.append(timeseries("Conversations by status over time",
                        status_targets(),
                        "none", (8, 15, 16, 6), "Same counts over time, stacked.",
                        stacking="normal", overrides=status_overrides()))


def anomalies(p):
    p.append(row("Anomalies", 21))
    p.append(timeseries("Anomalies by family",
                        targets(*[(f"sum(increase({m}{{{MODEL}}}[$__interval]))", label)
                                  for m, label in ANOMALY_FAMILIES]),
                        "short", (0, 22, 12, 8),
                        "New anomalies per interval across the selected models, stacked by family.",
                        stacking="normal", draw_style="bars"))
    p.append(timeseries("Anomalies by model",
                        targets((f'sum by (model) (increase({{__name__=~"{ANOMALY_NAME_RE}",{MODEL}}}[$__interval]))',
                                 "{{model}}")),
                        "short", (12, 22, 12, 8),
                        "New anomalies per interval of any family, stacked by model.",
                        stacking="normal", draw_style="bars"))
    p.append(bargauge("Anomalies in range by signal", targets(
        (in_range("context_guard_known_value_drift_total"), "known_value_drift"),
        (in_range("context_guard_tool_anomalies_total", by="signal"), "{{signal}}"),
        (in_range("context_guard_loop_events_total", by="signal"), "{{signal}}"),
        (in_range("context_guard_suspicious_identifiers_total"), "suspicious_identifier"),
    ), (0, 30, 12, 7),
        "Anomalies detected over the selected time range, by signal. Tool anomalies are "
        "tool_result_without_call and tool_call_id_reference_unknown; loop events are "
        "repeated_tool_call and response_loop."))
    for i, (metric, label) in enumerate(ANOMALY_FAMILIES):
        p.append(stat(f"{label} in range", targets((f"{in_range(metric)} or vector(0)", "")), "short",
                      (12 + 3 * i, 30, 3, 7), (("green", None), ("yellow", 1), ("red", 5)),
                      f"{label} across the selected models over the selected time range."))


def ingest_pipeline(p):
    p.append(row("Ingest pipeline", 37))
    p.append(timeseries("Events received", targets(
        (f"sum by (kind) (rate(context_guard_events_received_total{{{JOB}}}[$__rate_interval]))", "{{kind}}"),
    ), "short", (0, 38, 8, 7),
        "Telemetry events per second by kind: chat turns are scored, task calls (title, tags, "
        "follow-ups) and failures are recorded only, except context-overflow failures.",
        decimals=2, stacking="normal"))
    p.append(timeseries("Dropped events and processing errors", targets(
        (f"sum by (reason) (increase(context_guard_events_dropped_total{{{JOB}}}[$__interval]))", "dropped: {{reason}}"),
        (f"sum by (stage) (increase(context_guard_processing_errors_total{{{JOB}}}[$__interval]))", "error: {{stage}}"),
    ), "short", (8, 38, 8, 7),
        "Payloads rejected before processing (malformed, unsupported call type, queue full) and "
        "events whose processing failed. Both are skipped; the worker continues.",
        draw_style="bars"))
    p.append(timeseries("Ingest queue depth", targets((f"context_guard_queue_depth{{{JOB}}}", "queued batches")),
                        "none", (16, 38, 8, 7),
                        "Ingest batches waiting for the worker, sampled at each scrape. Sustained "
                        "growth means the worker cannot keep up with LiteLLM's flushes."))
    p.append(timeseries("Ingest batches", targets(
        (f"sum(rate(context_guard_ingest_batch_size_count{{{JOB}}}[$__rate_interval]))", "batches/s"),
        (f"sum(rate(context_guard_ingest_batch_size_sum{{{JOB}}}[$__rate_interval])) / "
         f"sum(rate(context_guard_ingest_batch_size_count{{{JOB}}}[$__rate_interval]))", "mean payloads per batch"),
        (f"histogram_quantile(0.95, sum by (le) (rate(context_guard_ingest_batch_size_bucket{{{JOB}}}[$__rate_interval])))",
         "p95 payloads per batch"),
    ), "short", (0, 45, 12, 6),
        "LiteLLM flushes one batch per DEFAULT_FLUSH_INTERVAL_SECONDS; the batch size is the "
        "number of completions in it.", decimals=2))
    p.append(stat("Events in range",
                  targets((f"sum(increase(context_guard_events_received_total{{{JOB}}}[$__range])) or vector(0)", "")),
                  "short", (12, 45, 4, 6), (("green", None),),
                  "Telemetry events of every kind over the selected time range."))
    p.append(stat("Dropped in range",
                  targets((f"sum(increase(context_guard_events_dropped_total{{{JOB}}}[$__range])) or vector(0)", "")),
                  "short", (16, 45, 4, 6), (("green", None), ("red", 1)),
                  "Payloads dropped over the selected time range."))
    p.append(stat("Errors in range",
                  targets((f"sum(increase(context_guard_processing_errors_total{{{JOB}}}[$__range])) or vector(0)", "")),
                  "short", (20, 45, 4, 6), (("green", None), ("red", 1)),
                  "Processing errors over the selected time range."))


def build():
    p = []
    current_state(p)
    conversation_health(p)
    anomalies(p)
    ingest_pipeline(p)
    return {
        "annotations": {"list": [{"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                                  "enable": True, "hide": True, "iconColor": "rgba(0, 211, 255, 1)",
                                  "name": "Annotations & Alerts", "type": "dashboard"}]},
        "editable": True, "fiscalYearStartMonth": 0, "graphTooltip": 1, "links": [],
        "panels": p, "preload": False, "refresh": "auto", "schemaVersion": 42,
        "tags": ["ai", "context-guard", "litellm", "open-webui"],
        "templating": {"list": variables()},
        "time": {"from": "now-6h", "to": "now"}, "timepicker": {}, "timezone": "browser",
        "title": "Context Guard", "uid": "context-guard", "version": 1,
    }


if __name__ == "__main__":
    print(json.dumps(build(), indent=2, ensure_ascii=False))
