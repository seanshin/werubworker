"""Tests for coworker.security.sensitive_filter."""

from coworker.security.sensitive_filter import sanitize_text, sanitize_command


class TestSanitizeText:
    def test_anthropic_key(self):
        text = "key is sk-ant-abcdefghijklmnopqrstuvwxyz here"
        assert "[ANTHROPIC_KEY]" in sanitize_text(text)
        assert "sk-ant-" not in sanitize_text(text)

    def test_openai_key(self):
        text = "using sk-abcdefghijklmnopqrstuv as key"
        assert "[API_KEY]" in sanitize_text(text)

    def test_aws_key(self):
        assert "[AWS_KEY]" in sanitize_text("AKIAIOSFODNN7EXAMPLE")

    def test_github_pat(self):
        text = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghij"
        assert "[GITHUB_PAT]" in sanitize_text(text)

    def test_slack_token(self):
        text = "token xoxb-123-456-abcdef"
        assert "[SLACK_TOKEN]" in sanitize_text(text)

    def test_gitlab_pat(self):
        text = "glpat-abcdefghijklmnopqrstuv"
        assert "[GITLAB_PAT]" in sanitize_text(text)

    def test_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig"
        assert "Bearer [REDACTED]" in sanitize_text(text)

    def test_password_assignment(self):
        assert "password=[REDACTED]" in sanitize_text("password=MyS3cret!")
        assert "password=[REDACTED]" in sanitize_text("PASSWORD: hunter2")

    def test_password_flag(self):
        assert "--password [REDACTED]" in sanitize_text("--password=secret123")

    def test_korean_ssn(self):
        assert "[주민번호]" in sanitize_text("주민번호 900101-1234567")

    def test_korean_phone(self):
        assert "[전화번호]" in sanitize_text("연락처 010-1234-5678")

    def test_db_uri(self):
        text = "postgres://user:pass@db.host:5432/mydb"
        assert "[DB_URI]" in sanitize_text(text)
        text2 = "mysql://root:secret@localhost/test"
        assert "[DB_URI]" in sanitize_text(text2)

    def test_plain_text_unchanged(self):
        text = "uptime && free -h && df -h"
        assert sanitize_text(text) == text

    def test_empty_string(self):
        assert sanitize_text("") == ""

    def test_none_like(self):
        assert sanitize_text("") == ""


class TestSanitizeCommand:
    def test_sshpass(self):
        cmd = "sshpass -p MySecret ssh user@host"
        result = sanitize_command(cmd)
        assert "MySecret" not in result
        assert "[REDACTED]" in result

    def test_pgpassword(self):
        cmd = "PGPASSWORD=secret123 psql -U admin"
        result = sanitize_command(cmd)
        assert "secret123" not in result
        assert "[REDACTED]" in result

    def test_mysql_pwd(self):
        cmd = "MYSQL_PWD=secret123 mysql -u root"
        result = sanitize_command(cmd)
        assert "secret123" not in result

    def test_mysql_p_flag(self):
        cmd = "mysql -u root -pMyPassword dbname"
        result = sanitize_command(cmd)
        assert "MyPassword" not in result

    def test_export_secret(self):
        cmd = "export DB_PASSWORD=hunter2"
        result = sanitize_command(cmd)
        assert "hunter2" not in result
        assert "=[REDACTED]" in result

    def test_normal_command_unchanged(self):
        cmd = "ls -la /var/log"
        assert sanitize_command(cmd) == cmd

    def test_combined_patterns(self):
        cmd = "PGPASSWORD=pass123 psql -h db.example.com -U admin"
        result = sanitize_command(cmd)
        assert "pass123" not in result
        assert "db.example.com" in result
