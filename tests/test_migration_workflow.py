import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/run_dotnet_migrations.yml"
).read_text()
MARKER = b"azure-cli-postgresql-v1\n"
SETTINGS = {
    "MIGRATION_CLIENT_ID": "migration-client",
    "MIGRATION_POSTGRES_HOST": "example.postgres.database.azure.com",
    "MIGRATION_POSTGRES_DATABASE": "example",
    "MIGRATION_POSTGRES_USERNAME": "migration-role",
    "AZURE_TENANT_ID": "tenant",
    "AZURE_SUBSCRIPTION_ID": "subscription",
}


def step(name):
    """Read a named step's source without a YAML dependency."""
    return WORKFLOW.split(f"      - name: {name}\n", 1)[1].split(
        "\n      - name: ", 1
    )[0]


GATE = step("Validate migration authentication contract")
SCRIPT = textwrap.dedent(GATE.split("        run: |\n", 1)[1])


class MigrationWorkflowTests(unittest.TestCase):
    def run_gate(self, mode="azure_cli", marker=MARKER, settings=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if marker is not None:
                (root / ".migration-auth-contract").write_bytes(marker)
            # Success-only sentinels model subsequent login/EF steps; no tools run.
            script = (
                "(\n"
                + SCRIPT
                + "\n)\nprintf 'login\\nef\\n' > reached-following-steps\n"
            )
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
                cwd=root,
                env={
                    "PATH": os.defpath,
                    "MIGRATION_AUTH_MODE": mode,
                    **(SETTINGS if settings is None else settings),
                },
                text=True,
                capture_output=True,
            )
            return result, (root / "reached-following-steps").exists()

    def test_supported_contract(self):
        result, continued = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(continued)

    def test_legacy_does_not_require_marker_or_migration_settings(self):
        for marker in (None, MARKER, b"unsupported\n"):
            with self.subTest(marker=marker):
                result, continued = self.run_gate("legacy", marker, {})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(continued)

    def test_strict_modes(self):
        for mode in ("", "Azure_Cli", "LEGACY", "azure_cli ", "password"):
            with self.subTest(mode=mode):
                result, continued = self.run_gate(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("migration_auth_mode must be", result.stdout)
                self.assertFalse(continued)

    def test_old_or_malformed_contract_stops_before_following_steps(self):
        for marker in (
            None,
            b"",
            MARKER.rstrip(b"\n"),
            MARKER.replace(b"\n", b"\r\n"),
            MARKER + b"\n",
            b" " + MARKER,
            b"\xef\xbb\xbf" + MARKER,
            b"azure-cli-postgresql-v2\n",
            MARKER + b"\0",
        ):
            with self.subTest(marker=marker):
                result, continued = self.run_gate(marker=marker)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Checked-out migration project", result.stdout)
                self.assertFalse(continued)

    def test_each_required_setting(self):
        for setting in SETTINGS:
            for value in (None, "", " \t\n"):
                with self.subTest(setting=setting, value=value):
                    settings = SETTINGS.copy()
                    if value is None:
                        del settings[setting]
                    else:
                        settings[setting] = value
                    result, continued = self.run_gate(settings=settings)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"setting is missing: {setting}", result.stdout)
                    self.assertFalse(continued)

    def test_values_are_not_executed_or_logged(self):
        settings = {
            key: "$(exit 99); ' \"\n::error::untrusted-value" for key in SETTINGS
        }
        result, continued = self.run_gate(settings=settings)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(continued)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_gate_precedes_login_build_and_dotnet(self):
        position = WORKFLOW.index("      - name: Validate migration")
        self.assertLess(WORKFLOW.index("      - name: Checkout\n"), position)
        for name in (
            "Azure login (OIDC / federated credential)",
            "Azure login with migration identity",
            "Set up .NET",
            "Build project and dependencies",
            "Install dotnet ef tool",
            "Update database",
            "Update database with migration identity",
        ):
            self.assertLess(position, WORKFLOW.index(f"      - name: {name}\n"))
            self.assertNotIn("always()", step(name))
        self.assertNotIn("continue-on-error", WORKFLOW)
        self.assertNotIn("dotnet", SCRIPT)
        self.assertNotIn("az ", SCRIPT)
        self.assertNotIn("${{", SCRIPT)
        self.assertIn("working-directory: ${{ inputs.working_directory }}", WORKFLOW)

    def test_default_and_legacy_contract_are_unchanged(self):
        self.assertIn('        default: "legacy"', WORKFLOW)
        self.assertIn('        default: "main"', WORKFLOW)
        self.assertIn("ref: ${{ inputs.pr_head_sha || inputs.checkout_ref }}", WORKFLOW)
        self.assertIn("environment: ${{ inputs.environment }}", WORKFLOW)
        login = step("Azure login (OIDC / federated credential)")
        update = step("Update database")
        for source in (login, update):
            self.assertIn("if: ${{ inputs.migration_auth_mode == 'legacy' }}", source)
            self.assertNotIn("MIGRATION_CLIENT_ID", source)
        for value in (
            "client-id: ${{ vars.CLIENTID }}",
            "tenant-id: ${{ vars.AZURE_TENANT_ID }}",
            "subscription-id: ${{ inputs.azure_subscription_id }}",
        ):
            self.assertIn(value, login)
        for value in (
            "run: dotnet ef database update --no-build --verbose",
            "AZURE_CLIENT_ID: ${{ vars.CLIENTID }}",
            "AZURE_TENANT_ID: ${{ vars.AZURE_TENANT_ID }}",
            "ASPNETCORE_ENVIRONMENT: ${{ vars.AspNetEnvironment }}",
            "Database__AllowedAuthMethods__0: ConnectionString",
        ):
            self.assertIn(value, update)
        self.assertNotIn("Migrations__", update)

    def test_azure_cli_mapping(self):
        login = step("Azure login with migration identity")
        update = step("Update database with migration identity")
        for source in (login, update):
            self.assertIn("if: ${{ inputs.migration_auth_mode == 'azure_cli' }}", source)
            self.assertNotIn("vars.CLIENTID", source)
        self.assertIn("client-id: ${{ vars.MIGRATION_CLIENT_ID }}", login)
        self.assertIn("tenant-id: ${{ vars.AZURE_TENANT_ID }}", login)
        self.assertIn("subscription-id: ${{ inputs.azure_subscription_id }}", login)
        self.assertIn("run: dotnet ef database update --no-build\n", update)
        self.assertNotIn("--verbose", update)
        self.assertNotIn("Database__AllowedAuthMethods", update)
        self.assertIn("Migrations__AuthenticationMode: AzureCli", update)
        self.assertIn("AZURE_CLIENT_ID: ${{ vars.MIGRATION_CLIENT_ID }}", update)
        self.assertIn("AZURE_TENANT_ID: ${{ vars.AZURE_TENANT_ID }}", update)
        self.assertIn(
            "ASPNETCORE_ENVIRONMENT: ${{ vars.AspNetEnvironment }}", update
        )
        for field in ("Host", "Database", "Username"):
            self.assertIn(
                f"Migrations__Postgres__{field}: "
                "${{ vars.MIGRATION_POSTGRES_" + field.upper() + " }}",
                update,
            )
        for setting in SETTINGS:
            expression = (
                "${{ inputs.azure_subscription_id }}"
                if setting == "AZURE_SUBSCRIPTION_ID"
                else "${{ vars." + setting + " }}"
            )
            self.assertIn(f"{setting}: {expression}", GATE)
        for name in (
            "Azure login (OIDC / federated credential)",
            "Azure login with migration identity",
        ):
            self.assertIn(
                "uses: azure/login@7ddb5af1ef8758cf1353cf3b42f940aee27ba21c",
                step(name),
            )


if __name__ == "__main__":
    unittest.main()
