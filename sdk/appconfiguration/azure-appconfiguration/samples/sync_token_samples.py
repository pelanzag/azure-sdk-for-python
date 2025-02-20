# coding: utf-8

# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

"""
FILE: sync_token_samples.py
DESCRIPTION:
    This sample demos update_sync_token for the AzureAppConfigurationClient
USAGE: python sync_token_samples.py
"""

from azure.appconfiguration import AzureAppConfigurationClient
from util import print_configuration_setting, get_connection_string


def handle_event_grid_notifications(event_grid_events):
    # type: (List[dict[str, Any]]) -> None
    CONNECTION_STRING = get_connection_string()

    all_keys = []

    with AzureAppConfigurationClient.from_connection_string(CONNECTION_STRING) as client:

        for event_grid_event in event_grid_events:
            if event_grid_event["eventType"] == 'Microsoft.KeyValueModified':
                sync_token = event['data']['syncToken']
                client.update_sync_token(sync_token)

                new_key = client.get_configuration_setting(key=event['data']['key'], label=event['data']['label'])

                all_keys.append(new_key)


if __name__ == "__main__":
    handle_event_grid_notifications([])
