import msal

from robotics_integration_tests.settings.settings import settings


def retrieve_access_token_for_integration_tests_app(resource_client_id: str) -> str:
    app = msal.ConfidentialClientApplication(
        client_id=settings.INTEGRATION_TESTS_CLIENT_ID,
        client_credential=settings.INTEGRATION_TESTS_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{settings.INTEGRATION_TESTS_TENANT_ID}",
    )
    result = app.acquire_token_for_client(
        scopes=[f"api://{resource_client_id}/.default"]
    )
    if "access_token" in result:
        return result["access_token"]
    else:
        raise RuntimeError(
            f"Unable to retrieve access token for integration tests app: {result}"
        )
