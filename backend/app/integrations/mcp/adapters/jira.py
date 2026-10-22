"""Jira adapter (SPEC 17.9): Jira is a read-only research source; app tasks stay independent."""

from __future__ import annotations

from typing import Any

from app.integrations.mcp.adapters.base import AdapterPreset, ServiceAdapter
from app.integrations.mcp.client import ToolInfo


class JiraAdapter(ServiceAdapter):
    name = "jira"
    label = "Jira"
    description = "Search Jira issues (e.g. via the mcp-atlassian server)."
    search_tool_candidates = ("jira_search", "search_issues", "search")
    read_only_tools = ("jira_search", "jira_get_issue", "jira_get_project_issues", "jira_get_transitions", "get_issue", "search_issues")
    external_write_tools = ("jira_create_issue", "jira_update_issue", "jira_delete_issue", "jira_add_comment", "jira_transition_issue", "create_issue", "update_issue")

    def preset(self) -> AdapterPreset:
        return AdapterPreset(
            adapter=self.name,
            label=self.label,
            description=self.description,
            transport="stdio",
            command="uvx",
            args=["mcp-atlassian"],
            auth_type="none",
            env_hints={"JIRA_URL": "https://your-site.atlassian.net", "JIRA_USERNAME": "you@example.com", "JIRA_API_TOKEN": "Atlassian API token"},
            tool_permissions=[
                {"tool_name": "jira_create_issue", "permission": "external_write", "enabled": False},
                {"tool_name": "jira_update_issue", "permission": "external_write", "enabled": False},
                {"tool_name": "jira_add_comment", "permission": "external_write", "enabled": False},
                {"tool_name": "jira_transition_issue", "permission": "external_write", "enabled": False},
            ],
        )

    def build_search_args(self, tool: ToolInfo, query: str, limit: int) -> dict[str, Any]:
        props = (tool.input_schema or {}).get("properties", {}) if isinstance(tool.input_schema, dict) else {}
        args: dict[str, Any] = {}
        if "jql" in props:
            escaped = query.replace('"', '\\"')
            args["jql"] = query if any(op in query for op in (" = ", " ~ ", "ORDER BY")) else f'text ~ "{escaped}" ORDER BY updated DESC'
        else:
            args = super().build_search_args(tool, query, limit)
        for key in ("limit", "max_results", "maxResults"):
            if key in props:
                args[key] = limit
        return args

    def normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        data = super().normalize_item(item)
        fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}
        data["title"] = data["title"] or fields.get("summary")
        data["status"] = (fields.get("status") or {}).get("name") if isinstance(fields.get("status"), dict) else item.get("status")
        data["source_type"] = "jira"
        return data
