# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

from typing import Any, List
from uuid import uuid4

from azure.core.credentials import AzureSasCredential
from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError
from azure.core.pipeline.policies import (
    ContentDecodePolicy,
    AsyncBearerTokenCredentialPolicy,
    AsyncRedirectPolicy,
    DistributedTracingPolicy,
    HttpLoggingPolicy,
    UserAgentPolicy,
    ProxyPolicy,
    AzureSasCredentialPolicy,
    RequestIdPolicy,
    CustomHookPolicy,
    NetworkTraceLoggingPolicy
)
from azure.core.pipeline.transport import (
    AsyncHttpTransport,
    HttpRequest,
)

from .._generated.aio import AzureTable
from .._base_client import AccountHostsMixin, get_api_version, extract_batch_part_metadata
from .._authentication import SharedKeyCredentialPolicy
from .._constants import STORAGE_OAUTH_SCOPE
from .._error import RequestTooLargeError
from .._models import BatchErrorException
from .._policies import StorageHosts, StorageHeadersPolicy
from .._sdk_moniker import SDK_MONIKER
from ._policies_async import AsyncTablesRetryPolicy


class AsyncTablesBaseClient(AccountHostsMixin):

    def __init__(
        self,
        account_url,  # type: str
        credential=None,  # type: str
        **kwargs  # type: Any
    ):
        # type: (...) -> None
        super(AsyncTablesBaseClient, self).__init__(account_url, credential=credential, **kwargs)
        self._client = AzureTable(
            self.url,
            policies=kwargs.pop('policies', self._policies),
            **kwargs
        )
        self._client._config.version = get_api_version(kwargs, self._client._config.version)  # pylint: disable=protected-access


    async def __aenter__(self):
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *args):
        await self._client.__aexit__(*args)

    async def close(self) -> None:
        """This method is to close the sockets opened by the client.
        It need not be used when using with a context manager.
        """
        await self._client.close()

    def _configure_credential(self, credential):
        # type: (Any) -> None
        if hasattr(credential, "get_token"):
            self._credential_policy = AsyncBearerTokenCredentialPolicy(
                credential, STORAGE_OAUTH_SCOPE
            )
        elif isinstance(credential, SharedKeyCredentialPolicy):
            self._credential_policy = credential
        elif isinstance(credential, AzureSasCredential):
            self._credential_policy = AzureSasCredentialPolicy(credential)
        elif credential is not None:
            raise TypeError("Unsupported credential: {}".format(credential))

    def _configure_policies(self, **kwargs):
        return [
            RequestIdPolicy(**kwargs),
            StorageHeadersPolicy(**kwargs),
            UserAgentPolicy(sdk_moniker=SDK_MONIKER, **kwargs),
            ProxyPolicy(**kwargs),
            self._credential_policy,
            ContentDecodePolicy(response_encoding="utf-8"),
            AsyncRedirectPolicy(**kwargs),
            StorageHosts(**kwargs),
            AsyncTablesRetryPolicy(**kwargs),
            CustomHookPolicy(**kwargs),
            NetworkTraceLoggingPolicy(**kwargs),
            DistributedTracingPolicy(**kwargs),
            HttpLoggingPolicy(**kwargs),
        ]

    async def _batch_send(
        self,
        entities,  # type: List[TableEntity]
        *reqs: "HttpRequest",
        **kwargs
    ):
        """Given a series of request, do a Storage batch call."""
        # Pop it here, so requests doesn't feel bad about additional kwarg
        policies = [StorageHeadersPolicy()]

        changeset = HttpRequest("POST", None)
        changeset.set_multipart_mixed(
            *reqs, policies=policies, boundary="changeset_{}".format(uuid4())
        )
        request = self._client._client.post(  # pylint: disable=protected-access
            url="https://{}/$batch".format(self._primary_hostname),
            headers={
                "x-ms-version": self.api_version,
                "DataServiceVersion": "3.0",
                "MaxDataServiceVersion": "3.0;NetFx",
                "Content-Type": "application/json",
                "Accept": "application/json"
            },
        )
        request.set_multipart_mixed(
            changeset,
            policies=policies,
            enforce_https=False,
            boundary="batch_{}".format(uuid4()),
        )

        pipeline_response = await self._client._client._pipeline.run(request, **kwargs)  # pylint: disable=protected-access
        response = pipeline_response.http_response

        if response.status_code == 403:
            raise ClientAuthenticationError(
                message="There was an error authenticating with the service",
                response=response,
            )
        if response.status_code == 404:
            raise ResourceNotFoundError(
                message="The resource could not be found", response=response
            )
        if response.status_code == 413:
            raise RequestTooLargeError(
                message="The request was too large", response=response
            )
        if response.status_code != 202:
            raise BatchErrorException(
                message="There is a failure in the batch operation.",
                response=response,
                parts=None,
            )

        parts_iter = response.parts()
        parts = []
        async for p in parts_iter:
            parts.append(p)
        if any(p for p in parts if not 200 <= p.status_code < 300):
            if any(p for p in parts if p.status_code == 404):
                raise ResourceNotFoundError(
                    message="The resource could not be found", response=response
                )
            if any(p for p in parts if p.status_code == 413):
                raise RequestTooLargeError(
                    message="The request was too large", response=response
                )


            raise BatchErrorException(
                message="There is a failure in the batch operation.",
                response=response,
                parts=parts,
            )
        return list(zip(entities, (extract_batch_part_metadata(p) for p in parts)))


class AsyncTransportWrapper(AsyncHttpTransport):
    """Wrapper class that ensures that an inner client created
    by a `get_client` method does not close the outer transport for the parent
    when used in a context manager.
    """
    def __init__(self, async_transport):
        self._transport = async_transport

    async def send(self, request, **kwargs):
        return await self._transport.send(request, **kwargs)

    async def open(self):
        pass

    async def close(self):
        pass

    async def __aenter__(self):
        pass

    async def __aexit__(self, *args):  # pylint: disable=arguments-differ
        pass
