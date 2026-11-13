import json
from unittest.mock import Mock

import pytest

from tala.utils.func import BoundedJSONRenderer
from tala.utils.log_snapshot import BlobLogSnapshotStore

SNAPSHOT_ID = "123e4567-e89b-42d3-a456-426614174000"


class TestBlobLogSnapshotStore:
    def test_oversized_event_is_retrievable_through_the_snapshot_reference(self):
        self.given_a_fake_blob_container()
        self.given_a_snapshot_store()
        self.given_an_oversized_event()
        self.when_the_event_is_rendered()
        self.then_the_complete_event_is_retrievable()

    def test_snapshot_blob_names_cannot_escape_the_configured_prefix(self):
        self.given_a_fake_blob_container()
        self.given_a_snapshot_store()

        with pytest.raises(ValueError, match="UUID version 4"):
            self.snapshot_store.read_snapshot("../../other-container/secret")

        assert self.container.blobs == {}

    def test_prefix_rejects_empty_and_traversal_components(self):
        self.given_a_fake_blob_container()

        with pytest.raises(ValueError, match="simple lowercase path components"):
            BlobLogSnapshotStore(self.container, "pipeline/../production")

    def given_a_fake_blob_container(self):
        self.container = FakeBlobContainer()

    def given_a_snapshot_store(self):
        self.snapshot_store = BlobLogSnapshotStore(self.container, "pipeline/staging")

    def given_an_oversized_event(self):
        self.event = {
            "event": "downstream request",
            "request_id": "request-123",
            "body": {
                "input": "hello " * 2_000
            },
        }
        policy = Mock(spec=["permits_snapshot"])
        policy.permits_snapshot.return_value = True
        self.renderer = BoundedJSONRenderer(max_bytes=256, snapshot_writer=self.snapshot_store, snapshot_policy=policy)

    def when_the_event_is_rendered(self):
        summary = self.renderer(None, None, self.event)
        self.parsed_summary = json.loads(summary)

    def then_the_complete_event_is_retrievable(self):
        snapshot_id = self.parsed_summary["log_snapshot_id"]
        assert self.parsed_summary["log_snapshot_state"] == "stored"
        assert self.container.last_overwrite is False
        assert self.container.last_blob_name == f"pipeline/staging/{snapshot_id}.json"
        assert json.loads(self.snapshot_store.read_snapshot(snapshot_id)) == self.event


class FakeBlobContainer:
    def __init__(self):
        self.blobs = {}
        self.last_blob_name = None
        self.last_overwrite = None

    def get_blob_client(self, blob):
        self.last_blob_name = blob
        return FakeBlobClient(self, blob)


class FakeBlobClient:
    def __init__(self, container, name):
        self._container = container
        self._name = name

    def upload_blob(self, content, overwrite):
        self._container.last_overwrite = overwrite
        if self._name in self._container.blobs and not overwrite:
            raise FileExistsError(self._name)
        self._container.blobs[self._name] = content.encode("utf-8")

    def download_blob(self):
        return FakeDownload(self._container.blobs[self._name])


class FakeDownload:
    def __init__(self, content):
        self._content = content

    def readall(self):
        return self._content
