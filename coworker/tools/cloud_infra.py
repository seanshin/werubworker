"""Cloud infrastructure tools — AWS, Cloudflare, and Wasabi.

Credentials are read from ``secrets.json`` via the ``SecretStore`` pattern.
AWS and Wasabi use ``boto3`` (already installed). Cloudflare uses ``httpx`` REST API.

Read-only tools don't require approval; mutating tools (DNS update, cache purge,
file upload) do.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

import aisuite as ai

from ..secrets import SecretStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CF_BASE = "https://api.cloudflare.com/client/v4"


def _get_secrets(context: Any) -> SecretStore:
    """Extract SecretStore from context (AgentContext or direct)."""
    if hasattr(context, "secrets") and context.secrets is not None:
        return context.secrets
    return SecretStore()


def _aws_creds(secrets: SecretStore) -> Optional[dict[str, Any]]:
    return secrets.get("aws:default")


def _cf_creds(secrets: SecretStore) -> Optional[dict[str, Any]]:
    return secrets.get("cloudflare:default")


def _wasabi_creds(secrets: SecretStore) -> Optional[dict[str, Any]]:
    return secrets.get("wasabi:default")


def _boto3_client(service: str, creds: dict[str, Any], **kwargs: Any) -> Any:
    import boto3

    return boto3.client(
        service,
        aws_access_key_id=creds.get("access_key_id") or creds.get("access_key"),
        aws_secret_access_key=creds.get("secret_access_key") or creds.get("secret_key"),
        region_name=kwargs.pop("region", None) or creds.get("region", "us-east-1"),
        endpoint_url=kwargs.pop("endpoint_url", None),
        **kwargs,
    )


def _cf_headers(creds: dict[str, Any]) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {creds['api_token']}",
        "Content-Type": "application/json",
    }


def _parse_period(period: str) -> timedelta:
    """Parse a human period string like '1h', '7d', '30m' into a timedelta."""
    period = period.strip().lower()
    try:
        if period.endswith("d"):
            return timedelta(days=int(period[:-1]))
        if period.endswith("h"):
            return timedelta(hours=int(period[:-1]))
        if period.endswith("m"):
            return timedelta(minutes=int(period[:-1]))
        return timedelta(hours=int(period))
    except ValueError:
        return timedelta(hours=1)


# ---------------------------------------------------------------------------
# Schema helpers (mirrors ssh/tools.py pattern)
# ---------------------------------------------------------------------------


def _meta(name: str, *, approval: bool = False, capabilities: list[str] | None = None):
    return ai.ToolMetadata(
        name=name,
        category="cloud_infra",
        risk_level="medium" if approval else "low",
        capabilities=capabilities or ["cloud"],
        requires_approval=approval,
    )


def _schema(
    name: str, description: str, properties: dict[str, Any], required: list[str]
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _attach(
    fn: Callable[..., Any],
    schema: dict[str, Any],
    *,
    approval: bool = False,
    caps: list[str] | None = None,
) -> Callable[..., Any]:
    name = schema["function"]["name"]
    fn.__coworker_schema__ = schema
    fn.__aisuite_tool_metadata__ = _meta(name, approval=approval, capabilities=caps)
    fn.__doc__ = schema["function"]["description"]
    fn.__name__ = name
    return fn


# ---------------------------------------------------------------------------
# Tool factory
# ---------------------------------------------------------------------------


def cloud_infra_tools(context: Any = None) -> list:
    """Return cloud infrastructure tools. Credentials from secrets.json."""
    secrets = _get_secrets(context) if context else SecretStore()
    tools: list[Callable[..., Any]] = []

    # ===== AWS tools =====

    # -- aws_ec2_list --
    def aws_ec2_list(region: str = "") -> dict:
        """List EC2 instances with status."""
        creds = _aws_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "AWS credentials not configured in secrets.json (aws:default)",
            }
        try:
            ec2 = _boto3_client("ec2", creds, region=region or None)
            resp = ec2.describe_instances()
            instances = []
            for reservation in resp.get("Reservations", []):
                for inst in reservation.get("Instances", []):
                    name = ""
                    for tag in inst.get("Tags", []):
                        if tag.get("Key") == "Name":
                            name = tag.get("Value", "")
                    instances.append(
                        {
                            "id": inst.get("InstanceId"),
                            "name": name,
                            "type": inst.get("InstanceType"),
                            "state": inst.get("State", {}).get("Name"),
                            "public_ip": inst.get("PublicIpAddress"),
                            "private_ip": inst.get("PrivateIpAddress"),
                            "az": inst.get("Placement", {}).get("AvailabilityZone"),
                        }
                    )
            return {"ok": True, "instances": instances, "count": len(instances)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            aws_ec2_list,
            _schema(
                "aws_ec2_list",
                "List EC2 instances with status, type, and IPs. Optionally filter by region.",
                {
                    "region": {
                        "type": "string",
                        "description": "AWS region (default: from credentials).",
                    }
                },
                [],
            ),
            caps=["cloud", "read"],
        )
    )

    # -- aws_s3_list --
    def aws_s3_list(bucket: str = "") -> dict:
        """List S3 buckets or objects in a bucket."""
        creds = _aws_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "AWS credentials not configured in secrets.json (aws:default)",
            }
        try:
            s3 = _boto3_client("s3", creds)
            if not bucket:
                resp = s3.list_buckets()
                buckets = [
                    {"name": b["Name"], "created": b["CreationDate"].isoformat()}
                    for b in resp.get("Buckets", [])
                ]
                return {"ok": True, "buckets": buckets, "count": len(buckets)}
            else:
                resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=100)
                objects = [
                    {
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "modified": obj["LastModified"].isoformat(),
                    }
                    for obj in resp.get("Contents", [])
                ]
                return {
                    "ok": True,
                    "bucket": bucket,
                    "objects": objects,
                    "count": len(objects),
                    "truncated": resp.get("IsTruncated", False),
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            aws_s3_list,
            _schema(
                "aws_s3_list",
                "List S3 buckets (no args) or objects in a specific bucket (first 100).",
                {
                    "bucket": {
                        "type": "string",
                        "description": "Bucket name. Empty = list all buckets.",
                    }
                },
                [],
            ),
            caps=["cloud", "read"],
        )
    )

    # -- aws_cloudwatch_metrics --
    def aws_cloudwatch_metrics(service: str, metric: str, period: str = "1h") -> dict:
        """Query CloudWatch metrics for an AWS service."""
        creds = _aws_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "AWS credentials not configured in secrets.json (aws:default)",
            }
        try:
            cw = _boto3_client("cloudwatch", creds)
            delta = _parse_period(period)
            end = datetime.now(timezone.utc)
            start = end - delta
            # Map common service/metric combos to namespace
            ns_map = {
                "ec2": "AWS/EC2",
                "rds": "AWS/RDS",
                "s3": "AWS/S3",
                "lambda": "AWS/Lambda",
                "elb": "AWS/ELB",
                "alb": "AWS/ApplicationELB",
            }
            namespace = ns_map.get(service.lower(), f"AWS/{service}")
            # Determine stat period in seconds (at least 60s)
            stat_period = max(60, int(delta.total_seconds() / 60))
            resp = cw.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric,
                StartTime=start,
                EndTime=end,
                Period=stat_period,
                Statistics=["Average", "Maximum", "Minimum"],
            )
            datapoints = sorted(resp.get("Datapoints", []), key=lambda d: d["Timestamp"])
            return {
                "ok": True,
                "namespace": namespace,
                "metric": metric,
                "period": period,
                "datapoints": [
                    {
                        "timestamp": dp["Timestamp"].isoformat(),
                        "average": dp.get("Average"),
                        "maximum": dp.get("Maximum"),
                        "minimum": dp.get("Minimum"),
                        "unit": dp.get("Unit"),
                    }
                    for dp in datapoints
                ],
                "count": len(datapoints),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            aws_cloudwatch_metrics,
            _schema(
                "aws_cloudwatch_metrics",
                "Query CloudWatch metrics for an AWS service (e.g. EC2 CPUUtilization).",
                {
                    "service": {
                        "type": "string",
                        "description": "AWS service (e.g. 'ec2', 'rds', 'lambda').",
                    },
                    "metric": {
                        "type": "string",
                        "description": "Metric name (e.g. 'CPUUtilization').",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period (e.g. '1h', '7d'). Default '1h'.",
                    },
                },
                ["service", "metric"],
            ),
            caps=["cloud", "read"],
        )
    )

    # -- aws_cost_explorer --
    def aws_cost_explorer(period: str = "7d") -> dict:
        """AWS cost analysis for a recent period."""
        creds = _aws_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "AWS credentials not configured in secrets.json (aws:default)",
            }
        try:
            ce = _boto3_client("ce", creds, region="us-east-1")  # CE is us-east-1 only
            delta = _parse_period(period)
            end = datetime.now(timezone.utc).date()
            start = end - delta
            resp = ce.get_cost_and_usage(
                TimePeriod={
                    "Start": start.isoformat(),
                    "End": end.isoformat(),
                },
                Granularity="DAILY",
                Metrics=["UnblendedCost", "UsageQuantity"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            results = []
            for result_by_time in resp.get("ResultsByTime", []):
                time_period = result_by_time.get("TimePeriod", {})
                for group in result_by_time.get("Groups", []):
                    svc = group["Keys"][0] if group.get("Keys") else "Unknown"
                    cost = group.get("Metrics", {}).get("UnblendedCost", {})
                    results.append(
                        {
                            "date": time_period.get("Start"),
                            "service": svc,
                            "amount": cost.get("Amount"),
                            "unit": cost.get("Unit"),
                        }
                    )
            return {"ok": True, "period": period, "costs": results, "count": len(results)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            aws_cost_explorer,
            _schema(
                "aws_cost_explorer",
                "AWS cost analysis grouped by service for a recent period.",
                {
                    "period": {
                        "type": "string",
                        "description": "Time period (e.g. '7d', '30d'). Default '7d'.",
                    }
                },
                [],
            ),
            caps=["cloud", "read"],
        )
    )

    # ===== Cloudflare tools =====

    # -- cf_dns_list --
    def cf_dns_list(zone: str = "") -> dict:
        """List Cloudflare DNS records for a zone."""
        creds = _cf_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "Cloudflare credentials not configured in secrets.json (cloudflare:default)",
            }
        try:
            import httpx

            zone_id = zone or creds.get("zone_id", "")
            if not zone_id:
                return {"ok": False, "error": "No zone ID provided and none in credentials."}
            resp = httpx.get(
                f"{_CF_BASE}/zones/{zone_id}/dns_records",
                headers=_cf_headers(creds),
                params={"per_page": 100},
                timeout=30,
            )
            data = resp.json()
            if not data.get("success"):
                return {"ok": False, "error": data.get("errors", "Unknown error")}
            records = [
                {
                    "id": r["id"],
                    "type": r["type"],
                    "name": r["name"],
                    "content": r["content"],
                    "proxied": r.get("proxied"),
                    "ttl": r.get("ttl"),
                }
                for r in data.get("result", [])
            ]
            return {"ok": True, "zone": zone_id, "records": records, "count": len(records)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            cf_dns_list,
            _schema(
                "cf_dns_list",
                "List Cloudflare DNS records for a zone.",
                {"zone": {"type": "string", "description": "Zone ID (default: from credentials)."}},
                [],
            ),
            caps=["cloud", "read"],
        )
    )

    # -- cf_dns_update --
    def cf_dns_update(zone: str, record_id: str, value: str) -> dict:
        """Update a Cloudflare DNS record value (requires approval)."""
        creds = _cf_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "Cloudflare credentials not configured in secrets.json (cloudflare:default)",
            }
        try:
            import httpx

            zone_id = zone or creds.get("zone_id", "")
            if not zone_id:
                return {"ok": False, "error": "No zone ID provided."}
            # First get the existing record to preserve type/name
            get_resp = httpx.get(
                f"{_CF_BASE}/zones/{zone_id}/dns_records/{record_id}",
                headers=_cf_headers(creds),
                timeout=30,
            )
            existing = get_resp.json()
            if not existing.get("success"):
                return {"ok": False, "error": existing.get("errors", "Record not found")}
            rec = existing["result"]
            # Update the record content
            put_resp = httpx.put(
                f"{_CF_BASE}/zones/{zone_id}/dns_records/{record_id}",
                headers=_cf_headers(creds),
                json={
                    "type": rec["type"],
                    "name": rec["name"],
                    "content": value,
                    "ttl": rec.get("ttl", 1),
                    "proxied": rec.get("proxied", False),
                },
                timeout=30,
            )
            data = put_resp.json()
            if not data.get("success"):
                return {"ok": False, "error": data.get("errors", "Update failed")}
            return {"ok": True, "record": data["result"]}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            cf_dns_update,
            _schema(
                "cf_dns_update",
                "Update a Cloudflare DNS record value. Requires approval.",
                {
                    "zone": {"type": "string", "description": "Zone ID (or empty for default)."},
                    "record_id": {"type": "string", "description": "DNS record ID to update."},
                    "value": {"type": "string", "description": "New record value/content."},
                },
                ["record_id", "value"],
            ),
            approval=True,
            caps=["cloud", "write"],
        )
    )

    # -- cf_analytics --
    def cf_analytics(zone: str = "", period: str = "24h") -> dict:
        """Cloudflare traffic analytics for a zone."""
        creds = _cf_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "Cloudflare credentials not configured in secrets.json (cloudflare:default)",
            }
        try:
            import httpx

            zone_id = zone or creds.get("zone_id", "")
            if not zone_id:
                return {"ok": False, "error": "No zone ID provided and none in credentials."}
            delta = _parse_period(period)
            since = (datetime.now(timezone.utc) - delta).isoformat()
            resp = httpx.get(
                f"{_CF_BASE}/zones/{zone_id}/analytics/dashboard",
                headers=_cf_headers(creds),
                params={"since": since, "continuous": "true"},
                timeout=30,
            )
            data = resp.json()
            if not data.get("success"):
                return {"ok": False, "error": data.get("errors", "Unknown error")}
            totals = data.get("result", {}).get("totals", {})
            return {
                "ok": True,
                "zone": zone_id,
                "period": period,
                "requests": totals.get("requests", {}),
                "bandwidth": totals.get("bandwidth", {}),
                "threats": totals.get("threats", {}),
                "pageviews": totals.get("pageviews", {}),
                "uniques": totals.get("uniques", {}),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            cf_analytics,
            _schema(
                "cf_analytics",
                "Cloudflare traffic analytics (requests, bandwidth, threats) for a zone.",
                {
                    "zone": {
                        "type": "string",
                        "description": "Zone ID (default: from credentials).",
                    },
                    "period": {
                        "type": "string",
                        "description": "Time period (e.g. '24h', '7d'). Default '24h'.",
                    },
                },
                [],
            ),
            caps=["cloud", "read"],
        )
    )

    # -- cf_cache_purge --
    def cf_cache_purge(zone: str, urls: str = "") -> dict:
        """Purge Cloudflare cache (requires approval). Empty urls = purge everything."""
        creds = _cf_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "Cloudflare credentials not configured in secrets.json (cloudflare:default)",
            }
        try:
            import httpx

            zone_id = zone or creds.get("zone_id", "")
            if not zone_id:
                return {"ok": False, "error": "No zone ID provided."}
            if urls:
                url_list = [u.strip() for u in urls.split(",") if u.strip()]
                body = {"files": url_list}
            else:
                body = {"purge_everything": True}
            resp = httpx.post(
                f"{_CF_BASE}/zones/{zone_id}/purge_cache",
                headers=_cf_headers(creds),
                json=body,
                timeout=30,
            )
            data = resp.json()
            if not data.get("success"):
                return {"ok": False, "error": data.get("errors", "Purge failed")}
            return {"ok": True, "purged": "all" if not urls else url_list}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            cf_cache_purge,
            _schema(
                "cf_cache_purge",
                "Purge Cloudflare cache. Empty urls = purge everything. Requires approval.",
                {
                    "zone": {"type": "string", "description": "Zone ID (or empty for default)."},
                    "urls": {
                        "type": "string",
                        "description": "Comma-separated URLs to purge (empty = purge all).",
                    },
                },
                [],
            ),
            approval=True,
            caps=["cloud", "write"],
        )
    )

    # ===== Wasabi tools =====

    # -- wasabi_list --
    def wasabi_list(bucket: str = "") -> dict:
        """List Wasabi buckets or objects in a bucket."""
        creds = _wasabi_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "Wasabi credentials not configured in secrets.json (wasabi:default)",
            }
        try:
            s3 = _boto3_client(
                "s3",
                creds,
                endpoint_url=creds.get("endpoint", "https://s3.wasabisys.com"),
            )
            if not bucket:
                resp = s3.list_buckets()
                buckets = [
                    {"name": b["Name"], "created": b["CreationDate"].isoformat()}
                    for b in resp.get("Buckets", [])
                ]
                return {"ok": True, "buckets": buckets, "count": len(buckets)}
            else:
                resp = s3.list_objects_v2(Bucket=bucket, MaxKeys=100)
                objects = [
                    {
                        "key": obj["Key"],
                        "size": obj["Size"],
                        "modified": obj["LastModified"].isoformat(),
                    }
                    for obj in resp.get("Contents", [])
                ]
                return {
                    "ok": True,
                    "bucket": bucket,
                    "objects": objects,
                    "count": len(objects),
                    "truncated": resp.get("IsTruncated", False),
                }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            wasabi_list,
            _schema(
                "wasabi_list",
                "List Wasabi S3-compatible buckets (no args) or objects in a bucket (first 100).",
                {
                    "bucket": {
                        "type": "string",
                        "description": "Bucket name. Empty = list all buckets.",
                    }
                },
                [],
            ),
            caps=["cloud", "read"],
        )
    )

    # -- wasabi_upload --
    def wasabi_upload(local_path: str, bucket: str, key: str) -> dict:
        """Upload a file to Wasabi (requires approval)."""
        creds = _wasabi_creds(secrets)
        if not creds:
            return {
                "ok": False,
                "error": "Wasabi credentials not configured in secrets.json (wasabi:default)",
            }
        if not os.path.isfile(local_path):
            return {"ok": False, "error": f"Local file not found: {local_path}"}
        try:
            s3 = _boto3_client(
                "s3",
                creds,
                endpoint_url=creds.get("endpoint", "https://s3.wasabisys.com"),
            )
            s3.upload_file(local_path, bucket, key)
            size = os.path.getsize(local_path)
            return {
                "ok": True,
                "bucket": bucket,
                "key": key,
                "size": size,
                "message": f"Uploaded {local_path} -> s3://{bucket}/{key}",
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}

    tools.append(
        _attach(
            wasabi_upload,
            _schema(
                "wasabi_upload",
                "Upload a local file to Wasabi S3-compatible storage. Requires approval.",
                {
                    "local_path": {"type": "string", "description": "Absolute path to local file."},
                    "bucket": {"type": "string", "description": "Destination bucket name."},
                    "key": {"type": "string", "description": "Object key (path) in the bucket."},
                },
                ["local_path", "bucket", "key"],
            ),
            approval=True,
            caps=["cloud", "write"],
        )
    )

    return tools
