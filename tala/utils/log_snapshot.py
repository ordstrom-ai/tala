"""Blob Storage adapter for complete, oversized structured log events."""

import re

SNAPSHOT_ID_PATTERN = re.compile(r"[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}\Z")
PREFIX_COMPONENT_PATTERN = re.compile(r"[a-z0-9][a-z0-9_.-]{0,62}\Z")


class BlobLogSnapshotStore:
    """Write immutable snapshots to an injected Azure Blob container client.

    Construct the client with the application's managed identity and bounded
    network timeouts. The container must already exist and be private. The
    application identity needs narrowly scoped write access; retrieval callers
    should use a separate reader identity where possible. This adapter never
    creates Azure resources, credentials, containers, or SAS URLs.
    This storage primitive does not grant capture permission or redact content.
    Use the logging admission policy before writing diagnostic snapshots; raw
    transcript data belongs to the separate restricted utterance archive.
    """
    def __init__(self, container_client, prefix):
        self._container_client = container_client
        self._prefix = self._normalize_prefix(prefix)

    def write_snapshot(self, snapshot_id, snapshot_json):
        blob_name = self._blob_name(snapshot_id)
        blob_client = self._container_client.get_blob_client(blob=blob_name)
        blob_client.upload_blob(snapshot_json, overwrite=False)

    def read_snapshot(self, snapshot_id):
        blob_name = self._blob_name(snapshot_id)
        blob_client = self._container_client.get_blob_client(blob=blob_name)
        return blob_client.download_blob().readall().decode("utf-8")

    def _blob_name(self, snapshot_id):
        if not SNAPSHOT_ID_PATTERN.fullmatch(snapshot_id):
            raise ValueError("Log snapshot IDs must be UUID version 4 values.")
        return f"{self._prefix}/{snapshot_id}.json"

    @staticmethod
    def _normalize_prefix(prefix):
        normalized_prefix = prefix.strip("/")
        components = normalized_prefix.split("/")
        if not normalized_prefix or any(not PREFIX_COMPONENT_PATTERN.fullmatch(component) for component in components):
            raise ValueError("Log snapshot prefixes must contain only simple lowercase path components.")
        return normalized_prefix
