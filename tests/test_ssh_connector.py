"""SSH connector tests — tools, client, accounts."""

from __future__ import annotations

from coworker.connectors.ssh.accounts import (
    list_servers,
    add_server,
    remove_server,
    get_server,
    PREFIX,
)
from coworker.connectors.ssh.client import SSHClient, SSHServer
from coworker.connectors.ssh.tools import ssh_tools
from coworker.secrets import SecretStore


def test_ssh_tools_factory(tmp_path):
    """Factory returns expected SSH tools."""
    secrets = SecretStore(tmp_path / "secrets.json")
    tools = ssh_tools(secrets)
    assert len(tools) >= 6
    names = {t.__name__ for t in tools}
    assert "ssh_list_servers" in names
    assert "ssh_execute" in names
    assert "ssh_server_status" in names


def test_ssh_list_servers_empty(tmp_path):
    """No servers registered returns an empty list."""
    secrets = SecretStore(tmp_path / "secrets.json")
    servers = list_servers(secrets)
    assert servers == []


def test_ssh_server_add_remove(tmp_path):
    """Add and remove a server."""
    secrets = SecretStore(tmp_path / "secrets.json")

    # Add
    result = add_server(secrets, "web-01", "192.168.1.10", port=22, username="deploy")
    assert result["ok"] is True
    assert result["server_id"] == "web-01"

    # List should now have one server
    servers = list_servers(secrets)
    assert len(servers) == 1
    assert servers[0]["server_id"] == "web-01"
    assert servers[0]["host"] == "192.168.1.10"

    # Duplicate should fail
    result = add_server(secrets, "web-01", "192.168.1.11")
    assert result["ok"] is False
    assert "already exists" in result["error"]

    # Remove
    result = remove_server(secrets, "web-01")
    assert result["ok"] is True
    assert list_servers(secrets) == []

    # Remove non-existent
    result = remove_server(secrets, "web-01")
    assert result["ok"] is False


def test_ssh_server_add_validation(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")

    result = add_server(secrets, "", "192.168.1.10")
    assert result["ok"] is False
    assert "required" in result["error"]

    result = add_server(secrets, "web-01", "")
    assert result["ok"] is False
    assert "required" in result["error"]


def test_get_server(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    add_server(secrets, "db-01", "10.0.0.5", port=2222, username="admin", key_path="~/.ssh/db_key")
    srv = get_server(secrets, "db-01")
    assert srv is not None
    assert srv.server_id == "db-01"
    assert srv.host == "10.0.0.5"
    assert srv.port == 2222
    assert srv.username == "admin"
    assert srv.key_path == "~/.ssh/db_key"


def test_get_server_not_found(tmp_path):
    secrets = SecretStore(tmp_path / "secrets.json")
    assert get_server(secrets, "nonexistent") is None


def test_ssh_client_build_command():
    """Verify the SSH command structure."""
    server = SSHServer(
        server_id="test",
        host="192.168.1.5",
        port=2222,
        username="admin",
        key_path="~/.ssh/test_key",
    )
    client = SSHClient(server)
    cmd = client._build_ssh_command("uptime")
    assert cmd[0] == "ssh"
    assert "-p" in cmd
    idx = cmd.index("-p")
    assert cmd[idx + 1] == "2222"
    assert "-i" in cmd
    assert "admin@192.168.1.5" in cmd
    assert cmd[-1] == "uptime"


def test_ssh_client_build_sudo_command():
    server = SSHServer(server_id="test", host="10.0.0.1", username="deploy")
    client = SSHClient(server)
    cmd = client._build_ssh_command("systemctl restart nginx", sudo=True)
    assert "sudo systemctl restart nginx" in cmd[-1]


def test_ssh_list_servers_tool(tmp_path):
    """The ssh_list_servers tool should return an ok result."""
    secrets = SecretStore(tmp_path / "secrets.json")
    tools = ssh_tools(secrets)
    list_tool = next(t for t in tools if t.__name__ == "ssh_list_servers")
    result = list_tool()
    assert result["ok"] is True
    assert result["count"] == 0
    assert result["servers"] == []
